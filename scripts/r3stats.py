"""Round-3 numbers and hypothesis statuses (rules: docs/plan/round3.md; no number is typed by hand).

Reads data/<d>/{n8,iowords,n11,r3runs.jsonl}, data/analysis/{r3-grid,r3-gate}.json and writes
data/analysis/r3-results.json (everything the round-3 text and tables print). Usage:
    python scripts/r3stats.py
"""

from __future__ import annotations

import json
import math
import statistics
import sys

import numpy as np
from scipy import stats

import affinity as af
import nornlib as nl
import round3 as r3

PILOT = r3.PILOT
SEEDS = r3.SEEDS
BOOT = 10000
BOOT_SEED = 20261024
RESULT = nl.DATA / "analysis" / "r3-results.json"


def f3(x: float | None) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def pfmt(p: float | None) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def wilcoxon(x: list[float], alternative: str) -> float:
    x = [v for v in x if v != 0.0]
    if len(x) < 5:
        return float("nan")
    return float(stats.wilcoxon(x, alternative=alternative).pvalue)


def holm(ps: dict[str, float]) -> dict[str, float]:
    """Holm adjustment with m = len(ps) always (3 sources); a NaN p counts as 1.0 (fix entry 2026-10-25)."""
    items = sorted(((1.0 if math.isnan(p) else p), k) for k, p in ps.items())
    out: dict[str, float] = {}
    running = 0.0
    m = len(items)
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def boot_ci(logratios: list[float], level: float = 0.90) -> tuple[float, float]:
    rng = np.random.default_rng(BOOT_SEED)
    arr = np.array(logratios)
    idx = rng.integers(0, len(arr), (BOOT, len(arr)))
    means = arr[idx].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])
    return math.exp(lo), math.exp(hi)


def runs_by(design: str) -> dict[tuple, dict]:
    out = {}
    for r in r3.records(design):
        if r["rc"] == 0:
            out[(r["arm"], r["start"], r["vseed"])] = r
    return out


def metric_ratio(design, cfg, base_cfg, start, metric="wirelength", base_start=None) -> float | None:
    """Geomean over seeds of arm / base (same VPR seed)."""
    runs = runs_by(design)
    vals = []
    for s in SEEDS:
        a = runs.get((cfg, start, s))
        b = runs.get((base_cfg, base_start or start, s))
        if a and b and a.get(metric) and b.get(metric):
            vals.append(a[metric] / b[metric])
    return nl.geomean(vals) if len(vals) == len(SEEDS) else None


def level_of(source: str) -> str:
    return {"module": "module", "word": "word", "wordio": "wordio"}[source]


def purity_gain(design, cfg, source, key="share") -> float | None:
    runs = runs_by(design)
    vals = []
    for s in SEEDS:
        a, b = runs.get((cfg, "analytic", s)), runs.get(("stock", "analytic", s))
        if a and b:
            lev = level_of(source)
            vals.append(a["purity"][lev][key] - b["purity"][lev][key])
    return statistics.mean(vals) if len(vals) == len(SEEDS) else None


def clb_growth(design, cfg) -> float | None:
    runs = runs_by(design)
    vals = []
    for s in SEEDS:
        a, b = runs.get((cfg, "analytic", s)), runs.get(("stock", "analytic", s))
        if a and b:
            vals.append(a["logic_clbs"] / b["logic_clbs"] - 1)
    return statistics.mean(vals) if len(vals) == len(SEEDS) else None


def designs_done(designs: list[str], needed: list[str]) -> list[str]:
    ok = []
    for d in designs:
        runs = runs_by(d)
        if all((c, st, s) in runs for c, st in needed for s in SEEDS):
            ok.append(d)
    return ok


def decide(statusfn, designs: list[str], pilot_free: list[str]) -> dict:
    """The status on n=all and n=without the pilot designs; differing statuses: inconclusive."""
    a = statusfn(designs)
    b = statusfn(pilot_free)
    final = a["status"] if a["status"] == b["status"] else "inconclusive (pilot-sensitive)"
    return {"status": final, "all": a, "no_pilot": b}


