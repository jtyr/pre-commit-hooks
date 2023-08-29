import argparse
import logging
import os
import sys
import yaml

from git import Repo
from packaging import version


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
    charts = []

    for p in map(os.path.abspath, paths):
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "Chart.yaml")):
            # It's a directory and contains Chart.yaml
            if p not in charts:
                charts.append(os.path.join(p, "Chart.yaml"))
        else:
            d = find_chart_dir(p)

            # Add the path if it found Chart.yaml in the tree
            if d is not None and d not in charts:
                charts.append(os.path.join(d, "Chart.yaml"))

    return charts


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
        content = blob.data_stream.read().decode("ascii")

    return content


def check_chart(repo, current_branch, main_branch, path, log):
    current_content = get_file_content(repo, current_branch, path)
    main_content = get_file_content(repo, main_branch, path)

    if main_content is None:
        log.info("It's a new chart")

        return

    try:
        main_yaml = yaml.safe_load(main_content)
    except Exception as e:
        log.error("Failed to parse YAML file from the main branch: %s" % e)

        sys.exit(1)

    try:
        current_yaml = yaml.safe_load(current_content)
    except Exception as e:
        log.error("Failed to parse YAML file from the current branch: %s" % e)

        sys.exit(1)

    if "version" not in main_yaml:
        log.error("File in the main branch has no version")

        sys.exit(1)

    if "version" not in current_yaml:
        log.error("File in the current branch has no version")

        sys.exit(1)

    try:
        main_version = version.parse(main_yaml["version"])
    except Exception as e:
        log.error("Failed to parse version from main branch: %s" % e)

        sys.exit(1)

    try:
        current_version = version.parse(current_yaml["version"])
    except Exception as e:
        log.error("Failed to parse version from current branch: %s" % e)

        sys.exit(1)

    if main_version >= current_version:
        log.warning(
            "Version wasn't bumped (%s >= %s)"
            % (main_yaml["version"], current_yaml["version"])
        )

        sys.exit(127)
    else:
        log.info(
            "Version bumped (%s < %s)" % (main_yaml["version"], current_yaml["version"])
        )


def main():
    # Parse args
    args = parse_args()

    # Get logger
    log = get_logger(args.debug)

    # Get list of charts
    charts = process_paths(args.PATH)

    # Create Git repo object and start querying all the details
    repo = Repo(args.PATH[0], search_parent_directories=True)

    # Current branch name
    current_branch = repo.active_branch

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
        log.error("Main branch not found")

        sys.exit(1)

    # Process individual charts
    for chart in charts:
        path = os.path.relpath(chart, start=repo.working_tree_dir)

        log.info("Processing chart: %s" % os.path.dirname(path))

        check_chart(repo, current_branch, main_branch, path, log)


if __name__ == "__main__":
    main()
