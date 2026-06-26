#!/usr/bin/env python3
"""Poll an HTTP endpoint or TCP port from inside the docker network until ready; exit 0 or 1.

Run as a one-shot container on the pool's network so readiness works whether the orchestrator runs
on the host or inside a container - it reaches the pool by container name, not via a published port,
so the orchestrator itself only ever needs the docker socket. stdlib only.

  python3 wait_ready.py --http http://openbench-pool:5662/api/v1/info --status 200 --timeout 40
  python3 wait_ready.py --tcp openbench-pool:3333 --timeout 60
"""
import argparse
import socket
import time
import urllib.error
import urllib.request


def _http_ready(url: str, status: int, body: str | None) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = response.read().decode("utf-8", "replace").strip()
            return response.status == status and (body is None or payload == body)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace").strip()
        return exc.code == status and (body is None or payload == body)
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _tcp_ready(host_port: str) -> bool:
    host, _, port = host_port.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=2):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", help="URL to GET")
    parser.add_argument("--tcp", help="host:port to connect to")
    parser.add_argument("--status", type=int, default=200, help="http: required status")
    parser.add_argument("--body", help="http: exact required response body")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if args.http and _http_ready(args.http, args.status, args.body):
            return 0
        if args.tcp and _tcp_ready(args.tcp):
            return 0
        time.sleep(1.0)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
