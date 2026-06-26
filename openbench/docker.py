"""Wrappers over `docker` / `docker compose`, plus a readiness/log helper and a CPU/RSS sampler.

The orchestrator drives everything through the Docker daemon: it builds images, runs the regtest
node + the pool + the load generators as containers, and pins each to CPU cores. It only needs the
docker socket, so it runs identically on the host or inside the `openbench` compose service
(docker-out-of-docker).

Bind mounts under docker-out-of-docker: when the orchestrator runs inside a container, a path like
`/workspace/probes` it wants to share with a sibling container must be expressed as the *host* path
the daemon sees, not the orchestrator's own container path. `host_source` discovers that by asking
the daemon for the orchestrator's own bind mounts (`docker inspect $self`) and rewriting the path
onto the matching host source - so the in-container mount path can be anything (no `$PWD` matching).
On the host (no enclosing container) it's a no-op.

CPU pinning: every container we launch takes a `cpuset` (-> `--cpuset-cpus`) so the pool and the
benchmark tools are confined to disjoint cores and never contend mid-measurement.
"""

from __future__ import annotations

import functools
import logging
import os
import pathlib
import re
import socket
import subprocess
import threading
import time

LOG = logging.getLogger(__name__)

DOCKER = "docker"
PROBE_IMAGE = os.environ.get("OPENBENCH_PROBE_IMAGE", "python:3.14-slim")
_STATS_FORMAT = "{{.CPUPerc}}|{{.MemUsage}}"
_SAMPLE_INTERVAL_SECONDS = 1.0
_RESPONSIVE_POLL_SECONDS = 0.1


class DockerError(RuntimeError):
    """A docker command failed (non-zero exit, or timed out); stderr is captured in the message."""


