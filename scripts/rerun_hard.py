"""Rerun the hard arm after a constraint-region change (kept records are replaced).

Deletes runs/<design>/runs/hard-* and drops the hard records from data/<design>/runs.jsonl,
then runs the hard arm for every seed of the seed families present.

Usage: python scripts/rerun_hard.py [design ...]
"""

from __future__ import annotations

import json
import shutil
import sys

import matrix
import nornlib as nl


def rerun(design: str) -> int:
    for seed in nl.SEED_FAMILIES:
        shutil.rmtree(nl.runs_dir(design, "runs", f"hard-{seed}"), ignore_errors=True)
    records = [r for r in matrix.load_records(design) if str(r.get("arm")) != "hard"]
    path = matrix.record_path(design)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records),
                    encoding="utf-8")
    for seed in nl.SEED_FAMILIES:
        matrix.hard(design, seed)
    return 0


def main(argv: list[str]) -> int:
    designs = argv or [p.parent.name for p in sorted(nl.DATA.glob("*/runs.jsonl"))]
    for design in designs:
        rerun(design)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
