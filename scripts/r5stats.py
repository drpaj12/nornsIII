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
PERM_REPS = 10000  # registered (protocol H21); an earlier draft ran 2000 (dated entry (f))
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
        reps = PERM_REPS
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
    growth_cells: dict[tuple, dict] = {}
    for level, packers in (("HDL", ("stock", "norns")), ("NL", ("stock",))):
        for pk in packers:
            logs = {m: per_design(keep, runs, level, pk, "known", m) for m in ("CLB", "WL", "CPD")}
            res[f"room_{level}_{pk}"] = decide_room({m: list(v.values()) for m, v in logs.items()})
            big = {m: [v for d, v in logs[m].items() if meta(d)[2] >= 32] for m in logs}
            res[f"room_{level}_{pk}_B32"] = decide_room(big)
            for m in ("W", "CUT"):
                v = list(per_design(keep, runs, level, pk, "known", m).values())
                res[f"report_{level}_{pk}_{m}"] = {"n": len(v), "gmean": gmean_ratio(v)}
            for m in ("CLB", "WL"):
                growth_cells[(level, pk, m)] = {}
                for d, v in logs[m].items():
                    topo, style, b, _ = meta(d)
                    growth_cells[(level, pk, m)].setdefault(f"{topo}_{style}", []).append((b, v))
            res[f"gap_by_size_{level}_{pk}"] = {
                m: {str(b): gmean_ratio([v for d, v in logs[m].items() if meta(d)[2] == b])
                    for b in sorted({meta(d)[2] for d in logs[m]})} for m in logs}
        reps = [r["reproduction"] for (d, arm, s), r in runs.items()
                if arm == "known" and meta(d)[3] == level and keep.get(d, {}).get("kept")]
        res[f"repro_{level}"] = decide_repro(reps)
    # H21: Holm over the registered 4 tests (2 packers x 2 metrics); H26: Holm over its 2 tests (NL, stock)
    joint = decide_growth({f"{pk}_{m}": growth_cells[("HDL", pk, m)] for pk in ("stock", "norns") for m in ("CLB", "WL")})
    for pk in ("stock", "norns"):
        res[f"growth_HDL_{pk}"] = {m: joint[f"{pk}_{m}"] for m in ("CLB", "WL")}
    res["growth_NL_stock"] = decide_growth({m: growth_cells[("NL", "stock", m)] for m in ("CLB", "WL")})
    # H28 / H18 literal pre-data rules and labelled variants
    nlk = [d for d in keep if meta(d)[3] == "NL"]
    res["keep_NL_literal"] = decide_keep({d: nl_literal_pass(keep[d]) for d in nlk}, cell_of)
    for thr in (0.05,):
        res[f"keep_NL_slack{int(thr * 100)}"] = decide_keep({d: nl_literal_pass(keep[d], slack=thr) for d in nlk}, cell_of)
    res["local_search"] = local_search_summary(keep)
    # variants on the literal-pass NL subset (H25 and H26 as the pre-data entry (b) rule would have decided them)
    lit = {d: k for d, k in keep.items() if meta(d)[3] != "NL" or nl_literal_pass(k)}
    logs_l = {m: per_design(lit, runs, "NL", "stock", "known", m) for m in ("CLB", "WL", "CPD")}
    res["room_NL_stock_literal_subset"] = decide_room({m: list(v.values()) for m, v in logs_l.items()})
    # H19/H20/H25 per topology (labelled variant of the registered rule)
    for level, pk in (("NL", "stock"), ("HDL", "stock"), ("HDL", "norns")):
        lg = {m: per_design(keep, runs, level, pk, "known", m) for m in ("CLB", "WL", "CPD")}
        res[f"room_by_topology_{level}_{pk}"] = {
            t: decide_room({m: [v for d, v in lg[m].items() if meta(d)[0] == t] for m in lg})
            for t in ("chain", "mesh", "tree", "rand")}
    # H22 variant: fraction of the gap closed on designs with r_stock >= 1.03
    res["gap_closed_HDL"] = gap_closed(keep, runs)
    res["leak_HDL"] = leak(keep, runs)
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
    res["h23"].update(h23_ceiling(keep, runs, gain))
    res["purity_gain_mean"] = {st: (sum(v for d, v in gain.items() if meta(d)[1] == st) /
                                    max(1, sum(1 for d in gain if meta(d)[1] == st))) for st in ("dp", "ctl")}
    res["attribution"] = attribution(keep)
    res["exploratory_topology_gap"] = topology_gap(keep, runs)
    return res


def nl_literal_pass(k: dict, slack: float | None = None) -> bool:
    """Netlist check of dated entry (b), the pre-data rule: zero improving swaps (and the other items k1 to k5). With `slack`
    the entry (c) rule at that bound is used instead (entry (c) itself uses 0.10)."""
    base = k["k1"] and k["k2"] and k["k3"] and k["k4"] and k["k5_move"]
    if slack is None:
        return bool(base and k["swap_violations"] == 0)
    return bool(base and k["slack"] <= slack)


