"""Reports: EXPERIMENT.md, the QoR/crossover tables and the paper's numbers.

Reads data/<design>/runs.jsonl (written by matrix.py) and writes docs/plan/EXPERIMENT.md,
docs/plan/tab-qor.md and docs/plan/tab-crossover.md. Ratio convention: seeded / baseline, so
below 1.0 is better; geomeans use the designs where both runs succeeded.

Usage: python scripts/report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import nornlib as nl


def load_records(design: str) -> list[dict[str, object]]:
    path = nl.DATA / design / "runs.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


ARMS = ("soft-full", "soft-inter", "hard")
FAMILIES = ("urd", "louvain", "spectral", "affinity", "kmeans_k", "kmeans_2k", "kmeans_4k")
METRICS = ("wirelength", "cpd_ns", "chan_width", "place_s")


def load_all() -> tuple[dict[str, list[dict[str, object]]], list[str]]:
    data: dict[str, list[dict[str, object]]] = {}
    designs = []
    for path in sorted(nl.DATA.glob("*/runs.jsonl")):
        design = path.parent.name
        recs = [r for r in load_records(design) if r.get("rc") == 0]
        data[design] = recs
        if recs:
            designs.append(design)
    order = [d for d in nl.DESIGN_ORDER if d in data]
    return data, order


def pick(recs: list[dict[str, object]], arm: str, seed: str = "", variant: str = "",
         scale: float | None = None) -> dict[str, object] | None:
    for r in recs:
        a = str(r.get("arm", ""))
        if arm == "soft" and a == "soft" and r.get("tag") == f"soft-{seed}-{variant}":
            return r
        if arm == "hard" and a == "hard" and r.get("tag") == f"hard-{seed}":
            return r
        if arm == "baseline" and a == "baseline":
            return r
        if arm == "unseeded" and a == "unseeded" and r.get("scale") == scale:
            return r
        if arm == "cold" and a == "cold" and r.get("scale") == scale:
            return r
        if arm == "hot" and a == "hot" and r.get("tag") == f"hot-{seed}":
            return r
    return None


def ratio(num: dict[str, object] | None, den: dict[str, object] | None,
          key: str) -> float | None:
    if not num or not den:
        return None
    a, b = num.get(key), den.get(key)
    if a is None or b in (None, 0):
        return None
    return float(a) / float(b)


def geomean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None and v > 0]
    return nl.geomean(vals) if vals else None


def qor_table(data: dict[str, list[dict[str, object]]], designs: list[str]) -> list[str]:
    rows = []
    rows.append("| seed | arm | wirelength | delay | chan width | place runtime | runs |")
    rows.append("|---|---|---|---|---|---|---|")
    specs = [(f, arm) for f in FAMILIES for arm in ARMS]
    specs.append(("all", "hard"))
    for fam, arm in specs:
        cols = {m: [] for m in METRICS}
        n_runs = 0
        for design in designs:
            base = pick(data[design], "baseline")
            seeds = FAMILIES if fam == "all" else (fam,)
            for seed in seeds:
                run = pick(data[design], "soft", seed, "full") if arm == "soft-full" else (
                    pick(data[design], "soft", seed, "inter") if arm == "soft-inter"
                    else pick(data[design], "hard", seed))
                if run is None:
                    continue
                n_runs += 1
                for m in METRICS:
                    r = ratio(run, base, m)
                    if r is not None:
                        cols[m].append(r)
        if n_runs == 0:
            continue
        rows.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            fam, arm,
            *(nl.fmt(geomean(cols[m])) for m in METRICS), n_runs))
    return rows


def crossover_table(data: dict[str, list[dict[str, object]]], designs: list[str]) -> list[str]:
    rows = ["| design | P* seed | crossover scale | cold WL | unseeded WL | cold start T (ns) "
            "| cold retention |", "|---|---|---|---|---|---|---|"]
    for design in designs:
        path = nl.runs_dir(design, "crossover", "crossover.json")
        if not path.is_file():
            rows.append(f"| {design} | (no sweep) | | | | | |")
            continue
        res = nl.read_json(path)
        scale = res.get("crossover_scale")
        cold = pick(data[design], "cold", scale=float(scale)) if scale is not None else None
        unseeded = pick(data[design], "unseeded", scale=float(scale)) if scale is not None else None
        rows.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            design, res.get("pstar"), scale if scale is not None else "> 16",
            cold.get("wirelength") if cold else "", unseeded.get("wirelength") if unseeded else "",
            nl.fmt(cold.get("init_t")) if cold else "",
            nl.fmt(cold.get("retention")) if cold else ""))
    return rows


def retention_table(data: dict[str, list[dict[str, object]]], designs: list[str]) -> list[str]:
    rows = ["| design | seed | retention@1 (full) | retention@1 (inter) | retention@hot | hot scale "
            "| hot WL | unseeded WL at hot |",
            "|---|---|---|---|---|---|---|---|"]
    for design in designs:
        path = nl.runs_dir(design, "crossover", "crossover.json")
        crossover = nl.read_json(path) if path.is_file() else {}
        hot_scale = (crossover.get("crossover_scale") or 0) * 2
        for seed in FAMILIES:
            full = pick(data[design], "soft", seed, "full")
            inter = pick(data[design], "soft", seed, "inter")
            hot = pick(data[design], "hot", seed)
            un = pick(data[design], "unseeded", scale=float(hot_scale)) if hot_scale else None
            rows.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                design, seed,
                nl.fmt(full.get("retention")) if full else "",
                nl.fmt(inter.get("retention")) if inter else "",
                nl.fmt(hot.get("retention")) if hot else "",
                f"{hot_scale:g}" if hot_scale else "",
                hot.get("wirelength") if hot else "",
                un.get("wirelength") if un else ""))
    return rows


def checkpoint_table(designs: list[str]) -> list[str]:
    rows = ["| design | P* | crossover scale (checkpointing on) | crossover scale (off) |",
            "|---|---|---|---|"]
    for design in designs:
        on = nl.runs_dir(design, "crossover", "crossover.json")
        off = nl.runs_dir(design, "crossover", "checkpoint.json")
        a = nl.read_json(on) if on.is_file() else {}
        b = nl.read_json(off) if off.is_file() else {}
        rows.append("| {} | {} | {} | {} |".format(
            design, a.get("pstar", ""),
            a.get("crossover_scale", "n/a"), b.get("crossover_scale_off", "n/a")))
    return rows


def per_design_table(data: dict[str, list[dict[str, object]]], designs: list[str]) -> list[str]:
    rows = ["| design | baseline WL | baseline delay | baseline chan | baseline place s "
            "| modules |", "|---|---|---|---|---|---|"]
    for design in designs:
        base = pick(data[design], "baseline")
        info = nl.runs_dir(design, "netlist", "info.json")
        modules = nl.read_json(info).get("modules") if info.is_file() else ""
        rows.append("| {} | {} | {} | {} | {} | {} |".format(
            design, nl.fmt(base.get("wirelength")) if base else "",
            nl.fmt(base.get("cpd_ns")) if base else "",
            nl.fmt(base.get("chan_width")) if base else "",
            nl.fmt(base.get("place_s")) if base else "", modules))
    return rows


def failures(data: dict[str, list[dict[str, object]]], designs: list[str]) -> list[str]:
    rows = []
    for design in designs:
        bad = [r for r in load_records(design) if r.get("rc") != 0]
        for r in bad:
            rows.append(f"| {design} | {r.get('tag')} | rc={r.get('rc')} |")
    return ["| design | tag | result |", "|---|---|---|"] + rows if rows else ["none."]


def write(designs: list[str]) -> None:
    data, order = load_all()
    designs = [d for d in order if d in designs or not designs]
    out = ["# The Norns III experiment: measured results", ""]
    out.append("Generated by `scripts/report.py` from `data/<design>/runs.jsonl`. Ratio "
               "convention: seeded / unseeded baseline, below 1.0 is better; geomeans use the "
               "designs where both runs succeeded.")
    out += ["", "## Baseline per design", ""] + per_design_table(data, designs)
    out += ["", "## QoR geomeans vs the unseeded baseline", ""] + qor_table(data, designs)
    out += ["", "## Crossover sweep (cold start from P*)", ""] + crossover_table(data, designs)
    out += ["", "## Retention and the hot step (2x crossover scale)", ""] + retention_table(
        data, designs)
    out += ["", "## Checkpointing arm (VPR --place_checkpointing, default on vs off)",
            ""] + checkpoint_table(designs)
    out += ["", "## Failed runs", ""] + failures(data, designs)
    out += ["", "## Method notes", "",
            "* Soft seeds are `--read_initial_place_file` with the cluster layout; `full` keeps "
            "the analytic order inside a cluster, `inter` shuffles it.",
            "* The hard arm is `--read_vpr_constraints` with one region per cluster; the "
            "intra-cluster arrangement is VPR's, so there is one hard variant.",
            "* VPR's placement macros (adder carry chains, mult_36) are respected: chains move "
            "as a vertical run, mult macros and pads stay anchored.",
            "* Crossover = the largest `--anneal_auto_init_t_scale` S at which the cold start "
            "still routes shorter than the unseeded run at the same S; the start temperature "
            "recorded by VPR is S x its automatic estimate.",
            "* Retention = fraction of a seed's cluster CLBs whose exit position is inside the "
            "cluster's seed bounding box; displacement = mean CLB distance from the seed slot.",
            "* Agent defaults: (1) the Loki L0 graph.json is built by Norns from the same Odin III "
            "BLIF because Loki's own key.json uses Odin API names that do not join to VPR atom "
            "names; the clusterings are Loki's `loki.analysis.cluster` code. (2) The hard arm "
            "constrains regions only, so it has no full/inter split. (3) Pad CLBs and mult_36 "
            "macros stay anchored; adder carry chains move as a vertical run. (4) One VPR run "
            "per configuration at `--seed 1` (deterministic). (5) Urd is degenerate (one "
            "cluster) on designs whose Odin hierarchy has a single module.",
            "* VPR checkpointing is a stock flag (`--place_checkpointing`, default on), not a "
            "patch; the on arm is the main matrix, the off arm repeats the cold-start scale "
            "sweep.",
            ""]
    path = nl.WS / "docs" / "plan" / "EXPERIMENT.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def main(argv: list[str]) -> int:
    write(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
