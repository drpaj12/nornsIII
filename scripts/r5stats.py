"""Round-5 statistics (decision rules of docs/plan/round5.md). Needs scipy (the Loki venv python, $NR_PY).

  python scripts/r5stats.py        reads data/r5/runs.jsonl and keep.json, writes data/analysis/r5-results.json
"""

from __future__ import annotations

import math
import random
import statistics
import sys

import nornlib as nl

BOOT_SEED = 20261026
N_BOOT = 10000
METRICS = {"CLB": "logic_clbs", "WL": "wirelength", "CPD": "cpd_ns", "W": "chan_width", "CUT": "cut"}
MIN_N = 12
MIN_CELLS = 6


def wilcoxon_p(values: list[float], alternative: str) -> float:
    """One-sided Wilcoxon signed-rank (zero differences dropped; fewer than 6 non-zero -> 1.0, as the protocol)."""
    from scipy.stats import wilcoxon
    nz = [v for v in values if v != 0]
    if len(nz) < 6:
        return 1.0
    p = float(wilcoxon(nz, alternative=alternative).pvalue)
    return 1.0 if math.isnan(p) else p


def holm(ps: list[float]) -> list[float]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out = [1.0] * len(ps)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        out[i] = run
    return out


def boot_ci(values: list[float], lo: float = 0.05, hi: float = 0.95) -> tuple[float, float]:
    rnd = random.Random(BOOT_SEED)
    n = len(values)
    means = sorted(sum(values[rnd.randrange(n)] for _ in range(n)) / n for _ in range(N_BOOT))
    return means[int(lo * N_BOOT)], means[int(hi * N_BOOT) - 1]


def gmean_ratio(logs: list[float]) -> float:
    return math.exp(sum(logs) / len(logs)) if logs else float("nan")


def decide_room(logs_by_metric: dict[str, list[float]]) -> dict:
    """H19/H20/H25: ratio of a packer to the known clustering. Supported iff gm >= 1.05 and Holm p (one-sided r > 1) < 0.05;
    not supported iff gm <= 1.02 or the 90% interval of the mean log ratio lies inside [log 0.98, log 1.02]."""
    ms = sorted(logs_by_metric)
    ps = [wilcoxon_p(logs_by_metric[m], "greater") for m in ms]
    adj = holm(ps)
    out = {}
    for m, p, pa in zip(ms, ps, adj):
        v = logs_by_metric[m]
        n = len(v)
        gm = gmean_ratio(v)
        ci = boot_ci(v) if n else (float("nan"), float("nan"))
        if n < MIN_N:
            status = "inconclusive (n too small)"
        elif gm >= 1.05 and pa < 0.05:
            status = "supported"
        elif gm <= 1.02 or (ci[0] >= math.log(0.98) and ci[1] <= math.log(1.02)):
            status = "not supported"
        else:
            status = "inconclusive"
        out[m] = {"n": n, "gmean": gm, "p": p, "p_holm": pa, "ci90": [math.exp(ci[0]), math.exp(ci[1])], "status": status}
    return out


def decide_close(logs_by_metric: dict[str, list[float]]) -> dict:
    """H22: norns / stock. Supported iff gm <= 0.99 and Holm p (ratio < 1) < 0.05; not supported iff gm >= 1.00 or the 90%
    interval lies inside [0.98, 1.02]."""
    ms = sorted(logs_by_metric)
    ps = [wilcoxon_p(logs_by_metric[m], "less") for m in ms]
    adj = holm(ps)
    out = {}
    for m, p, pa in zip(ms, ps, adj):
        v = logs_by_metric[m]
        n = len(v)
        gm = gmean_ratio(v)
        ci = boot_ci(v) if n else (float("nan"), float("nan"))
        if n < MIN_N:
            status = "inconclusive (n too small)"
        elif gm <= 0.99 and pa < 0.05:
            status = "supported"
        elif gm >= 1.00 or (ci[0] >= math.log(0.98) and ci[1] <= math.log(1.02)):
            status = "not supported"
        else:
            status = "inconclusive"
        out[m] = {"n": n, "gmean": gm, "p": p, "p_holm": pa, "ci90": [math.exp(ci[0]), math.exp(ci[1])], "status": status}
    return out


def slope(xs: list[float], ys: list[float]) -> float:
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else float("nan")


