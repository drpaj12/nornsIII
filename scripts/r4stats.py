"""Round-4 numbers and hypothesis statuses (rules: docs/plan/round4.md; no number is typed by hand).

Reads data/<d>/{r4census,r4near,r4hier,r4depth,r4runs.jsonl,n8,n11,r3runs.jsonl} and writes
data/analysis/r4-results.json (everything the round-4 text and tables print). Usage:
    python scripts/r4stats.py
"""

from __future__ import annotations

import gzip
import json
import math
import re
import statistics
import sys

import numpy as np
from scipy import stats

import nornlib as nl

PILOT = ("ch_intrinsics", "stereovision3", "diffeq2", "diffeq1")  # the 4 smallest: the n=11 variant drops them
SEEDS = (1, 2, 3)
BOOT = 10000
BOOT_SEED = 20261025
RESULT = nl.DATA / "analysis" / "r4-results.json"
DESIGNS = list(nl.DESIGN_ORDER)
CLASSES = ("SC", "SN", "SI", "OR", "FL")


# ---------------------------------------------------------------------------------------
# helpers

def nan(x: float | None) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def wilcoxon(x: list[float], alternative: str) -> float:
    x = [v for v in x if v != 0.0]
    if len(x) < 6:
        return float("nan")
    return float(stats.wilcoxon(x, alternative=alternative).pvalue)


def holm(ps: dict[str, float]) -> dict[str, float]:
    """Holm adjustment with m = len(ps); a NaN p counts as 1.0."""
    items = sorted(((1.0 if nan(p) else p), k) for k, p in ps.items())
    out: dict[str, float] = {}
    running = 0.0
    m = len(items)
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def boot_ci(values: list[float], level: float = 0.90) -> tuple[float, float]:
    rng = np.random.default_rng(BOOT_SEED)
    arr = np.array(values)
    idx = rng.integers(0, len(arr), (BOOT, len(arr)))
    means = arr[idx].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def med(x: list[float]) -> float | None:
    return statistics.median(x) if x else None


def need(n: int, k: int = 12) -> int:
    """The literal count rule 'k of 15' for n designs with data: k when n == 15, else ceil(0.8 n) (labelled)."""
    return k if n == 15 else math.ceil(0.8 * n)


def recs(design: str, name: str) -> list[dict]:
    path = nl.DATA / design / name
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def r4runs(design: str) -> dict[tuple[str, str, int], dict]:
    out: dict[tuple[str, str, int], dict] = {}
    for r in recs(design, "r4runs.jsonl"):
        if r.get("rc") == 0:
            out[(r["pack"], r["start"], r["vseed"])] = r
    return out


def jload(design: str, name: str) -> dict | None:
    p = nl.DATA / design / name
    return nl.read_json(p) if p.is_file() else None


def share_sum(sh: dict, names: tuple[str, ...]) -> float:
    return sum(sh[c] for c in names)


# ---------------------------------------------------------------------------------------
# RQ-N17

