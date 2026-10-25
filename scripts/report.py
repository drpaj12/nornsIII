"""Reports: EXPERIMENT.md, the QoR/crossover tables and the paper's numbers.

Reads data/<design>/runs.jsonl (written by matrix.py) and writes docs/plan/EXPERIMENT.md,
docs/plan/tab-qor.md and docs/plan/tab-crossover.md. Ratio convention: seeded / baseline, so
below 1.0 is better; geomeans use the designs where both runs succeeded.

Usage: python scripts/report.py
"""

from __future__ import annotations

import json
import sys

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
        if arm == "hot" and a == "hot" and str(r.get("tag", "")).startswith(f"hot-{seed}-"):
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
    rows = ["| design | P* seed | crossover scale | cold WL | unseeded WL | cold start T "
            "(VPR cost units) | cold retention |", "|---|---|---|---|---|---|---|"]
    for design in designs:
        path = nl.data_crossover(design, "crossover.json")
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
            ("%.4g" % cold["init_t"]) if cold and cold.get("init_t") is not None else "",
            nl.fmt(cold.get("retention")) if cold else ""))
    return rows


def retention_table(data: dict[str, list[dict[str, object]]], designs: list[str]) -> list[str]:
    rows = ["| design | seed | retention@1 (full) | retention@1 (inter) | retention@hot | hot scale "
            "| hot WL | unseeded WL at hot |",
            "|---|---|---|---|---|---|---|---|"]
    for design in designs:
        path = nl.data_crossover(design, "crossover.json")
        crossover = nl.read_json(path) if path.is_file() else {}
        hot_scale = (crossover.get("crossover_scale") or 0) * 2
        for seed in FAMILIES:
            full = pick(data[design], "soft", seed, "full")
            inter = pick(data[design], "soft", seed, "inter")
            hot = pick(data[design], "hot", seed)
            if hot is not None and hot.get("scale") is not None:
                hot_scale = float(hot["scale"])
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
        on = nl.data_crossover(design, "crossover.json")
        off = nl.data_crossover(design, "checkpoint.json")
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
        info = nl.DATA / design / "netlist.json"
        if not info.is_file():
            info = nl.runs_dir(design, "netlist", "info.json")
        modules = nl.read_json(info).get("modules") if info.is_file() else ""
        rows.append("| {} | {} | {} | {} | {} | {} |".format(
            design, nl.fmt(base.get("wirelength")) if base else "",
            nl.fmt(base.get("cpd_ns")) if base else "",
            nl.fmt(base.get("chan_width")) if base else "",
            nl.fmt(base.get("place_s")) if base else "", modules))
    return rows


def failures(data: dict[str, list[dict[str, object]]], designs: list[str]) -> list[str]:
    """Unresolved failures: the latest record per tag is still rc != 0."""
    rows = []
    for design in designs:
        latest: dict[str, dict[str, object]] = {}
        for r in load_records(design):
            latest[str(r.get("tag"))] = r
        for tag in sorted(latest):
            r = latest[tag]
            if r.get("rc") != 0:
                rows.append(f"| {design} | {tag} | rc={r.get('rc')} | "
                            f"{r.get('error') or ''} |")
    return ["| design | tag | result | cause |", "|---|---|---|---|"] + rows if rows else ["none."]


