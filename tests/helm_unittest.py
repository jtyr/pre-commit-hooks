import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from hooks.helm_unittest import (
    find_chart_directories,
    check_helm_unittest_available,
    run_helm_unittest,
    apply_path_substitution,
    main,
    parse_args,
    get_logger,
)


class TestCheckHelmUnittest(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.charts_dir = Path(self.test_dir) / "charts"
        self.charts_dir.mkdir()

        # Create a test chart
        self.chart_dir = self.charts_dir / "test-chart"
        self.chart_dir.mkdir()

        # Create Chart.yaml
        chart_yaml = self.chart_dir / "Chart.yaml"
        chart_yaml.write_text("""
apiVersion: v2
name: test-chart
version: 1.0.0
""")

        # Create test directory
        tests_dir = self.chart_dir / "tests" / "unittest"
        tests_dir.mkdir(parents=True)

        # Create a test file
        test_file = tests_dir / "deployment_test.yaml"
        test_file.write_text("""
suite: test deployment
templates:
  - deployment.yaml
tests:
  - it: should be a Deployment
    asserts:
      - isKind:
          of: Deployment
""")

    def test_parse_args_default(self):
        """Test parsing arguments with defaults."""
        with patch("sys.argv", ["helm_unittest.py"]):
            args = parse_args()
            self.assertEqual(args.charts_dir, "charts")
            self.assertEqual(args.tests_path, "tests/unittest")
            self.assertEqual(args.test_files, "*.yaml")
            self.assertFalse(args.failfast)
            self.assertFalse(args.debug)
            self.assertEqual(
                args.path_sub_pattern, "^charts/(libchart),helper-charts/\\1"
            )
            self.assertEqual(args.files, [])

    def test_parse_args_custom(self):
        """Test parsing arguments with custom values."""
        with patch(
            "sys.argv",
            [
                "helm_unittest.py",
                "--charts-dir",
                "my-charts",
                "--tests-path",
                "my-tests",
                "--test-files",
                "*.test.yaml",
                "--failfast",
                "--debug",
                "--path-sub-pattern",
                "^charts/(.*),helper-charts/\\1-test",
                "file1.yaml",
                "file2.yaml",
            ],
        ):
            args = parse_args()
            self.assertEqual(args.charts_dir, "my-charts")
            self.assertEqual(args.tests_path, "my-tests")
            self.assertEqual(args.test_files, "*.test.yaml")
            self.assertTrue(args.failfast)
            self.assertTrue(args.debug)
            self.assertEqual(
                args.path_sub_pattern, "^charts/(.*),helper-charts/\\1-test"
            )
            self.assertEqual(args.files, ["file1.yaml", "file2.yaml"])

    def test_get_logger_info(self):
        """Test logger configuration for info level."""
        logger = get_logger(debug=False)
        self.assertEqual(logger.level, 0)  # Should inherit from root logger

    def test_get_logger_debug(self):
        """Test logger configuration for debug level."""
        logger = get_logger(debug=True)
        self.assertEqual(logger.level, 0)  # Should inherit from root logger

    def test_find_chart_directories_under_charts_dir(self):
        """Test finding chart directories when files are under charts directory."""
        logger = get_logger(debug=False)
        changed_files = [
            str(self.chart_dir / "Chart.yaml"),
            str(self.chart_dir / "values.yaml"),
        ]

        chart_dirs = find_chart_directories(changed_files, str(self.charts_dir), logger)

        self.assertEqual(len(chart_dirs), 1)
        self.assertIn(self.chart_dir, chart_dirs)

    def test_find_chart_directories_not_under_charts_dir(self):
        """Test finding chart directories when files are not under charts directory."""
        logger = get_logger(debug=False)

        # Create a chart outside of charts directory
        other_chart = Path(self.test_dir) / "other-chart"
        other_chart.mkdir()
        (other_chart / "Chart.yaml").write_text("apiVersion: v2\nname: other")

        changed_files = [str(other_chart / "values.yaml")]

        chart_dirs = find_chart_directories(changed_files, str(self.charts_dir), logger)

        self.assertEqual(len(chart_dirs), 1)
        self.assertIn(other_chart, chart_dirs)

    def test_find_chart_directories_no_charts(self):
        """Test finding chart directories when no charts are found."""
        logger = get_logger(debug=False)
        changed_files = ["/some/random/file.txt"]

        chart_dirs = find_chart_directories(changed_files, str(self.charts_dir), logger)

        self.assertEqual(len(chart_dirs), 0)

    def test_apply_path_substitution_with_pattern(self):
        """Test path substitution with a valid pattern."""
        logger = get_logger(debug=False)
        chart_path = Path("charts/mylib")
        pattern = "^charts/(.*),helper-charts/\\1-test"

        result_path, use_helper_chart_tests = apply_path_substitution(
            chart_path, pattern, logger
        )

        self.assertEqual(result_path, Path("helper-charts/mylib-test"))
        self.assertTrue(use_helper_chart_tests)

    def test_apply_path_substitution_with_default_pattern(self):
        """Test path substitution with the default pattern for libchart."""
        logger = get_logger(debug=False)
        chart_path = Path("charts/libchart")
        pattern = "^charts/(libchart),helper-charts/\\1"

        result_path, use_helper_chart_tests = apply_path_substitution(
            chart_path, pattern, logger
        )

        self.assertEqual(result_path, Path("helper-charts/libchart"))
        self.assertTrue(use_helper_chart_tests)

    def test_apply_path_substitution_no_match(self):
        """Test path substitution when pattern doesn't match."""
        logger = get_logger(debug=False)
        chart_path = Path("other/mylib")
        pattern = "^charts/(.*),helper-charts/\\1-test"

        result_path, use_helper_chart_tests = apply_path_substitution(
            chart_path, pattern, logger
        )

        self.assertEqual(result_path, chart_path)
        self.assertFalse(use_helper_chart_tests)

    def test_apply_path_substitution_no_pattern(self):
        """Test path substitution when no pattern is provided."""
        logger = get_logger(debug=False)
        chart_path = Path("charts/mylib")

        result_path, use_helper_chart_tests = apply_path_substitution(
            chart_path, None, logger
        )

        self.assertEqual(result_path, chart_path)
        self.assertFalse(use_helper_chart_tests)

    def test_apply_path_substitution_invalid_pattern(self):
        """Test path substitution with invalid pattern format."""
        logger = get_logger(debug=False)
        chart_path = Path("charts/mylib")
        pattern = "invalid-pattern-no-comma"

        result_path, use_helper_chart_tests = apply_path_substitution(
            chart_path, pattern, logger
        )

        self.assertEqual(result_path, chart_path)
        self.assertFalse(use_helper_chart_tests)

    def test_apply_path_substitution_invalid_regex(self):
        """Test path substitution with invalid regex."""
        logger = get_logger(debug=False)
        chart_path = Path("charts/mylib")
        pattern = "[invalid-regex,replacement"

        result_path, use_helper_chart_tests = apply_path_substitution(
            chart_path, pattern, logger
        )

        self.assertEqual(result_path, chart_path)
        self.assertFalse(use_helper_chart_tests)

    @patch("subprocess.run")
    def test_check_helm_unittest_available_success(self, mock_run):
        """Test checking if helm unittest is available - success case."""
        mock_run.return_value = MagicMock()

        result = check_helm_unittest_available()

        self.assertTrue(result)
        mock_run.assert_called_once_with(
            ["helm", "unittest", "--help"], capture_output=True, text=True, check=True
        )

    @patch("subprocess.run")
    def test_check_helm_unittest_available_failure(self, mock_run):
        """Test checking if helm unittest is available - failure case."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "helm")

        result = check_helm_unittest_available()

        self.assertFalse(result)

    @patch("subprocess.run")
    def test_run_helm_unittest_success(self, mock_run):
        """Test running helm unittest - success case."""
        logger = get_logger(debug=False)
        mock_run.return_value = MagicMock(stdout="All tests passed", stderr="")

        result = run_helm_unittest(
            self.chart_dir,
            "tests/unittest",
            "*.yaml",
            False,
            None,  # No path substitution
            logger,
        )

        self.assertTrue(result)
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_run_helm_unittest_failure(self, mock_run):
        """Test running helm unittest - failure case."""
        logger = get_logger(debug=False)
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "helm", output="Test failed", stderr="Error"
        )

        result = run_helm_unittest(
            self.chart_dir,
            "tests/unittest",
            "*.yaml",
            False,
            None,  # No path substitution
            logger,
        )

        self.assertFalse(result)

    def test_run_helm_unittest_no_tests_dir(self):
        """Test running helm unittest when tests directory doesn't exist."""
        logger = get_logger(debug=False)

        # Remove tests directory
        import shutil

        shutil.rmtree(self.chart_dir / "tests")

        result = run_helm_unittest(
            self.chart_dir,
            "tests/unittest",
            "*.yaml",
            False,
            None,  # No path substitution
            logger,
        )

        # Should return True (success) when no tests directory exists
        self.assertTrue(result)

    def test_run_helm_unittest_no_test_files(self):
        """Test running helm unittest when no test files exist."""
        logger = get_logger(debug=False)

        # Remove test files
        for test_file in (self.chart_dir / "tests" / "unittest").glob("*"):
            test_file.unlink()

        result = run_helm_unittest(
            self.chart_dir,
            "tests/unittest",
            "*.yaml",
            False,
            None,  # No path substitution
            logger,
        )

        # Should return True (success) when no test files exist
        self.assertTrue(result)

    @patch("subprocess.run")
    def test_run_helm_unittest_with_path_substitution(self, mock_run):
        """Test running helm unittest with path substitution."""
        logger = get_logger(debug=False)
        mock_run.return_value = MagicMock(stdout="All tests passed", stderr="")

        # Create a helper chart directory structure
        helper_chart_dir = Path(self.test_dir) / "helper-charts" / "test-chart-helper"
        helper_chart_dir.mkdir(parents=True)

        # Create Chart.yaml for helper chart
        helper_chart_yaml = helper_chart_dir / "Chart.yaml"
        helper_chart_yaml.write_text("""
apiVersion: v2
name: test-chart-helper
type: application
version: 1.0.0
""")

        # Create tests directory in helper chart
        helper_tests_dir = helper_chart_dir / "tests" / "unittest"
        helper_tests_dir.mkdir(parents=True)

        # Create a test file in helper chart
        helper_test_file = helper_tests_dir / "library_test.yaml"
        helper_test_file.write_text("""
suite: test library chart
templates:
  - library-template.yaml
tests:
  - it: should be a library
    asserts:
      - isKind:
          of: ConfigMap
""")

        # Use the full path pattern that will match our test setup
        charts_path = str(self.charts_dir / "test-chart")
        pattern = f"^{re.escape(str(self.charts_dir))}/test-chart,{helper_chart_dir}"

        result = run_helm_unittest(
            charts_path, "tests/unittest", "*.yaml", False, pattern, logger
        )

        self.assertTrue(result)
        mock_run.assert_called_once()

        # Verify the command was called with the helper chart path
        call_args = mock_run.call_args[0][0]
        self.assertIn(str(helper_chart_dir), call_args)

    @patch("hooks.helm_unittest.check_helm_unittest_available")
    @patch("hooks.helm_unittest.parse_args")
    def test_main_no_helm_unittest(self, mock_parse_args, mock_available):
        """Test main function when helm unittest is not available."""
        mock_parse_args.return_value = MagicMock(files=[], path_sub_pattern=None)
        mock_available.return_value = False

        result = main()

        self.assertEqual(result, 1)

    @patch("hooks.helm_unittest.check_helm_unittest_available")
    @patch("hooks.helm_unittest.parse_args")
    def test_main_no_files(self, mock_parse_args, mock_available):
        """Test main function when no files are provided."""
        mock_parse_args.return_value = MagicMock(files=[], path_sub_pattern=None)
        mock_available.return_value = True

        result = main()

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