def n17() -> dict:
    cen = {d: jload(d, "r4census.json") for d in DESIGNS}
    near = {d: jload(d, "r4near.json") for d in DESIGNS}
    have = [d for d in DESIGNS if cen[d] and "stock" in cen[d]["arms"]]
    out: dict = {"n": len(have), "designs": have, "arms": {}}
    for arm in ("stock", "r3", "r4"):
        out["arms"][arm] = {d: {"share": cen[d]["arms"][arm]["pairs"]["share"], "share_w1": cen[d]["arms"][arm]["pairs"]["share_w1"],
                                "pairs": cen[d]["arms"][arm]["pairs"]["pairs"], "null": cen[d]["arms"][arm]["null"]["mean"],
                                "logic_clbs": cen[d]["arms"][arm]["logic_clbs"]}
                            for d in have if arm in cen[d]["arms"]}
    # H17a
    s = {d: cen[d]["arms"]["stock"]["pairs"]["share"] for d in have}
    sv = [s[d]["SC"] for d in have]
    tv = [s[d]["SI"] + s[d]["OR"] for d in have]
    fv = [s[d]["SN"] + s[d]["FL"] for d in have]
    ms, mt, mf = (med(v) for v in (sv, tv, fv))
    n = len(have)
    h17a: dict = {"n": n, "median_SC": ms, "median_SI_OR": mt, "median_SN_FL": mf,
                  "s_lt_t": sum(1 for a, b in zip(sv, tv, strict=True) if a < b)}
    if n >= 12 and ms is not None:
        shape_ok = ms <= 0.25 and mt >= 0.50 and ms < mf < mt and h17a["s_lt_t"] >= need(n)
        shape_no = mt < 0.40 or ms > 0.30
        h17a["shape"] = "supported" if shape_ok else ("not supported" if shape_no else "inconclusive")
        num_ok = abs(ms - 0.10) <= 0.10 and abs(mt - 0.75) <= 0.10 and abs(mf - 0.15) <= 0.10
        num_no = max(abs(ms - 0.10), abs(mt - 0.75), abs(mf - 0.15)) > 0.20
        h17a["numbers"] = "supported" if num_ok else ("not supported" if num_no else "inconclusive")
    else:
        h17a["shape"] = h17a["numbers"] = "inconclusive (n < 12)"
    out["H17a"] = h17a
    # H17b
    both = [d for d in have if "r4" in cen[d]["arms"]]
    dsc = [cen[d]["arms"]["r4"]["pairs"]["share"]["SC"] - cen[d]["arms"]["stock"]["pairs"]["share"]["SC"] for d in both]
    dsi = [cen[d]["arms"]["r4"]["pairs"]["share"]["SI"] - cen[d]["arms"]["stock"]["pairs"]["share"]["SI"] for d in both]
    h17b: dict = {"n": len(both), "median_dSC": med(dsc), "mean_dSC": statistics.fmean(dsc) if dsc else None,
                  "median_dSI": med(dsi)}
    if len(both) >= 12:
        ps = holm({"SC": wilcoxon(dsc, "two-sided"), "SI": wilcoxon(dsi, "two-sided")})
        lo, hi = boot_ci(dsc)
        h17b.update({"p_holm_SC": ps["SC"], "p_holm_SI": ps["SI"], "ci90_mean_dSC": [lo, hi]})
        if abs(h17b["median_dSC"]) >= 0.02 and ps["SC"] < 0.05:
            h17b["status"] = "supported (%s)" % ("SC share up" if h17b["median_dSC"] > 0 else "SC share down")
        elif lo >= -0.01 and hi <= 0.01:
            h17b["status"] = "not supported"
        else:
            h17b["status"] = "inconclusive"
    else:
        h17b["status"] = "inconclusive (n < 12)"
    out["H17b"] = h17b
    # H17c
    ratios, rows = [], []
    for d in have:
        a = near[d]["arms"].get("stock") if near[d] else None
        if not a or a["packing_differs"]:
            continue
        m = a["margins"]["0.1"]
        er = a["edge_crossing"]["rate"]
        if m["hops"] >= 20 and er:
            ratios.append(m["hop_crossing_rate"] / er)
            rows.append(d)
    h17c: dict = {"n": len(ratios), "designs": rows, "ratios": ratios, "median_ratio": med(ratios)}
    # Primary status: the literal rule of docs/plan/round4.md (the >= 20 hops filter is registered, so the n
    # that passes it is the registered n; the rule has no n < 12 clause). A Wilcoxon needs >= 6 non-zero
    # differences, else p is NaN (counts as 1.0).
    if ratios:
        p = wilcoxon([r - 1 for r in ratios], "less")
        h17c["p"] = p
        if med(ratios) <= 0.80 and not nan(p) and p < 0.05:
            h17c["status"] = "supported"
        elif med(ratios) >= 1.0:
            h17c["status"] = "not supported"
        else:
            h17c["status"] = "inconclusive"
    else:
        h17c["status"] = "inconclusive"
    # Labelled variant (the reading of round 4 before the fix round): fewer than 12 designs -> inconclusive.
    h17c["status_n12_variant"] = "inconclusive (n < 12)" if len(ratios) < 12 else h17c["status"]
    out["H17c"] = h17c
    # H17d
    dd = [cen[d]["arms"]["stock"]["pairs"]["share"]["SC"] + cen[d]["arms"]["stock"]["pairs"]["share"]["SN"]
          - cen[d]["arms"]["stock"]["null"]["mean"]["SC"] - cen[d]["arms"]["stock"]["null"]["mean"]["SN"] for d in have]
    h17d: dict = {"n": len(dd), "median_excess": med(dd), "positive": sum(1 for v in dd if v > 0)}
    if len(dd) >= 12:
        h17d["p"] = wilcoxon(dd, "greater")
        if h17d["median_excess"] >= 0.05 and h17d["p"] < 0.05 and h17d["positive"] >= need(len(dd)):
            h17d["status"] = "supported"
        elif h17d["median_excess"] < 0.01:
            h17d["status"] = "not supported"
        else:
            h17d["status"] = "inconclusive"
    else:
        h17d["status"] = "inconclusive (n < 12)"
    out["H17d"] = h17d
    # per-design near-critical table
    tab = {}
    for d in have:
        row: dict = {}
        for pack in ("stock", "norns"):
            a = near[d]["arms"].get(pack) if near[d] else None
            if a:
                row[pack] = {"differs": a["packing_differs"], "paths": a["paths_in_report"],
                             "m5": a["margins"]["0.05"], "m10": a["margins"]["0.1"], "share_w2": a["share_w2"],
                             "edge_rate": a["edge_crossing"]["rate"]}
        tab[d] = row
    out["near"] = tab
    # source / rejection / proposal summaries
    summ = {}
    for arm in ("stock", "r3", "r4"):
        tot_mol: dict[str, int] = {}
        gain: dict[str, list[float]] = {}
        rej = {}
        hit = []
        zero = []
        for d in have:
            a = cen[d]["arms"].get(arm)
            if not a:
                continue
            for src, v in a["sources"].items():
                tot_mol[src] = tot_mol.get(src, 0) + v["molecules"]
                gain.setdefault(src, []).append(v["mean_queue_gain"])
            rej[d] = a["rejections_per_cluster"]
            if a.get("proposals") and a["proposals"]["hit_rate"] is not None:
                hit.append(a["proposals"]["hit_rate"])
                zero.append(a["proposals"]["zero_share"])
        total = sum(tot_mol.values()) or 1
        summ[arm] = {"source_share": {k: v / total for k, v in sorted(tot_mol.items())},
                     "median_queue_gain": {k: med(v) for k, v in sorted(gain.items())},
                     "median_rejections_per_cluster": med(list(rej.values())),
                     "median_hit_rate": med(hit), "median_zero_share": med(zero)}
    out["summary"] = summ
    return out


