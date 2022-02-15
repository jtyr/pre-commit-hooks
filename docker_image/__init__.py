import json
import sys

from pathlib import Path

from pre_commit.languages import docker
from pre_commit.util import cmd_output_b
from pre_commit.util import CalledProcessError


# To allow to mock the docker functionality
DOCKER = docker

# To allow to mock the path to the scheduler proc file
PROC_SHED = "/proc/1/sched"

# To allow to mock the path to the .dockerenv file
DOCKERENV = "/.dockerenv"

# To allow to mock the command used to list overlay type mounts
MOUNT_OVERLAY = ("mount", "-t", "overlay")

# To allow to mock the command to list running Docker containers
DOCKER_PS = ("docker", "ps", "--format", "{{ .ID }}")

# To allow to mock the command to inspect Docker container
DOCKER_INSPECT = ("dockere", "inspect")

# To allow to mock command line arguments
SYS_ARGV = sys.argv


def _is_in_docker_dockerenv() -> bool:
    return Path(DOCKERENV).exists()


def _is_in_docker_sched() -> bool:
    try:
        with open(PROC_SHED, "rb") as f:
            line = f.readline()

            if line.startswith(b"systemd ") or line.startswith(b"init "):
                return False

            return True
    except FileNotFoundError:
        return False


def _is_in_docker() -> bool:
    if (
        DOCKER._is_in_docker_orig()
        or _is_in_docker_dockerenv()
        or _is_in_docker_sched()
    ):
        return True

    return False


def _get_container_id_cgroup() -> str:
    try:
        return DOCKER._get_container_id_orig()
    except RuntimeError:
        return ""


def _get_container_id_sched() -> str:
    # The idea here is to try to match the the workdir option found in the
    # overlay mount with the GraphDriver.Data.WorkDir from the docker describe.

    # Get details for the overlay mount type
    try:
        _, out, _ = cmd_output_b(*MOUNT_OVERLAY)
    except CalledProcessError:
        # No mount command available or the -t option is not supported
        return ""

    lines = out.decode().strip().split("\n")

    # There is always only one overlay mount inside the container
    if len(lines) > 1 or lines[0] == "" or "(" not in lines[0]:
        return ""

    _, all_opts = lines[0].strip(")").split("(")
    opts = all_opts.split(",")

    # Search for workdir option
    for opt in opts:
        if "=" in opt:
            k, v = opt.split("=")

            if k == "workdir":
                # We have found workdir
                workdir = v

                break
    else:
        # No workdir was found
        return ""

    # Get list IDs for all running containers
    try:
        _, out, _ = cmd_output_b(*DOCKER_PS)
    except CalledProcessError:
        # There is probably no docker command
        return ""

    container_ids = out.decode().strip().split("\n")

    # Check if there are any container IDs
    if len(container_ids) == 1 and container_ids[0] == "":
        return ""

    # Search for a container that has the workdir we got from the mount command
    for container_id in container_ids:
        try:
            DOCKER_INSPECT_TMP = DOCKER_INSPECT + (container_id,)
            _, out, _ = cmd_output_b(*DOCKER_INSPECT_TMP)
        except CalledProcessError:
            # Container probably doesn't exist anymore
            return ""

        (container,) = json.loads(out)

        if (
            "GraphDriver" in container
            and "Data" in container["GraphDriver"]
            and "WorkDir" in container["GraphDriver"]["Data"]
            and container["GraphDriver"]["Data"]["WorkDir"] == workdir
        ):
            # We have found matching container!
            return container_id
    else:
        # No matching container found
        return ""


def _get_container_id() -> str:
    container_id = _get_container_id_cgroup()

    if container_id == "":
        container_id = _get_container_id_sched()

    return container_id


def main() -> None:
    # Override methods with local replacement
    DOCKER._is_in_docker_orig = DOCKER._is_in_docker
    DOCKER._is_in_docker = _is_in_docker
    DOCKER._get_container_id_orig = DOCKER._get_container_id
    DOCKER._get_container_id = _get_container_id

    # Get docker command enriched by the hook args
    cmd = DOCKER.docker_cmd() + tuple(SYS_ARGV[1:])

    # Run the command
    try:
        returncode, stdout, stderr = cmd_output_b(*cmd)
    except CalledProcessError as e:
        returncode, stdout, stderr = e.returncode, e.stdout, e.stderr

    # Print stdout if any
    if stdout:
        print(stdout.decode().rstrip())

    # Print stderr if any
    if stderr:
        print(stderr.decode().rstrip())

    return returncode


if __name__ == "__main__":
    main()
