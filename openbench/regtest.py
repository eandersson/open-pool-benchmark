"""The shared regtest bitcoind backend every pool-under-test mines against.

A private, harness-controlled regtest chain thrown away with the run. It runs as the `bitcoind`
service of `regtest/docker-compose.yml`; the orchestrator drives it with `bitcoin-cli` exec'd in
the container.
"""

from __future__ import annotations

import logging
import pathlib
import time
from typing import Any

import msgspec

from openbench import config
from openbench import docker

LOG = logging.getLogger(__name__)

_READY_TIMEOUT_SECONDS = 60
_MATURITY_BLOCKS = 110
_WALLET_NAME = "openbench"


class Backend:
    """Lifecycle + RPC/mining helpers for the regtest bitcoind compose service."""

    def __init__(
        self, regtest: config.Regtest, compose_files: list[pathlib.Path], project: str
    ) -> None:
        self._regtest = regtest
        self._files = compose_files
        self._project = project

    @property
    def network(self) -> str:
        return self._regtest.network

    @property
    def container(self) -> str:
        return self._regtest.bitcoind_container

    @property
    def rpc_user(self) -> str:
        return self._regtest.rpc_user

    @property
    def rpc_pass(self) -> str:
        return self._regtest.rpc_pass

    @property
    def address(self) -> str:
        return self._regtest.address

    def rpc_endpoint_in_network(self) -> str:
        """The RPC URL a probe container on the shared network uses to reach bitcoind."""
        return f"http://{self.container}:{self._regtest.rpc_port}"

    def _cli(self, *args: object) -> str:
        base = [
            "bitcoin-cli",
            "-regtest",
            f"-rpcuser={self._regtest.rpc_user}",
            f"-rpcpassword={self._regtest.rpc_pass}",
            f"-rpcport={self._regtest.rpc_port}",
        ]
        return docker.exec_in(self.container, base + [str(arg) for arg in args])

    def _try(self, *args: object) -> bool:
        try:
            self._cli(*args)
            return True
        except docker.DockerError:
            return False

    def up(self) -> None:
        """Start bitcoind and block until its RPC answers.

        `--build` keeps the image in sync with the Dockerfile (which bakes bitcoin.conf in);
        layer caching makes it a no-op once built.
        """
        LOG.info("starting regtest bitcoind (%s)", self.container)
        docker.compose(self._files, self._project, ["up", "-d", "--build", "bitcoind", "postgres"])
        deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._try("getblockchaininfo"):
                return
            time.sleep(1.0)
        tail = "\n".join(docker.logs(self.container).splitlines()[-25:])
        raise RuntimeError(
            f"regtest bitcoind did not become ready within {_READY_TIMEOUT_SECONDS}s. "
            f"Recent {self.container} logs:\n{tail or '(no container output)'}"
        )

    def down(self) -> None:
        docker.compose(self._files, self._project, ["down", "-v", "--remove-orphans"], check=False)

    def build_miner_image(self) -> None:
        """Build the cpuminer image (`openbench-miner:latest`) used for realistic mining load."""
        docker.compose(self._files, self._project, ["build", "miner"])

    def ensure_wallet(self) -> None:
        if not self._try("loadwallet", _WALLET_NAME):
            self._try("-named", "createwallet", f"wallet_name={_WALLET_NAME}")

    def new_address(self) -> str:
        return self._cli("getnewaddress").strip()

    def generate(self, blocks: int, address: str) -> None:
        self._cli("generatetoaddress", blocks, address)

    def block_count(self) -> int:
        """Current best-block height -- how we confirm a pool actually produced a block on-chain."""
        return int(self._cli("getblockcount").strip())

    @staticmethod
    def _coinbase_info(block: dict[str, Any]) -> tuple[list[str], str]:
        """From a getblock(verbosity=2) result: the coinbase output addresses and its scriptSig hex.

        A solo pool's coinbase pays the miner's address and carries its tag in the input script; the
        witness-commitment output has no address and is skipped.
        """
        coinbase = block["tx"][0]
        addresses: list[str] = []
        for vout in coinbase.get("vout", []):
            script = vout.get("scriptPubKey", {})
            if script.get("address"):
                addresses.append(script["address"])
            addresses.extend(script.get("addresses", []))  # pre-22.0 Core used a list
        sig = coinbase.get("vin", [{}])[0].get("coinbase", "")
        return addresses, sig

    def coinbase_pays(self, height: int, address: str, tag: str) -> tuple[bool, bool]:
        """Whether the block at `height` pays `address` and embeds `tag` in its coinbase scriptSig.

        This is the core solo-pool correctness check: a pool can produce a block bitcoind accepts
        while paying the wrong address, which only inspecting the coinbase catches.
        """
        block_hash = self._cli("getblockhash", height).strip()
        block = msgspec.json.decode(self._cli("getblock", block_hash, 2))
        addresses, sig = self._coinbase_info(block)
        return address in addresses, tag.encode().hex() in sig.lower()

    def mine_to_maturity(self) -> str:
        """Mine past coinbase maturity for spendable coins; return the address mined to."""
        self.ensure_wallet()
        address = self.new_address()
        LOG.info("mining %d blocks to maturity", _MATURITY_BLOCKS)
        self.generate(_MATURITY_BLOCKS, address)
        return address