# ---------------------------------------------------------------------------------------
# RQ-N12 knowns

def n12() -> dict:
    rows = []

    def add(kid: str, name: str, holds: int | None, n: int, p: float | None, known: bool | None, note: str) -> None:
        rows.append({"id": kid, "relation": name, "holds": holds, "n": n, "p": p, "known": known, "note": note})

    for kid, key in (("K1", "module"), ("K2", "word")):
        vals, ok = [], 0
        for d in DESIGNS:
            n11 = jload(d, "n11.json")
            if not n11 or nan(n11.get(f"d_{key}")):
                continue
            vals.append(n11[f"d_{key}"])
            if n11[f"d_{key}"] < 0 and n11.get(f"d_{key}_negative_seeds") == 3:
                ok += 1
        p = wilcoxon(vals, "less") if len(vals) >= 6 else float("nan")
        known = (ok >= 12 and p < 0.05) if len(vals) >= 6 else None
        add(kid, f"same-{key} CLBs closer than net connectivity predicts (all 3 seeds)", ok, len(vals), p, known,
            "data: round-3 n11; null: label permutation within connectivity strata; test: Wilcoxon one-sided over designs")
    # K3
    vals, ok = [], 0
    for d in DESIGNS:
        n8 = jload(d, "n8.json")
        if not n8:
            continue
        sh, nu = n8["stock"]["word"]["share"], n8["null"]["word"]["share"]
        vals.append(sh - nu)
        if sh <= 0.80 and sh > nu:
            ok += 1
    p = wilcoxon(vals, "greater") if len(vals) >= 6 else float("nan")
    add("K3", "stock packing dilutes words: word plurality share <= 0.80 and above the null's", ok, len(vals), p,
        (ok >= 12) if vals else None, "data: round-3 n8; descriptive count (no test beyond the stated null comparison)")
    # K4
    vals, ok = [], 0
    for d in DESIGNS:
        n11 = jload(d, "n11.json")
        if not n11 or nan(n11.get("stability")) or nan(n11.get("stability_null")):
            continue
        vals.append(n11["stability"] - n11["stability_null"])
        if n11["stability"] > n11["stability_null"]:
            ok += 1
    p = wilcoxon(vals, "greater") if len(vals) >= 6 else float("nan")
    add("K4", "4-nearest-neighbour stability across seeds exceeds the permuted null", ok, len(vals), p,
        (ok >= 12 and p < 0.05) if len(vals) >= 6 else None, "data: round-3 n11; test: Wilcoxon one-sided")
    # K5
    same, tot = 0, 0
    for d in DESIGNS:
        r = r4runs(d)
        for pack in ("stock", "norns"):
            shas = [r[(pack, "analytic", s)].get("net_sha256") for s in SEEDS if (pack, "analytic", s) in r]
            if len(shas) == 3 and all(shas):
                tot += 1
                same += 1 if len(set(shas)) == 1 else 0
    add("K5", "packing does not depend on the VPR seed (.net identical across the 3 seeds)", same, tot, None,
        (same == tot and tot >= 24) if tot else None, "data: round-4 analytic runs, (design, packing) pairs; no test")
    # K6
    lim = []
    for d in DESIGNS:
        path = nl.runs_dir(d, "r3", "stock.analytic.s1", "vpr.out")
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        blocks = re.findall(r"Physical Tile (\w+):\n\s+Block Utilization: ([0-9.]+) Logical Block", text)
        if blocks:
            lim.append((d, max(blocks, key=lambda b: float(b[1]))[0]))
    clb = sum(1 for _, t in lim if t == "clb")
    add("K6", "the grid is sized by the logic (clb) tile: it has the highest utilisation", clb, len(lim), None,
        (clb >= 12) if lim else None, "data: round-3 stock vpr.out; descriptive. Limiting types: " + ", ".join(f"{d}:{t}" for d, t in lim))
    # K7
    vals, ok = [], 0
    for d in DESIGNS:
        r = nl.runs_dir(d, "r4", "stock.analytic.s1", "attr.json")
        pj = nl.runs_dir(d, "r4", "stock.analytic.s1", "paths.json.gz")
        if not r.is_file() or not pj.is_file():
            continue
        paths = json.load(gzip.open(pj, "rt"))
        crit = paths[0]["nodes"]
        tot_d = sum(n[5] or 0 for n in crit) or 1
        hard_d = sum((n[5] or 0) for n in crit if n[1] not in (".names", ".latch", ".input", ".output"))
        flat = nl.runs_dir(d, "r4", "stock.analytic.s1", "final.flat_place")
        fl = nl.Flat(flat)
        nlogic = len(fl.atoms) or 1
        nhard = sum(1 for v in fl.atoms.values() if v[5] and ("mult" in v[5].lower() or "adder" in v[5].lower() or "ram" in v[5].lower()))
        vals.append(hard_d / tot_d - nhard / nlogic)
        ok += 1 if hard_d / tot_d > nhard / nlogic else 0
    p = wilcoxon(vals, "greater") if len(vals) >= 6 else float("nan")
    add("K7", "adder, multiplier and memory atoms hold more of the critical-path delay than of the design's atoms", ok,
        len(vals), p, (ok >= 12 and p < 0.05) if len(vals) >= 6 else None,
        "data: round-4 stock analytic seed 1 attribution; test: Wilcoxon one-sided")
    # K8
    rho_list = []
    for d in DESIGNS:
        r = r4runs(d)
        xs = [r[("stock", "analytic", s)] for s in SEEDS if ("stock", "analytic", s) in r]
        xs += [r[("norns", "analytic", s)] for s in SEEDS if ("norns", "analytic", s) in r]
        wl = [x["wirelength"] for x in xs]
        cp = [x["cpd_ns"] for x in xs]
        if len(xs) >= 5 and len(set(wl)) > 1 and len(set(cp)) > 1:
            rho_list.append(float(stats.spearmanr(wl, cp).statistic))
    add("K8", "routed wirelength and CPD move together across runs of one design (Spearman > 0)",
        sum(1 for v in rho_list if v > 0), len(rho_list), None, (sum(1 for v in rho_list if v > 0) >= 12) if rho_list else None,
        "data: round-4 analytic runs (both packings, 3 seeds); descriptive")
    for r in rows:  # labelled variant: the count k = 12 of 15 scaled to the n actually defined (ceil(0.8 n))
        if r["known"] is None or r["n"] < 6:
            r["known_scaled"] = None
        elif r["id"] == "K5":
            r["known_scaled"] = r["holds"] == r["n"]
        else:
            r["known_scaled"] = r["holds"] >= math.ceil(0.8 * r["n"]) and (r["p"] is None or nan(r["p"]) or r["p"] < 0.05)
    return {"rows": rows, "n_known": sum(1 for r in rows if r["known"]),
            "n_known_scaled": sum(1 for r in rows if r.get("known_scaled"))}