def _run(
    args: list[str],
    *,
    capture: bool = False,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    LOG.debug("docker %s", " ".join(args))
    try:
        result = subprocess.run([DOCKER, *args], capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DockerError(f"`docker {' '.join(args)}` timed out after {timeout}s") from exc
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip() if capture else "(stderr not captured)"
        raise DockerError(f"`docker {' '.join(args)}` exited {result.returncode}: {stderr}")
    return result


_CONTAINER_ID_RE = re.compile(r"/(?:docker/containers|containers)/([0-9a-f]{64})/")


def _self_container_id() -> str | None:
    """Best-effort id of the container the orchestrator runs in, or None on the host.

    The hostname is the short container id by default; if that isn't inspectable (e.g. a custom
    hostname), fall back to the 64-hex id embedded in /proc/self/mountinfo (the docker-managed
    resolv.conf/hostname mounts reference it).
    """
    name = socket.gethostname()
    if name and _run(["inspect", name], capture=True, check=False).returncode == 0:
        return name
    try:
        text = pathlib.Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        return None
    match = _CONTAINER_ID_RE.search(text)
    return match.group(1) if match else None


@functools.lru_cache(maxsize=1)
def _self_bind_mounts() -> tuple[tuple[str, str], ...]:
    """The orchestrator's own (destination, host-source) bind mounts; empty when run on the host.

    Cached: mounts don't change over a run. Sorted longest-destination-first so the most specific
    mount wins when one is nested inside another.
    """
    container_id = _self_container_id()
    if not container_id:
        return ()
    template = (
        '{{range .Mounts}}{{if eq .Type "bind"}}{{.Destination}}\t{{.Source}}\n{{end}}{{end}}'
    )
    result = _run(["inspect", "-f", template, container_id], capture=True, check=False)
    if result.returncode != 0:
        return ()
    mounts = []
    for line in result.stdout.splitlines():
        if "\t" in line:
            destination, source = line.split("\t", 1)
            mounts.append((destination.strip(), source.strip()))
    mounts.sort(key=lambda pair: len(pair[0]), reverse=True)
    return tuple(mounts)


def host_source(path: str | pathlib.Path) -> str:
    """The host path the daemon sees for an in-container path, via the orchestrator's bind mounts.

    Returns the path unchanged when no mount covers it - i.e. when the orchestrator runs on the host
    (then the path already *is* a host path), or for a path outside the mounted tree. Inputs are
    absolute container (POSIX) paths, so matching is done with PurePosixPath (no filesystem access).
    """
    text = str(path)
    candidate = pathlib.PurePosixPath(text)
    for destination, source in _self_bind_mounts():
        dest = pathlib.PurePosixPath(destination)
        if candidate == dest:
            return source
        if dest in candidate.parents:
            return f"{source.rstrip('/')}/{candidate.relative_to(dest).as_posix()}"
    return text


def mount(host_path: str | pathlib.Path, container_path: str, *, read_only: bool = True) -> str:
    """Format a `-v` bind-mount string, translating the source to the host path the daemon sees."""
    suffix = ":ro" if read_only else ""
    return f"{host_source(host_path)}:{container_path}{suffix}"


def _cpuset_args(cpuset: str | None) -> list[str]:
    return ["--cpuset-cpus", cpuset] if cpuset else []


def available() -> bool:
    """True if the docker CLI is installed and the daemon answers."""
    try:
        _run(["info"], capture=True, check=False, timeout=20)
        return True
    except OSError, subprocess.SubprocessError, DockerError:
        return False


def compose(
    files: list[pathlib.Path],
    project: str,
    args: list[str],
    *,
    capture: bool = False,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `docker compose -f <each file> -p <project> <args>` (used for the regtest node)."""
    command = ["compose"]
    for compose_file in files:
        command += ["-f", str(compose_file)]
    command += ["-p", project, *args]
    return _run(command, capture=capture, check=check, timeout=timeout)


def image_exists(image: str) -> bool:
    return _run(["image", "inspect", image], capture=True, check=False).returncode == 0


def pull(image: str) -> None:
    LOG.info("pulling image %s", image)
    _run(["pull", image])


def build(tag: str, context: str | pathlib.Path, dockerfile: str | None = None) -> None:
    LOG.info("building image %s from %s", tag, context)
    args = ["build", "-t", tag]
    if dockerfile:
        args += ["-f", str(pathlib.Path(dockerfile))]
    args.append(str(pathlib.Path(context).resolve()))
    _run(args)


def run_detached(
    name: str,
    image: str,
    *,
    network: str,
    cpuset: str | None = None,
    entrypoint: str | None = None,
    command: list[str] | None = None,
    env: dict[str, str] | None = None,
    ports: list[str] | None = None,
    volumes: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> None:
    """`docker run -d` a named container on `network`, pinned to `cpuset`."""
    args = ["run", "-d", "--name", name, "--network", network, *_cpuset_args(cpuset)]
    if entrypoint:
        args += ["--entrypoint", entrypoint]
    for key, value in (env or {}).items():
        args += ["-e", f"{key}={value}"]
    for published in ports or []:
        args += ["-p", published]
    for volume in volumes or []:
        args += ["-v", volume]
    args += extra_args or []
    args.append(image)
    args += command or []
    _run(args)


def run_oneshot(
    image: str,
    command: list[str],
    *,
    network: str | None = None,
    cpuset: str | None = None,
    volumes: list[str] | None = None,
    env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    timeout: float | None = None,
) -> str:
    """`docker run --rm` (pinned to `cpuset`) and return stdout."""
    args = ["run", "--rm", *_cpuset_args(cpuset)]
    if network:
        args += ["--network", network]
    for key, value in (env or {}).items():
        args += ["-e", f"{key}={value}"]
    for volume in volumes or []:
        args += ["-v", volume]
    args += extra_args or []
    args.append(image)
    args += command
    return _run(args, capture=True, timeout=timeout).stdout


def run_oneshot_status(
    image: str,
    command: list[str],
    *,
    network: str | None = None,
    cpuset: str | None = None,
    volumes: list[str] | None = None,
    env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    timeout: float | None = None,
) -> tuple[int, str]:
    """Like run_oneshot but never raises on a non-zero exit - returns (exit_code, stdout+stderr).

    Used where the exit code IS the verdict: the readiness check and the miner's work audit (3 on a
    failed audit). A failed check must not look like a Docker infrastructure error.
    """
    args = ["run", "--rm", *_cpuset_args(cpuset)]
    if network:
        args += ["--network", network]
    for key, value in (env or {}).items():
        args += ["-e", f"{key}={value}"]
    for volume in volumes or []:
        args += ["-v", volume]
    args += extra_args or []
    args.append(image)
    args += command
    result = _run(args, capture=True, check=False, timeout=timeout)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def exec_in(container: str, command: list[str], *, check: bool = True) -> str:
    return _run(["exec", container, *command], capture=True, check=check).stdout


def logs(name: str) -> str:
    result = _run(["logs", name], capture=True, check=False)
    return (result.stdout or "") + (result.stderr or "")


def published_ports(name: str) -> str:
    """The container's host port mappings (`docker port`), e.g. '3333/tcp -> 127.0.0.1:49153'."""
    return _run(["port", name], capture=True, check=False).stdout.strip()


def remove(*names: str) -> None:
    for name in names:
        _run(["rm", "-f", name], capture=True, check=False)


def is_running(name: str) -> bool:
    args = ["ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"]
    output = _run(args, capture=True).stdout
    return name in output.split()


def stats_once(name: str) -> str | None:
    """One `docker stats` sample as `CPU%|MemUsage`, or None if the container is gone."""
    result = _run(
        ["stats", "--no-stream", "--format", _STATS_FORMAT, name], capture=True, check=False
    )
    line = result.stdout.strip()
    return line or None


def wait_log(name: str, pattern: str, *, timeout_seconds: int = 60) -> bool:
    """Poll a container's logs until `pattern` (a plain substring) appears (read via the socket)."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if pattern in logs(name):
            return True
        if not is_running(name):
            return pattern in logs(name)
        time.sleep(_SAMPLE_INTERVAL_SECONDS)
    return False


class StatsSampler:
    """Background thread sampling a container's CPU%/RSS once a second until stopped.

    `docker stats --no-stream` already blocks for its own ~1s sample window, so that call is the
    pacer; the loop only adds a short responsiveness poll so __exit__ can stop it promptly. `lines`
    accumulates raw `CPU%|MemUsage` strings for report.parse_docker_stats.
    """

    def __init__(self, container: str) -> None:
        self._container = container
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self.lines: list[str] = []

    def _loop(self) -> None:
        while not self._stop.is_set() and is_running(self._container):
            sample = stats_once(self._container)
            if sample:
                self.lines.append(sample)
            self._stop.wait(_RESPONSIVE_POLL_SECONDS)

    def __enter__(self) -> StatsSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
