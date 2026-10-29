#!/usr/bin/env python3
"""Rent exponent (Mimir metric rent.p) per design set: real VTR Verilog, MCNC, Loki, synthetic r5/n5/r6.

Reads the Mimir main store read-only (SQLite, mode=ro) and writes data/analysis/rent-split.json.
The measurer is mimir/rent.py (recursive METIS bisection, seeds 1 to 3); a negative exponent or a
low-confidence flag is reported, not dropped. Standard library only.

Usage: python3 -I scripts/rent_split.py --store <mimir-main.db> [--out data/analysis/rent-split.json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from pathlib import Path

REAL_PREFIXES = ("r5_", "n5_", "r6_")


def group_of(source: str, level: str, design: str) -> str | None:
    """Set name of one (source, level, design), or None if it is outside the five sets."""
    if source == "mcnc":
        return "MCNC"
    if source.startswith("loki:"):
        return f"Loki ({level} level)"
    if source == "norns-netlist":
        for p in REAL_PREFIXES:
            if design.startswith(p):
                return "synthetic " + p.rstrip("_")
        return "real VTR Verilog"
    return None


def summarise(runs: list[tuple[str, float, bool]]) -> dict:
    """runs: (design, rent.p, low_confidence) per measurer seed."""
    vals = [v for _, v, _ in runs]
    per: dict[str, list[float]] = {}
    for d, v, _ in runs:
        per.setdefault(d, []).append(v)
    dmean = [statistics.fmean(v) for v in per.values()]
    return {
        "n_designs": len(per),
        "n_runs": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "mean_of_design_means": round(statistics.fmean(dmean), 4),
        "negative_runs": sum(v < 0 for v in vals),
        "negative_designs": sum(m < 0 for m in dmean),
        "low_confidence_runs": sum(lc for _, _, lc in runs),
        "low_confidence_designs": len({d for d, _, lc in runs if lc}),
        "confident_runs": sum(not lc for _, _, lc in runs),
        "confident_mean": round(statistics.fmean([v for _, v, lc in runs if not lc]), 4)
        if any(not lc for _, _, lc in runs) else None,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/analysis/rent-split.json"))
    args = ap.parse_args(argv)
    db = sqlite3.connect(f"file:{args.store}?mode=ro", uri=True)
    low = {
        (r[0], r[1], r[2], r[3], r[4]): bool(r[5])
        for r in db.execute(
            "select source, level, design, arch, seed, value from records where metric='rent.low_confidence'"
        )
    }
    groups: dict[str, list[tuple[str, float, bool]]] = {}
    for source, level, design, arch, seed, value in db.execute(
        "select source, level, design, arch, seed, value from records where metric='rent.p'"
    ):
        g = group_of(source, level, design)
        if g is None:
            continue
        lc = low.get((source, level, design, arch, seed), False)
        groups.setdefault(g, []).append((f"{source}|{level}|{design}|{arch}", float(value), lc))
    order = ["real VTR Verilog", "MCNC", "Loki (lut level)", "Loki (gate level)",
             "synthetic r5", "synthetic n5", "synthetic r6"]
    out = {"metric": "rent.p", "store": args.store.name,
           "sets": {g: summarise(groups[g]) for g in order if g in groups}}
    syn = [r for g in groups if g.startswith("synthetic") for r in groups[g]]
    out["sets"]["synthetic all"] = summarise(syn)
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for g, s in out["sets"].items():
        print(g, s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