# ---------------------------------------------------------------------------------------
# RQ-N13

def spearman_p(x: list[float], y: list[float]) -> tuple[float, float]:
    res = stats.spearmanr(x, y)
    return float(res.statistic), float(res.pvalue)


def partial_spearman(x: list[float], y: list[float], z: list[float]) -> tuple[float, float]:
    rxy, rxz, ryz = (float(stats.spearmanr(a, b).statistic) for a, b in ((x, y), (x, z), (y, z)))
    r = (rxy - rxz * ryz) / math.sqrt(max((1 - rxz ** 2) * (1 - ryz ** 2), 1e-12))
    n = len(x)
    t = r * math.sqrt((n - 3) / max(1 - r * r, 1e-12))
    return r, float(2 * stats.t.sf(abs(t), n - 3))


def n13() -> dict:
    rows = []
    for d in DESIGNS:
        h = jload(d, "r4hier.json")
        r = r4runs(d)
        if not h or ("stock", "analytic", 1) not in r:
            continue
        row: dict = {"design": d, "S": h["S"], "M": h["M"], "D": h["D"], "A_med": h["A_med"], "rent": h["rent"]}
        for pack in ("stock", "norns"):
            rr = [r[(pack, "analytic", s)] for s in SEEDS if (pack, "analytic", s) in r]
            if len(rr) == 3:
                row[pack] = {"area": statistics.fmean(x["grid"][0] * x["grid"][1] for x in rr),
                             "clbs": statistics.fmean(x["logic_clbs"] for x in rr),
                             "W": statistics.fmean(x["chan_width"] for x in rr)}
        rows.append(row)
    out: dict = {"rows": rows, "n": len(rows)}
    if len(rows) < 8:
        out["status"] = {"H13a": "inconclusive (n < 8)", "H13b": "inconclusive (n < 8)", "H13c": "inconclusive (n < 8)"}
        return out
    lm = [math.log(x["M"]) for x in rows]
    ls = [math.log(x["S"]) for x in rows]
    tests_a, tests_b = {}, {}
    for pack in ("stock", "norns"):
        for key in ("area", "clbs", "W"):
            ys = [math.log(x[pack][key]) for x in rows]
            rho, p = spearman_p(lm, ys)
            tests_a[f"{pack}.{key}"] = {"rho": rho, "p": p}
            rp, pp = partial_spearman(lm, ys, ls)
            tests_b[f"{pack}.{key}"] = {"rho": rp, "p": pp}
    for tests in (tests_a, tests_b):
        adj = holm({k: v["p"] for k, v in tests.items()})
        for k in tests:
            tests[k]["p_holm"] = adj[k]
    a_ok = all(tests_a[f"{p}.area"]["rho"] >= 0.6 and tests_a[f"{p}.area"]["p_holm"] < 0.05 for p in ("stock", "norns"))
    a_no = all(tests_a[f"{p}.area"]["rho"] < 0.3 for p in ("stock", "norns"))
    b_ok = all(abs(tests_b[f"{p}.area"]["rho"]) >= 0.5 and tests_b[f"{p}.area"]["p_holm"] < 0.05 for p in ("stock", "norns"))
    b_no = all(abs(tests_b[f"{p}.area"]["rho"]) < 0.3 for p in ("stock", "norns"))
    ratio = [math.log(x["norns"]["area"] / x["stock"]["area"]) for x in rows]
    rc, pc = spearman_p(lm, ratio)
    out.update({"H13a": tests_a, "H13b": tests_b, "H13c": {"rho": rc, "p": pc},
                "status": {"H13a": "supported" if a_ok else ("not supported" if a_no else "inconclusive"),
                           "H13b": "supported" if b_ok else ("not supported" if b_no else "inconclusive"),
                           "H13c": "supported" if abs(rc) >= 0.5 and pc < 0.05 else ("not supported" if abs(rc) < 0.3 else "inconclusive")}})
    return out


