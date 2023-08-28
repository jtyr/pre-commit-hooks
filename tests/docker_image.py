import builtins
import io
import os
import sys
import unittest

from contextlib import redirect_stdout, redirect_stderr
from pre_commit.languages import docker
from unittest import mock


class Common:
    def __init__(self):
        # Path to the fixtures directory
        self.fixtures_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "fixtures")
        )

    def mock_open(self, filename):
        with open(filename, "rb") as f:
            data = f.read()

        return mock.patch.object(
            builtins,
            "open",
            new_callable=mock.mock_open,
            read_data=data,
        )

    def docker_image_path(self, subdir):
        return os.path.join(self.fixtures_path, "docker_image", subdir)


# Custom TestCase class that implements the Common class as a parameter
class MyTestCase(unittest.TestCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)

        # Create extra object with all Common stuff
        self.common = Common()

        # Don't limit the diff output
        self.maxDiff = None


class TestDockerImage(MyTestCase):
    def test_is_in_docker_sched(self):
        # Test cases
        tests = {
            "inside Docker": {
                "dir": self.common.docker_image_path("is_in_docker_sched"),
                "file": "docker",
                "expected": True,
            },
            "outside Docker - Systemd": {
                "dir": self.common.docker_image_path("is_in_docker_sched"),
                "file": "systemd",
                "expected": False,
            },
            "outside Docker - Init": {
                "dir": self.common.docker_image_path("is_in_docker_sched"),
                "file": "init",
                "expected": False,
            },
            "non-existing file": {
                "dir": self.common.docker_image_path("is_in_docker_sched"),
                "file": "non-existent",
                "expected": False,
            },
        }

        # Force module reload
        if "hooks.docker_image" in sys.modules:
            del sys.modules["hooks.docker_image"]

        import hooks.docker_image as di

        # Run individual test
        def _run_test(test):
            di.PROC_SHED = os.path.join(
                self.common.docker_image_path(test["dir"]), test["file"]
            )

            # Actual test value
            actual = di._is_in_docker_sched()

            # Test the test value against the expected value
            self.assertEqual(
                actual,
                test["expected"],
                "expected: '{}', got: '{}'".format(test["expected"], actual),
            )

        # Run individual tests
        for name, test in tests.items():
            with self.subTest(name=name):
                _run_test(test)

    def test_is_in_docker_dockerenv(self):
        # Test cases
        tests = {
            "file exists": {
                "dir": self.common.docker_image_path("is_in_docker_dockerenv"),
                "file": ".dockerenv",
                "expected": True,
            },
            "file doesn't exist": {
                "dir": self.common.docker_image_path("is_in_docker_dockerenv"),
                "file": "non-existent",
                "expected": False,
            },
        }

        # Force module reload
        if "hooks.docker_image" in sys.modules:
            del sys.modules["hooks.docker_image"]

        import hooks.docker_image as di

        # Run individual test
        def _run_test(test):
            di.DOCKERENV = os.path.join(
                self.common.docker_image_path(test["dir"]), test["file"]
            )

            # Actual test value
            actual = di._is_in_docker_dockerenv()

            # Test the test value against the expected value
            self.assertEqual(
                actual,
                test["expected"],
                "expected: '{}', got: '{}'".format(test["expected"], actual),
            )

        # Run individual tests
        for name, test in tests.items():
            with self.subTest(name=name):
                _run_test(test)

    def test_is_in_docker(self):
        # Test cases
        tests = {
            "only cgroup success": {
                "dir_cgroup": self.common.docker_image_path("is_in_docker_cgroup"),
                "file_cgroup": "docker",
                "dir_dockerenv": self.common.docker_image_path(
                    "is_in_docker_dockerenv"
                ),
                "file_dockerenv": "non-existing",
                "dir_sched": self.common.docker_image_path("is_in_docker_sched"),
                "file_sched": "systemd",
                "expected": True,
            },
            "only dockerenv success": {
                "dir_cgroup": self.common.docker_image_path("is_in_docker_cgroup"),
                "file_cgroup": "no-docker",
                "dir_dockerenv": self.common.docker_image_path(
                    "is_in_docker_dockerenv"
                ),
                "file_dockerenv": ".dockerenv",
                "dir_sched": self.common.docker_image_path("is_in_docker_sched"),
                "file_sched": "init",
                "expected": True,
            },
            "only sched success": {
                "dir_cgroup": self.common.docker_image_path("is_in_docker_cgroup"),
                "file_cgroup": "no-docker",
                "dir_dockerenv": self.common.docker_image_path(
                    "is_in_docker_dockerenv"
                ),
                "file_dockerenv": "non-existing",
                "dir_sched": self.common.docker_image_path("is_in_docker_sched"),
                "file_sched": "docker",
                "expected": True,
            },
            "all failure": {
                "dir_cgroup": self.common.docker_image_path("is_in_docker_cgroup"),
                "file_cgroup": "no-docker",
                "dir_dockerenv": self.common.docker_image_path(
                    "is_in_docker_dockerenv"
                ),
                "file_dockerenv": "non-existing",
                "dir_sched": self.common.docker_image_path("is_in_docker_sched"),
                "file_sched": "init",
                "expected": False,
            },
        }

        # Force module reload
        if "hooks.docker_image" in sys.modules:
            del sys.modules["hooks.docker_image"]

        import hooks.docker_image as di

        # Fake the di.DOCKER._is_in_docker_orig to be able to mock open()
        def _is_in_docker_orig_test():
            with self.common.mock_open(self.___file_param):
                return docker._is_in_docker()

        # Override the function with the one above
        di.DOCKER._is_in_docker_orig = _is_in_docker_orig_test

        # Run individual test
        def _run_test(test):
            self.___file_param = os.path.join(
                self.common.docker_image_path(test["dir_cgroup"]),
                test["file_cgroup"],
            )
            di.DOCKERENV = os.path.join(
                self.common.docker_image_path(test["dir_dockerenv"]),
                test["file_dockerenv"],
            )
            di.PROC_SHED = os.path.join(
                self.common.docker_image_path(test["dir_sched"]),
                test["file_sched"],
            )

            # Actual test value
            actual = di._is_in_docker()

            # Test the test value against the expected value
            self.assertEqual(
                actual,
                test["expected"],
                "expected: '{}', got: '{}'".format(test["expected"], actual),
            )

        # Run individual tests
        for name, test in tests.items():
            with self.subTest(name=name):
                _run_test(test)

    def test_get_container_id_cgroup(self):
        # Test cases
        tests = {
            "docker": {
                "dir": self.common.docker_image_path("is_in_docker_cgroup"),
                "file": "docker",
                "expected": (
                    "c33988ec7651ebc867cb24755eaf637a"
                    "6734088bc7eef59d5799293a9e5450f7"
                ),
            },
            "not docker": {
                "dir": self.common.docker_image_path("is_in_docker_cgroup"),
                "file": "no-docker",
                "expected": "",
            },
            "exception": {
                "dir": self.common.docker_image_path("is_in_docker_cgroup"),
                "file": "empty",
                "expected": "",
            },
        }

        # Force module reload
        if "hooks.docker_image" in sys.modules:
            del sys.modules["hooks.docker_image"]

        import hooks.docker_image as di

        # Fake the di._get_container_id_cgroup_orig to be able to mock open()
        def _get_container_id_cgroup_test():
            with self.common.mock_open(self.___file_param):
                return di._get_container_id_cgroup_orig()

        # Override some of the functions
        di.DOCKER._get_container_id_orig = docker._get_container_id
        di._get_container_id_cgroup_orig = di._get_container_id_cgroup
        di._get_container_id_cgroup = _get_container_id_cgroup_test

        # Run individual test
        def _run_test(test):
            self.___file_param = os.path.join(
                self.common.docker_image_path(test["dir"]), test["file"]
            )

            # Actual test value
            actual = di._get_container_id_cgroup()

            # Test the test value against the expected value
            self.assertEqual(
                actual,
                test["expected"],
                "expected: '{}', got: '{}'".format(test["expected"], actual),
            )

        # Run individual tests
        for name, test in tests.items():
            with self.subTest(name=name):
                _run_test(test)

    def test_get_container_id_sched(self):
        # Test cases
        tests = {
            "all good": {
                "dir": self.common.docker_image_path("get_container_id"),
                "mount": "mount_docker",
                "docker_ps": "docker_ps",
                "docker_inspect": "docker_inspect",
                "expected": "147ed436a89f",
            },
            "mount failure": {
                "dir": self.common.docker_image_path("get_container_id"),
                "mount": "non-existent",
                "docker_ps": "",
                "docker_inspect": "",
                "expected": "",
            },
            "mount empty": {
                "dir": self.common.docker_image_path("get_container_id"),
                "mount": "mount_empty",
                "docker_ps": "",
                "docker_inspect": "",
                "expected": "",
            },
            "mount no workdir": {
                "dir": self.common.docker_image_path("get_container_id"),
                "mount": "mount_no_workdir",
                "docker_ps": "",
                "docker_inspect": "",
                "expected": "",
            },
            "docker ps failure": {
                "dir": self.common.docker_image_path("get_container_id"),
                "mount": "mount_docker",
                "docker_ps": "non-existent",
                "docker_inspect": "",
                "expected": "",
            },
            "docker ps empty": {
                "dir": self.common.docker_image_path("get_container_id"),
                "mount": "mount_docker",
                "docker_ps": "docker_ps_empty",
                "docker_inspect": "",
                "expected": "",
            },
            "docker inspect failure": {
                "dir": self.common.docker_image_path("get_container_id"),
                "mount": "mount_docker",
                "docker_ps": "docker_ps",
                "docker_inspect": "non-existent",
                "expected": "",
            },
            "docker inspect empty": {
                "dir": self.common.docker_image_path("get_container_id"),
                "mount": "mount_docker",
                "docker_ps": "docker_ps",
                "docker_inspect": "docker_inspect_empty",
                "expected": "",
            },
        }

        # Force module reload
        if "hooks.docker_image" in sys.modules:
            del sys.modules["hooks.docker_image"]

        import hooks.docker_image as di

        # Run individual test
        def _run_test(test):
            # Override commands
            di.MOUNT_OVERLAY = (
                "cat",
                os.path.join(self.common.docker_image_path(test["dir"]), test["mount"]),
            )
            di.DOCKER_PS = (
                "cat",
                os.path.join(
                    self.common.docker_image_path(test["dir"]), test["docker_ps"]
                ),
            )
            di.DOCKER_INSPECT = (
                "sh",
                "-c",
                "cat %s"
                % os.path.join(
                    self.common.docker_image_path(test["dir"]), test["docker_inspect"]
                ),
            )

            # Actual test value
            actual = di._get_container_id_sched()

            # Test the test value against the expected value
            self.assertEqual(
                actual,
                test["expected"],
                "expected: '{}', got: '{}'".format(test["expected"], actual),
            )

        # Run individual tests
        for name, test in tests.items():
            with self.subTest(name=name):
                _run_test(test)

    def test_get_container_id(self):
        # Test cases
        tests = {
            "cgroup set": {
                "cgroup_id": "222222222222",
                "sched_id": "111111111111",
                "expected": "222222222222",
            },
            "cgroup unset": {
                "cgroup_id": "",
                "sched_id": "111111111111",
                "expected": "111111111111",
            },
            "non set": {
                "cgroup_id": "",
                "sched_id": "",
                "expected": "",
            },
        }

        # Force module reload
        if "hooks.docker_image" in sys.modules:
            del sys.modules["hooks.docker_image"]

        import hooks.docker_image as di

        def _get_container_id_cgroup_test():
            return self.___cgroup_id

        def _get_container_id_sched_test():
            return self.___sched_id

        # Mock functions
        di._get_container_id_cgroup = _get_container_id_cgroup_test
        di._get_container_id_sched = _get_container_id_sched_test

        # Run individual test
        def _run_test(test):
            # Set testing IDs
            self.___cgroup_id = test["cgroup_id"]
            self.___sched_id = test["sched_id"]

            # Actual test value
            actual = di._get_container_id()

            # Test the test value against the expected value
            self.assertEqual(
                actual,
                test["expected"],
                "expected: '{}', got: '{}'".format(test["expected"], actual),
            )

        # Run individual tests
        for name, test in tests.items():
            with self.subTest(name=name):
                _run_test(test)

    def test_main(self):
        # Test cases
        tests = {
            "success": {
                "cmd": ("sh",),
                "argv": ["", "-c", "echo 'stdout'; >&2 echo 'stderr'"],
                "expected": 0,
            },
            "failure": {
                "cmd": ("sh",),
                "argv": ["", "-c", "cat /non-existent"],
                "expected": 1,
            },
        }

        # Force module reload
        if "hooks.docker_image" in sys.modules:
            del sys.modules["hooks.docker_image"]

        import hooks.docker_image as di

        def docker_cmd_test():
            return self.___cmd

        # Mock function
        di.DOCKER.docker_cmd = docker_cmd_test

        # Run individual test
        def _run_test(test):
            # Set testing cmd
            self.___cmd = test["cmd"]
            di.SYS_ARGV = test["argv"]

            f_out = io.StringIO()
            f_err = io.StringIO()

            # Actual test value
            with redirect_stdout(f_out):
                with redirect_stderr(f_err):
                    actual = di.main()

            # Test the test value against the expected value
            self.assertEqual(
                actual,
                test["expected"],
                "expected: '{}', got: '{}'".format(test["expected"], actual),
            )

        # Run individual tests
        for name, test in tests.items():
            with self.subTest(name=name):
                _run_test(test)
