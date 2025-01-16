import argparse
import logging
import os
import semver
import sys

from git import Repo


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
        "-p",
        "--autofix-portion",
        metavar="NAME",
        help="wpecifies which semver portion should be autofixed (default: patch)",
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
        "-d",
        "--debug",
        help="debug output",
        action="store_true",
    )

    parser.add_argument(
        "PATH",
        help="files or directories",
        nargs="+",
    )

    # Parse args
    args = parser.parse_args()

    return args


def get_logger(debug):
    if debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    format = "[%(asctime)s] %(levelname)s: %(message)s"

    logging.basicConfig(level=level, format=format)

    return logging.getLogger(__name__)


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


def search_file(tree, path):
    blob = None

    for blob in tree.traverse():
        if blob.path == path:
            break

        if blob.type == "tree":
            search_file(blob, path)
    else:
        blob = None

    return blob


def get_file_content(repo, branch, path):
    tree = repo.tree(branch)

    blob = search_file(tree, path)
    content = None

    if blob is not None:
        content = blob.data_stream.read().decode("ascii").strip()

    return content


def get_local_file_content(path, log):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception as e:
        log.error("Failed to read file '%s' from the current branch: %s" % (path, e))

        sys.exit(1)


def check_version(
    repo, current_branch, main_branch, path, autofix, autofix_portion, log
):
    current_version = get_local_file_content(path, log)
    main_version = get_file_content(repo, main_branch, path)

    if main_version is None:
        log.info("It's a new directory")

        return

    if len(main_version) == 0:
        log.error("File in the main branch has no version")

        return 1

    if len(current_version) == 0:
        log.error("File in the current branch has no version")

        return 1

    try:
        comparison_result = semver.compare(main_version, current_version)
    except Exception as e:
        log.error("Failed to compare versions: %s" % e)

        return 1

    # Check if the main version is smaller than the current version
    if comparison_result == -1:
        log.info("Version was incremented (%s > %s)" % (current_version, main_version))
    else:
        log.warning(
            "Version wasn't incremented (%s <= %s)" % (current_version, main_version)
        )

        if autofix:
            log.info("Autofixing the %s portion of the version" % autofix_portion)

            if autofix_portion == "major":
                current_version = semver.bump_major(main_version)
            elif autofix_portion == "minor":
                current_version = semver.bump_minor(main_version)
            elif autofix_portion == "patch":
                current_version = semver.bump_patch(main_version)
            elif autofix_portion == "prerelease":
                current_version = semver.bump_prerelease(main_version)
            elif autofix_portion == "build":
                current_version = semver.bump_build(main_version)

            log.info("Autofixed version: %s" % current_version)

            try:
                with open(path, "w") as f:
                    f.write("%s\n" % current_version)
            except Exception as e:
                log.error("Failed to write into the version file: %s" % e)

        return 127


def main():
    # Parse args
    args = parse_args()

    # Get logger
    log = get_logger(args.debug)

    # Get list of directories containing the version file
    dirs = process_paths(args.PATH, args.version_file)

    # Create Git repo object and start querying all the details
    repo = Repo(args.PATH[0], search_parent_directories=True)

    # Current branch head
    current_branch = repo.head

    # Main branch name
    main_branch_name = args.branch
    main_branch = None

    # Get reference to the main branch head
    for i, head in enumerate(repo.heads):
        if head.name == main_branch_name:
            main_branch = repo.heads[i]

            break

    # Check that we found the main branch
    if main_branch is None:
        # If the branch wasn't found, try to find it on the remote
        remote = None

        for r in repo.remotes:
            if r.name == args.remote:
                remote = r

        if remote is not None:
            for ref in remote.refs:
                if ref.name == "%s/%s" % (args.remote, args.branch):
                    try:
                        main_branch = repo.create_head(ref.remote_head, ref)

                        break
                    except Exception as e:
                        log.error(
                            "Main branch '%s' not found. Failed to create head "
                            "from remote '%s': %s" % (args.branch, args.remote, e)
                        )

                        sys.exit(1)
            else:
                log.error(
                    "Main branch '%s' not found. Failed to find it "
                    "on the remote '%s'." % (args.branch, args.remote)
                )

                sys.exit(1)
        else:
            log.error(
                "Main branch '%s' not found. Couldn't find the remote '%s'."
                % (args.branch, args.remote)
            )

            sys.exit(1)

    final_status = 0
    dirs_cnt = len(dirs)

    # Process individual directories
    for i, d in enumerate(dirs):
        path = os.path.relpath(d, start=repo.working_tree_dir)

        log.info("Processing directory: %s" % os.path.dirname(path))

        status = check_version(
            repo,
            current_branch,
            main_branch,
            path,
            args.autofix,
            args.autofix_portion,
            log,
        )

        if final_status == 0 and status is not None:
            final_status = status

        if i + 1 < dirs_cnt:
            log.info("~~~")

    sys.exit(final_status)


if __name__ == "__main__":
    main()