# ---------------------------------------------------------------------------------------
# RQ-N14 / N16 / N15

def ratios(designs: list[str], num: tuple[str, str], den: tuple[str, str], metric: str) -> dict[str, float]:
    out = {}
    for d in designs:
        r = r4runs(d)
        vals = []
        for s in SEEDS:
            a, b = r.get((num[0], num[1], s)), r.get((den[0], den[1], s))
            if a and b and a.get(metric) and b.get(metric):
                vals.append(a[metric] / b[metric])
        if len(vals) == len(SEEDS):
            out[d] = nl.geomean(vals)
    return out


def ratio_block(rat: dict[str, float]) -> dict:
    vals = list(rat.values())
    blk: dict = {"n": len(vals), "designs": list(rat)}
    if len(vals) < 6:
        return blk
    lr = [math.log(v) for v in vals]
    lo, hi = boot_ci(lr)
    blk.update({"gm": nl.geomean(vals), "better": sum(1 for v in vals if v < 1), "p": wilcoxon(lr, "less"),
                "lo90": math.exp(lo), "hi90": math.exp(hi)})
    return blk


def decide_ratio(blk: dict, p_holm: float | None) -> str:
    if blk["n"] < 12:
        return "inconclusive (n < 12)"
    if blk["gm"] <= 0.99 and p_holm is not None and p_holm < 0.05:
        return "supported (better)"
    if blk["gm"] >= 1.00 or (blk["lo90"] >= 0.98 and blk["hi90"] <= 1.02):
        return "not supported"
    return "inconclusive"


