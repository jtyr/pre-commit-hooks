import os
import unittest
from unittest.mock import patch

from hooks.check_version import (
    changed_paths_since_main,
    find_version_dir,
    get_logger,
    main,
    parse_args,
    process_paths,
)

from tests._git_fixture import GitRepoFixture


def _run_main(argv):
    """Invoke the hook's main() with patched argv and return the exit code."""
    with patch("sys.argv", argv):
        try:
            main()
        except SystemExit as e:
            return e.code if e.code is not None else 0

    return 0


class TestParseArgs(unittest.TestCase):
    def test_defaults(self):
        with patch("sys.argv", ["check_version.py", "some/path"]):
            args = parse_args()
            self.assertEqual(args.version_file, ".version")
            self.assertEqual(args.branch, "main")
            self.assertEqual(args.remote, "origin")
            self.assertFalse(args.autofix)
            self.assertEqual(args.autofix_strategy, "fixed")
            self.assertEqual(args.autofix_portion, "patch")
            self.assertFalse(args.debug)
            self.assertEqual(args.PATH, ["some/path"])

    def test_explicit_strategy_conventional(self):
        argv = [
            "check_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            "x",
        ]
        with patch("sys.argv", argv):
            args = parse_args()
            self.assertEqual(args.autofix_strategy, "conventional")
            self.assertTrue(args.autofix)

    def test_invalid_strategy_rejected(self):
        argv = ["check_version.py", "--autofix-strategy=bogus", "x"]
        with patch("sys.argv", argv):
            with self.assertRaises(SystemExit):
                parse_args()


class TestGetLogger(unittest.TestCase):
    def test_logger_runs(self):
        log = get_logger(debug=False)
        self.assertIsNotNone(log)