def round2_section() -> list[str]:
    """Round-two tables (bitwise seeds, random and permuted arms, N1, N2) from r2lib."""
    import r2lib
    R = r2lib.compute()
    out = ["Round-two arms at scale 1, geomean ratios vs the unseeded baseline (below 1.0 is "
           "better); `better` = designs with routed wirelength below the baseline.", "",
           "| arm | wirelength | delay | chan width | place runtime | start T | better |",
           "|---|---|---|---|---|---|---|"]
    for key, v in R["vs_base"].items():
        if key in ("urd", "words", "words_inter", "slices", "hier", "words_partial", "random",
                   "urd_shuf") or key.endswith("_shuf"):
            if v["n"]:
                out.append("| {} | {} | {} | {} | {} | {} | {}/{} |".format(
                    key, r2lib.f3(v["wirelength"]), r2lib.f3(v["cpd_ns"]),
                    r2lib.f3(v["chan_width"]), r2lib.f3(v["place_s"]), r2lib.f2(v["init_t"]),
                    v["wins"], v["n"]))
    out += ["", f"Best new family: {R['best']}.", "", "| hypothesis | status | deciding number |",
            "|---|---|---|"]
    h = R["hyp"]
    for key in ("H7a", "H7b", "H7c", "H7d", "H4", "H1", "H2"):
        if key not in h:
            continue
        v = h[key]
        if key in ("H7a", "H7b", "H7d"):
            num = f"geomean {r2lib.f3(v['gm'])}, better on {v['wins']}/{v['n']}, p={r2lib.pfmt(v['p'])}"
        elif key == "H7c":
            num = f"hier rank {v['rank']}/{v['of']} ({r2lib.f3(v['hier_gm'])}); best {v['best_name']}"
        elif key == "H4":
            num = "; ".join(f"{k}: random {r2lib.f3(c['random'])} > permuted "
                            f"{r2lib.f3(c['shuffled'])} > quotient {r2lib.f3(c['quotient'])}"
                            for k, c in v.items() if isinstance(c, dict))
        elif key == "H1":
            num = "; ".join(f"{lab}: {a['above_null']}/{a['n_z']} NMI, {a['dens_above_null']}/"
                            f"{a['dens_n_z']} compactness above null+2sd"
                            for lab, a in R["n1"].items())
        else:
            num = (f"{v['n_pos']} positive and {v['n_neg']} negative of {v['n_pairs']} correlations "
                   f"at p<0.05 (n=15)")
        out.append(f"| {key} | {v['status']} | {num} |")
    c = R["coverage_all"]
    out += ["", "Word membership (Odin III bus names and spans joined by net id): "
            f"{c['in_word']}/{c['blocks']} blocks in a word; flip-flops {c['ff_word']}/{c['ff_total']}, "
            f"LUTs {c['lut_word']}/{c['lut_total']}, hard cells {c['hard_word']}/{c['hard_total']}; "
            f"{c['unjoined']} of {c['odin_cells']} Odin cells found no BLIF block; the rerun BLIF equals the kept one "
            f"on all designs: {c['identical']}.", "",
            "| design | blocks | in a word | words | words >= 2 | largest (module,file:line) group |",
            "|---|---|---|---|---|---|"]
    for w in R["coverage"]:
        out.append(f"| {w['design']} | {w['blocks']} | {w['blocks_in_word']} | {w['words']} | "
                   f"{w['words_ge2']} | {w['line_groups_largest'][0]} |")
    if "n1" in R:
        out += ["", "N1 medians over designs (NMI / compactness): analytic start, VPR final, "
                "random null.", "", "| labels | n | NMI start | NMI final | NMI null | comp start "
                "| comp final | comp null |", "|---|---|---|---|---|---|---|---|"]
        for lab, a in R["n1"].items():
            out.append(f"| {lab} | {a['n']} | {r2lib.f3(a['nmi_initial'])} | "
                       f"{r2lib.f3(a['nmi_final'])} | {r2lib.f3(a['nmi_null'])} | "
                       f"{r2lib.f3(a['dens_initial'])} | {r2lib.f3(a['dens_final'])} | "
                       f"{r2lib.f3(a['dens_null'])} |")
    if "n2" in R:
        out += ["", "N2 Spearman rho (p, n) between structure and gain (1 - wirelength ratio).",
                "", "| pair | rho | p | n |", "|---|---|---|---|"]
        for k, v in R["n2"]["spearman"].items():
            out.append(f"| {k} | {v['rho']:.3f} | {r2lib.pfmt(v['p'])} | {v['n']} |")
    if R.get("xover") and R["xover"]["n"]:
        x = R["xover"]
        out += ["", f"Crossover of the best new family: median scale {x['median']:g} vs round one "
                f"{x['r1_median']:g} (n={x['n']}); retention at 2S median "
                f"{r2lib.f2(x['hot_ret_median'])}; wins vs unseeded at 2S {x['hot_wins'][0]}/"
                f"{x['hot_wins'][1]}."]
    return out


