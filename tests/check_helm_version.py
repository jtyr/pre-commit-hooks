import os
import unittest
from unittest.mock import patch

from hooks.check_helm_version import (
    changed_paths_since_main,
    find_chart_dir,
    get_logger,
    main,
    parse_args,
    process_paths,
)

from tests._git_fixture import GitRepoFixture

CHART_TEMPLATE = """\
apiVersion: v2
name: my-chart
version: {version}
"""


def _run_main(argv):
    with patch("sys.argv", argv):
        try:
            main()
        except SystemExit as e:
            return e.code if e.code is not None else 0

    return 0


class TestParseArgs(unittest.TestCase):
    def test_defaults(self):
        with patch("sys.argv", ["check_helm_version.py", "some/path"]):
            args = parse_args()
            self.assertEqual(args.branch, "main")
            self.assertEqual(args.remote, "origin")
            self.assertFalse(args.autofix)
            self.assertEqual(args.autofix_strategy, "fixed")
            self.assertEqual(args.autofix_portion, "patch")
            self.assertFalse(args.debug)
            self.assertEqual(args.PATH, ["some/path"])

    def test_explicit_strategy_conventional(self):
        argv = [
            "check_helm_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            "x",
        ]
        with patch("sys.argv", argv):
            args = parse_args()
            self.assertEqual(args.autofix_strategy, "conventional")

    def test_invalid_strategy_rejected(self):
        argv = ["check_helm_version.py", "--autofix-strategy=bogus", "x"]
        with patch("sys.argv", argv):
            with self.assertRaises(SystemExit):
                parse_args()


class TestGetLogger(unittest.TestCase):
    def test_logger_runs(self):
        log = get_logger(debug=False)
        self.assertIsNotNone(log)


class TestFindChartDir(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="1.0.0")
        )
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")

    def tearDown(self):
        self.fixture.cleanup()

    def test_finds_chart_in_parent(self):
        target = os.path.join(self.fixture.dir, "charts", "foo", "templates", "x.yaml")
        result = find_chart_dir(target)
        self.assertEqual(result, os.path.join(self.fixture.dir, "charts", "foo"))

    def test_returns_none_when_no_chart(self):
        target = os.path.join(self.fixture.dir, "README.md")
        result = find_chart_dir(target)
        self.assertIsNone(result)


class TestProcessPaths(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="1.0.0")
        )
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")

    def tearDown(self):
        self.fixture.cleanup()

    def test_finds_chart_from_subpath(self):
        target = os.path.join(self.fixture.dir, "charts", "foo", "templates", "x.yaml")
        result = process_paths([target])
        self.assertEqual(
            result,
            {os.path.join(self.fixture.dir, "charts", "foo", "Chart.yaml")},
        )

    def test_chart_directory_directly(self):
        chart_dir = os.path.join(self.fixture.dir, "charts", "foo")
        result = process_paths([chart_dir])
        self.assertEqual(
            result,
            {os.path.join(self.fixture.dir, "charts", "foo", "Chart.yaml")},
        )

    def test_paths_without_chart_are_skipped(self):
        result = process_paths(["/tmp"])
        self.assertEqual(result, set())


