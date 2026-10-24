"""Keep the per-temperature placement cost curves as small data (gzipped JSON).

VPR prints one cost row per annealing temperature; runs/ (logs and placements) is local and not
committed, so this extracts the curves into data/<design>/curves/<tag>.json.gz, which is small
enough to keep. Every number in the paper traces to data/ (records or curves).

Usage: python scripts/keep_curves.py [design ...]
"""

from __future__ import annotations

import gzip
import json
import sys

import nornlib as nl


def keep(design: str) -> int:
    runs = nl.runs_dir(design, "runs")
    out = nl.DATA / design / "curves"
    if not runs.is_dir():
        return 0
    count = 0
    for log in sorted(runs.glob("*/vpr.out")):
        metrics = nl.Metrics(log)
        if not metrics.curve:
            continue
        path = out / f"{log.parent.name}.json.gz"
        nl.ensure_dir(path.parent)
        payload = json.dumps({"design": design, "tag": log.parent.name,
                              "curve": metrics.curve}, sort_keys=True) + "\n"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(payload)
        count += 1
    print(f"{design}: {count} cost curves kept")
    return count


def main(argv: list[str]) -> int:
    designs = argv or [p.parent.name for p in sorted(nl.DATA.glob("*/runs.jsonl"))]
    for design in designs:
        keep(design)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