def h9(grid: dict, designs: list[str]) -> dict:
    out: dict = {}
    head = {s: f"{s}-b{grid['sources'][s]['beta_m']:g}" for s in af.SOURCES}
    pilot_free = [d for d in designs if d not in PILOT]

    def a_status(ds: list[str], source: str) -> dict:
        cfg = head[source]
        gains = [purity_gain(d, cfg, source) for d in ds]
        grow = [clb_growth(d, cfg) for d in ds]
        pairs = [(g, c) for g, c in zip(gains, grow) if g is not None and c is not None]
        if len(pairs) < 5:
            return {"status": "inconclusive", "n": len(pairs)}
        g = [p[0] for p in pairs]
        c = [p[1] for p in pairs]
        p = wilcoxon(g, "greater")
        return {"n": len(pairs), "median_gain": statistics.median(g), "p": p,
                "median_growth": statistics.median(c), "max_growth": max(c), "status": None}

    ps_a = {}
    res_a = {}
    for source in af.SOURCES:
        res_a[source] = {"all": a_status(designs, source), "no_pilot": a_status(pilot_free, source)}
        ps_a[source] = res_a[source]["all"].get("p", float("nan"))
    hp = holm(ps_a)
    for source in af.SOURCES:
        for key in ("all", "no_pilot"):
            r = res_a[source][key]
            if r.get("status") is None:
                padj = hp[source] if key == "all" else holm({s: res_a[s]["no_pilot"].get("p", float("nan"))
                                                              for s in af.SOURCES})[source]
                r["p_holm"] = padj
                g, gr, mx = r["median_gain"], r["median_growth"], r["max_growth"]
                if g >= 0.05 and padj < 0.05 and gr <= 0.05 and mx <= 0.15:
                    r["status"] = "supported"
                elif g < 0.02 or (gr > 0.05 and g < 0.05):
                    r["status"] = "not supported"
                else:
                    r["status"] = "inconclusive"
        a, b = res_a[source]["all"], res_a[source]["no_pilot"]
        res_a[source]["status"] = a["status"] if a["status"] == b["status"] else "inconclusive (pilot-sensitive)"
    out["H9a"] = res_a

    def wl_ratios(ds: list[str], cfg: str, base: str, start: str) -> list[float]:
        vals = [metric_ratio(d, cfg, base, start) for d in ds]
        return [v for v in vals if v is not None]

    def b_status(ds: list[str], source: str) -> dict:
        ratios = wl_ratios(ds, head[source], "stock", "analytic")
        if len(ratios) < 5:
            return {"status": "inconclusive", "n": len(ratios)}
        lr = [math.log(v) for v in ratios]
        lo, hi = boot_ci(lr)
        return {"n": len(ratios), "gm": nl.geomean(ratios), "p": wilcoxon(lr, "two-sided"),
                "lo90": lo, "hi90": hi, "better": sum(1 for v in ratios if v < 1), "status": None}

    res_b = {s: {"all": b_status(designs, s), "no_pilot": b_status(pilot_free, s)} for s in af.SOURCES}
    for key in ("all", "no_pilot"):
        hpb = holm({s: res_b[s][key].get("p", float("nan")) for s in af.SOURCES})
        for s in af.SOURCES:
            r = res_b[s][key]
            if r.get("status") is None:
                r["p_holm"] = hpb[s]
                if abs(math.log(r["gm"])) >= math.log(1.01) and hpb[s] < 0.05:
                    r["status"] = "supported (%s)" % ("lower WL" if r["gm"] < 1 else "higher WL")
                elif r["lo90"] >= 0.98 and r["hi90"] <= 1.02:
                    r["status"] = "not supported"
                else:
                    r["status"] = "inconclusive"
    for s in af.SOURCES:
        a, b = res_b[s]["all"], res_b[s]["no_pilot"]
        res_b[s]["status"] = a["status"] if a["status"] == b["status"] else "inconclusive (pilot-sensitive)"
    out["H9b"] = res_b

    def c_status(ds: list[str], source: str) -> dict:
        ratios = []
        for d in ds:
            runs = runs_by(d)
            vals = []
            for s in SEEDS:
                a, b = runs.get((head[source], "seed", s)), runs.get(("stock", "seed", s))
                if a and b and a.get("wirelength") and b.get("wirelength"):
                    vals.append(a["wirelength"] / b["wirelength"])
            if len(vals) == len(SEEDS):
                ratios.append(nl.geomean(vals))
        if len(ratios) < 5:
            return {"status": "inconclusive", "n": len(ratios)}
        lr = [math.log(v) for v in ratios]
        return {"n": len(ratios), "gm": nl.geomean(ratios), "p": wilcoxon(lr, "less"),
                "better": sum(1 for v in ratios if v < 1), "status": None}

    res_c = {s: {"all": c_status(designs, s), "no_pilot": c_status(pilot_free, s)} for s in af.SOURCES}
    for key in ("all", "no_pilot"):
        hpc = holm({s: res_c[s][key].get("p", float("nan")) for s in af.SOURCES})
        for s in af.SOURCES:
            r = res_c[s][key]
            if r.get("status") is None:
                r["p_holm"] = hpc[s]
                if r["gm"] <= 0.99 and hpc[s] < 0.05:
                    r["status"] = "supported"
                elif r["gm"] >= 1.00:
                    r["status"] = "not supported"
                else:
                    r["status"] = "inconclusive"
    for s in af.SOURCES:
        a, b = res_c[s]["all"], res_c[s]["no_pilot"]
        res_c[s]["status"] = a["status"] if a["status"] == b["status"] else "inconclusive (pilot-sensitive)"
    out["H9c"] = res_c

    def h10b_status(ds: list[str]) -> dict:
        ratios = []
        for d in ds:
            v = metric_ratio(d, head["wordio"], head["word"], "analytic")
            if v is not None:
                ratios.append(v)
        if len(ratios) < 5:
            return {"status": "inconclusive", "n": len(ratios)}
        lr = [math.log(v) for v in ratios]
        lo, hi = boot_ci(lr)
        gm = nl.geomean(ratios)
        p = wilcoxon(lr, "two-sided")
        if gm <= 0.99 and p < 0.05:
            status = "supported"
        elif gm >= 1.00 or (lo >= 0.98 and hi <= 1.02):
            status = "not supported"
        else:
            status = "inconclusive"
        return {"n": len(ratios), "gm": gm, "p": p, "lo90": lo, "hi90": hi, "status": status,
                "better": sum(1 for v in ratios if v < 1)}

    out["H10b"] = decide(h10b_status, designs, pilot_free)
    out["headline"] = head
    return out