class TestCheckFixed(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="1.0.0")
        )
        self.fixture.add("charts/foo/Chart.yaml")
        self.fixture.commit("seed chart")
        self.fixture.create_branch("feature")
        self.cwd = os.getcwd()
        os.chdir(self.fixture.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        self.fixture.cleanup()

    def test_passes_when_version_is_bumped(self):
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="1.0.1")
        )
        argv = [
            "check_helm_version.py",
            "--branch=main",
            "charts/foo/Chart.yaml",
        ]
        self.assertEqual(_run_main(argv), 0)

    def test_fails_when_version_is_not_bumped(self):
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        argv = [
            "check_helm_version.py",
            "--branch=main",
            "charts/foo/templates/x.yaml",
        ]
        self.assertEqual(_run_main(argv), 127)

    def test_autofix_writes_bumped_version(self):
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        argv = [
            "check_helm_version.py",
            "--branch=main",
            "--autofix",
            "charts/foo/templates/x.yaml",
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")) as f:
            self.assertIn("version: 1.0.1", f.read())

    def test_autofix_minor_portion(self):
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        argv = [
            "check_helm_version.py",
            "--branch=main",
            "--autofix",
            "--autofix-portion=minor",
            "charts/foo/templates/x.yaml",
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")) as f:
            self.assertIn("version: 1.1.0", f.read())

    def test_no_op_at_commit_msg_stage(self):
        msg_path = os.path.join(self.fixture.dir, ".git", "COMMIT_EDITMSG")
        with open(msg_path, "w") as f:
            f.write("anything\n")

        # Don't bump the version on purpose
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        argv = ["check_helm_version.py", msg_path]
        self.assertEqual(_run_main(argv), 0)


class TestCheckConventional(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="1.0.0")
        )
        self.fixture.add("charts/foo/Chart.yaml")
        self.fixture.commit("seed chart")
        self.fixture.create_branch("feature")
        self.cwd = os.getcwd()
        os.chdir(self.fixture.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        self.fixture.cleanup()

    def _msg_path(self, message):
        path = os.path.join(self.fixture.dir, ".git", "COMMIT_EDITMSG")
        with open(path, "w") as f:
            f.write(message)

        return path

    def test_strict_no_qualifying_message_fails(self):
        """In --conventional-strict mode, a no-bump CC message fails."""
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.add("charts/foo/templates/x.yaml")
        path = self._msg_path("chore: nothing\n")
        argv = [
            "check_helm_version.py",
            "--autofix-strategy=conventional",
            "--conventional-strict",
            path,
        ]
        self.assertEqual(_run_main(argv), 1)

    def test_non_cc_message_fails_even_without_strict(self):
        """A non-CC message fails regardless of --conventional-strict."""
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.add("charts/foo/templates/x.yaml")
        path = self._msg_path("just some text\n")
        argv = [
            "check_helm_version.py",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 1)

    def test_no_bump_cc_message_passes_in_default_mode(self):
        """In the default (non-strict) mode, a valid no-bump CC message passes."""
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.add("charts/foo/templates/x.yaml")
        path = self._msg_path("style: reformat\n")
        argv = [
            "check_helm_version.py",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 0)

        # Version stays at baseline
        with open(os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")) as f:
            self.assertIn("version: 1.0.0", f.read())

    def test_feat_writes_minor_bump(self):
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.add("charts/foo/templates/x.yaml")
        path = self._msg_path("feat: add new template\n")
        argv = [
            "check_helm_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")) as f:
            self.assertIn("version: 1.1.0", f.read())

    def test_fix_writes_patch_bump(self):
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.add("charts/foo/templates/x.yaml")
        path = self._msg_path("fix: correct value\n")
        argv = [
            "check_helm_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")) as f:
            self.assertIn("version: 1.0.1", f.read())

    def test_user_bumped_higher_than_expected_passes(self):
        """A manual bump above the CC-derived expected is accepted as-is."""
        # CC says minor (1.0.0 -> 1.1.0), user manually bumped to 2.0.0
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="2.0.0")
        )
        self.fixture.add("charts/foo/Chart.yaml")
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.add("charts/foo/templates/x.yaml")
        path = self._msg_path("feat: add x\n")
        argv = [
            "check_helm_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 0)

        with open(os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")) as f:
            self.assertIn("version: 2.0.0", f.read())

    def test_user_bumped_below_expected_fails(self):
        """A manual bump below the CC-derived expected still fails / autofixes."""
        # CC says minor (1.0.0 -> 1.1.0), user only bumped to 1.0.5
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="1.0.5")
        )
        self.fixture.add("charts/foo/Chart.yaml")
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.add("charts/foo/templates/x.yaml")
        path = self._msg_path("feat: add x\n")
        argv = [
            "check_helm_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")) as f:
            self.assertIn("version: 1.1.0", f.read())

    def test_breaking_writes_major_bump(self):
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.add("charts/foo/templates/x.yaml")
        path = self._msg_path("feat!: incompatible change\n")
        argv = [
            "check_helm_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")) as f:
            self.assertIn("version: 2.0.0", f.read())

    def test_baseline_0_0_0_when_chart_is_new(self):
        # Start the new chart below the CC-derived 0.1.0 so autofix kicks in
        self.fixture.write(
            "charts/bar/Chart.yaml", CHART_TEMPLATE.format(version="0.0.0")
        )
        self.fixture.add("charts/bar/Chart.yaml")
        path = self._msg_path("feat: brand new chart\n")
        argv = [
            "check_helm_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, "charts/bar/Chart.yaml")) as f:
            self.assertIn("version: 0.1.0", f.read())

    def test_no_op_at_pre_commit_stage(self):
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        argv = [
            "check_helm_version.py",
            "--autofix-strategy=conventional",
            "charts/foo/templates/x.yaml",
        ]
        self.assertEqual(_run_main(argv), 0)


class TestChartIsolation(unittest.TestCase):
    """Path filtering: a commit touching chart A must not bump chart B."""

    def setUp(self):
        self.fixture = GitRepoFixture()
        # Both charts present on main from the start
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="1.0.0")
        )
        self.fixture.write(
            "charts/bar/Chart.yaml", CHART_TEMPLATE.format(version="2.0.0")
        )
        self.fixture.add("charts/foo/Chart.yaml", "charts/bar/Chart.yaml")
        self.fixture.commit("seed both charts")
        self.fixture.create_branch("feature")
        self.cwd = os.getcwd()
        os.chdir(self.fixture.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        self.fixture.cleanup()

    def _msg_path(self, message):
        path = os.path.join(self.fixture.dir, ".git", "COMMIT_EDITMSG")
        with open(path, "w") as f:
            f.write(message)

        return path

    def test_feat_on_foo_does_not_qualify_for_bar(self):
        # On feature: feat: commit only touches foo, and pre-bumps foo to 1.1.0
        # so foo's check passes deterministically.
        self.fixture.write("charts/foo/templates/x.yaml", "x: 1\n")
        self.fixture.write(
            "charts/foo/Chart.yaml", CHART_TEMPLATE.format(version="1.1.0")
        )
        self.fixture.add("charts/foo/templates/x.yaml", "charts/foo/Chart.yaml")
        self.fixture.commit("feat: add x to foo")

        # In-flight: change to bar with a non-CC message so bar fails
        # regardless of --conventional-strict (path-filter excludes foo's
        # feat from bar).
        self.fixture.write("charts/bar/templates/y.yaml", "y: 1\n")
        self.fixture.add("charts/bar/templates/y.yaml")
        path = self._msg_path("just an update\n")

        argv = [
            "check_helm_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        # foo passes (already at expected 1.1.0).
        # bar fails because no CC message touched charts/bar.
        self.assertEqual(_run_main(argv), 1)


class TestChangedPathsSinceMain(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.create_branch("feature")

    def tearDown(self):
        self.fixture.cleanup()

    def test_picks_up_uncommitted_changes(self):
        self.fixture.write("charts/foo/Chart.yaml", "version: 1.0.0\n")
        self.fixture.add("charts/foo/Chart.yaml")

        result = changed_paths_since_main(self.fixture.repo, self.fixture.main)
        expected = os.path.join(self.fixture.dir, "charts/foo/Chart.yaml")
        self.assertIn(expected, result)


if __name__ == "__main__":
    unittest.main()
