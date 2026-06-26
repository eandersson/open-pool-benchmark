"""Unit tests for the docker-stats parser and the table/CSV helpers."""

from __future__ import annotations

import unittest

from openbench import report
from openbench.tests import base


class ParseDockerStatsTests(unittest.TestCase):
    def test_mean_cpu_and_peak_rss_mib(self) -> None:
        lines = ["100.0%|200MiB / 2GiB", "300.0%|326MiB / 2GiB"]
        cpu, rss = report.parse_docker_stats(lines)
        self.assertEqual(cpu, 200.0)
        self.assertEqual(rss, 326.0)

    def test_gib_normalised_to_mib(self) -> None:
        _, rss = report.parse_docker_stats(["10%|1.5GiB / 4GiB"])
        self.assertEqual(rss, 1.5 * 1024)

    def test_kib_normalised_to_mib(self) -> None:
        _, rss = report.parse_docker_stats(["10%|512kiB / 4GiB"])
        self.assertAlmostEqual(rss, 0.5)

    def test_empty_input_is_zero(self) -> None:
        self.assertEqual(report.parse_docker_stats([]), (0.0, 0.0))

    def test_malformed_lines_skipped(self) -> None:
        cpu, rss = report.parse_docker_stats(["garbage", "", "50.0%|100MiB / 1GiB", "no-pipe-here"])
        self.assertEqual(cpu, 50.0)
        self.assertEqual(rss, 100.0)


class RenderTableTests(unittest.TestCase):
    def test_columns_aligned_to_widest_cell(self) -> None:
        text = report.render_table(["pool", "val/s"], [["pogolo", "391349"], ["x", "27"]])
        lines = text.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(len({len(line) for line in lines}), 1)
        self.assertIn("pogolo", lines[1])


class WriteCsvTests(base.TempDirTestCase):
    def test_roundtrip(self) -> None:
        import csv

        path = self.make_tempdir() / "out.csv"
        report.write_csv(path, ["pool", "val/s"], [["pogolo", 391349], ["x", 27]])
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0], ["pool", "val/s"])
        self.assertEqual(rows[1], ["pogolo", "391349"])