def arms() -> dict:
    metrics = ("wirelength", "chan_width", "cpd_ns")
    out: dict = {}
    for variant, designs in (("all", DESIGNS), ("no4", [d for d in DESIGNS if d not in PILOT])):
        res: dict = {"H14": {}, "H16": {}, "ref": {}}
        # H14: norns against stock, analytic start
        h14 = {m: ratio_block(ratios(designs, ("norns", "analytic"), ("stock", "analytic"), m)) for m in metrics}
        adj = holm({m: h14[m].get("p", float("nan")) for m in metrics})
        for m in metrics:
            h14[m]["p_holm"] = adj[m]
            h14[m]["status"] = decide_ratio(h14[m], adj[m])
        res["H14"] = h14
        # H16: stagebit against analytic start, within each packing
        h16 = {}
        for pack in ("stock", "norns"):
            for m in metrics:
                h16[f"{pack}.{m}"] = ratio_block(ratios(designs, (pack, "stagebit"), (pack, "analytic"), m))
        adj16 = holm({k: v.get("p", float("nan")) for k, v in h16.items()})
        for k in h16:
            h16[k]["p_holm"] = adj16[k]
            h16[k]["status"] = decide_ratio(h16[k], adj16[k])
        res["H16"] = h16
        ref = {}
        for pack in ("stock", "norns"):
            for m in metrics:
                ref[f"{pack}.wordseed_vs_analytic.{m}"] = ratio_block(ratios(designs, (pack, "wordseed"), (pack, "analytic"), m))
                ref[f"{pack}.stagebit_vs_wordseed.{m}"] = ratio_block(ratios(designs, (pack, "stagebit"), (pack, "wordseed"), m))
        res["ref"] = ref
        out[variant] = res
    # CPD check, independent quantities: the log's `Final critical path delay` (rec cpd_ns) against path 1 of the
    # timing report (arrival minus required time = minus its slack, report precision 1e-3 ns; paths.json.gz keeps
    # the report's arrival and slack). rec attr_cpd_ns is the same log line read again, so it is not used here.
    agree, tot, repro, repro_n = 0, 0, 0, 0
    worst, arr_gap = 0.0, []
    for d in DESIGNS:
        r = r4runs(d)
        for key, rec in r.items():
            pj = nl.runs_dir(d, "r4", f"{key[0]}.{key[1]}.s{key[2]}", "paths.json.gz")
            if rec.get("cpd_ns") is not None and pj.is_file():
                p1 = json.load(gzip.open(pj, "rt"))[0]
                tot += 1
                diff = abs(-p1["slack"] - rec["cpd_ns"])
                worst = max(worst, diff)
                agree += 1 if diff <= 5.5e-4 else 0
                arr_gap.append(rec["cpd_ns"] - p1["arrival"])
        r3 = {x["tag"]: x for x in recs(d, "r3runs.jsonl") if x.get("rc") == 0}
        for s in SEEDS:
            a, b = r.get(("stock", "analytic", s)), r3.get(f"stock.analytic.s{s}")
            if a and b:
                repro_n += 1
                repro += 1 if (a["wirelength"] == b["wirelength"] and a["chan_width"] == b["chan_width"] and abs(a["cpd_ns"] - b["cpd_ns"]) < 1e-4) else 0
    out["checks"] = {"cpd_agree": agree, "cpd_total": tot, "cpd_max_diff": worst,
                     "cpd_minus_arrival_median": med(arr_gap), "cpd_minus_arrival_max": max(arr_gap) if arr_gap else None, "stock_repro": repro, "stock_repro_n": repro_n}
    return out


