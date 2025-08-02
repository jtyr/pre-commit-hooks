# =============================================================================
# BEGIN UPSTREAM — copied verbatim from
# https://github.com/pre-commit/pre-commit/blob/main/pre_commit/languages/docker.py
# =============================================================================
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import re
from collections.abc import Sequence

from pre_commit import lang_base
from pre_commit.prefix import Prefix
from pre_commit.util import CalledProcessError
from pre_commit.util import cmd_output_b

ENVIRONMENT_DIR = "docker"
PRE_COMMIT_LABEL = "PRE_COMMIT"
get_default_version = lang_base.basic_get_default_version
health_check = lang_base.basic_health_check
in_env = lang_base.no_env  # no special environment for docker

_HOSTNAME_MOUNT_RE = re.compile(
    rb"""
    /containers
    (?:/overlay-containers)?
    /([a-z0-9]{64})
    (?:/userdata)?
    /hostname
    """,
    re.VERBOSE,
)


def _get_container_id() -> str | None:
    with contextlib.suppress(FileNotFoundError):
        with open("/proc/1/mountinfo", "rb") as f:
            for line in f:
                m = _HOSTNAME_MOUNT_RE.search(line)
                if m:
                    return m[1].decode()

    return None


def _get_docker_path(path: str) -> str:
    container_id = _get_container_id()
    if container_id is None:
        return path

    try:
        _, out, _ = cmd_output_b("docker", "inspect", container_id)
    except CalledProcessError:
        # self-container was not visible from here (perhaps docker-in-docker)
        return path

    (container,) = json.loads(out)
    for mount in container["Mounts"]:
        src_path = mount["Source"]
        to_path = mount["Destination"]
        if os.path.commonpath((path, to_path)) == to_path:
            # So there is something in common,
            # and we can proceed remapping it
            return path.replace(to_path, src_path)
    # we're in Docker, but the path is not mounted, cannot really do anything,
    # so fall back to original path
    return path


def md5(s: str) -> str:  # pragma: win32 no cover
    return hashlib.md5(s.encode()).hexdigest()


def docker_tag(prefix: Prefix) -> str:  # pragma: win32 no cover
    md5sum = md5(os.path.basename(prefix.prefix_dir)).lower()
    return f"pre-commit-{md5sum}"


def build_docker_image(
    prefix: Prefix,
    *,
    pull: bool,
) -> None:  # pragma: win32 no cover
    cmd: tuple[str, ...] = (
        "docker",
        "build",
        "--tag",
        docker_tag(prefix),
        "--label",
        PRE_COMMIT_LABEL,
    )
    if pull:
        cmd += ("--pull",)
    # This must come last for old versions of docker.  See #477
    cmd += (".",)
    lang_base.setup_cmd(prefix, cmd)


def install_environment(
    prefix: Prefix,
    version: str,
    additional_dependencies: Sequence[str],
) -> None:  # pragma: win32 no cover
    lang_base.assert_version_default("docker", version)
    lang_base.assert_no_additional_deps("docker", additional_dependencies)

    directory = lang_base.environment_dir(prefix, ENVIRONMENT_DIR, version)

    # Docker doesn't really have relevant disk environment, but pre-commit
    # still needs to cleanup its state files on failure
    build_docker_image(prefix, pull=True)
    os.mkdir(directory)


@functools.lru_cache(maxsize=1)
def _is_rootless() -> bool:  # pragma: win32 no cover
    retcode, out, _ = cmd_output_b(
        "docker",
        "system",
        "info",
        "--format",
        "{{ json . }}",
    )
    if retcode != 0:
        return False

    info = json.loads(out)
    try:
        return (
            # docker:
            # https://docs.docker.com/reference/api/engine/version/v1.48/#tag/System/operation/SystemInfo
            "name=rootless" in (info.get("SecurityOptions") or ())
            or
            # podman:
            # https://docs.podman.io/en/latest/_static/api.html?version=v5.4#tag/system/operation/SystemInfoLibpod
            info["host"]["security"]["rootless"]
        )
    except KeyError:
        return False


def get_docker_user() -> tuple[str, ...]:  # pragma: win32 no cover
    if _is_rootless():
        return ()

    try:
        return ("-u", f"{os.getuid()}:{os.getgid()}")
    except AttributeError:
        return ()


def get_docker_tty(
    *, color: bool
) -> tuple[str, ...]:  # pragma: win32 no cover  # noqa: E501
    return ("--tty",) if color else ()


def docker_cmd(*, color: bool) -> tuple[str, ...]:  # pragma: win32 no cover
    return (
        "docker",
        "run",
        "--rm",
        *get_docker_tty(color=color),
        *get_docker_user(),
        # https://docs.docker.com/engine/reference/commandline/run/#mount-volumes-from-container-volumes-from
        # The `Z` option tells Docker to label the content with a private
        # unshared label. Only the current container can use a private volume.
        "-v",
        f"{_get_docker_path(os.getcwd())}:/src:rw,Z",
        "--workdir",
        "/src",
    )


