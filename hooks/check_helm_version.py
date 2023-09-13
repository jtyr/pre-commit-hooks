import argparse
import logging
import os
import semver
import sys
from ruamel.yaml import YAML

from git import Repo


# Global variables
yaml = YAML()


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


def get_local_file_content(path, log):
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        log.error("Failed to read file '%s' from the current branch: %s" % (path, e))

        sys.exit(1)


def check_chart(
    yaml, repo, current_branch, main_branch, path, autofix, autofix_portion, log
):
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
                current_yaml["version"] = semver.bump_major(current_yaml["version"])
            elif autofix_portion == "minor":
                current_yaml["version"] = semver.bump_minor(current_yaml["version"])
            elif autofix_portion == "patch":
                current_yaml["version"] = semver.bump_patch(current_yaml["version"])
            elif autofix_portion == "prerelease":
                current_yaml["version"] = semver.bump_prerelease(
                    current_yaml["version"]
                )
            elif autofix_portion == "build":
                current_yaml["version"] = semver.bump_build(current_yaml["version"])

            log.info("Autofixed version: %s" % current_yaml["version"])

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

    # Get list of charts
    charts = process_paths(args.PATH)

    # YAML reader/writer
    yaml = YAML()

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
    charts_cnt = len(charts)

    # Process individual charts
    for i, chart in enumerate(charts):
        path = os.path.relpath(chart, start=repo.working_tree_dir)

        log.info("Processing chart: %s" % os.path.dirname(path))

        status = check_chart(
            yaml,
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

        if i + 1 < charts_cnt:
            log.info("~~~")

    sys.exit(final_status)


if __name__ == "__main__":
    main()