def h15() -> dict:
    rows = []
    for d in DESIGNS:
        r = jload(d, "r4depth.json")
        if r:
            rows.append(r)
    use = [r for r in rows if r["enough"] and r["rho"] is not None]
    out: dict = {"rows": rows, "n": len(use)}
    if len(use) >= 6:
        rhos = [r["rho"] for r in use]
        out.update({"median_rho": med(rhos), "positive": sum(1 for v in rhos if v > 0),
                    "p": wilcoxon(rhos, "greater"), "overlap_median": med([r["top5_overlap"] for r in use]),
                    "overlap_expected_median": med([r["top5_expected"] for r in use])})
        if out["median_rho"] >= 0.30 and out["p"] < 0.05 and out["positive"] >= 0.8 * len(use):
            out["status"] = "supported"
        elif out["median_rho"] < 0.10:
            out["status"] = "not supported"
        else:
            out["status"] = "inconclusive"
        if len(use) < 12:
            out["status"] += " (n < 12 designs with >= 8 spans)"
    else:
        out["status"] = "inconclusive (n < 6 designs with >= 8 spans)"
    return out


def main() -> int:
    res = {"n17": n17(), "n12": n12(), "n13": n13(), "arms": arms(), "h15": h15()}
    nl.write_json(RESULT, res)
    h = res["n17"]
    print("H17a", h["H17a"].get("shape"), h["H17a"].get("numbers"), "H17b", h["H17b"]["status"], "H17c", h["H17c"]["status"],
          "H17d", h["H17d"]["status"])
    print("knowns", res["n12"]["n_known"], "H13", res["n13"].get("status"), "H15", res["h15"]["status"])
    print("H14", {m: v["status"] for m, v in res["arms"]["all"]["H14"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