def decide_growth(cells: dict[str, dict[str, list[tuple[int, float]]]]) -> dict:
    """H21/H26: cells[test][cell] = [(B, ln r)]. Per test: cells with >= 5 sizes; median slope of ln r on log2 B."""
    tests = sorted(cells)
    slopes = {}
    ps = []
    for t in tests:
        s = []
        for c, pts in sorted(cells[t].items()):
            if len(pts) >= 5:
                s.append(slope([math.log2(b) for b, _ in pts], [y for _, y in pts]))
        slopes[t] = s
        ps.append(wilcoxon_p(s, "greater") if len(s) >= MIN_CELLS else 1.0)
    adj = holm(ps)
    out = {}
    rnd = random.Random(BOOT_SEED)
    for t, p, pa in zip(tests, ps, adj):
        s = slopes[t]
        med = statistics.median(s) if s else float("nan")
        pos = sum(1 for x in s if x > 0)
        if len(s) < MIN_CELLS:
            status = "inconclusive (n too small)"
        elif med >= 0.01 and pos >= 6 and pa < 0.05:
            status = "supported"
        elif med <= 0.002:
            status = "not supported"
        else:
            status = "inconclusive"
        # permutation null: ln r permuted over the sizes of each cell, median slope at least the observed
        ge = 0
        reps = 2000
        for _ in range(reps):
            sl = []
            for c, pts in sorted(cells[t].items()):
                if len(pts) >= 5:
                    ys = [y for _, y in pts]
                    rnd.shuffle(ys)
                    sl.append(slope([math.log2(b) for b, _ in pts], ys))
            ge += bool(sl) and statistics.median(sl) >= med
        out[t] = {"cells": len(s), "median_slope": med, "positive_cells": pos, "p": p, "p_holm": pa,
                  "perm_p": ge / reps if s else float("nan"), "slopes": s, "status": status}
    return out


def decide_h23(d: list[float]) -> dict:
    n = len(d)
    med = statistics.median(d) if d else float("nan")
    p = wilcoxon_p(d, "greater")
    frac = sum(1 for x in d if x > 0) / n if n else float("nan")
    if n < MIN_N:
        status = "inconclusive (n too small)"
    elif med >= 0.05 and p < 0.05 and frac >= 0.70:
        status = "supported"
    elif med < 0.01:
        status = "not supported"
    else:
        status = "inconclusive"
    return {"n": n, "median": med, "p": p, "frac_positive": frac, "status": status}


def decide_keep(kept_flags: dict[str, bool], cell_of: dict[str, str]) -> dict:
    """H18 / H28: share kept and kept per cell."""
    n = len(kept_flags)
    share = sum(kept_flags.values()) / n if n else float("nan")
    cells: dict[str, int] = {}
    for d, k in kept_flags.items():
        cells[cell_of[d]] = cells.get(cell_of[d], 0) + bool(k)
    if share >= 0.90 and cells and min(cells.values()) >= 6:
        status = "supported"
    elif share < 0.70:
        status = "not supported"
    else:
        status = "inconclusive"
    return {"n": n, "kept": sum(kept_flags.values()), "share": share, "kept_per_cell": cells, "status": status}


def decide_repro(rates: list[float]) -> dict:
    n = len(rates)
    mean = sum(rates) / n if n else float("nan")
    full = sum(1 for r in rates if r >= 1.0) / n if n else float("nan")
    if mean >= 0.99 and full >= 0.90:
        status = "supported"
    elif mean < 0.90:
        status = "not supported"
    else:
        status = "inconclusive"
    return {"n": n, "mean": mean, "share_full": full, "status": status}


# ---------------------------------------------------------------------------------------
# data

def load() -> tuple[dict, dict]:
    import r5lib as rl
    keep = nl.read_json(rl.DATA5 / "keep.json")
    runs: dict = {}
    for r in rl.jsonl(rl.DATA5 / "runs.jsonl"):
        if r["rc"] == 0:
            runs[(r["design"], r["arm"], r["vseed"])] = r
    return keep, runs


def meta(design: str) -> tuple[str, str, int, str]:
    import r5gen
    topo, style, b = r5gen.parse_name("r5_" + design.split("_", 1)[1])
    return topo, style, b, ("NL" if design.startswith("n5_") else "HDL")


