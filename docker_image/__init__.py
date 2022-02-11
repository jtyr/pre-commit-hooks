import json
import sys

from pathlib import Path

from pre_commit.languages import docker
from pre_commit.util import cmd_output_b
from pre_commit.util import CalledProcessError


def _is_in_docker_sched() -> bool:
    try:
        with open("/proc/1/sched", "rb") as f:
            line = f.readline()

            if line.startswith(b"systemd ") or line.startswith(b"init "):
                return False

            return True
    except FileNotFoundError:
        return False


def _is_in_docker_dockerenv() -> bool:
    return Path(".dockerenv").exists()


def _is_in_docker() -> bool:
    if docker._is_in_docker_orig() or _is_in_docker_dockerenv or _is_in_docker_sched():
        return True

    return False


def _get_container_id_cgroup() -> str:
    try:
        return docker._get_container_id_orig()
    except RuntimeError:
        return ""


def _get_container_id_sched() -> str:
    # The idea here is to try to match the the workdir option found in the
    # overlay mount with the GraphDriver.Data.WorkDir from the docker describe.

    # Get details for the overlay mount type
    try:
        _, out, _ = cmd_output_b("mount", "-t", "overlay")
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
        _, out, _ = cmd_output_b("docker", "ps", "--format", "{{ .ID }}")
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
            _, out, _ = cmd_output_b("docker", "inspect", container_id)
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

        if container_id == "":
            raise RuntimeError("Failed to find the container ID.")

    return container_id


def main() -> None:
    # Override methods with local replacement
    docker._is_in_docker_orig = docker._is_in_docker
    docker._is_in_docker = _is_in_docker
    docker._get_container_id_orig = docker._get_container_id
    docker._get_container_id = _get_container_id

    # Get docker command enriched by the hook args
    cmd = docker.docker_cmd() + tuple(sys.argv[1:])

    # Run the command
    try:
        returncode, stdout, stderr = cmd_output_b(*cmd)
    except CalledProcessError as e:
        returncode, stdout, stderr = e.returncode, e.stdout, e.stderr

    # Print stderr if any
    if stdout:
        print(stdout.decode().rstrip())

    # Print stderr if any
    if stderr:
        print(stderr.decode().rstrip())

    return returncode


if __name__ == "__main__":
    main()
