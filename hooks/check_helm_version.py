import argparse
import logging
import os
import semver
import sys
from ruamel.yaml import YAML

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
        description="Check whether the Helm chart version was incremented."
    )

    # Add script options
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
        help="Whether to automatically increment the version",
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
        help="Specifies which semver portion should be autofixed (default: patch)",
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
        help="chart files or directories",
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


def find_chart_dir(path):
    d = os.path.dirname(path)

    found = False

    # Search for Chart.yaml file up the filesystem tree
    while d != os.path.sep and len(d) > 0:
        if os.path.isfile(os.path.join(d, "Chart.yaml")):
            found = True

            break

        new_d = os.path.dirname(d)

        if new_d == d:
            d = ""
        else:
            d = new_d

    if found:
        return d


def process_paths(paths):
    charts = set()

    for p in map(os.path.abspath, paths):
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "Chart.yaml")):
            # It's a directory and contains Chart.yaml
            if p not in charts:
                charts.add(os.path.join(p, "Chart.yaml"))
        else:
            d = find_chart_dir(p)

            # Add the path if it found Chart.yaml in the tree
            if d is not None and d not in charts:
                charts.add(os.path.join(d, "Chart.yaml"))

    return charts


def check_fixed(yaml, repo, main_branch, path, autofix, autofix_portion, log):
    current_content = get_local_file_content(path, log)
    main_content = get_file_content(repo, main_branch, path)

    if main_content is None:
        log.info("It's a new chart")

        return

    try:
        main_yaml = yaml.load(main_content)
    except Exception as e:
        log.error("Failed to parse YAML file from the main branch: %s" % e)

        return 1

    try:
        current_yaml = yaml.load(current_content)
    except Exception as e:
        log.error("Failed to parse YAML file from the current branch: %s" % e)

        return 1

    if "version" not in main_yaml:
        log.error("File in the main branch has no version")

        return 1

    if "version" not in current_yaml:
        log.error("File in the current branch has no version")

        return 1

    try:
        comparison_result = semver.compare(
            main_yaml["version"], current_yaml["version"]
        )
    except Exception as e:
        log.error("Failed to compare versions: %s" % e)

        return 1

    # Check if the main version is smaller than the current version
    if comparison_result == -1:
        log.info(
            "Version was incremented (%s > %s)"
            % (current_yaml["version"], main_yaml["version"])
        )
    else:
        log.warning(
            "Version wasn't incremented (%s <= %s)"
            % (current_yaml["version"], main_yaml["version"])
        )

        if autofix:
            log.info("Autofixing the %s portion of the version" % autofix_portion)

            if autofix_portion == "major":
                current_yaml["version"] = semver.bump_major(main_yaml["version"])
            elif autofix_portion == "minor":
                current_yaml["version"] = semver.bump_minor(main_yaml["version"])
            elif autofix_portion == "patch":
                current_yaml["version"] = semver.bump_patch(main_yaml["version"])
            elif autofix_portion == "prerelease":
                current_yaml["version"] = semver.bump_prerelease(main_yaml["version"])
            elif autofix_portion == "build":
                current_yaml["version"] = semver.bump_build(main_yaml["version"])

            log.info("Autofixed version: %s" % current_yaml["version"])

            try:
                with open(path, "w") as f:
                    yaml.dump(current_yaml, f)
            except Exception as e:
                log.error("Failed to write YAML file: %s" % e)

        return 127


def check_conventional(
    yaml,
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
    current_content = get_local_file_content(path, log)
    main_content = get_file_content(repo, main_branch, path)

    if main_content is None:
        baseline = "0.0.0"

        log.info("Chart does not exist on main; using 0.0.0 as baseline")
    else:
        try:
            main_yaml = yaml.load(main_content)
        except Exception as e:
            log.error("Failed to parse YAML file from the main branch: %s" % e)

            return 1

        if "version" not in main_yaml:
            log.error("File in the main branch has no version")

            return 1

        baseline = main_yaml["version"]

    try:
        current_yaml = yaml.load(current_content)
    except Exception as e:
        log.error("Failed to parse YAML file from the current branch: %s" % e)

        return 1

    if "version" not in current_yaml:
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
                "%s in range %s..%s for chart '%s' (including the "
                "in-flight message)."
                % (reason.capitalize(), main_branch.name, current_branch.name, dir_path)
            )

            return 1

        log.info(
            "Only no-bump Conventional Commits messages found; no version "
            "change required (current: %s)" % current_yaml["version"]
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
        cmp = semver.compare(current_yaml["version"], expected)
    except Exception as e:
        log.error("Failed to compare versions: %s" % e)

        return 1

    if cmp == 0:
        log.info("Version matches the expected: %s" % current_yaml["version"])

        return

    if cmp > 0:
        log.info(
            "Version %s is above the expected %s; accepting manual bump"
            % (current_yaml["version"], expected)
        )

        return

    log.warning(
        "Version is %s but expected at least %s based on commit messages"
        % (current_yaml["version"], expected)
    )

    if autofix:
        log.info("Autofixing version to %s" % expected)

        current_yaml["version"] = expected

        try:
            with open(path, "w") as f:
                yaml.dump(current_yaml, f)
        except Exception as e:
            log.error("Failed to write YAML file: %s" % e)

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

    # YAML reader/writer
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    # Create Git repo object and start querying all the details
    repo = Repo(os.getcwd(), search_parent_directories=True)

    # Current branch head
    current_branch = repo.head

    # Resolve main branch
    main_branch = find_main_branch(repo, args.branch, args.remote, log)

    # Determine the set of charts to check based on the stage
    if commit_msg_stage:
        candidate_paths = changed_paths_since_main(repo, main_branch)
        charts = process_paths(candidate_paths)

        try:
            with open(args.PATH[0]) as f:
                in_flight_message = f.read()
        except Exception as e:
            log.error("Failed to read commit message file '%s': %s" % (args.PATH[0], e))

            sys.exit(1)
    else:
        charts = process_paths(args.PATH)
        in_flight_message = None

    final_status = 0
    charts_cnt = len(charts)

    # Process individual charts
    for i, chart in enumerate(charts):
        path = os.path.relpath(chart, start=repo.working_tree_dir)
        dir_path = os.path.dirname(path)

        log.info("Processing chart: %s" % dir_path)

        if args.autofix_strategy == "conventional":
            status = check_conventional(
                yaml,
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
                yaml,
                repo,
                main_branch,
                path,
                args.autofix,
                args.autofix_portion,
                log,
            )

        if final_status == 0 and status is not None:
            final_status = status

        if i + 1 < charts_cnt:
            log.info("~~~")

    sys.exit(final_status)


if __name__ == "__main__":
    main()
