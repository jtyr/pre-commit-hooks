import argparse
import os
import tomlkit

from hooks.common.get_file_content import (
    get_file_content,
    get_local_file_content,
)
from hooks.common.git_helpers import path_under_dir
from hooks.common.version_check import (
    VersionError,
    VersionTarget,
    add_common_args,
    get_logger,
    run,
)

DEFAULT_INCLUDE = r"(^|/)(Cargo\.toml|[^/]+\.rs)$"


def parse_args():
    # Define parser
    parser = argparse.ArgumentParser(
        description="Check whether the Cargo crate version was incremented."
    )

    # Add script options
    add_common_args(parser)

    parser.add_argument(
        "-i",
        "--include",
        metavar="REGEXP",
        help=(
            "only changes of repo-relative paths matching this regexp "
            "require a version bump (default: %s)" % DEFAULT_INCLUDE.replace("%", "%%")
        ),
        default=DEFAULT_INCLUDE,
    )
    parser.add_argument(
        "-e",
        "--exclude",
        metavar="REGEXP",
        help="changes of repo-relative paths matching this regexp are ignored",
    )

    parser.add_argument(
        "PATH",
        help="changed files",
        nargs="*",
    )

    # Parse args
    args = parser.parse_args()

    return args


def get_value(doc, keys):
    """Return the value at the nested `keys` or None if it doesn't exist."""
    value = doc

    for key in keys:
        if not hasattr(value, "get"):
            return None

        value = value.get(key)

        if value is None:
            return None

    return value


def is_workspace_inherited(value):
    return hasattr(value, "get") and value.get("workspace") is True


def parent_dir(path):
    return os.path.dirname(path) if path else None


class CargoIndex:
    """All Cargo manifests tracked in the repo, keyed by repo-relative dir."""

    def __init__(self, repo, log):
        self.repo = repo
        self.log = log
        self.crates = {}
        self.workspaces = {}

        for f in repo.git.ls_files("-z").split("\0"):
            if os.path.basename(f) != "Cargo.toml":
                continue

            path = os.path.join(repo.working_tree_dir, f)

            if not os.path.isfile(path):
                continue

            try:
                with open(path) as fh:
                    doc = tomlkit.parse(fh.read())
            except Exception as e:
                log.debug("Skipping unparsable manifest '%s': %s" % (f, e))

                continue

            d = os.path.dirname(f)

            if "workspace" in doc:
                self.workspaces[d] = doc

            if "package" in doc:
                self.crates[d] = doc

    def crate_name(self, crate_dir):
        return get_value(self.crates[crate_dir], ("package", "name"))

    def version(self, crate_dir):
        return get_value(self.crates[crate_dir], ("package", "version"))

    def workspace_dir(self, crate_dir):
        """Return the dir of the workspace the crate belongs to or None."""
        explicit = get_value(self.crates[crate_dir], ("package", "workspace"))

        if isinstance(explicit, str):
            d = os.path.normpath(os.path.join(crate_dir, explicit))

            return "" if d == "." else d

        d = crate_dir

        while d is not None:
            if d in self.workspaces:
                return d

            d = parent_dir(d)

    def owner(self, path):
        """Return the dir of the crate the repo-relative path belongs to."""
        if path in self.crates:
            return path

        d = os.path.dirname(path)

        while d is not None:
            if d in self.crates:
                return d

            d = parent_dir(d)

    def inheriting_crates(self, workspace_dir):
        return sorted(
            d
            for d in self.crates
            if is_workspace_inherited(self.version(d))
            and self.workspace_dir(d) == workspace_dir
        )


def exists_on_branch(branch, path):
    try:
        branch.commit.tree / path
    except KeyError:
        return False

    return True


