import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run Helm unittest on changed Helm charts."
    )

    parser.add_argument(
        "-c",
        "--charts-dir",
        metavar="DIR",
        help="directory containing Helm charts (default: charts)",
        default="charts",
    )
    parser.add_argument(
        "-t",
        "--tests-path",
        metavar="PATH",
        help="relative path to test files within chart (default: tests/unittest)",
        default="tests/unittest",
    )
    parser.add_argument(
        "-f",
        "--test-files",
        metavar="PATTERN",
        help="glob pattern for test files (default: *.yaml)",
        default="*.yaml",
    )
    parser.add_argument(
        "--failfast",
        help="stop on first test failure",
        action="store_true",
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="enable debug output",
        action="store_true",
    )
    parser.add_argument(
        "--path-sub-pattern",
        metavar="PATTERN",
        help="regexp substitution pattern for chart paths (format: 'pattern,replacement') (default: ^charts/(libchart),helper-charts/\\1)",
        default="^charts/(libchart),helper-charts/\\1",
    )

    parser.add_argument(
        "files",
        nargs="*",
        help="files that have changed (provided by pre-commit)",
    )

    return parser.parse_args()


def get_logger(debug):
    """Set up logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    format_str = "[%(asctime)s] %(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=format_str)
    return logging.getLogger(__name__)


def apply_path_substitution(chart_path, path_sub_pattern, log):
    """
    Apply path substitution pattern to chart path for library charts.

    Args:
        chart_path: Original chart path
        path_sub_pattern: Substitution pattern in format 'pattern,replacement'
        log: Logger instance

    Returns:
        Tuple of (substituted_path, use_helper_chart_tests)
    """
    if not path_sub_pattern:
        return chart_path, False

    try:
        # Parse the substitution pattern
        if "," not in path_sub_pattern:
            log.error(
                f"Invalid path substitution pattern: '{path_sub_pattern}'. Expected format: 'pattern,replacement'"
            )
            return chart_path, False

        pattern, replacement = path_sub_pattern.split(",", 1)

        # Convert Path to string for regex operations
        chart_path_str = str(chart_path)

        # Apply substitution
        substituted_path_str = re.sub(pattern, replacement, chart_path_str)

        if substituted_path_str != chart_path_str:
            substituted_path = Path(substituted_path_str)
            log.debug(f"Path substitution applied: {chart_path} -> {substituted_path}")

            # For library charts, tests should be in the helper chart, not the original chart
            return substituted_path, True
        else:
            log.debug(f"No path substitution needed for: {chart_path}")
            return chart_path, False

    except re.error as e:
        log.error(f"Invalid regex pattern in path substitution: {e}")
        return chart_path, False


def find_chart_directories(changed_files, charts_dir, log):
    """
    Find all Helm chart directories that contain changed files.

    Args:
        changed_files: List of file paths that have changed
        charts_dir: Base directory containing Helm charts
        log: Logger instance

    Returns:
        Set of chart directory paths
    """
    chart_dirs = set()
    charts_path = Path(charts_dir)

    log.debug(f"Looking for charts in directory: {charts_path.absolute()}")
    log.debug(f"Changed files: {changed_files}")

    for file_path in changed_files:
        file_path = Path(file_path)
        log.debug(f"Processing file: {file_path}")

        # Check if the file is under the charts directory
        try:
            relative_path = file_path.relative_to(charts_path)
            log.debug(f"File is under charts dir, relative path: {relative_path}")

            # Find the chart directory by looking for Chart.yaml
            current_dir = charts_path / relative_path.parts[0]

            # Traverse up from the file location to find Chart.yaml
            for parent in [current_dir] + list(current_dir.parents):
                if parent == charts_path:
                    break

                chart_yaml = parent / "Chart.yaml"
                if chart_yaml.exists():
                    log.debug(f"Found Chart.yaml in: {parent}")
                    chart_dirs.add(parent)
                    break

        except ValueError:
            # File is not under charts directory, check if it might be a chart itself
            log.debug(f"File not under charts dir: {file_path}")

            # Check if any parent directory contains Chart.yaml
            for parent in [file_path.parent] + list(file_path.parents):
                chart_yaml = parent / "Chart.yaml"
                if chart_yaml.exists():
                    log.debug(f"Found Chart.yaml in: {parent}")
                    chart_dirs.add(parent)
                    break

    log.info(f"Found {len(chart_dirs)} chart directories with changes")
    for chart_dir in sorted(chart_dirs):
        log.info(f"  - {chart_dir}")

    return chart_dirs


def check_helm_unittest_available():
    """Check if helm unittest plugin is available."""
    try:
        subprocess.run(
            ["helm", "unittest", "--help"], capture_output=True, text=True, check=True
        )

        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def has_dependencies(chart_path):
    """Return True if the chart's Chart.yaml declares any dependencies."""
    chart_yaml = chart_path / "Chart.yaml"
    if not chart_yaml.is_file():
        return False
    with open(chart_yaml) as f:
        for line in f:
            if re.match(r"^dependencies:", line):
                return True
    return False


