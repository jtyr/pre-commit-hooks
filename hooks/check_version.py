import argparse
import os

from hooks.common.get_file_content import (
    get_file_content,
    get_local_file_content,
)
from hooks.common.git_helpers import (  # noqa: F401
    changed_paths_since_main,
    path_under_dir,
)
from hooks.common.version_check import (
    VersionError,
    VersionTarget,
    add_common_args,
    get_logger,
    run,
)


def parse_args():
    # Define parser
    parser = argparse.ArgumentParser(
        description="Check whether the semantic version in a plain text file was incremented."
    )

    # Add script options
    parser.add_argument(
        "-v",
        "--version-file",
        metavar="NAME",
        help="name of the plain text file that holds the semantic version (default: .version)",
        default=".version",
    )
    add_common_args(parser)

    parser.add_argument(
        "PATH",
        help="files or directories",
        nargs="+",
    )

    # Parse args
    args = parser.parse_args()

    return args


def find_version_dir(path, version_file):
    d = os.path.dirname(path)

    found = False

    # Search for the version file up the filesystem tree
    while d != os.path.sep and len(d) > 0:
        if os.path.isfile(os.path.join(d, version_file)):
            found = True

            break

        new_d = os.path.dirname(d)

        if new_d == d:
            d = ""
        else:
            d = new_d

    if found:
        return d


def process_paths(paths, version_file):
    dirs = set()

    for p in map(os.path.abspath, paths):
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, version_file)):
            # It's a directory and contains the version file
            if p not in dirs:
                dirs.add(os.path.join(p, version_file))
        else:
            d = find_version_dir(p, version_file)

            # Add the path if it found the version file in the tree
            if d is not None and d not in dirs:
                dirs.add(os.path.join(d, version_file))

    return dirs


class VersionFileTarget(VersionTarget):
    def __init__(self, path, log):
        self.path = path
        self.dir_path = os.path.dirname(path)
        self.label = "directory: %s" % self.dir_path
        self.log = log

    def main_version(self, repo, main_branch):
        content = get_file_content(repo, main_branch, self.path)

        if content is None:
            return None

        version = content.strip()

        if len(version) == 0:
            raise VersionError("File in the main branch has no version")

        return version

    def current_version(self):
        version = get_local_file_content(self.path, self.log).strip()

        if len(version) == 0:
            raise VersionError("File in the current branch has no version")

        return version

    def write_version(self, version):
        try:
            with open(self.path, "w") as f:
                f.write("%s\n" % version)
        except Exception as e:
            raise VersionError("Failed to write into the version file: %s" % e)

    def owns(self, path):
        return path_under_dir(path, self.dir_path)

    def pathspecs(self):
        return self.dir_path or None


def main():
    # Parse args
    args = parse_args()

    # Get logger
    log = get_logger(args.debug)

    def find_targets(repo, main_branch, paths):
        return [
            VersionFileTarget(os.path.relpath(f, start=repo.working_tree_dir), log)
            for f in sorted(process_paths(paths, args.version_file))
        ]

    run(args, log, find_targets)


if __name__ == "__main__":
    main()