def round3_section() -> list[str]:
    """Round 3 (the Norns packer): hypothesis table from data/analysis/r3-results.json."""
    import r3stats
    import write_round3 as w3
    if not r3stats.RESULT.is_file():
        return ["Not run yet."]
    R = nl.read_json(r3stats.RESULT)
    out = ["Protocol: `docs/plan/round3.md` (committed before any round-3 run; the entry d805789 is an amendment "
           "to H11 and the entry of 2026-10-25 records the fix round). Statuses follow its rules (H11: the text of "
           "4fb8b60, variants labelled in the paper); numbers from `scripts/r3stats.py`.", ""]
    if "gate" in R:
        g = R["gate"]
        out += [f"Control gate (stock vs Norns packer `.net`, option absent and beta 0, `--pack` and the analytical flow): "
                f"{g['n_checks']} comparisons over {g['designs']} designs, "
                f"{'all byte-identical' if g['all_identical'] else 'NOT all identical'}.", ""]
    fx = R.get("fix", {})
    if fx.get("gate2"):
        out += [f"Beta-0 gate extension (module and word+io affinity files, `--pack`, seed 1): "
                f"{fx['gate2']['identical']} of {fx['gate2']['n_checks']} byte-identical.", ""]
    if fx.get("ident"):
        i = fx["ident"]
        out += [f"Log-counter packer vs the previous binary (headline configs, seed 1): {i['net_identical']} of {i['n']} "
                f"`.net` byte-identical, {i['flat_identical']} of {i['n']} flat placements identical to Stage 4.", ""]
    out += ["| RQ | hypothesis | status | deciding number |", "|---|---|---|---|"]
    for rq, hyp, status, num in w3.h_rows(R):
        out.append(f"| {rq} | {hyp.replace(chr(92), '')} | {status} | {num.replace(chr(92), '').replace('$', '')} |")
    return out


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
    out += ["", "## Round 2 (bitwise seeds, random and permuted starts, N1, N2)", ""] \
        + round2_section()
    out += ["", "## Round 3 (the Norns packer, I/O words, packing experiments, proximity)", ""] \
        + round3_section()
    out += ["", "## Failed runs", ""] + failures(data, designs)
    out += ["", "## Method notes", "",
            "* Soft seeds are `--read_initial_place_file` with the cluster layout; `full` keeps "
            "the analytic order inside a cluster, `inter` shuffles it.",
            "* The hard arm is `--read_vpr_constraints` with one region per cluster; the "
            "intra-cluster arrangement is VPR's, so there is one hard variant.",
            "* VPR's placement macros (adder carry chains, mult_36) are respected: chains move "
            "as a vertical run, mult macros and pads stay anchored.",
            "* Crossover = the largest `--anneal_auto_init_t_scale` S at which the cold start "
            "from P* still routes shorter than the unseeded run at the same S; the start "
            "temperature recorded by VPR is S x its automatic estimate. The sweep is run once "
            "per design: P* is that design's best scale-1 soft or hard placement over its seven "
            "seeds, so S is design-level, and the hot step then cold-starts every seed at 2S. "
            "When the sweep "
            "stopped at its cap (16, or 256 for or1200 and stereovision3), S is a lower bound on "
            "the fall point.",
            "* Retention = fraction of a seed's cluster CLBs whose exit position is inside the "
            "cluster's seed bounding box; displacement = mean CLB distance from the seed slot. "
            "For the hard arm retention is 1 by construction (the constraints cannot be "
            "violated), so the hard rows only confirm the regions were respected.",
            "* The unresolved blob_merge hard-kmeans_2k run is an initial-placement failure, not "
            "packing infeasibility: VPR cannot place 9 CLBs inside the k-means_2k regions and "
            "exits with 'the constraints may be too tight' (initial_placement.cpp:309). The hard "
            "arm therefore has 104 runs, and every hard geomean excludes it.",
            "* The crossover and checkpointing sweep results are kept in "
            "`data/<design>/crossover/`; the generators read only these committed copies (the "
            "run logs and placements under `runs/` are local).",
            "* Agent defaults: (1) the Loki L0 graph.json is built by Norns from the same Odin III "
            "BLIF because Loki's own key.json uses Odin API names that do not join to VPR atom "
            "names; the clusterings are Loki's `loki.analysis.cluster` code. (2) The hard arm "
            "constrains regions only, so it has no full/inter split. (3) Pad CLBs and mult_36 "
            "macros stay anchored; adder carry chains move as a vertical run. (4) One VPR run "
            "per configuration at `--seed 1` (deterministic). (5) Urd has one cluster only on sha "
            "and stereovision3; diffeq1 and diffeq2 (one module each) get two Urd clusters (the "
            "module and a flat group), and the other designs get one cluster per populated "
            "module (3 to 23).",
            "* Round 2 agent defaults: (6) word membership comes from Odin III bus names and "
            "spans joined to the BLIF by net id (the BLIF line is a statement, too coarse); "
            "(7) a CLB joins a word cluster when >= 1/3 of its atoms are word atoms, else it "
            "keeps its Urd module cluster; (8) the Rent exponent is fitted on BFS balls, the "
            "inverse Rent exponent is -p; (9) the random null of N1 permutes logic-CLB "
            "coordinates (20 samples); (10) hypothesis statuses follow the decision rules in "
            "the paper's methodology section.",
            "* Regenerating round two: `scripts/build_words.py`, `scripts/build_word_seeds.py`, "
            "`scripts/round2.py` (VPR; `soft`, then `freeze`, then `chunk stage2`) and "
            "`scripts/structure.py all|graph|partial` need the local `runs/` tree; then "
            "`scripts/report.py` (this file), `scripts/fill_paper.py`, "
            "`scripts/write_paper_prose.py` and `scripts/write_round2.py` regenerate every "
            "document from the committed `data/` alone.",
            "* Regenerating round three: `scripts/n8.py`, `scripts/io_words.py`, `sh packer/build.sh` "
            "(the Norns packer), `scripts/round3.py gate|pilot|grid|chunk arms` (VPR, heavy lock) and "
            "`scripts/n11.py`, `scripts/r3fix.py ident|stockn|gate2|match` (fix round) need the local `runs/` tree; then `scripts/r3stats.py`, "
            "`scripts/write_round3.py` and `scripts/report.py` regenerate the documents from the "
            "committed `data/` alone. The protocol is `docs/plan/round3.md`.",
            "* VPR checkpointing is a stock flag (`--place_checkpointing`, default on), not a "
            "patch; the on arm is the main matrix, the off arm repeats the cold-start scale "
            "sweep (extended by doubling while the control still wins, to the same 256 cap).", ""]
    remaining = [d for d in nl.DESIGN_ORDER if d not in designs]
    if remaining:
        out += ["", "## Remaining matrix (continuation lane)", "",
                "Designs not started in this lane, smallest first: " + ", ".join(remaining) + ".",
                "Per design, run exactly:", "",
                "    scripts/run_design.sh <design>", "",
                "then extend the crossover and the checkpointing control if the lane has time:", "",
                "    . scripts/env.sh && $NR_PY scripts/matrix.py crossover <design>",
                "    . scripts/env.sh && $NR_PY scripts/matrix.py checkpoint <design>",
                "",
                "Also pending for a continuation lane: extend the checkpointing-off control "
                "sweep of or1200 past its current 16 cap (`matrix.py checkpoint or1200`).",
                "    . scripts/env.sh && $NR_PY scripts/backfill.py && $NR_PY scripts/report.py", ""]
    path = nl.WS / "docs" / "plan" / "EXPERIMENT.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def main(argv: list[str]) -> int:
    write(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
