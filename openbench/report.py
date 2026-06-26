"""Result formatting: the `docker stats` parser, an aligned text table, and a CSV writer.

`parse_docker_stats` replaces the identical inline-Python one-liner the old bash drivers embedded in
four scripts - one place to read `CPU%|MemUsage` samples now.
"""

from __future__ import annotations

import csv
import pathlib
from collections.abc import Sequence

_GIB_IN_MIB = 1024.0
_KIB_IN_MIB = 1.0 / 1024.0


def parse_docker_stats(lines: Sequence[str]) -> tuple[float, float]:
    """Fold raw `CPU%|MemUsage` samples (e.g. `602.13%|326MiB / 2GiB`) into (mean CPU%, peak RSS).

    Peak RSS is in MiB. Malformed lines are skipped, not fatal - sampling is best-effort.
    """
    cpu_samples: list[float] = []
    mem_samples_mib: list[float] = []
    for line in lines:
        if "|" not in line:
            continue
        cpu_text, mem_text = line.split("|", 1)
        try:
            cpu_samples.append(float(cpu_text.strip().rstrip("%")))
        except ValueError:
            pass
        used = mem_text.split("/")[0].strip()
        number = "".join(char for char in used if char.isdigit() or char == ".")
        try:
            value = float(number)
        except ValueError:
            continue
        if "GiB" in used:
            value *= _GIB_IN_MIB
        elif "kiB" in used:
            value *= _KIB_IN_MIB
        mem_samples_mib.append(value)
    mean_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0
    peak_rss = max(mem_samples_mib) if mem_samples_mib else 0.0
    return mean_cpu, peak_rss


def render_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """A monospace table: every column right-aligned to its widest cell, header included."""
    columns = [headers, *rows]
    widths = [max(len(str(column[index])) for column in columns) for index in range(len(headers))]
    out = []
    for row in (headers, *rows):
        out.append("  ".join(str(cell).rjust(widths[index]) for index, cell in enumerate(row)))
    return "\n".join(out)


def write_csv(
    path: str | pathlib.Path, headers: Sequence[str], rows: Sequence[Sequence[object]]
) -> None:
    path = pathlib.Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
