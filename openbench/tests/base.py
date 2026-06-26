"""Shared fixtures + builders for the openbench unit tests."""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from openbench import config

VALID_REGISTRY_YAML = """
regtest:
  rpc_user: openbench
  rpc_pass: openbenchpass
  rpc_port: 18443
  address: bcrt1qexampleaddress

profiles:
  validation:
    difficulty: 1000000
    coinbase_tag: /openbench/

pools:
  pogolo:
    description: pogolo test
    source: image
    image: 0xf0xx0/pogolo:latest
    stratum_port: 5661
    api_port: 5662
    config:
      format: toml
      template: pools/pogolo/bench.toml
      mount: /config/pogolo.toml
    readiness:
      kind: http
      url: http://127.0.0.1:${API_PORT}/api/v1/info
      status: 200
  disabled-pool:
    description: an opt-in pool
    enabled: false
    source: build
    build_context: ../somewhere
    stratum_port: 3333
    config:
      format: none
    readiness:
      kind: tcp
"""


class TempDirTestCase(unittest.TestCase):
    """Provides a fresh temp dir that is cleaned up after each test."""

    def make_tempdir(self) -> pathlib.Path:
        path = pathlib.Path(tempfile.mkdtemp(prefix="openbench-test-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def write_registry(self, text: str) -> pathlib.Path:
        directory = self.make_tempdir()
        registry_path = directory / "pools.yml"
        registry_path.write_text(text, encoding="utf-8")
        return registry_path


def sample_regtest(**overrides: object) -> config.Regtest:
    values: dict[str, object] = {
        "rpc_user": "openbench",
        "rpc_pass": "openbenchpass",
        "rpc_port": 18443,
        "bitcoind_container": "bitcoind",
        "network": "openbench-regtest_default",
        "compose_project": "openbench-regtest",
        "address": "bcrt1qexampleaddress",
    }
    values.update(overrides)
    return config.Regtest(**values)  # type: ignore[arg-type]


def sample_profile(**overrides: object) -> config.Profile:
    values: dict[str, object] = {
        "name": "validation",
        "difficulty": 1000000.0,
        "coinbase_tag": "/openbench/",
    }
    values.update(overrides)
    return config.Profile(**values)  # type: ignore[arg-type]


def sample_pinning(**overrides: object) -> config.Pinning:
    values: dict[str, object] = {
        "enabled": True,
        "bitcoind_cpus": "0",
        "pool_cpus": "1",
        "bench_cpus": "2",
    }
    values.update(overrides)
    return config.Pinning(**values)  # type: ignore[arg-type]


def sample_pool(**overrides: object) -> config.PoolSpec:
    values: dict[str, object] = {
        "name": "pogolo",
        "description": "pogolo test",
        "source": "image",
        "stratum_port": 5661,
        "api_port": 5662,
        "image": "0xf0xx0/pogolo:latest",
        "config": config.ConfigSpec(
            format="toml", template="pools/pogolo/bench.toml", mount="/config/pogolo.toml"
        ),
        "readiness": config.Readiness(kind="http", url="http://127.0.0.1:${API_PORT}/api/v1/info"),
    }
    values.update(overrides)
    return config.PoolSpec(**values)  # type: ignore[arg-type]
