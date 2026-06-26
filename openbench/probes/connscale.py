#!/usr/bin/env python3
"""Open N Stratum connections (subscribe + authorize each) and hold them open
idle, to measure a pool's per-connection memory footprint at scale (e.g. 10k).
No share flood -- just established, idle connections -- so it isolates the memory
cost of a connection. Opens in batches to respect the listen backlog. stdlib only.
"""
import argparse
import asyncio
import json
import time

ESTABLISHED = 0
FAILED = 0


async def one_conn(host: str, port: int, address: str, stop: asyncio.Event) -> None:
    global ESTABLISHED, FAILED
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except Exception:
        FAILED += 1
        return
    try:
        writer.write((json.dumps({"id": 1, "method": "mining.subscribe",
                                  "params": ["connscale/1.0"]}) + "\n").encode())
        writer.write((json.dumps({"id": 2, "method": "mining.authorize",
                                  "params": [address, "x"]}) + "\n").encode())
        await writer.drain()
        while True:
            line = await asyncio.wait_for(reader.readline(), 30)
            if not line:
                FAILED += 1
                return
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == 2:
                break
        ESTABLISHED += 1
        await stop.wait()
    except Exception:
        FAILED += 1
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=3333)
    ap.add_argument("--address", required=True)
    ap.add_argument("--connections", type=int, default=10000)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--hold", type=float, default=14.0)
    args = ap.parse_args()

    stop = asyncio.Event()
    tasks = []
    for i in range(0, args.connections, args.batch):
        for _ in range(min(args.batch, args.connections - i)):
            tasks.append(asyncio.create_task(one_conn(args.host, args.port, args.address, stop)))
        await asyncio.sleep(0.15)

    deadline = time.time() + 90
    while ESTABLISHED + FAILED < args.connections and time.time() < deadline:
        await asyncio.sleep(0.5)
    print(f"ESTABLISHED {ESTABLISHED}/{args.connections}", flush=True)

    await asyncio.sleep(args.hold)
    stop.set()
    await asyncio.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
