"""The per-run context the runner builds and the pool adapters consume.

Bundles what every pool in a run shares: the parsed registry, the live regtest backend, and a
scratch directory. The scratch lives inside the repo so rendered configs are reachable by the docker
daemon for bind mounts (including docker-out-of-docker).
"""

from __future__ import annotations

import dataclasses
import pathlib

from openbench import config
from openbench import regtest as regtest_module


@dataclasses.dataclass(frozen=True)
class RunContext:
    registry: config.Registry
    backend: regtest_module.Backend
    scratch: pathlib.Path

    @property
    def address(self) -> str:
        return self.backend.address