def per_design(keep: dict, runs: dict, level: str, arm: str, ref: str, metric: str) -> dict[str, float]:
    """design -> ln of the geometric mean over seeds of arm / ref, kept designs with all seeds of both arms."""
    out = {}
    key = METRICS[metric]
    for d, k in keep.items():
        if not k["kept"] or meta(d)[3] != level:
            continue
        ls = []
        for s in (1, 2, 3):
            a, r = runs.get((d, arm, s)), runs.get((d, ref, s))
            if not a or not r or not a.get(key) or not r.get(key):
                ls = []
                break
            ls.append(math.log(a[key] / r[key]))
        if ls:
            out[d] = sum(ls) / len(ls)
    return out


def analyse() -> dict:
    keep, runs = load()
    res: dict = {"n_designs": len(keep)}
    cell_of = {d: f"{meta(d)[0]}_{meta(d)[1]}" for d in keep}
    for level in ("HDL", "NL"):
        ds = [d for d in keep if meta(d)[3] == level]
        res[f"keep_{level}"] = decide_keep({d: keep[d]["kept"] for d in ds}, cell_of)
        if level == "HDL":
            res["keep_HDL_original_rule"] = decide_keep({d: keep[d].get("kept_original_rule", False) for d in ds}, cell_of)
    for level, packers in (("HDL", ("stock", "norns")), ("NL", ("stock",))):
        for pk in packers:
            logs = {m: per_design(keep, runs, level, pk, "known", m) for m in ("CLB", "WL", "CPD")}
            res[f"room_{level}_{pk}"] = decide_room({m: list(v.values()) for m, v in logs.items()})
            big = {m: [v for d, v in logs[m].items() if meta(d)[2] >= 32] for m in logs}
            res[f"room_{level}_{pk}_B32"] = decide_room(big)
            for m in ("W", "CUT"):
                v = list(per_design(keep, runs, level, pk, "known", m).values())
                res[f"report_{level}_{pk}_{m}"] = {"n": len(v), "gmean": gmean_ratio(v)}
            cells: dict[str, dict[str, list]] = {}
            for m in ("CLB", "WL"):
                cells[m] = {}
                for d, v in logs[m].items():
                    topo, style, b, _ = meta(d)
                    cells[m].setdefault(f"{topo}_{style}", []).append((b, v))
            res[f"growth_{level}_{pk}"] = decide_growth(cells)
            res[f"gap_by_size_{level}_{pk}"] = {
                m: {str(b): gmean_ratio([v for d, v in logs[m].items() if meta(d)[2] == b])
                    for b in sorted({meta(d)[2] for d in logs[m]})} for m in logs}
        reps = [r["reproduction"] for (d, arm, s), r in runs.items()
                if arm == "known" and meta(d)[3] == level and keep.get(d, {}).get("kept")]
        res[f"repro_{level}"] = decide_repro(reps)
    # H22 and H23 (HDL only)
    logs = {m: per_design(keep, runs, "HDL", "norns", "stock", m) for m in ("CLB", "WL", "CPD")}
    res["close_HDL"] = decide_close({m: list(v.values()) for m, v in logs.items()})
    res["close_HDL_by_style"] = {
        st: decide_close({m: [v for d, v in logs[m].items() if meta(d)[1] == st] for m in logs}) for st in ("dp", "ctl")}
    gain: dict[str, float] = {}
    for d, k in keep.items():
        if k["kept"] and meta(d)[3] == "HDL":
            a, b = runs.get((d, "norns", 1)), runs.get((d, "stock", 1))
            if a and b:
                gain[d] = a["purity"] - b["purity"]
                res.setdefault("null_purity_max", 0.0)
                res["null_purity_max"] = max(res["null_purity_max"], a["null_purity_max"], b["null_purity_max"])
    pairs = []
    for d in gain:
        topo, style, b, _ = meta(d)
        if style == "dp":
            other = f"r5_{topo}_ctl_{b}"
            if other in gain:
                pairs.append(gain[d] - gain[other])
    res["h23"] = decide_h23(pairs)
    res["purity_gain_mean"] = {st: (sum(v for d, v in gain.items() if meta(d)[1] == st) /
                                    max(1, sum(1 for d in gain if meta(d)[1] == st))) for st in ("dp", "ctl")}
    return res


def main() -> int:
    res = analyse()
    nl.write_json(nl.DATA / "analysis" / "r5-results.json", res)
    for k, v in sorted(res.items()):
        if isinstance(v, dict) and "status" in v:
            print(k, v["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
