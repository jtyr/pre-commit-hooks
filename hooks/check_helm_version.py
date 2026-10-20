import argparse
import os
from ruamel.yaml import YAML

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
        description="Check whether the Helm chart version was incremented."
    )

    # Add script options
    add_common_args(parser)

    parser.add_argument(
        "PATH",
        help="chart files or directories",
        nargs="*",
    )

    # Parse args
    args = parser.parse_args()

    return args


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


class ChartTarget(VersionTarget):
    def __init__(self, yaml, path, log):
        self.yaml = yaml
        self.path = path
        self.dir_path = os.path.dirname(path)
        self.label = "chart: %s" % self.dir_path
        self.log = log

    def main_version(self, repo, main_branch):
        content = get_file_content(repo, main_branch, self.path)

        if content is None:
            return None

        try:
            data = self.yaml.load(content)
        except Exception as e:
            raise VersionError("Failed to parse YAML file from the main branch: %s" % e)

        if "version" not in data:
            raise VersionError("File in the main branch has no version")

        return data["version"]

    def _load_current(self):
        content = get_local_file_content(self.path, self.log)

        try:
            return self.yaml.load(content)
        except Exception as e:
            raise VersionError(
                "Failed to parse YAML file from the current branch: %s" % e
            )

    def current_version(self):
        data = self._load_current()

        if "version" not in data:
            raise VersionError("File in the current branch has no version")

        return data["version"]

    def write_version(self, version):
        data = self._load_current()
        data["version"] = version

        try:
            with open(self.path, "w") as f:
                self.yaml.dump(data, f)
        except Exception as e:
            raise VersionError("Failed to write YAML file: %s" % e)

    def owns(self, path):
        return path_under_dir(path, self.dir_path)

    def pathspecs(self):
        return self.dir_path or None


def main():
    # Parse args
    args = parse_args()

    # Get logger
    log = get_logger(args.debug)

    # YAML reader/writer
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    def find_targets(repo, main_branch, paths):
        return [
            ChartTarget(yaml, os.path.relpath(chart, start=repo.working_tree_dir), log)
            for chart in sorted(process_paths(paths))
        ]

    # Deleted paths are included so that find_chart_dir can walk up to the
    # still-existing Chart.yaml and include the chart in the check.
    run(args, log, find_targets, include_deleted=True)


if __name__ == "__main__":
    main()
