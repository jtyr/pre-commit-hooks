import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hooks.bats import (
    check_bats_available,
    get_logger,
    main,
    parse_args,
    resolve_pattern,
    run_bats,
)

TRIVIAL_BATS = """\
@test "trivial" {
    [ 1 -eq 1 ]
}
"""

FAILING_BATS = """\
@test "trivial" {
    [ 1 -eq 2 ]
}
"""


class TestParseArgs(unittest.TestCase):
    def test_parse_args_default(self):
        """Default --pattern is {name}.bats, no files."""
        with patch("sys.argv", ["bats.py"]):
            args = parse_args()
            self.assertEqual(args.pattern, "{name}.bats")
            self.assertFalse(args.debug)
            self.assertEqual(args.files, [])

    def test_parse_args_custom(self):
        """Custom --pattern, --debug, and positional files are captured."""
        argv = [
            "bats.py",
            "--pattern",
            "../tests/{name}.bats",
            "--debug",
            "foo.sh",
            "bar.sh",
        ]
        with patch("sys.argv", argv):
            args = parse_args()
            self.assertEqual(args.pattern, "../tests/{name}.bats")
            self.assertTrue(args.debug)
            self.assertEqual(args.files, ["foo.sh", "bar.sh"])


class TestGetLogger(unittest.TestCase):
    def test_get_logger_info(self):
        logger = get_logger(debug=False)
        self.assertEqual(logger.level, 0)

    def test_get_logger_debug(self):
        logger = get_logger(debug=True)
        self.assertEqual(logger.level, 0)


class TestResolvePattern(unittest.TestCase):
    def setUp(self):
        self.root = Path("/repo")
        self.sh = Path("/repo/scripts/foo.sh")

    def test_default_pattern_same_dir(self):
        """Default pattern resolves to <dir>/<name>.bats."""
        result = resolve_pattern("{name}.bats", self.sh, self.root)
        self.assertEqual(result, Path("/repo/scripts/foo.bats"))

    def test_name_underscore_test_pattern(self):
        """`{name}_test.bats` resolves in same directory."""
        result = resolve_pattern("{name}_test.bats", self.sh, self.root)
        self.assertEqual(result, Path("/repo/scripts/foo_test.bats"))

    def test_relative_directory_pattern(self):
        """`../tests/{name}.bats` resolves relative to the script's parent."""
        result = resolve_pattern("../tests/{name}.bats", self.sh, self.root)
        self.assertEqual(result, Path("/repo/tests/foo.bats"))

    def test_root_placeholder_absolute(self):
        """`{root}/...` resolves to an absolute path from root."""
        result = resolve_pattern("{root}/tests/{name}.bats", self.sh, self.root)
        self.assertEqual(result, Path("/repo/tests/foo.bats"))

    def test_bats_file_with_sh_extension(self):
        """Pattern may produce .sh extension (`{name}_test.sh`)."""
        result = resolve_pattern("{name}_test.sh", self.sh, self.root)
        self.assertEqual(result, Path("/repo/scripts/foo_test.sh"))


class TestCheckBatsAvailable(unittest.TestCase):
    def test_bats_available_when_run_succeeds(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            self.assertTrue(check_bats_available())

    def test_bats_unavailable_when_file_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(check_bats_available())

    def test_bats_unavailable_when_run_raises(self):
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "bats"),
        ):
            self.assertFalse(check_bats_available())


class TestRunBats(unittest.TestCase):
    def test_run_bats_returns_true_on_zero_exit(self):
        logger = get_logger(debug=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            self.assertTrue(run_bats(Path("/tmp/x.bats"), logger))

    def test_run_bats_returns_false_on_nonzero_exit(self):
        logger = get_logger(debug=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            self.assertFalse(run_bats(Path("/tmp/x.bats"), logger))


class TestMain(unittest.TestCase):
    """End-to-end tests that exercise main() against a real filesystem.

    When `bats` is installed on the test host, the bats runs actually
    execute (the fixture files contain trivially passing/failing @test
    blocks). When it isn't, the `check_bats_available` guard is patched
    so the exercised code path is still the dispatcher itself.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write(self, rel_path, content):
        path = Path(self.test_dir) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def _have_bats(self):
        try:
            subprocess.run(
                ["bats", "--version"],
                capture_output=True,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def test_no_files_returns_zero(self):
        argv = ["bats.py"]
        with patch("sys.argv", argv):
            self.assertEqual(main(), 0)

    def test_non_sh_files_are_skipped(self):
        argv = ["bats.py", "README.md", "foo.yaml"]
        with patch("sys.argv", argv), patch(
            "hooks.bats.check_bats_available", return_value=True
        ):
            self.assertEqual(main(), 0)

    def test_missing_companion_is_silently_skipped(self):
        self._write("scripts/foo.sh", "")
        argv = ["bats.py", "scripts/foo.sh"]
        with patch("sys.argv", argv), patch(
            "hooks.bats.check_bats_available", return_value=True
        ):
            self.assertEqual(main(), 0)

    def test_matching_companion_runs_bats(self):
        if not self._have_bats():
            self.skipTest("bats not installed")
        self._write("scripts/foo.sh", "")
        self._write("scripts/foo.bats", TRIVIAL_BATS)
        argv = ["bats.py", "scripts/foo.sh"]
        with patch("sys.argv", argv):
            self.assertEqual(main(), 0)

    def test_failing_bats_returns_one(self):
        if not self._have_bats():
            self.skipTest("bats not installed")
        self._write("scripts/foo.sh", "")
        self._write("scripts/foo.bats", FAILING_BATS)
        argv = ["bats.py", "scripts/foo.sh"]
        with patch("sys.argv", argv):
            self.assertEqual(main(), 1)

    def test_duplicate_companion_runs_bats_once(self):
        """Two .sh files resolving to the same bats file: run once."""
        if not self._have_bats():
            self.skipTest("bats not installed")
        self._write("scripts/foo.sh", "")
        self._write("scripts/bar.sh", "")
        shared = self._write("scripts/shared.bats", TRIVIAL_BATS)
        argv = [
            "bats.py",
            "--pattern",
            "shared.bats",
            "scripts/foo.sh",
            "scripts/bar.sh",
        ]
        with patch("sys.argv", argv), patch(
            "hooks.bats.run_bats", return_value=True
        ) as mock_run:
            self.assertEqual(main(), 0)
            calls = mock_run.call_args_list
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].args[0], shared.resolve())

    def test_relative_tests_dir_pattern(self):
        if not self._have_bats():
            self.skipTest("bats not installed")
        self._write("scripts/foo.sh", "")
        self._write("tests/foo.bats", TRIVIAL_BATS)
        argv = [
            "bats.py",
            "--pattern",
            "../tests/{name}.bats",
            "scripts/foo.sh",
        ]
        with patch("sys.argv", argv):
            self.assertEqual(main(), 0)

    def test_root_placeholder_pattern(self):
        if not self._have_bats():
            self.skipTest("bats not installed")
        self._write("scripts/foo.sh", "")
        self._write("tests/foo.bats", TRIVIAL_BATS)
        argv = [
            "bats.py",
            "--pattern",
            "{root}/tests/{name}.bats",
            "scripts/foo.sh",
        ]
        with patch("sys.argv", argv):
            self.assertEqual(main(), 0)

    def test_bats_not_installed_returns_one(self):
        argv = ["bats.py", "scripts/foo.sh"]
        with patch("sys.argv", argv), patch(
            "hooks.bats.check_bats_available", return_value=False
        ):
            self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