def h8(designs: list[str]) -> dict:
    rows = {d: nl.read_json(nl.DATA / d / "n8.json") for d in designs}
    share = [rows[d]["stock"]["word"]["share"] for d in designs]
    split = [rows[d]["stock"]["word"]["split"] for d in designs]
    nullshare = [rows[d]["null"]["word"]["share"] for d in designs]
    msh = statistics.median(share)
    msp = statistics.median(split)
    if msh <= 0.80 and msp >= 1.5:
        status = "supported"
    elif msh > 0.80 and msp < 1.5:
        status = "not supported"
    else:
        status = "inconclusive"
    mod = [rows[d]["stock"]["module"]["share"] for d in designs]
    dec = {k: statistics.median([rows[d]["decompose"][k] for d in designs])
           for k in ("word", "loss_abc", "loss_pack", "no_word_mixed", "no_word_none", "word_in_own_clb")}
    return {"status": status, "median_share": msh, "median_split": msp,
            "median_null_share": statistics.median(nullshare), "median_module_share": statistics.median(mod),
            "above_null": sum(1 for a, b in zip(share, nullshare) if a > b), "n": len(designs),
            "decompose_median": dec,
            "split_gt1": sum(1 for v in split if v > 1.0)}


def h10a(designs: list[str], need: int = 12) -> dict:
    rows = {d: nl.read_json(nl.DATA / d / "iowords.json") for d in designs}
    gain = [rows[d]["lut_cov_union"] - rows[d]["lut_cov_word"] for d in designs]
    med = statistics.median(gain)
    pos = sum(1 for g in gain if g > 0)
    if med >= 0.05 and pos >= need:
        status = "supported"
    elif med < 0.01:
        status = "not supported"
    else:
        status = "inconclusive"
    return {"status": status, "median_gain": med, "positive": pos, "n": len(designs), "need": need,
            "median_cov_word": statistics.median([rows[d]["lut_cov_word"] for d in designs]),
            "median_cov_union": statistics.median([rows[d]["lut_cov_union"] for d in designs])}


