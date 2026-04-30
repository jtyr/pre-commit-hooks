import argparse
import logging
import os
import semver
import sys

from git import Repo

from hooks.common.conventional import bump_from_messages
from hooks.common.get_file_content import (
    get_file_content,
    get_local_file_content,
)
from hooks.common.git_helpers import (
    changed_paths_since_main,
    find_main_branch,
    is_commit_msg_invocation,
    iter_commit_messages,
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


def check_fixed(repo, main_branch, path, autofix, autofix_portion, log):
    current_version = get_local_file_content(path, log).strip()
    main_content = get_file_content(repo, main_branch, path)
    main_version = main_content.strip() if main_content is not None else None

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


def check_conventional(
    repo,
    main_branch,
    current_branch,
    path,
    dir_path,
    in_flight_message,
    autofix,
    conventional_strict,
    log,
):
    main_content = get_file_content(repo, main_branch, path)

    if main_content is None:
        baseline = "0.0.0"

        log.info("Version file does not exist on main; using 0.0.0 as baseline")
    else:
        baseline = main_content.strip()

    if len(baseline) == 0:
        log.error("File in the main branch has no version")

        return 1

    current_version = get_local_file_content(path, log).strip()

    if len(current_version) == 0:
        log.error("File in the current branch has no version")

        return 1

    messages = list(
        iter_commit_messages(repo, main_branch, current_branch, dir_path=dir_path)
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
                "%s in range %s..%s for directory '%s' (including the "
                "in-flight message)."
                % (reason.capitalize(), main_branch.name, current_branch.name, dir_path)
            )

            return 1

        # Non-strict mode with at least one valid CC message but no bump
        # required: accept whatever the current version is.
        log.info(
            "Only no-bump Conventional Commits messages found; no version "
            "change required (current: %s)" % current_version
        )

        return

    if portion == "major":
        expected = semver.bump_major(baseline)
    elif portion == "minor":
        expected = semver.bump_minor(baseline)
    elif portion == "patch":
        expected = semver.bump_patch(baseline)

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

        try:
            with open(path, "w") as f:
                f.write("%s\n" % expected)
        except Exception as e:
            log.error("Failed to write into the version file: %s" % e)

    return 127


def main():
    # Parse args
    args = parse_args()

    # Get logger
    log = get_logger(args.debug)

    commit_msg_stage = is_commit_msg_invocation(args.PATH)

    # Behavior matrix:
    #   fixed strategy is only relevant at the pre-commit stage.
    #   conventional strategy is only relevant at the commit-msg stage.
    if args.autofix_strategy == "fixed" and commit_msg_stage:
        return

    if args.autofix_strategy == "conventional" and not commit_msg_stage:
        return

    # Create Git repo object and start querying all the details
    repo = Repo(os.getcwd(), search_parent_directories=True)

    # Current branch head
    current_branch = repo.head

    # Resolve main branch
    main_branch = find_main_branch(repo, args.branch, args.remote, log)

    # Determine the set of version files to check based on the stage
    if commit_msg_stage:
        # commit-msg stage: derive candidate paths from changes since main
        candidate_paths = changed_paths_since_main(repo, main_branch)
        dirs = process_paths(candidate_paths, args.version_file)

        # Read the in-flight commit message
        try:
            with open(args.PATH[0]) as f:
                in_flight_message = f.read()
        except Exception as e:
            log.error("Failed to read commit message file '%s': %s" % (args.PATH[0], e))

            sys.exit(1)
    else:
        # pre-commit stage: dirs come from the staged file paths
        dirs = process_paths(args.PATH, args.version_file)
        in_flight_message = None

    final_status = 0
    dirs_cnt = len(dirs)

    # Process individual directories
    for i, d in enumerate(dirs):
        path = os.path.relpath(d, start=repo.working_tree_dir)
        dir_path = os.path.dirname(path)

        log.info("Processing directory: %s" % dir_path)

        if args.autofix_strategy == "conventional":
            status = check_conventional(
                repo,
                main_branch,
                current_branch,
                path,
                dir_path,
                in_flight_message,
                args.autofix,
                args.conventional_strict,
                log,
            )
        else:
            status = check_fixed(
                repo,
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