class TestFindVersionDir(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.write(".version", "1.0.0\n")
        self.fixture.write("sub/file.txt", "hi\n")

    def tearDown(self):
        self.fixture.cleanup()

    def test_finds_version_in_parent(self):
        target = os.path.join(self.fixture.dir, "sub", "file.txt")
        result = find_version_dir(target, ".version")
        self.assertEqual(result, self.fixture.dir)

    def test_returns_none_when_not_found(self):
        target = os.path.join(self.fixture.dir, "sub", "file.txt")
        result = find_version_dir(target, ".missing")
        self.assertIsNone(result)


class TestProcessPaths(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.write(".version", "1.0.0\n")
        self.fixture.write("sub/file.txt", "hi\n")

    def tearDown(self):
        self.fixture.cleanup()

    def test_finds_version_file_from_subpath(self):
        target = os.path.join(self.fixture.dir, "sub", "file.txt")
        result = process_paths([target], ".version")
        self.assertEqual(result, {os.path.join(self.fixture.dir, ".version")})

    def test_directory_with_version_file(self):
        result = process_paths([self.fixture.dir], ".version")
        self.assertEqual(result, {os.path.join(self.fixture.dir, ".version")})

    def test_paths_without_version_are_skipped(self):
        result = process_paths(["/tmp"], ".version")
        self.assertEqual(result, set())


class TestCheckFixed(unittest.TestCase):
    """Tests for the fixed strategy (existing behavior)."""

    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.write(".version", "1.0.0\n")
        self.fixture.add(".version")
        self.fixture.commit("seed version")
        self.fixture.create_branch("feature")
        self.cwd = os.getcwd()
        os.chdir(self.fixture.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        self.fixture.cleanup()

    def test_passes_when_version_is_bumped(self):
        self.fixture.write(".version", "1.0.1\n")
        argv = ["check_version.py", "--branch=main", ".version"]
        self.assertEqual(_run_main(argv), 0)

    def test_fails_when_version_is_not_bumped(self):
        self.fixture.write("noise.txt", "x\n")
        argv = ["check_version.py", "--branch=main", "noise.txt"]
        self.assertEqual(_run_main(argv), 127)

    def test_autofix_writes_bumped_version(self):
        self.fixture.write("noise.txt", "x\n")
        argv = [
            "check_version.py",
            "--branch=main",
            "--autofix",
            "noise.txt",
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "1.0.1")

    def test_autofix_minor_portion(self):
        self.fixture.write("noise.txt", "x\n")
        argv = [
            "check_version.py",
            "--branch=main",
            "--autofix",
            "--autofix-portion=minor",
            "noise.txt",
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "1.1.0")

    def test_no_op_at_commit_msg_stage(self):
        """fixed strategy should be a no-op at commit-msg stage."""
        # Write the COMMIT_EDITMSG file
        msg_path = os.path.join(self.fixture.dir, ".git", "COMMIT_EDITMSG")
        with open(msg_path, "w") as f:
            f.write("anything\n")

        # Don't bump the version on purpose; commit-msg stage should not flag it
        self.fixture.write("noise.txt", "x\n")
        argv = ["check_version.py", msg_path]
        self.assertEqual(_run_main(argv), 0)


class TestCheckConventional(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.write(".version", "1.0.0\n")
        self.fixture.add(".version")
        self.fixture.commit("seed version")
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
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        path = self._msg_path("chore: nothing important\n")
        argv = [
            "check_version.py",
            "--autofix-strategy=conventional",
            "--conventional-strict",
            path,
        ]
        self.assertEqual(_run_main(argv), 1)

    def test_non_cc_message_fails_even_without_strict(self):
        """A non-CC message fails regardless of --conventional-strict."""
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        path = self._msg_path("just some text\n")
        argv = [
            "check_version.py",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 1)

    def test_no_bump_cc_message_passes_in_default_mode(self):
        """In the default (non-strict) mode, a valid no-bump CC message passes."""
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        path = self._msg_path("style: tweak whitespace\n")
        argv = [
            "check_version.py",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 0)

        # Version stays at baseline
        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "1.0.0")

    def test_no_bump_cc_message_passes_when_user_manually_bumped(self):
        """Lenient: if only no-bump CC messages are present, accept any version."""
        self.fixture.write(".version", "1.5.0\n")
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt", ".version")
        path = self._msg_path("chore: bump for fun\n")
        argv = [
            "check_version.py",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 0)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "1.5.0")

    def test_feat_in_inflight_message_writes_minor_bump(self):
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        path = self._msg_path("feat: add new thing\n")
        argv = [
            "check_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "1.1.0")

    def test_fix_in_inflight_message_writes_patch_bump(self):
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        path = self._msg_path("fix: correct bug\n")
        argv = [
            "check_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "1.0.1")

    def test_breaking_in_inflight_writes_major_bump(self):
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        path = self._msg_path("feat!: incompatible change\n")
        argv = [
            "check_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "2.0.0")

    def test_committed_feat_plus_inflight_fix_yields_minor(self):
        # Make a feat commit on the feature branch
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        self.fixture.commit("feat: add thing")

        # In-flight is just a fix
        self.fixture.write("b.txt", "y\n")
        self.fixture.add("b.txt")
        path = self._msg_path("fix: tweak\n")
        argv = [
            "check_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "1.1.0")

    def test_user_bumped_higher_than_expected_passes(self):
        """A manual bump above the CC-derived expected is accepted as-is."""
        # CC says minor (1.0.0 -> 1.1.0), user manually bumped to 2.0.0
        self.fixture.write(".version", "2.0.0\n")
        self.fixture.add(".version")
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        path = self._msg_path("feat: add new thing\n")
        argv = [
            "check_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 0)

        # Version stays at the manually-set 2.0.0
        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "2.0.0")

    def test_user_bumped_below_expected_fails(self):
        """A manual bump below the CC-derived expected still fails / autofixes."""
        # CC says minor (1.0.0 -> 1.1.0), user only bumped to 1.0.5
        self.fixture.write(".version", "1.0.5\n")
        self.fixture.add(".version")
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")
        path = self._msg_path("feat: add new thing\n")
        argv = [
            "check_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "1.1.0")

    def test_passes_when_version_already_at_expected(self):
        # Pre-bump to the expected value
        self.fixture.write(".version", "1.1.0\n")
        self.fixture.add(".version")
        self.fixture.commit("feat: add thing and bump")

        # Fresh in-flight needs to also qualify (we look at all messages)
        self.fixture.write("b.txt", "y\n")
        self.fixture.add("b.txt")
        path = self._msg_path("docs: update\n")
        argv = [
            "check_version.py",
            "--autofix-strategy=conventional",
            path,
        ]
        # docs alone wouldn't qualify but the prior feat: is in main..HEAD
        self.assertEqual(_run_main(argv), 0)

    def test_baseline_0_0_0_when_no_main_version(self):
        """A new directory without a version file on main starts from 0.0.0."""
        # Remove the version file from main and make it brand new in the branch
        self.fixture.checkout("main")
        self.fixture.repo.index.remove([".version"], working_tree=True)
        self.fixture.commit("remove version")

        self.fixture.create_branch("feature2")
        self.fixture.write(".version", "0.0.0\n")  # below the CC-derived 0.1.0
        self.fixture.add(".version")
        path = self._msg_path("feat: brand new feature\n")
        argv = [
            "check_version.py",
            "--autofix",
            "--autofix-strategy=conventional",
            path,
        ]
        self.assertEqual(_run_main(argv), 127)

        with open(os.path.join(self.fixture.dir, ".version")) as f:
            self.assertEqual(f.read().strip(), "0.1.0")

    def test_no_op_at_pre_commit_stage(self):
        """conventional strategy should be a no-op at pre-commit stage."""
        self.fixture.write("noise.txt", "x\n")
        argv = [
            "check_version.py",
            "--autofix-strategy=conventional",
            "noise.txt",
        ]
        self.assertEqual(_run_main(argv), 0)


class TestChangedPathsSinceMain(unittest.TestCase):
    def setUp(self):
        self.fixture = GitRepoFixture()
        self.fixture.create_branch("feature")

    def tearDown(self):
        self.fixture.cleanup()

    def test_picks_up_uncommitted_changes(self):
        self.fixture.write("a.txt", "x\n")
        self.fixture.add("a.txt")

        result = changed_paths_since_main(self.fixture.repo, self.fixture.main)
        expected = os.path.join(self.fixture.dir, "a.txt")
        self.assertIn(expected, result)

    def test_picks_up_committed_changes(self):
        self.fixture.write("b.txt", "y\n")
        self.fixture.add("b.txt")
        self.fixture.commit("feat: add b")

        result = changed_paths_since_main(self.fixture.repo, self.fixture.main)
        expected = os.path.join(self.fixture.dir, "b.txt")
        self.assertIn(expected, result)


if __name__ == "__main__":
    unittest.main()
