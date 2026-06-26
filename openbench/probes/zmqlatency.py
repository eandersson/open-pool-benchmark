#!/usr/bin/env python3
"""Measure the ZMQ fastblock critical path: from a new block at bitcoind to a
connected Stratum client receiving the fresh mining.notify. Lower = miners stop
hashing the stale block sooner (less wasted work, less orphan risk). Uniform
across pools (measured from the client's perspective). stdlib only.

Connects one Stratum client, then repeatedly generates a block at bitcoind (RPC)
and times until a mining.notify with a *new* job_id arrives.
"""
import argparse
import asyncio
import base64
import json
import time
import urllib.request


def rpc_call(url: str, auth: str, method: str, params: list):
    body = json.dumps({"jsonrpc": "1.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        url, data=body,
        headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())["result"]


class Client:
    def __init__(self):
        self.job_id = None
        self.new_job = asyncio.Event()

    async def connect(self, host, port, address):
        self._r, self._w = await asyncio.open_connection(host, port)
        self._send({"id": 1, "method": "mining.subscribe", "params": ["zmqbench/1.0"]})
        self._send({"id": 2, "method": "mining.authorize", "params": [address, "x"]})
        await self._w.drain()
        asyncio.create_task(self._read())

    def _send(self, obj):
        self._w.write((json.dumps(obj) + "\n").encode())

    async def _read(self):
        while True:
            line = await self._r.readline()
            if not line:
                return
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("method") == "mining.notify":
                job_id = message["params"][0]
                if job_id != self.job_id:
                    self.job_id = job_id
                    self.new_job.set()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=3333)
    ap.add_argument("--address", required=True, help="valid regtest payout address")
    ap.add_argument("--rpc", required=True, help="bitcoind RPC url, e.g. http://bitcoind:18443")
    ap.add_argument("--rpc-user", default="openbench")
    ap.add_argument("--rpc-pass", default="openbenchpass")
    ap.add_argument("--rounds", type=int, default=20)
    args = ap.parse_args()

    auth = base64.b64encode(f"{args.rpc_user}:{args.rpc_pass}".encode()).decode()
    gen_addr = await asyncio.to_thread(rpc_call, args.rpc, auth, "getnewaddress", [])

    c = Client()
    await c.connect(args.host, args.port, args.address)
    try:
        await asyncio.wait_for(c.new_job.wait(), 30)
    except asyncio.TimeoutError:
        print("never received an initial job")
        return

    lats = []
    for _ in range(args.rounds):
        await asyncio.sleep(0.4)
        c.new_job.clear()
        t0 = time.perf_counter()
        await asyncio.to_thread(rpc_call, args.rpc, auth, "generatetoaddress", [1, gen_addr])
        try:
            await asyncio.wait_for(c.new_job.wait(), 10)
        except asyncio.TimeoutError:
            continue
        lats.append((time.perf_counter() - t0) * 1000.0)
    if lats:
        lats.sort()
        n = len(lats)
        print("n=%-3d  median=%.1f ms  avg=%.1f ms  min=%.1f  max=%.1f"
              % (n, lats[n // 2], sum(lats) / n, lats[0], lats[-1]))
    else:
        print("no new-work notifications observed")


if __name__ == "__main__":
    asyncio.run(main())