def h11_rule(vals: list[float], neg: list[int], need: int) -> dict:
    """The registered H11 rule for one relation: median <= -0.05, one-sided Wilcoxon p < 0.05, and
    negative on >= 2 of 3 seeds in `need` designs (registered: 12 of the 15 designs)."""
    n = len(vals)
    if n < 5:
        return {"status": "inconclusive", "n": n}
    med = statistics.median(vals)
    p = wilcoxon(vals, "less")
    consistent = sum(1 for x in neg if x >= 2)
    if med <= -0.05 and p < 0.05 and consistent >= need:
        status = "supported"
    elif med > -0.01:
        status = "not supported"
    else:
        status = "inconclusive"
    return {"status": status, "n": n, "median_d": med, "p": p, "consistent": consistent, "need": need}


def pooled_perm_p(rows: dict, rel: str, designs: list[str], draws: int | None) -> float:
    """Permutation p of the median over designs of d (label permutations within strata, pooled over designs)."""
    cols = []
    obs = []
    for d in designs:
        seeds = rows[d]["seeds"]
        arr = np.array([s[f"perm_d_{rel}"][:draws] for s in seeds], dtype=float)
        with np.errstate(all="ignore"):
            cols.append(np.nanmean(arr, axis=0))
        obs.append(rows[d][f"d_{rel}"])
    if not cols:
        return float("nan")
    with np.errstate(all="ignore"):
        pooled = np.nanmedian(np.vstack(cols), axis=0)
    o = statistics.median(obs)
    return float((int(np.sum(pooled <= o)) + 1) / (len(pooled) + 1))


def h11_variants(rows: dict, designs: list[str]) -> dict:
    """The H11 statuses of a set of designs under the registered rule (no exclusion) and the d805789
    amendment (>= 95% related pairs excluded per design), each with the literal need (12) and the
    unregistered scaling ceil(12/15 n)."""
    out: dict = {}
    for vname, amend in (("registered", False), ("amended", True)):
        for scaled in (False, True):
            key = vname + ("_scaled" if scaled else "")
            res: dict = {}
            for rel in ("word", "module"):
                keep = [d for d in designs if d in rows and not math.isnan(rows[d][f"d_{rel}"])
                        and not (amend and rows[d][f"excluded_amend_{rel}"])]
                vals = [rows[d][f"d_{rel}"] for d in keep]
                neg = [rows[d][f"d_{rel}_negative_seeds"] for d in keep]
                need = math.ceil(12 / 15 * len(keep)) if scaled else 12
                res[rel] = h11_rule(vals, neg, need)
                res[rel]["excluded"] = sorted(set(designs) - set(keep))
                res[rel]["p_perm"] = pooled_perm_p(rows, rel, keep, 200 if amend else None) if len(keep) >= 5 else float("nan")
                res[rel]["perm_draws"] = 200 if amend else PERMS_POOLED
            st = [res[r]["status"] for r in ("word", "module")]
            res["status"] = "supported" if all(x == "supported" for x in st) else (
                "not supported" if all(x == "not supported" for x in st) else "inconclusive")
            out[key] = res
    return out


PERMS_POOLED = 1000


def h11(designs: list[str]) -> dict:
    rows = {}
    for d in designs:
        p = nl.DATA / d / "n11.json"
        if p.is_file():
            rows[d] = nl.read_json(p)
    pilot_free = [d for d in designs if d not in PILOT]
    var = h11_variants(rows, designs)
    out: dict = {rel: var["registered"][rel] for rel in ("word", "module")}
    out["status"] = var["registered"]["status"]
    out["variants"] = var
    out["no_pilot"] = h11_variants(rows, pilot_free)
    stab = [r["stability"] for r in rows.values() if r.get("stability") is not None]
    nul = [r["stability_null"] for r in rows.values() if r.get("stability_null") is not None]
    out["stability"] = statistics.mean(stab) if stab else None
    out["stability_null"] = statistics.mean(nul) if nul else None
    out["n_designs"] = len(rows)
    out["d_positive"] = {rel: sorted(d for d in rows if not math.isnan(rows[d][f"d_{rel}"]) and rows[d][f"d_{rel}"] > 0)
                         for rel in ("word", "module")}
    out["share"] = {d: {"word": rows[d]["share_word"], "module": rows[d]["share_module"]} for d in rows}
    return out


def secondary(grid: dict, designs: list[str]) -> dict:
    """Median ratios against stock for the headline configs (runtime, grid, chan width, CLB count)."""
    out: dict = {}
    for start in ("analytic", "seed"):
        for source in af.SOURCES:
            cfg = f"{source}-b{grid['sources'][source]['beta_m']:g}"
            row = {}
            for metric in ("wirelength", "chan_width", "cpd_ns", "pack_s", "flow_s", "logic_clbs"):
                vals = [metric_ratio(d, cfg, "stock", start, metric) for d in designs]
                vals = [v for v in vals if v is not None]
                row[metric] = nl.geomean(vals) if vals else None
            out[f"{source}.{start}"] = row
    return out


