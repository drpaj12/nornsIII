"""Backfill retention/displacement on kept run records (after a metric fix).

Every record's final placement lives in runs/<design>/runs/<tag>/final.place, and the seed a run
started from is reproducible from the kept seed files, so retention and displacement can be
recomputed without rerunning VPR. Rewrites data/<design>/runs.jsonl in place.

Usage: python scripts/backfill.py [design ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matrix
import nornlib as nl


def seed_of(design: str, rec: dict[str, object]) -> tuple[Path | None, str | None]:
    arm = str(rec.get("arm", ""))
    tag = str(rec.get("tag", ""))
    if arm == "soft":
        seed = tag.split("-")[1]
        return nl.runs_dir(design, "seeds", f"{seed}-{tag.split('-')[2]}.place"), seed
    if arm == "hard":
        return None, tag.split("-", 1)[1]
    if arm == "hot":
        seed = tag.split("-", 1)[1]
        return nl.runs_dir(design, "crossover", f"{seed}-P.place"), seed
    if arm in ("cold", "cold-off"):
        pstar = nl.runs_dir(design, "crossover", "Pstar.place")
        path = nl.runs_dir(design, "crossover", "crossover.json")
        region = ""
        if path.is_file():
            region = str(nl.read_json(path).get("region_seed", ""))
        return pstar, region or None
    return None, None


def backfill(design: str) -> int:
    records = matrix.load_records(design)
    updated = 0
    for rec in records:
        if rec.get("rc") != 0:
            continue
        run_dir = nl.runs_dir(design, "runs", str(rec.get("tag")))
        final = run_dir / "final.place"
        if not final.is_file():
            continue
        seed, region = seed_of(design, rec)
        if seed is not None and not seed.is_file():
            seed = None
        if seed is None and region is None:
            continue
        values = matrix.compute_retention(design, seed, final, region)
        for key, value in values.items():
            if value is not None or rec.get(key) is None:
                if rec.get(key) != value:
                    rec[key] = value
                    updated += 1
    path = matrix.record_path(design)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records),
                    encoding="utf-8")
    print(f"{design}: {updated} fields updated")
    return 0


def main(argv: list[str]) -> int:
    designs = argv or [p.parent.name for p in sorted(nl.DATA.glob("*/runs.jsonl"))]
    for design in designs:
        backfill(design)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
