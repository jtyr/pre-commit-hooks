import logging
import os
import re
import semver
import sys

from git import Repo

from hooks.common.conventional import bump_from_messages
from hooks.common.git_helpers import (
    changed_paths_since_main,
    find_main_branch,
    is_commit_msg_invocation,
    is_validation_invocation,
    iter_commit_messages,
    staged_paths,
)


class VersionError(Exception):
    """Raised by a version target when the version can't be read or written."""


class VersionTarget:
    """A single version that the hook checks and possibly bumps.

    Subclasses define where the version is stored and which paths belong to
    it. All paths are relative to the repo root.
    """

    label = None

    def main_version(self, repo, main_branch):
        """Return the version from the main branch or None if it's new."""
        raise NotImplementedError

    def current_version(self):
        raise NotImplementedError

    def write_version(self, version):
        raise NotImplementedError

    def owns(self, path):
        """Whether a change of `path` belongs to this version."""
        raise NotImplementedError

    def pathspecs(self):
        """Git pathspecs used to filter commit messages (None for no filter)."""
        raise NotImplementedError

    def finalize(self, autofix, log):
        """Extra check run after the version check. Returns a status or None."""
        return None


def add_common_args(parser):
    parser.add_argument(
        "-b",
        "--branch",
        metavar="NAME",
        help="branch to compare the version agains (default: main)",
        default="main",
    )
    parser.add_argument(
        "-r",
        "--remote",
        metavar="NAME",
        help="remote name where the main branch exists (default: origin)",
        default="origin",
    )
    parser.add_argument(
        "-a",
        "--autofix",
        help="whether to automatically increment the version",
        action="store_true",
    )
    parser.add_argument(
        "-s",
        "--autofix-strategy",
        metavar="NAME",
        help=(
            "strategy used to determine the version bump: 'fixed' uses "
            "--autofix-portion, 'conventional' derives the bump from "
            "Conventional Commits messages (default: fixed)"
        ),
        choices=["fixed", "conventional"],
        default="fixed",
    )
    parser.add_argument(
        "-p",
        "--autofix-portion",
        metavar="NAME",
        help="specifies which semver portion should be autofixed (default: patch)",
        choices=[
            "major",
            "minor",
            "patch",
            "prerelease",
            "build",
        ],
        default="patch",
    )
    parser.add_argument(
        "--conventional-strict",
        help=(
            "with --autofix-strategy=conventional, fail unless at least one "
            "Conventional Commits message qualifies for a version bump. "
            "When not set (default), valid Conventional Commits messages "
            "with no-bump types (chore, docs, style, refactor, revert, "
            "test, build, ci) are accepted without changing the version."
        ),
        action="store_true",
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="debug output",
        action="store_true",
    )


def get_logger(debug, name=__name__):
    if debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    format = "[%(asctime)s] %(levelname)s: %(message)s"

    logging.basicConfig(level=level, format=format)

    return logging.getLogger(name)


def bump_version(version, portion):
    if portion == "major":
        return semver.bump_major(version)
    elif portion == "minor":
        return semver.bump_minor(version)
    elif portion == "patch":
        return semver.bump_patch(version)
    elif portion == "prerelease":
        return semver.bump_prerelease(version)
    elif portion == "build":
        return semver.bump_build(version)


def _write_version(target, version, log):
    try:
        target.write_version(version)
    except VersionError as e:
        log.error("%s" % e)


def check_fixed(target, repo, main_branch, autofix, autofix_portion, log):
    try:
        main_version = target.main_version(repo, main_branch)
    except VersionError as e:
        log.error("%s" % e)

        return 1

    if main_version is None:
        log.info("It's new on the main branch")

        return

    try:
        current_version = target.current_version()
    except VersionError as e:
        log.error("%s" % e)

        return 1

    try:
        comparison_result = semver.compare(main_version, current_version)
    except Exception as e:
        log.error("Failed to compare versions: %s" % e)

        return 1

    # Check if the main version is smaller than the current version
    if comparison_result == -1:
        log.info("Version was incremented (%s > %s)" % (current_version, main_version))

        return

    log.warning(
        "Version wasn't incremented (%s <= %s)" % (current_version, main_version)
    )

    if autofix:
        log.info("Autofixing the %s portion of the version" % autofix_portion)

        current_version = bump_version(main_version, autofix_portion)

        log.info("Autofixed version: %s" % current_version)

        _write_version(target, current_version, log)

    return 127


