"""Unit tests for the runner's pure helpers (the Docker-driven parts are covered by live runs)."""

from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from openbench import config
from openbench import runner
from openbench.tests import base


def _registry() -> config.Registry:
    return config.Registry(
        pools={},
        profiles={},
        regtest=base.sample_regtest(),
        pinning=base.sample_pinning(),
        root=pathlib.Path("."),
    )


def _probe_result(val: float, p50: float, cpu: float, rss: float) -> dict:
    return {
        "validated_per_sec": val,
        "latency_ms": {"p50": p50, "p95": p50 * 2, "p99": p50 * 3, "max": p50 * 4},
        "cpu_pct": cpu,
        "rss_mib": rss,
    }


class BenchBestRunTests(unittest.TestCase):
    def test_best_run_wins_and_metrics_are_from_it(self) -> None:
        runs = [
            _probe_result(100.0, 1.0, 50.0, 10.0),
            _probe_result(200.0, 3.0, 70.0, 20.0),
            _probe_result(180.0, 9.0, 90.0, 99.0),
        ]
        with mock.patch("openbench.runner._run_bench_probe", side_effect=runs):
            result = runner._bench_pool(
                pool=mock.Mock(), address="addr", knobs=runner.BenchKnobs(), repeat=3
            )
        self.assertEqual(result["validated_per_sec"], 200.0)
        self.assertEqual(result["latency_ms"]["p50"], 3.0)
        self.assertEqual(result["latency_ms"]["p95"], 6.0)
        self.assertEqual(result["cpu_pct"], 70.0)
        self.assertEqual(result["rss_mib"], 20.0)
        self.assertEqual(result["runs"], 3)
        self.assertEqual(result["validated_per_sec_per_run"], [100.0, 200.0, 180.0])

    def test_single_run_is_passthrough(self) -> None:
        with mock.patch(
            "openbench.runner._run_bench_probe", side_effect=[_probe_result(123.0, 1.0, 5.0, 6.0)]
        ):
            result = runner._bench_pool(mock.Mock(), "addr", runner.BenchKnobs(), 1)
        self.assertEqual(result["validated_per_sec"], 123.0)
        self.assertEqual(result["runs"], 1)
        self.assertEqual(result["validated_per_sec_per_run"], [123.0])

    def test_calls_probe_once_per_repeat(self) -> None:
        with mock.patch(
            "openbench.runner._run_bench_probe", side_effect=[_probe_result(1.0, 1.0, 1.0, 1.0)] * 3
        ) as probe:
            runner._bench_pool(mock.Mock(), "addr", runner.BenchKnobs(), 3)
        self.assertEqual(probe.call_count, 3)


class CoreAllocationTests(unittest.TestCase):
    def test_format_cpuset_collapses_runs(self) -> None:
        self.assertEqual(runner._format_cpuset([5, 6, 7, 8]), "5-8")
        self.assertEqual(runner._format_cpuset([2, 4, 5, 7]), "2,4-5,7")
        self.assertEqual(runner._format_cpuset([3]), "3")

    def test_load_generator_gets_the_leftover_cores(self) -> None:
        pinned = runner._registry_for_cores(_registry(), "1-4", host_cores=16).pinning
        self.assertEqual(pinned.pool_cpus, "1-4")
        self.assertEqual(pinned.bench_cpus, "5-15")  # everything after bitcoind(0) + pool(1-4)
        self.assertEqual(pinned.bitcoind_cpus, "0")  # unchanged
        self.assertTrue(pinned.enabled)

    def test_no_free_cores_raises(self) -> None:
        with self.assertRaises(config.ConfigError):
            runner._registry_for_cores(_registry(), "1-3", host_cores=4)  # 0 + 1,2,3 = all 4


class SuiteTests(unittest.TestCase):
    def test_benches_each_core_config_then_rest_once_at_largest(self) -> None:
        calls = []

        def stub(name: str, code: int):
            def run(*_args: object, **kwargs: object) -> int:
                calls.append((name, kwargs.get("label")))
                return code

            return run

        with (
            mock.patch.multiple(
                "openbench.runner",
                bench=stub("bench", 0),
                sweep=stub("sweep", 0),
                connscale=stub("connscale", 0),
                conn_limit=stub("conn-limit", 1),  # one failure -> non-zero overall
                latency=stub("latency", 0),
                validate=stub("validate", 0),
            ),
            mock.patch(
                "openbench.runner._registry_for_cores", side_effect=lambda reg, cpus, host: reg
            ),
        ):
            code = runner.suite(
                mock.Mock(), ["pogolo"], "validation", runner.BenchKnobs(), cores=["1", "1-4"]
            )

        self.assertEqual(
            [name for name, _ in calls],
            ["bench", "bench", "sweep", "connscale", "conn-limit", "latency", "validate"],
        )
        self.assertEqual([lbl for name, lbl in calls if name == "bench"], ["1-core", "4-core"])
        self.assertEqual([lbl for name, lbl in calls if name == "sweep"], ["4-core"])  # the largest
        self.assertEqual(code, 1)