def run_hook(
    prefix: Prefix,
    entry: str,
    args: Sequence[str],
    file_args: Sequence[str],
    *,
    is_local: bool,
    require_serial: bool,
    color: bool,
) -> tuple[int, bytes]:  # pragma: win32 no cover
    # Rebuild the docker image in case it has gone missing, as many people do
    # automated cleanup of docker images.
    build_docker_image(prefix, pull=False)

    entry_exe, *cmd_rest = lang_base.hook_cmd(entry, args)

    entry_tag = ("--entrypoint", entry_exe, docker_tag(prefix))
    return lang_base.run_xargs(
        (*docker_cmd(color=color), *entry_tag, *cmd_rest),
        file_args,
        require_serial=require_serial,
        color=color,
    )


# =============================================================================
# END UPSTREAM
# =============================================================================


# =============================================================================
# BEGIN LOCAL EXTENSIONS
#
# Additional DinD detection layered on top of the upstream `_get_container_id`
# so that the hook can still find the container ID in environments where
# `/proc/1/mountinfo` does not reveal it (e.g. custom Docker images running
# on GitHub-hosted runners). The approach is based on the PR proposed at
# https://github.com/pre-commit/pre-commit/pull/2242, extended with an extra
# `/.dockerenv` marker-file detection signal.
# =============================================================================
import sys
from pathlib import Path

# Keep a reference to the upstream implementation so the combined version below
# can still call it as the primary detection method.
_get_container_id_mountinfo = _get_container_id


# -------- Mockable module-level values (used by the tests) --------

# Path to the cgroup proc file.
PROC_CGROUP = "/proc/1/cgroup"

# Path to the scheduler proc file.
PROC_SHED = "/proc/1/sched"

# Path to the `.dockerenv` marker file.
DOCKERENV = "/.dockerenv"

# Command used to list overlay type mounts.
MOUNT_OVERLAY = ("mount", "-t", "overlay")

# Command to list running Docker containers.
DOCKER_PS = ("docker", "ps", "--format", "{{ .ID }}")

# Command to inspect Docker container (container ID is appended at call site).
DOCKER_INSPECT = ("docker", "inspect")

# Mockable command-line arguments.
SYS_ARGV = sys.argv


# -------- Detection signals --------


def _is_in_docker_cgroup() -> bool:
    """Detect via `/proc/1/cgroup` - either the word `docker` appears on a
    line, or a `cpuset` entry has a 64-char container ID as its basename."""
    try:
        with open(PROC_CGROUP, "rb") as f:
            for line in f.readlines():
                if b"docker" in line:
                    return True

                parts = line.strip().split(b":")

                if len(parts) == 3:
                    _, name, path = parts

                    if name == b"cpuset" and len(os.path.basename(path)) == 64:
                        return True

            return False
    except FileNotFoundError:
        return False


def _is_in_docker_dockerenv() -> bool:
    """Detect via the `/.dockerenv` marker file."""
    return Path(DOCKERENV).exists()


def _is_in_docker_sched() -> bool:
    """Detect via `/proc/1/sched` - outside a container the first line starts
    with `systemd ...` or `init ...`."""
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
        _get_container_id_mountinfo() is not None
        or _is_in_docker_cgroup()
        or _is_in_docker_dockerenv()
        or _is_in_docker_sched()
    ):
        return True

    return False


# -------- Fallback ID lookup via mount + docker ps + docker inspect --------


def _get_container_id_cgroup() -> str:
    """Extract the container ID from the `cpuset` line in `/proc/1/cgroup`."""
    try:
        with open(PROC_CGROUP, "rb") as f:
            for line in f.readlines():
                parts = line.split(b":")

                if len(parts) == 3 and parts[1] == b"cpuset":
                    cid = os.path.basename(parts[2]).strip().decode()

                    if cid:
                        return cid
    except FileNotFoundError:
        return ""

    return ""


def _get_container_id_sched() -> str:
    """Find the container ID by matching the workdir of the overlay mount
    against `GraphDriver.Data.WorkDir` from `docker inspect`."""

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
            # Container probably does not exist anymore
            return ""

        (container,) = json.loads(out)

        if (
            "GraphDriver" in container
            and "Data" in container["GraphDriver"]
            and "WorkDir" in container["GraphDriver"]["Data"]
            and container["GraphDriver"]["Data"]["WorkDir"] == workdir
        ):
            return container_id
    else:
        return ""


# -------- Override the upstream `_get_container_id` --------


def _get_container_id() -> str | None:  # type: ignore[no-redef]
    """Combined container ID lookup.

    Tries the upstream mountinfo-based detection first, then falls back to the
    cgroup-based lookup and the mount/docker-ps/docker-inspect heuristic when
    the other DinD signals (`.dockerenv`, `/proc/1/sched`) indicate we are
    inside a container.
    """
    container_id = _get_container_id_mountinfo()
    if container_id is not None:
        return container_id

    if not _is_in_docker():
        return None

    container_id = _get_container_id_cgroup()
    if container_id:
        return container_id

    container_id = _get_container_id_sched()
    if container_id:
        return container_id

    return None


# -------- Entry point --------


def main() -> int:
    # Get docker command enriched by the hook args
    cmd = docker_cmd(color=False) + tuple(SYS_ARGV[1:])

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
