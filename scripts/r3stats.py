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
    items = sorted(((p, k) for k, p in ps.items() if not math.isnan(p)))
    out: dict[str, float] = {k: float("nan") for k in ps}
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
            vals.append(a["clbs"] / b["clbs"] - 1)
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


def h10a(designs: list[str]) -> dict:
    rows = {d: nl.read_json(nl.DATA / d / "iowords.json") for d in designs}
    gain = [rows[d]["lut_cov_union"] - rows[d]["lut_cov_word"] for d in designs]
    med = statistics.median(gain)
    pos = sum(1 for g in gain if g > 0)
    if med >= 0.05 and pos >= 12:
        status = "supported"
    elif med < 0.01:
        status = "not supported"
    else:
        status = "inconclusive"
    return {"status": status, "median_gain": med, "positive": pos, "n": len(designs),
            "median_cov_word": statistics.median([rows[d]["lut_cov_word"] for d in designs]),
            "median_cov_union": statistics.median([rows[d]["lut_cov_union"] for d in designs])}


def h11(designs: list[str]) -> dict:
    out: dict = {}
    rows = {}
    for d in designs:
        p = nl.DATA / d / "n11.json"
        if p.is_file():
            rows[d] = nl.read_json(p)
    for rel in ("word", "module"):
        vals = [(d, r[f"d_{rel}"], r[f"d_{rel}_negative_seeds"]) for d, r in rows.items()
                if not math.isnan(r[f"d_{rel}"])]
        v = [x[1] for x in vals]
        if len(v) < 5:
            out[rel] = {"status": "inconclusive", "n": len(v)}
            continue
        med = statistics.median(v)
        p = wilcoxon(v, "less")
        consistent = sum(1 for x in vals if x[2] >= 2)
        need = math.ceil(12 / 15 * len(v))
        if med <= -0.05 and p < 0.05 and consistent >= need:
            status = "supported"
        elif med > -0.01:
            status = "not supported"
        else:
            status = "inconclusive"
        out[rel] = {"status": status, "n": len(v), "median_d": med, "p": p, "consistent": consistent,
                    "need": need, "excluded": sorted(set(rows) - {x[0] for x in vals})}
    st = [out[r]["status"] for r in ("word", "module")]
    out["status"] = "supported" if all(s == "supported" for s in st) else (
        "not supported" if all(s == "not supported" for s in st) else "inconclusive")
    stab = [r["stability"] for r in rows.values() if r.get("stability") is not None]
    nul = [r["stability_null"] for r in rows.values() if r.get("stability_null") is not None]
    out["stability"] = statistics.mean(stab) if stab else None
    out["stability_null"] = statistics.mean(nul) if nul else None
    out["n_designs"] = len(rows)
    return out


def secondary(grid: dict, designs: list[str]) -> dict:
    """Median ratios against stock for the headline configs (runtime, grid, chan width, CLB count)."""
    out: dict = {}
    for start in ("analytic", "seed"):
        for source in af.SOURCES:
            cfg = f"{source}-b{grid['sources'][source]['beta_m']:g}"
            row = {}
            for metric in ("wirelength", "chan_width", "cpd_ns", "pack_s", "flow_s", "clbs"):
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


def compute() -> dict:
    designs = list(nl.DESIGN_ORDER)
    res: dict = {"H8": h8(designs), "H10a": h10a(designs), "H11": h11(designs)}
    gate_path = nl.DATA / "analysis" / "r3-gate.json"
    if gate_path.is_file():
        gate = nl.read_json(gate_path)
        res["gate"] = {"designs": len(gate),
                       "all_identical": all(r["identical"] for rows in gate.values() for r in rows),
                       "n_checks": sum(len(rows) for rows in gate.values())}
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
