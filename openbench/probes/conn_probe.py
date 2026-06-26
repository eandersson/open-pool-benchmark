#!/usr/bin/env python3
"""Open Stratum connections ONE AT A TIME, holding each open, until the pool stops
accepting (refuses / accepts-then-closes) or stops responding (no reply in time).
Reports how many were held. Distinguishes a LOCAL fd-limit (our side) from a pool limit.

Each connection subscribes AND authorizes so the pool's auth-timeout can't reclaim early
connections before we reach the ceiling. stdlib only.

  python3 conn_probe.py <host> <port> <address> [safety_cap]
"""
import errno
import json
import socket
import sys
import time


def main() -> int:
    host, port, address = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else 5000

    conns: list[socket.socket] = []
    reason = f"reached the {cap:,}-connection safety cap (no ceiling hit)"
    started = time.time()
    step = 100 if cap <= 20000 else 1000

    while len(conns) < cap:
        nth = len(conns) + 1
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except OSError as exc:
            reason = (f"LOCAL fd limit hit at #{nth} ({exc}) -- raise the container ulimit; "
                      f"this is OUR side, not the pool")
            break
        sock.settimeout(8.0)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
        except OSError:
            pass
        try:
            sock.connect((host, port))
        except OSError as exc:
            local = {errno.EMFILE, errno.ENFILE, errno.EADDRNOTAVAIL, errno.EADDRINUSE, errno.ENOBUFS}
            tag = "LOCAL resource limit" if exc.errno in local else "pool REFUSED"
            reason = f"{tag} at connection #{nth} ({type(exc).__name__}: {exc})"
            sock.close()
            break
        try:
            sock.sendall(json.dumps({"id": 1, "method": "mining.subscribe",
                                     "params": ["conntest/1.0"]}).encode() + b"\n")
            sock.sendall(json.dumps({"id": 2, "method": "mining.authorize",
                                     "params": [address, "x"]}).encode() + b"\n")
            buf = b""
            while b"result" not in buf and b"method" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("pool closed the connection with no reply")
                buf += chunk
        except OSError as exc:
            reason = (f"connection #{nth} connected but was NOT held "
                      f"({type(exc).__name__}: {exc})")
            sock.close()
            break
        conns.append(sock)
        if len(conns) % step == 0:
            print(f"  {len(conns):,} held ({time.time() - started:.1f}s)", flush=True)

    print(f"RESULT {host}:{port}  held={len(conns):,}  stopped_because: {reason}")
    for sock in conns:
        try:
            sock.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
