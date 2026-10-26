"""Round-6 statistics (decision rules of docs/plan/round6.md). Needs scipy (the Loki venv python, $NR_PY).

  python scripts/r6stats.py        reads data/r6/runs.jsonl and keep.json, writes data/analysis/r6-results.json
Reuses the round-5 helpers (Wilcoxon, Holm, bootstrap, slope, H24 and H19 rules).
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys

import nornlib as nl
import r5stats as s5
import r6gen

BOOT_SEED = s5.BOOT_SEED
PERM_REPS = 10000
MIN_N = s5.MIN_N
MIN_CELLS6 = 8
METRICS = {"CLB": "logic_clbs", "WL": "wirelength", "CPD": "cpd_ns", "W": "chan_width", "CUT": "cut"}
PRIMARY = ("CLB", "WL", "CPD")
BENEFIT_LEVELS = (0, 25, 50, 75)
ALL_LEVELS = (0, 25, 50, 75, 100)
HEADROOM = ("mesh", "tree")


def ci_inside(ci: tuple[float, float], lo: float = 0.98, hi: float = 1.02) -> bool:
    return ci[0] >= math.log(lo) and ci[1] <= math.log(hi)


def ratio_summary(v: list[float]) -> dict:
    ci = s5.boot_ci(v) if v else (float("nan"), float("nan"))
    return {"n": len(v), "gmean": s5.gmean_ratio(v), "ci90": [math.exp(ci[0]), math.exp(ci[1])]}


# ---------------------------------------------------------------------------------------
# decision rules (one function per hypothesis)

def decide_keep6(kept_flags: dict[str, bool], group_of: dict[str, str]) -> dict:
    """H29: >= 90% kept and every group has >= 5 kept; not supported iff < 70% kept."""
    n = len(kept_flags)
    share = sum(kept_flags.values()) / n if n else float("nan")
    groups: dict[str, int] = {}
    for d, k in kept_flags.items():
        groups[group_of[d]] = groups.get(group_of[d], 0) + bool(k)
    if share >= 0.90 and groups and min(groups.values()) >= 5:
        status = "supported"
    elif share < 0.70:
        status = "not supported"
    else:
        status = "inconclusive"
    return {"n": n, "kept": sum(kept_flags.values()), "share": share, "kept_per_group": groups, "status": status}


def decide_align(levels: list[int], a_m: list[float]) -> dict:
    """H30: Spearman rho(level, measured purity), medians at level 0 and 100."""
    from scipy.stats import spearmanr
    n = len(levels)
    m0 = [a for lv, a in zip(levels, a_m) if lv == 0]
    m100 = [a for lv, a in zip(levels, a_m) if lv == 100]
    med0 = statistics.median(m0) if m0 else float("nan")
    med100 = statistics.median(m100) if m100 else float("nan")
    rho = float(spearmanr(levels, a_m).statistic) if n >= 3 and len(set(a_m)) > 1 else float("nan")
    if rho >= 0.9 and med100 >= 0.95 and med0 <= 0.35:
        status = "supported"
    elif rho < 0.7 or med0 > 0.60 or med100 < 0.80:
        status = "not supported"
    else:
        status = "inconclusive"
    if math.isnan(rho):
        status = "inconclusive"
    return {"n": n, "rho": rho, "median_level0": med0, "median_level100": med100, "status": status}


def decide_leak(logs_by_metric: dict[str, list[float]]) -> dict:
    """H33: norns / stock at level 100. Supported iff gm <= 0.95 and Holm p (ratio < 1, over the metrics) < 0.05; not supported
    iff gm >= 0.99 or the 90% interval lies inside [0.98, 1.02]."""
    ms = sorted(logs_by_metric)
    ps = [s5.wilcoxon_p(logs_by_metric[m], "less") for m in ms]
    adj = s5.holm(ps)
    out = {}
    for m, p, pa in zip(ms, ps, adj):
        v = logs_by_metric[m]
        r = ratio_summary(v)
        ci = (math.log(r["ci90"][0]), math.log(r["ci90"][1])) if v else (float("nan"), float("nan"))
        gm = r["gmean"]
        if len(v) < MIN_N:
            status = "inconclusive (n too small)"
        elif gm <= 0.95 and pa < 0.05:
            status = "supported"
        elif gm >= 0.99 or ci_inside(ci):
            status = "not supported"
        else:
            status = "inconclusive"
        out[m] = {**r, "p": p, "p_holm": pa, "status": status}
    return out


def decide_benefit(logs_by_level: dict[int, list[float]]) -> dict:
    """H34: norns / stock per level, one metric, Holm over the levels (one-sided ratio < 1). Supported iff gm <= 0.99 and Holm
    p < 0.05; not supported iff gm >= 1.00 or the 90% interval lies inside [0.98, 1.02]."""
    ls = sorted(logs_by_level)
    ps = [s5.wilcoxon_p(logs_by_level[x], "less") for x in ls]
    adj = s5.holm(ps)
    out = {}
    for x, p, pa in zip(ls, ps, adj):
        v = logs_by_level[x]
        r = ratio_summary(v)
        ci = (math.log(r["ci90"][0]), math.log(r["ci90"][1])) if v else (float("nan"), float("nan"))
        gm = r["gmean"]
        if len(v) < MIN_N:
            status = "inconclusive (n too small)"
        elif gm <= 0.99 and pa < 0.05:
            status = "supported"
        elif gm >= 1.00 or ci_inside(ci):
            status = "not supported"
        else:
            status = "inconclusive"
        out[str(x)] = {**r, "p": p, "p_holm": pa, "status": status}
    return out


def decide_hurt(logs_by_level: dict[int, list[float]]) -> dict:
    """H35: norns / stock per level, Holm over the levels (one-sided ratio > 1). Supported (it hurts) iff gm >= 1.02 and Holm
    p < 0.05; not supported iff gm <= 1.01 or the 90% interval lies inside [0.98, 1.02]."""
    ls = sorted(logs_by_level)
    ps = [s5.wilcoxon_p(logs_by_level[x], "greater") for x in ls]
    adj = s5.holm(ps)
    out = {}
    for x, p, pa in zip(ls, ps, adj):
        v = logs_by_level[x]
        r = ratio_summary(v)
        ci = (math.log(r["ci90"][0]), math.log(r["ci90"][1])) if v else (float("nan"), float("nan"))
        gm = r["gmean"]
        if len(v) < MIN_N:
            status = "inconclusive (n too small)"
        elif gm >= 1.02 and pa < 0.05:
            status = "supported"
        elif gm <= 1.01 or ci_inside(ci):
            status = "not supported"
        else:
            status = "inconclusive"
        out[str(x)] = {**r, "p": p, "p_holm": pa, "status": status}
    return out


def cell_slopes(cells: dict[str, list[tuple[float, float]]]) -> dict[str, float]:
    """cell -> slope of y on x; a cell needs >= 4 points and a spread of x >= 0.4, else dropped."""
    out = {}
    for c, pts in sorted(cells.items()):
        if len(pts) >= 4 and max(x for x, _ in pts) - min(x for x, _ in pts) >= 0.4:
            out[c] = s5.slope([x for x, _ in pts], [y for _, y in pts])
    return out


def decide_dose(cells_by_metric: dict[str, dict[str, list[tuple[float, float]]]]) -> dict:
    """H36: per metric, median over cells of the slope of ln ratio on measured alignment. Supported iff median <= -0.10, slope < 0
    in >= 70% of the cells and Holm p (slope < 0, over the metrics) < 0.05; not supported iff median >= -0.03; < 8 cells ->
    inconclusive (n too small). Permutation null: ln ratios permuted over the levels of each cell."""
    ms = sorted(cells_by_metric)
    slopes = {m: cell_slopes(cells_by_metric[m]) for m in ms}
    ps = [s5.wilcoxon_p(list(slopes[m].values()), "less") if len(slopes[m]) >= MIN_CELLS6 else 1.0 for m in ms]
    adj = s5.holm(ps)
    out = {}
    rnd = random.Random(BOOT_SEED)
    for m, p, pa in zip(ms, ps, adj):
        s = list(slopes[m].values())
        med = statistics.median(s) if s else float("nan")
        neg = sum(1 for x in s if x < 0)
        if len(s) < MIN_CELLS6:
            status = "inconclusive (n too small)"
        elif med <= -0.10 and neg >= 0.70 * len(s) and pa < 0.05:
            status = "supported"
        elif med >= -0.03:
            status = "not supported"
        else:
            status = "inconclusive"
        ge = 0
        used = {c: pts for c, pts in cells_by_metric[m].items() if c in slopes[m]}
        for _ in range(PERM_REPS if s else 0):
            sl = []
            for c, pts in sorted(used.items()):
                ys = [y for _, y in pts]
                rnd.shuffle(ys)
                sl.append(s5.slope([x for x, _ in pts], ys))
            ge += statistics.median(sl) <= med
        ci = s5.boot_ci(s) if len(s) >= 2 else (float("nan"), float("nan"))
        out[m] = {"cells": len(s), "median_slope": med, "negative_cells": neg, "p": p, "p_holm": pa,
                  "perm_p": ge / PERM_REPS if s else float("nan"), "ci90_mean_slope": list(ci), "slopes": s, "status": status}
    return out


def decide_control(logs: list[float]) -> dict:
    """H37: chain, norns / stock WL. Supported (no effect) iff the 90% interval lies inside [0.98, 1.02]; not supported iff
    gm <= 0.97 or >= 1.03."""
    r = ratio_summary(logs)
    ci = (math.log(r["ci90"][0]), math.log(r["ci90"][1])) if logs else (float("nan"), float("nan"))
    gm = r["gmean"]
    if len(logs) < MIN_N:
        status = "inconclusive (n too small)"
    elif ci_inside(ci):
        status = "supported"
    elif gm <= 0.97 or gm >= 1.03:
        status = "not supported"
    else:
        status = "inconclusive"
    return {**r, "status": status}


# ---------------------------------------------------------------------------------------
# data

def load() -> tuple[dict, dict]:
    keep = nl.read_json(nl.DATA / "r6" / "keep.json")
    runs: dict = {}
    for line in (nl.DATA / "r6" / "runs.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["rc"] == 0:
                runs[(r["design"], r["arm"], r["vseed"])] = r
    return keep, runs


def meta(design: str) -> tuple[str, int, int]:
    return r6gen.parse_name(design)


def per_design(keep: dict, runs: dict, arm: str, ref: str, metric: str, ref_design=None) -> dict[str, float]:
    """design -> ln of the geometric mean over matched seeds (>= 2) of arm / ref, KEPT designs. ref_design(d) names the design
    the reference runs belong to (default: the same design)."""
    out = {}
    key = METRICS[metric]
    for d, k in keep.items():
        if not k["kept"]:
            continue
        rd = ref_design(d) if ref_design else d
        ls = []
        for s in (1, 2, 3):
            a, r = runs.get((d, arm, s)), runs.get((rd, ref, s))
            if a and r and a.get(key) and r.get(key):
                ls.append(math.log(a[key] / r[key]))
        if len(ls) >= 2:
            out[d] = sum(ls) / len(ls)
    return out


def pick(vals: dict[str, float], topos=None, level=None) -> list[float]:
    return [v for d, v in sorted(vals.items())
            if (topos is None or meta(d)[0] in topos) and (level is None or meta(d)[1] == level)]


def analyse() -> dict:
    keep, runs = load()
    res: dict = {"n_designs": len(keep)}
    group = {d: f"{meta(d)[0]}_a{meta(d)[1]}" for d in keep}
    res["keep"] = decide_keep6({d: keep[d]["kept"] for d in keep}, group)
    res["keep_k1_k4"] = decide_keep6({d: keep[d]["kept_k1_k4"] for d in keep}, group)
    kd = [d for d in keep if keep[d]["kept"]]
    res["align"] = decide_align([meta(d)[1] for d in kd], [keep[d]["word_purity"] for d in kd])
    res["align_by_level"] = {str(lv): ratio_summary_plain([keep[d]["word_purity"] for d in kd if meta(d)[1] == lv])
                             for lv in ALL_LEVELS}
    reps = [r["reproduction"] for (d, arm, s), r in runs.items() if arm == "known" and keep.get(d, {}).get("kept")]
    res["repro"] = s5.decide_repro(reps)
    drop = {d for (d, arm, s), r in runs.items() if arm == "known" and keep.get(d, {}).get("kept") and r["reproduction"] < 0.9}
    res["excluded_low_reproduction"] = sorted(drop)
    keep_eff = {d: ({**k, "kept": k["kept"] and d not in drop}) for d, k in keep.items()}

    pd = {(a, r, m): per_design(keep_eff, runs, a, r, m) for a, r in (("stock", "known"), ("norns", "known"), ("norns", "stock"))
          for m in PRIMARY}
    # H32: room, unit = cell (topology, B), mean over the cell's levels
    cells = {}
    for m in PRIMARY:
        by: dict[str, list[float]] = {}
        for d, v in pd[("stock", "known", m)].items():
            if meta(d)[0] in HEADROOM:
                by.setdefault(f"{meta(d)[0]}_{meta(d)[2]}", []).append(v)
        cells[m] = [sum(v) / len(v) for _, v in sorted(by.items())]
    res["room"] = s5.decide_room(cells)
    # H33 leak
    res["leak_a1"] = decide_leak({m: pick(pd[("norns", "stock", m)], HEADROOM, 100) for m in PRIMARY})
    # H34 / H35, WL primary; CLB and CPD secondary
    res["benefit"] = {m: decide_benefit({lv: pick(pd[("norns", "stock", m)], HEADROOM, lv) for lv in BENEFIT_LEVELS})
                      for m in PRIMARY}
    res["hurt"] = {m: decide_hurt({lv: pick(pd[("norns", "stock", m)], HEADROOM, lv) for lv in ALL_LEVELS}) for m in PRIMARY}
    sup = [lv for lv in BENEFIT_LEVELS if res["benefit"]["WL"][str(lv)]["status"] == "supported"]
    res["break_even"] = {"level": min(sup) if sup else None, "supported_levels": sup,
                         "lowest_measured_alignment": min((median_am(keep_eff, lv) for lv in sup), default=None)}
    # H36 dose-response
    dose = {}
    for m in PRIMARY:
        cl: dict[str, list[tuple[float, float]]] = {}
        for d, v in pd[("norns", "stock", m)].items():
            if meta(d)[0] in HEADROOM:
                cl.setdefault(f"{meta(d)[0]}_{meta(d)[2]}", []).append((keep[d]["word_purity"], v))
        dose[m] = cl
    res["dose"] = decide_dose(dose)
    leakfree = {m: {c: [p for p in pts if p[0] <= 0.80] for c, pts in cl.items()} for m, cl in dose.items()}
    res["dose_leakfree_variant"] = decide_dose(leakfree)
    # H37 chain control
    res["control_chain"] = decide_control(pick(pd[("norns", "stock", "WL")], ("chain",)))
    res["placebo"] = placebo(keep_eff, runs)
    res["tables"] = tables(pd)
    res["gap_closed"] = gap_closed(pd)
    res["leak"] = leak(keep_eff, runs)
    res["purity"] = purity_table(keep_eff, runs)
    res["failed_runs"] = sorted(f"{r['design']}/{r['arm']}.s{r['vseed']}" for r in all_failed())
    return res


def all_failed() -> list[dict]:
    out = []
    for line in (nl.DATA / "r6" / "runs.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["rc"] != 0:
                out.append(r)
    return out


def ratio_summary_plain(v: list[float]) -> dict:
    return {"n": len(v), "median": statistics.median(v) if v else float("nan"), "min": min(v) if v else float("nan"),
            "max": max(v) if v else float("nan")}


def median_am(keep: dict, level: int) -> float:
    v = [k["word_purity"] for d, k in keep.items() if k["kept"] and meta(d)[1] == level]
    return statistics.median(v) if v else float("nan")


def placebo(keep: dict, runs: dict) -> dict:
    """stock at level L / stock at level 100 of the same cell: the same logic, only register names differ in the HDL."""
    out = {}
    for m in PRIMARY:
        v = per_design(keep, runs, "stock", "stock", m, ref_design=lambda d: f"r6_{meta(d)[0]}_a100_{meta(d)[2]}")
        out[m] = {str(lv): ratio_summary(pick(v, HEADROOM, lv)) for lv in (0, 25, 50, 75)}
    return out


def tables(pd: dict) -> dict:
    out: dict = {}
    for (a, r, m), v in pd.items():
        for lv in ALL_LEVELS:
            for name, topos in (("mesh_tree", HEADROOM), ("mesh", ("mesh",)), ("tree", ("tree",)), ("chain", ("chain",))):
                out[f"{a}/{r}_{m}_{name}_a{lv}"] = ratio_summary(pick(v, topos, lv))
    return out


def gap_closed(pd: dict) -> dict:
    """(r_stock - r_norns)/(r_stock - 1) per design with r_stock (vs known) >= 1.03, per level, mesh and tree."""
    out: dict = {}
    for m in PRIMARY:
        for lv in ALL_LEVELS:
            vals = []
            for d, ls in pd[("stock", "known", m)].items():
                rs = math.exp(ls)
                if meta(d)[0] in HEADROOM and meta(d)[1] == lv and rs >= 1.03 and d in pd[("norns", "known", m)]:
                    vals.append((rs - math.exp(pd[("norns", "known", m)][d])) / (rs - 1))
            out[f"{m}_a{lv}"] = {"n": len(vals), "mean": sum(vals) / len(vals) if vals else float("nan"),
                                 "median": statistics.median(vals) if vals else float("nan")}
    return out


def leak(keep: dict, runs: dict) -> dict:
    """Per level: designs whose norns .net equals the stock .net on all three seeds, mean measured word-file purity."""
    out: dict = {}
    for lv in ALL_LEVELS:
        ds = [d for d, k in keep.items() if k["kept"] and meta(d)[1] == lv]
        same = n = 0
        for d in ds:
            a = [runs.get((d, "norns", s)) for s in (1, 2, 3)]
            b = [runs.get((d, "stock", s)) for s in (1, 2, 3)]
            if all(a) and all(b):
                n += 1
                same += all(x["net_sha256"] == y["net_sha256"] for x, y in zip(a, b))
        out[str(lv)] = {"designs": n, "net_equal_stock": same,
                        "mean_word_purity": sum(keep[d]["word_purity"] for d in ds) / len(ds) if ds else float("nan")}
    return out


def purity_table(keep: dict, runs: dict) -> dict:
    out: dict = {}
    for arm in ("stock", "norns", "known"):
        for lv in ALL_LEVELS:
            vals = [r["purity"] for (d, a, s), r in runs.items() if a == arm and keep.get(d, {}).get("kept") and meta(d)[1] == lv]
            nulls = [r["null_purity"] for (d, a, s), r in runs.items() if a == arm and keep.get(d, {}).get("kept") and meta(d)[1] == lv]
            out[f"{arm}_a{lv}"] = {"n": len(vals), "purity": sum(vals) / len(vals) if vals else float("nan"),
                                   "null": sum(nulls) / len(nulls) if nulls else float("nan")}
    return out


def main() -> int:
    res = analyse()
    nl.write_json(nl.DATA / "analysis" / "r6-results.json", res)
    for k, v in sorted(res.items()):
        if isinstance(v, dict) and "status" in v:
            print(k, v["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