def ensure_dependencies(chart_path, log):
    """
    Run `helm dependency update` if the chart declares dependencies but the
    `charts/` subdirectory is missing.
    """
    if not has_dependencies(chart_path):
        return True
    if (chart_path / "charts").is_dir():
        return True

    log.info(f"Running helm dependency update for chart: {chart_path.name}")
    try:
        subprocess.run(
            ["helm", "dependency", "update", str(chart_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"helm dependency update failed for chart: {chart_path.name}")
        log.error("STDOUT:")
        log.error(e.stdout)
        log.error("STDERR:")
        log.error(e.stderr)
        return False


def run_helm_unittest(
    chart_dir, tests_path, test_files, failfast, path_sub_pattern, log
):
    """
    Run helm unittest on a specific chart directory.

    Args:
        chart_dir: Path to the chart directory
        tests_path: Relative path to test files within chart
        test_files: Glob pattern for test files
        failfast: Whether to stop on first failure
        path_sub_pattern: Path substitution pattern for library charts
        log: Logger instance

    Returns:
        True if tests passed, False otherwise
    """
    chart_path = Path(chart_dir)

    # Apply path substitution if specified (for library charts)
    actual_chart_path, use_helper_chart_tests = apply_path_substitution(
        chart_path, path_sub_pattern, log
    )

    # Determine where to look for tests
    tests_dir = actual_chart_path / tests_path

    # Check if tests directory exists
    if not tests_dir.exists():
        log.warning(f"Tests directory not found: {tests_dir}")
        log.warning(f"Skipping unittest for chart: {chart_path.name}")
        return True

    # Check if there are any test files
    test_file_list = list(tests_dir.glob(test_files))

    if not test_file_list:
        log.warning(
            f"No test files found matching pattern '{test_files}' in: {tests_dir}"
        )
        log.warning(f"Skipping unittest for chart: {chart_path.name}")
        return True

    log.info(f"Running helm unittest for chart: {chart_path.name}")
    log.debug(f"Original chart directory: {chart_path}")
    log.debug(f"Actual chart directory for testing: {actual_chart_path}")
    log.debug(f"Tests directory: {tests_dir}")
    if use_helper_chart_tests:
        log.debug("Using tests from helper chart location due to path substitution")
    log.debug(f"Test files found: {[f.name for f in test_file_list]}")

    # Ensure subchart dependencies are built before running the tests
    if not ensure_dependencies(actual_chart_path, log):
        return False

    # Build the helm unittest command
    cmd = ["helm", "unittest"]

    if failfast:
        cmd.append("--failfast")

    # Specify test file pattern
    cmd.extend(["-f", f"{tests_path}/{test_files}"])

    # Add the actual chart directory (which might be substituted)
    cmd.append(str(actual_chart_path))

    log.debug(f"Running command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        log.info(f"✓ Tests passed for chart: {chart_path.name}")
        if log.level == logging.DEBUG:
            log.debug("STDOUT:")
            log.debug(result.stdout)

        return True

    except subprocess.CalledProcessError as e:
        log.error(f"✗ Tests failed for chart: {chart_path.name}")
        log.error("STDOUT:")
        log.error(e.stdout)
        log.error("STDERR:")
        log.error(e.stderr)
        return False


def main():
    """Main function."""
    args = parse_args()
    log = get_logger(args.debug)

    log.debug(f"Arguments: {args}")

    # Check if helm unittest is available
    if not check_helm_unittest_available():
        log.error("helm unittest plugin is not available")
        log.error(
            "Please install it with: helm plugin install https://github.com/helm-unittest/helm-unittest"
        )
        return 1

    # If no files are provided, exit successfully
    if not args.files:
        log.info("No files provided, nothing to check")
        return 0

    # Find chart directories that contain changed files
    chart_dirs = find_chart_directories(args.files, args.charts_dir, log)

    if not chart_dirs:
        log.info("No Helm charts found with changes")
        return 0

    # Run tests for each chart
    failed_charts = []

    for chart_dir in sorted(chart_dirs):
        success = run_helm_unittest(
            chart_dir,
            args.tests_path,
            args.test_files,
            args.failfast,
            args.path_sub_pattern,
            log,
        )

        if not success:
            failed_charts.append(chart_dir)

            if args.failfast:
                log.error("Stopping on first failure (--failfast enabled)")
                break

    # Report results
    if failed_charts:
        log.error(f"Tests failed for {len(failed_charts)} chart(s):")
        for chart_dir in failed_charts:
            log.error(f"  - {chart_dir}")
        return 1
    else:
        log.info("All tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