def seed_noise(designs: list[str]) -> dict:
    cv = {}
    for d in designs:
        runs = runs_by(d)
        wl = [runs[("stock", "analytic", s)]["wirelength"] for s in SEEDS if ("stock", "analytic", s) in runs]
        if len(wl) == len(SEEDS):
            cv[d] = statistics.pstdev(wl) / statistics.mean(wl)
    return {"cv_median": statistics.median(cv.values()) if cv else None,
            "cv_max": max(cv.values()) if cv else None, "n": len(cv)}


def fixes(designs: list[str]) -> dict:
    """Fix-round measurements (scripts/r3fix.py, data/analysis/r3fix-*.json): packer identity after the log counter,
    proposal hit-rate, matched affinity entries, the stock arm on the Norns binary, the beta-0 gate extension."""
    out: dict = {}
    ident = nl.DATA / "analysis" / "r3fix-ident.json"
    if ident.is_file():
        res = nl.read_json(ident)
        rows = [r for d in designs for r in res.get(d, [])]
        prop = {d: {} for d in designs}
        for d in designs:
            for r in res.get(d, []):
                src = r["cfg"].split("-b")[0]
                p = r["proposals"] or {}
                if p:
                    prop[d][src] = {**p, "hit_rate": p["queued"] / p["attempted"] if p["attempted"] else None,
                                    "zero_share": p["calls_zero_queued"] / p["calls"] if p["calls"] else None}
        tot = {src: {k: sum(prop[d][src][k] for d in designs if src in prop[d])
                     for k in ("calls", "calls_zero_queued", "attempted", "queued")} for src in af.SOURCES}
        out["ident"] = {"n": len(rows), "net_identical": sum(1 for r in rows if r["net_identical_old_new"]),
                        "flat_identical": sum(1 for r in rows if r["flat_identical_stage4"]),
                        "designs": len(res), "proposals": prop, "totals": tot,
                        "hit_rate_median": {src: statistics.median([prop[d][src]["hit_rate"] for d in designs
                                                                     if src in prop[d] and prop[d][src]["hit_rate"] is not None])
                                            for src in af.SOURCES},
                        "zero_share_median": {src: statistics.median([prop[d][src]["zero_share"] for d in designs
                                                                       if src in prop[d] and prop[d][src]["zero_share"] is not None])
                                              for src in af.SOURCES}}
    match = nl.DATA / "analysis" / "r3fix-match.json"
    if match.is_file():
        m = nl.read_json(match)
        frac = {src: [m[d][src]["matched"] / m[d][src]["entries"] for d in designs] for src in af.SOURCES}
        worst = {src: min(((m[d][src]["matched"] / m[d][src]["entries"], d) for d in designs)) for src in af.SOURCES}
        out["match"] = {"rows": m, "median": {s_: statistics.median(v) for s_, v in frac.items()},
                        "worst": {s_: {"fraction": w[0], "design": w[1]} for s_, w in worst.items()}}
    stockn = nl.DATA / "analysis" / "r3fix-stockn.json"
    if stockn.is_file():
        sn = nl.read_json(stockn)
        ratios: dict[str, list[float]] = {src: [] for src in af.SOURCES}
        ratios_old: dict[str, list[float]] = {src: [] for src in af.SOURCES}
        for d in designs:
            runs = runs_by(d)
            base = {r["seed"]: r["pack_s"] for r in sn.get(d, []) if r["rc"] == 0 and r["pack_s"]}
            if len(base) != len(SEEDS):
                continue
            for src in af.SOURCES:
                cfg = f"{src}-b{r3_beta(src)}"
                vals = [runs[(cfg, "analytic", s_)]["pack_s"] / base[s_] for s_ in SEEDS
                        if (cfg, "analytic", s_) in runs and runs[(cfg, "analytic", s_)].get("pack_s")]
                old = [runs[(cfg, "analytic", s_)]["pack_s"] / runs[("stock", "analytic", s_)]["pack_s"] for s_ in SEEDS
                       if (cfg, "analytic", s_) in runs and runs[(cfg, "analytic", s_)].get("pack_s")
                       and runs.get(("stock", "analytic", s_), {}).get("pack_s")]
                if len(vals) == len(SEEDS):
                    ratios[src].append(nl.geomean(vals))
                if len(old) == len(SEEDS):
                    ratios_old[src].append(nl.geomean(old))
        out["stockn"] = {"n_runs": sum(len(v) for v in sn.values()),
                         "flat_identical": sum(1 for v in sn.values() for r in v if r["flat_identical_stage4_stock"]),
                         "pack_ratio_same_binary": {src: nl.geomean(v) if v else None for src, v in ratios.items()},
                         "pack_ratio_other_build": {src: nl.geomean(v) if v else None for src, v in ratios_old.items()},
                         "n_designs": {src: len(v) for src, v in ratios.items()}}
    tm = nl.DATA / "analysis" / "r3fix-timing.json"
    if tm.is_file():
        t = nl.read_json(tm)
        per: dict[str, list[float]] = {src: [] for src in af.SOURCES}
        starts, loads = [], []
        for d in designs:
            rows = t.get(d, [])
            starts += [r["start"] for r in rows]
            loads += [r["load1"] for r in rows]
            for src in af.SOURCES:
                vals = []
                for s_ in SEEDS:
                    a = [r["pack_s"] for r in rows if r["seed"] == s_ and r["arm"] == f"{src}-b4" and r["pack_s"]]
                    b = [r["pack_s"] for r in rows if r["seed"] == s_ and r["arm"] == "stock" and r["pack_s"]]
                    if a and b:
                        vals.append(a[0] / b[0])
                if len(vals) == len(SEEDS):
                    per[src].append(nl.geomean(vals))
        out["timing"] = {"ratio": {src: nl.geomean(v) if v else None for src, v in per.items()},
                         "n_designs": {src: len(v) for src, v in per.items()},
                         "window": [min(starts), max(starts)] if starts else None,
                         "load1_median": statistics.median(loads) if loads else None,
                         "load1_max": max(loads) if loads else None, "n_runs": sum(len(v) for v in t.values())}
    g2 = nl.DATA / "analysis" / "r3fix-gate2.json"
    if g2.is_file():
        gg = nl.read_json(g2)
        out["gate2"] = {"designs": len(gg), "n_checks": sum(len(v) for v in gg.values()),
                        "identical": sum(1 for v in gg.values() for r in v if r["identical"])}
    return out