def check_conventional(
    target,
    repo,
    main_branch,
    current_branch,
    in_flight_message,
    autofix,
    conventional_strict,
    log,
    path_filter=None,
):
    try:
        baseline = target.main_version(repo, main_branch)
    except VersionError as e:
        log.error("%s" % e)

        return 1

    if baseline is None:
        baseline = "0.0.0"

        log.info("Version does not exist on main; using 0.0.0 as baseline")

    try:
        current_version = target.current_version()
    except VersionError as e:
        log.error("%s" % e)

        return 1

    messages = list(
        iter_commit_messages(
            repo,
            main_branch,
            current_branch,
            dir_path=target.pathspecs(),
            path_filter=(
                None
                if path_filter is None
                else lambda p: path_filter(p) and target.owns(p)
            ),
        )
    )

    if in_flight_message:
        messages.append(in_flight_message)

    portion, has_valid_cc = bump_from_messages(messages)

    if portion is None:
        if conventional_strict or not has_valid_cc:
            reason = (
                "no Conventional Commits message qualifying for a version bump"
                if conventional_strict
                else "no Conventional Commits messages found at all"
            )

            log.error(
                "%s in range %s..%s for %s (including the in-flight message)."
                % (
                    reason.capitalize(),
                    main_branch.name,
                    current_branch.name,
                    target.label,
                )
            )

            return 1

        # Non-strict mode with at least one valid CC message but no bump
        # required: accept whatever the current version is.
        log.info(
            "Only no-bump Conventional Commits messages found; no version "
            "change required (current: %s)" % current_version
        )

        return

    expected = bump_version(baseline, portion)

    log.info(
        "Conventional Commits bump '%s' from baseline %s -> expected at least %s"
        % (portion, baseline, expected)
    )

    try:
        cmp = semver.compare(current_version, expected)
    except Exception as e:
        log.error("Failed to compare versions: %s" % e)

        return 1

    if cmp == 0:
        log.info("Version matches the expected: %s" % current_version)

        return

    if cmp > 0:
        log.info(
            "Version %s is above the expected %s; accepting manual bump"
            % (current_version, expected)
        )

        return

    log.warning(
        "Version is %s but expected at least %s based on commit messages"
        % (current_version, expected)
    )

    if autofix:
        log.info("Autofixing version to %s" % expected)

        _write_version(target, expected, log)

    return 127


def path_matches(path, include=None, exclude=None):
    """Whether the repo-relative path passes the include/exclude regexps."""
    if include is not None and not re.search(include, path):
        return False

    if exclude is not None and re.search(exclude, path):
        return False

    return True


def filter_paths(paths, repo, include=None, exclude=None):
    """Filter absolute paths by regexps matched against repo-relative paths."""
    return {
        p
        for p in paths
        if path_matches(
            os.path.relpath(p, start=repo.working_tree_dir), include, exclude
        )
    }


def run(args, log, find_targets, include_deleted=False, include=None, exclude=None):
    """Run the version check for all targets found from the changed paths.

    `find_targets(repo, main_branch, paths)` receives absolute paths and
    returns a list of `VersionTarget` objects. Exits with the final status.
    """
    commit_msg_stage = is_commit_msg_invocation(args.PATH)
    validation_mode = is_validation_invocation()

    # Behavior matrix:
    #   fixed strategy: only at the pre-commit stage.
    #   conventional strategy: at the commit-msg stage, or at the pre-commit
    #     stage when pre-commit was invoked with --from-ref/--to-ref (or at
    #     the pre-push stage) -- i.e. a branch-wide validation run.
    if args.autofix_strategy == "fixed" and commit_msg_stage:
        return

    if (
        args.autofix_strategy == "conventional"
        and not commit_msg_stage
        and not validation_mode
    ):
        return

    # Create Git repo object and start querying all the details
    repo = Repo(os.getcwd(), search_parent_directories=True)

    # Current branch head
    current_branch = repo.head

    # Resolve main branch
    main_branch = find_main_branch(repo, args.branch, args.remote, log)

    in_flight_message = None
    in_flight_touched = set()

    if commit_msg_stage:
        # commit-msg stage: derive candidate paths from changes since main
        paths = changed_paths_since_main(repo, main_branch)

        try:
            with open(args.PATH[0]) as f:
                in_flight_message = f.read()
        except Exception as e:
            log.error("Failed to read commit message file '%s': %s" % (args.PATH[0], e))

            sys.exit(1)

        # Paths that the in-flight commit actually touches -- used to scope
        # the in-flight message to only the relevant targets.
        in_flight_touched = {
            os.path.relpath(p, start=repo.working_tree_dir)
            for p in filter_paths(
                {os.path.join(repo.working_tree_dir, p) for p in staged_paths(repo)},
                repo,
                include,
                exclude,
            )
        }
    else:
        paths = set(map(os.path.abspath, args.PATH))

        # pre-commit's default file list excludes deleted paths, so a
        # deletion-only commit would otherwise never reach find_targets.
        if include_deleted:
            for p in changed_paths_since_main(repo, main_branch):
                if not os.path.exists(p):
                    paths.add(p)

    paths = filter_paths(paths, repo, include, exclude)
    targets = find_targets(repo, main_branch, paths)

    final_status = 0
    targets_cnt = len(targets)

    for i, target in enumerate(targets):
        log.info("Processing %s" % target.label)

        if args.autofix_strategy == "conventional":
            # Only attach the in-flight message to targets the in-flight
            # commit actually touched (otherwise a feat: commit for target A
            # would spuriously bump target B).
            target_in_flight = (
                in_flight_message
                if in_flight_message and any(target.owns(p) for p in in_flight_touched)
                else None
            )

            status = check_conventional(
                target,
                repo,
                main_branch,
                current_branch,
                target_in_flight,
                args.autofix,
                args.conventional_strict,
                log,
                path_filter=(
                    None
                    if include is None and exclude is None
                    else lambda p: path_matches(p, include, exclude)
                ),
            )
        else:
            status = check_fixed(
                target,
                repo,
                main_branch,
                args.autofix,
                args.autofix_portion,
                log,
            )

        if final_status == 0 and status is not None:
            final_status = status

        status = target.finalize(args.autofix, log)

        if final_status == 0 and status is not None:
            final_status = status

        if i + 1 < targets_cnt:
            log.info("~~~")

    sys.exit(final_status)