class CargoTarget(VersionTarget):
    """A version in a Cargo.toml shared by one or more crates."""

    def __init__(self, index, manifest, keys, crate_dirs, lock_dir, log):
        self.index = index
        self.manifest = manifest
        self.keys = keys
        self.crate_dirs = crate_dirs
        self.lock_path = os.path.join(lock_dir, "Cargo.lock")
        self.log = log

    def _parse(self, content, where):
        try:
            return tomlkit.parse(content)
        except Exception as e:
            raise VersionError(
                "Failed to parse '%s' from the %s: %s" % (self.manifest, where, e)
            )

    def main_version(self, repo, main_branch):
        content = get_file_content(repo, main_branch, self.manifest)

        if content is None:
            return None

        version = get_value(self._parse(content, "main branch"), self.keys)

        # A version that wasn't managed on main is treated as new
        if not isinstance(version, str):
            return None

        return str(version)

    def _load_current(self):
        return self._parse(
            get_local_file_content(self.manifest, self.log), "current branch"
        )

    def current_version(self):
        version = get_value(self._load_current(), self.keys)

        if not isinstance(version, str):
            raise VersionError(
                "No %s found in '%s'" % (".".join(self.keys), self.manifest)
            )

        return str(version)

    def write_version(self, version):
        doc = self._load_current()
        table = get_value(doc, self.keys[:-1])
        old = table[self.keys[-1]]

        table[self.keys[-1]] = tomlkit.string(
            version, literal=old.as_string().startswith("'")
        )

        try:
            with open(self.manifest, "w") as f:
                f.write(tomlkit.dumps(doc))
        except Exception as e:
            raise VersionError("Failed to write '%s': %s" % (self.manifest, e))

    def owns(self, path):
        return self.index.owner(path) in self.crate_dirs

    def pathspecs(self):
        specs = [d or "." for d in self.crate_dirs]

        # Nested crates have their own version
        for c in sorted(self.index.crates):
            if c not in self.crate_dirs and any(
                c != d and path_under_dir(c, d) for d in self.crate_dirs
            ):
                specs.append(":(exclude)%s" % c)

        return specs

    def finalize(self, autofix, log):
        """Make sure Cargo.lock has the same version as the manifest."""
        if not os.path.isfile(self.lock_path):
            log.debug("No %s found" % self.lock_path)

            return

        try:
            version = self.current_version()
        except VersionError:
            # Already reported by the version check
            return

        names = {self.index.crate_name(d) for d in self.crate_dirs}

        try:
            with open(self.lock_path) as f:
                lock = tomlkit.parse(f.read())
        except Exception as e:
            log.error("Failed to parse '%s': %s" % (self.lock_path, e))

            return 1

        stale = [
            p
            for p in lock.get("package", [])
            if "source" not in p and p.get("name") in names and p["version"] != version
        ]

        if not stale:
            return

        for p in stale:
            log.warning(
                "Version of '%s' in %s is %s but expected %s"
                % (p["name"], self.lock_path, p["version"], version)
            )

        if not autofix:
            log.error(
                "%s is out of sync; run 'cargo update --workspace' or use "
                "--autofix" % self.lock_path
            )

            return 1

        for p in stale:
            p["version"] = version

        try:
            with open(self.lock_path, "w") as f:
                f.write(tomlkit.dumps(lock))
        except Exception as e:
            log.error("Failed to write '%s': %s" % (self.lock_path, e))

            return 1

        log.info("Autofixed %s" % self.lock_path)

        return 127


class CargoPackageTarget(CargoTarget):
    def __init__(self, index, crate_dir, log):
        workspace_dir = index.workspace_dir(crate_dir)

        super().__init__(
            index,
            os.path.join(crate_dir, "Cargo.toml"),
            ("package", "version"),
            [crate_dir],
            crate_dir if workspace_dir is None else workspace_dir,
            log,
        )

        self.label = "crate: %s (%s)" % (index.crate_name(crate_dir), crate_dir or ".")


class CargoWorkspaceTarget(CargoTarget):
    def __init__(self, index, workspace_dir, log):
        super().__init__(
            index,
            os.path.join(workspace_dir, "Cargo.toml"),
            ("workspace", "package", "version"),
            index.inheriting_crates(workspace_dir),
            workspace_dir,
            log,
        )

        self.label = "workspace: %s (%s)" % (
            workspace_dir or ".",
            ", ".join(index.crate_name(d) for d in self.crate_dirs),
        )


def find_targets(repo, main_branch, paths, log):
    index = CargoIndex(repo, log)
    targets = {}

    for p in sorted(paths):
        rel = os.path.relpath(p, start=repo.working_tree_dir)
        crate_dir = index.owner(rel)

        if crate_dir is None:
            continue

        # A path of a whole crate deleted from the branch would otherwise be
        # attributed to the parent crate.
        if not os.path.exists(p):
            d = os.path.dirname(rel)
            deleted_crate = False

            while d != crate_dir and d is not None:
                if exists_on_branch(main_branch, os.path.join(d, "Cargo.toml")):
                    deleted_crate = True

                    break

                d = parent_dir(d)

            if deleted_crate:
                continue

        version = index.version(crate_dir)

        if isinstance(version, str):
            key = ("package", crate_dir)

            if key not in targets:
                targets[key] = CargoPackageTarget(index, crate_dir, log)
        elif is_workspace_inherited(version):
            workspace_dir = index.workspace_dir(crate_dir)

            if workspace_dir is None:
                log.error(
                    "Crate '%s' inherits the version but no workspace was found"
                    % crate_dir
                )

                continue

            key = ("workspace", workspace_dir)

            if key not in targets:
                targets[key] = CargoWorkspaceTarget(index, workspace_dir, log)
        else:
            log.debug("Crate '%s' has no version; skipping" % (crate_dir or "."))

    return list(targets.values())


def main():
    # Parse args
    args = parse_args()

    # Get logger
    log = get_logger(args.debug)

    run(
        args,
        log,
        lambda repo, main_branch, paths: find_targets(repo, main_branch, paths, log),
        include_deleted=True,
        include=args.include,
        exclude=args.exclude,
    )


if __name__ == "__main__":
    main()