def local_search_summary(keep: dict) -> dict:
    nlk = {d: k for d, k in keep.items() if d.startswith("n5_")}
    sl = sorted(k["slack"] for k in nlk.values())
    return {"n": len(nlk), "converged_within_cap": sum(k["ls_converged_within_cap"] for k in nlk.values()),
            "max_rounds": max(k["ls_rounds"] for k in nlk.values()),
            "slack_min": sl[0], "slack_median": statistics.median(sl), "slack_max": sl[-1],
            "slack_converged_max": max(k["slack_converged"] for k in nlk.values()),
            "slack_le5": sum(x <= 0.05 for x in sl), "slack_le10": sum(x <= 0.10 for x in sl),
            "swap_zero": sum(k["swap_violations"] == 0 for k in nlk.values()),
            "restart_designs": sum("search_best" in k for k in nlk.values()),
            "search_best_min_gap": min(k["search_best"] - k["cut"] for k in nlk.values() if "search_best" in k),
            "search_smaller": sum(bool(k.get("search_found_smaller")) for k in nlk.values()),
            "search_best_range": [min(k["search_best"] for k in nlk.values() if k["b"] == 8 if "search_best" in k),
                                  max(k["search_best"] for k in nlk.values() if k["b"] == 8 if "search_best" in k)],
            "block_cut_b8_range": [min(k["cut"] for k in nlk.values() if k["b"] == 8),
                                   max(k["cut"] for k in nlk.values() if k["b"] == 8)]}


def gap_closed(keep: dict, runs: dict) -> dict:
    """EXPLORATORY variant of H22: (r_stock - r_norns) / (r_stock - 1) per design with r_stock >= 1.03 (r = ratio to known)."""
    out: dict = {}
    for m in ("CLB", "WL", "CPD"):
        st = per_design(keep, runs, "HDL", "stock", "known", m)
        nr = per_design(keep, runs, "HDL", "norns", "known", m)
        vals = []
        for d, ls in st.items():
            rs = math.exp(ls)
            if rs >= 1.03 and d in nr:
                vals.append((rs - math.exp(nr[d])) / (rs - 1))
        out[m] = {"n": len(vals), "mean": sum(vals) / len(vals) if vals else float("nan"),
                  "median": statistics.median(vals) if vals else float("nan")}
    return out


def leak(keep: dict, runs: dict) -> dict:
    """Per style, HDL level: designs whose norns .net equals the stock .net on all three seeds, and mean purity of both arms."""
    out: dict = {}
    for st in ("dp", "ctl"):
        ds = [d for d, k in keep.items() if k["kept"] and meta(d)[3] == "HDL" and meta(d)[1] == st]
        same = 0
        pn, ps, n = 0.0, 0.0, 0
        for d in ds:
            a = [runs.get((d, "norns", s)) for s in (1, 2, 3)]
            b = [runs.get((d, "stock", s)) for s in (1, 2, 3)]
            if not all(a) or not all(b):
                continue
            same += all(x["net_sha256"] == y["net_sha256"] for x, y in zip(a, b))
            pn += sum(x["purity"] for x in a) / 3
            ps += sum(x["purity"] for x in b) / 3
            n += 1
        out[st] = {"designs": n, "net_equal_stock": same, "purity_norns": pn / n if n else float("nan"),
                   "purity_stock": ps / n if n else float("nan")}
    return out


def h23_ceiling(keep: dict, runs: dict, gain: dict) -> dict:
    """The ceiling of H23: pairs with d = 0 and the mean headroom (1 - stock purity of the dp design) against the 0.05 threshold."""
    zero, head, dd = 0, [], []
    for d in gain:
        topo, style, b, _ = meta(d)
        other = f"r5_{topo}_ctl_{b}"
        if style == "dp" and other in gain:
            dd.append(gain[d] - gain[other])
            zero += (gain[d] - gain[other]) == 0
            head.append(1 - runs[(d, "stock", 1)]["purity"])
    return {"pairs_zero": zero, "mean_headroom": sum(head) / len(head) if head else float("nan"),
            "mean_d": sum(dd) / len(dd) if dd else float("nan")}


def attribution(keep: dict) -> dict:
    """CPD cross-check (VPR against the Odin III attribution, 0.5% tolerance) and the share of member-member hops of the
    reported critical paths that cross CLBs, per level and arm."""
    import r5lib as rl
    out: dict = {}
    for d, k in keep.items():
        if not k["kept"]:
            continue
        for arm in ("stock", "norns", "known"):
            for s in (1, 2, 3):
                p = nl.runs_dir(d, "r5", f"{arm}.s{s}", "metrics.json")
                if not p.is_file():
                    continue
                r = nl.read_json(p)
                if r.get("rc") != 0 or "attr_cpd_ns" not in r:
                    continue
                o = out.setdefault(f"{meta(d)[3]}_{arm}", {"runs": 0, "disagree": 0, "hops": 0, "crossing": 0})
                o["runs"] += 1
                o["disagree"] += abs(r["attr_cpd_ns"] - r["cpd_ns"]) > 0.005 * r["cpd_ns"]
                o["hops"] += r.get("path_hops", 0)
                o["crossing"] += r.get("path_hops_crossing", 0)
    for o in out.values():
        o["crossing_share"] = o["crossing"] / o["hops"] if o["hops"] else float("nan")
    del rl
    return out


def topology_gap(keep: dict, runs: dict) -> dict:
    """EXPLORATORY (dated entry (e) of the protocol): geometric-mean ratio to the known clustering per topology; no status."""
    out: dict = {}
    for level, arm in (("NL", "stock"), ("HDL", "stock"), ("HDL", "norns")):
        for m in ("WL", "CLB", "CPD"):
            by: dict[str, list[float]] = {}
            for d, v in per_design(keep, runs, level, arm, "known", m).items():
                by.setdefault(meta(d)[0], []).append(v)
            out[f"{level}_{arm}_{m}"] = {t: gmean_ratio(v) for t, v in sorted(by.items())}
    return out


def main() -> int:
    res = analyse()
    nl.write_json(nl.DATA / "analysis" / "r5-results.json", res)
    for k, v in sorted(res.items()):
        if isinstance(v, dict) and "status" in v:
            print(k, v["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