def r3_beta(source: str) -> str:
    return "%g" % nl.read_json(r3.GRID)["sources"][source]["beta_m"]


def compute() -> dict:
    designs = list(nl.DESIGN_ORDER)
    pilot_free = [d for d in designs if d not in PILOT]
    res: dict = {"H8": h8(designs), "H10a": h10a(designs), "H11": h11(designs)}
    # fix entry 2026-10-25: the n=11 pass for H8 and H10a too (they use stock packings only, so the pilot,
    # which only chose beta, cannot move them; reported, the primary status stays the n=15 one)
    res["H8"]["no_pilot"] = h8(pilot_free)
    res["H10a"]["no_pilot"] = h10a(pilot_free, math.ceil(12 / 15 * len(pilot_free)))  # 12 of 15 scaled: not registered
    gate_path = nl.DATA / "analysis" / "r3-gate.json"
    if gate_path.is_file():
        gate = nl.read_json(gate_path)
        res["gate"] = {"designs": len(gate),
                       "all_identical": all(r["identical"] for rows in gate.values() for r in rows),
                       "n_checks": sum(len(rows) for rows in gate.values())}
    res["fix"] = fixes(designs)
    grid_path = r3.GRID
    if grid_path.is_file():
        grid = nl.read_json(grid_path)
        res["grid"] = grid
        needed = [(c[0], st) for c in r3.configs() for st in ("analytic", "seed")]
        done = designs_done(designs, needed)
        res["designs_done"] = done
        res["checkpoint_only"] = len(done) < len(designs)
        if len(done) >= 5:
            res.update(h9(grid, done))
            res["secondary"] = secondary(grid, done)
            res["seed_noise"] = seed_noise(done)
    return res


def main(argv: list[str]) -> int:
    res = compute()
    nl.write_json(RESULT, res)
    print(json.dumps({k: (v if k in ("H8", "H10a", "H11", "gate") else "...") for k, v in res.items()}, indent=1, default=str)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
