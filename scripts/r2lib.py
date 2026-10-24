"""Round-2 numbers: every figure of the round-2 paper text and EXPERIMENT.md comes from here.

Reads data/<design>/runs.jsonl, data/<design>/words.json, data/<design>/crossover/xover-*.json
and data/analysis/{n1,n2}.json. Ratio convention as report.py: variant / unseeded baseline, below
1 is better. Paired comparisons are per design (variant A / variant B), reported as the
geomean ratio, the number of designs where A is better, and a two-sided exact sign-test p.
"""

from __future__ import annotations

import math
import statistics

import nornlib as nl
import report
import r2_best

NEW = r2_best.NEW
ROUND1 = report.FAMILIES


def rec(data, design, fam, var="full"):
    return report.pick(data[design], "soft", fam, var)


def paired(data, designs, a, b, metric="wirelength"):
    """a, b = (family, variant). Per-design ratios a/b over the designs where both exist."""
    vals = []
    for d in designs:
        r = report.ratio(rec(data, d, *a), rec(data, d, *b), metric)
        if r is not None:
            vals.append(r)
    wins = sum(1 for v in vals if v < 1)
    losses = sum(1 for v in vals if v > 1)
    return {"n": len(vals), "gm": nl.geomean(vals) if vals else float("nan"), "wins": wins,
            "ties": len(vals) - wins - losses, "p": sign_p(wins, wins + losses)}


def sign_p(k: int, n: int) -> float:
    if n == 0:
        return float("nan")
    from scipy import stats
    return float(stats.binomtest(k, n, 0.5).pvalue)


def vs_base(data, designs, fam, var="full", tag=None):
    """Geomean ratios vs the baseline for one soft arm (tag overrides the family/variant)."""
    cols = {m: [] for m in (*report.METRICS, "init_t")}
    n = wins = 0
    for d in designs:
        base = report.pick(data[d], "baseline")
        run = rec(data, d, fam, var)
        if run is None:
            continue
        n += 1
        for m in (*report.METRICS, "init_t"):
            r = report.ratio(run, base, m)
            if r is not None:
                cols[m].append(r)
        r = report.ratio(run, base, "wirelength")
        if r is not None and r < 1:
            wins += 1
    return {"n": n, "wins": wins, **{m: nl.geomean(cols[m]) if cols[m] else float("nan")
                                     for m in (*report.METRICS, "init_t")}}


def coverage(designs):
    rows = []
    for d in designs:
        p = nl.DATA / d / "words.json"
        if p.is_file():
            rows.append(nl.read_json(p))
    return rows


def hyp_status(gm, p, better_is_lower=True):
    if math.isnan(gm):
        return "inconclusive"
    if gm < 1 and p < 0.05:
        return "supported"
    if gm >= 1:
        return "not supported"
    return "inconclusive"


def compute() -> dict:
    data, all_designs = report.load_all()
    designs = r2_best.round2_designs(data, all_designs)
    out: dict = {"designs": designs, "n_designs": len(designs), "n_all": len(all_designs)}
    best = r2_best.best_family()
    out["best"] = best
    out["best_now"] = r2_best.current_best()
    out["best_n"] = (len(nl.read_json(r2_best.FROZEN)["designs"]) if r2_best.FROZEN.is_file()
                     else len(designs))
    fams = {"urd": ("urd", "full")}
    for f in ROUND1:
        fams[f] = (f, "full")
    for f in NEW:
        fams[f] = (f, "full")
    out["vs_base"] = {f: vs_base(data, designs, *fv) for f, fv in fams.items()}
    out["vs_base"]["words_inter"] = vs_base(data, designs, "words", "inter")
    out["vs_base"]["random"] = vs_base(data, designs, "random")
    out["vs_base"]["urd_shuf"] = vs_base(data, designs, "urd_shuf")
    if best:
        out["vs_base"][f"{best}_shuf"] = vs_base(data, designs, f"{best}_shuf")
    cov = coverage(designs)
    out["coverage"] = cov
    tot = sum(c["blocks"] for c in cov) or 1
    out["coverage_all"] = {
        "blocks": sum(c["blocks"] for c in cov),
        "in_word": sum(c["blocks_in_word"] for c in cov),
        "ff_total": sum(c["kind_total"]["ff"] for c in cov),
        "ff_word": sum(c["by_kind"]["ff"] for c in cov),
        "lut_total": sum(c["kind_total"]["lut"] for c in cov),
        "lut_word": sum(c["by_kind"]["lut"] for c in cov),
        "hard_total": sum(c["kind_total"]["hard"] for c in cov),
        "hard_word": sum(c["by_kind"]["hard"] for c in cov),
        "median_share": statistics.median([c["blocks_in_word"] / c["blocks"] for c in cov]) if cov else None,
        "identical": all(c["blif_identical"] for c in cov) if cov else None,
        "unjoined": sum(c["unjoined_cells"] for c in cov),
        "words": sum(c["words"] for c in cov),
        "max_line_group": [max(c["line_groups_largest"][0] for c in cov)] if cov else None,
        "lines": sum(c.get("statement_lines", 0) for c in cov),
        "lines_multi": sum(c.get("lines_with_several_words", 0) for c in cov),
        "max_words_line": max((c.get("max_words_on_line", 0) for c in cov), default=0),
    }
    h: dict = {}
    # H7a words vs urd; H7b slices vs words (wl, chan); H7c rank of hier; H7d partial vs words
    a = paired(data, designs, ("words", "full"), ("urd", "full"))
    h["H7a"] = {**a, "status": hyp_status(a["gm"], a["p"])}
    b = paired(data, designs, ("slices", "full"), ("words", "full"))
    bc = paired(data, designs, ("slices", "full"), ("words", "full"), "chan_width")
    if math.isnan(b["gm"]):
        st = "inconclusive"
    elif b["gm"] >= 1:
        st = "not supported"
    elif b["p"] < 0.05 and bc["gm"] < 1:
        st = "supported"
    else:
        st = "inconclusive"
    h["H7b"] = {**b, "chan_gm": bc["gm"], "chan_wins": bc["wins"], "chan_n": bc["n"],
                "status": st}
    ranks = sorted(((v["wirelength"], f) for f, v in out["vs_base"].items()
                    if f in fams and v["n"] == len(designs)), key=lambda x: x[0])
    names = [f for _g, f in ranks]
    h["H7c"] = {"rank": names.index("hier") + 1 if "hier" in names else None,
                "of": len(names), "best_name": names[0] if names else None,
                "hier_gm": out["vs_base"]["hier"]["wirelength"],
                "best_gm": ranks[0][0] if ranks else float("nan"),
                "status": "supported" if names and names[0] == "hier" else "not supported"}
    d_ = paired(data, designs, ("words_partial", "full"), ("words", "full"))
    if math.isnan(d_["gm"]):
        st = "inconclusive"
    elif d_["gm"] <= 1.0:
        st = "supported"
    elif d_["gm"] <= 1.01:
        st = "inconclusive"
    else:
        st = "not supported"
    h["H7d"] = {**d_, "status": st}
    # H4: random > shuffled > quotient >= analytic, for Urd and for the best word family
    chain = {}
    for name, (rnd, shuf, quo) in {"urd": ("random", "urd_shuf", "urd"),
                                   "best": ("random", f"{best}_shuf" if best else "", best or "")}.items():
        vals = {k: out["vs_base"].get(k, {}).get("wirelength", float("nan"))
                for k in (rnd, shuf, quo)}
        chain[name] = {"random": vals[rnd], "shuffled": vals[shuf], "quotient": vals[quo],
                       "holds": (vals[rnd] > vals[shuf] > vals[quo] >= 1.0)
                       if not any(math.isnan(v) for v in vals.values()) else None}
    h["H4"] = chain
    holds = [c["holds"] for c in chain.values() if c["holds"] is not None]
    h["H4"]["status"] = ("supported" if holds and all(holds) else
                         "not supported" if holds and not any(holds) else "inconclusive")
    out["hyp"] = h
    same = {}
    for name, (x, y) in {"slices_words": (("slices", "full"), ("words", "full")),
                         "hier_urd": (("hier", "full"), ("urd", "full")),
                         "partial_words": (("words_partial", "full"), ("words", "full"))}.items():
        same[name] = [d for d in designs if rec(data, d, *x) and rec(data, d, *y)
                      and rec(data, d, *x).get("wirelength") == rec(data, d, *y).get("wirelength")
                      and rec(data, d, *x).get("chan_width") == rec(data, d, *y).get("chan_width")]
    out["same"] = same
    # N1
    n1p = nl.DATA / "analysis" / "n1.json"
    if n1p.is_file():
        n1 = nl.read_json(n1p)
        agg = {}
        for lab in ("module", "word"):
            rows = [r[lab] for r in n1["designs"]
                    if r[lab]["labels"] >= 2 and not math.isnan(r[lab]["final"][0])]
            z = [(r["final"][0] - r["null_nmi_mean"]) / r["null_nmi_sd"]
                 for r in rows if r["null_nmi_sd"] > 0]
            agg[lab] = {
                "n": len(rows),
                "nmi_final": statistics.median([r["final"][0] for r in rows]) if rows else None,
                "nmi_initial": statistics.median([r["initial"][0] for r in rows]) if rows else None,
                "nmi_null": statistics.median([r["null_nmi_mean"] for r in rows]) if rows else None,
                "dens_final": statistics.median([r["final"][1] for r in rows]) if rows else None,
                "dens_initial": statistics.median([r["initial"][1] for r in rows]) if rows else None,
                "dens_null": statistics.median([r["null_density_mean"] for r in rows]) if rows else None,
                "above_null": sum(1 for x in z if x > 2), "n_z": len(z),
                "dens_above_null": sum(1 for r in rows if r["null_density_sd"] > 0 and
                                       (r["final"][1] - r["null_density_mean"])
                                       / r["null_density_sd"] > 2),
                "final_ge_initial": sum(1 for r in rows if r["final"][0] >= r["initial"][0]),
            }
        out["n1"] = agg
        def share(a, key):
            return a[key] / a["n_z"] if a["n_z"] else 0.0
        ok = all(share(a, "above_null") >= 2 / 3 and share(a, "dens_above_null") >= 2 / 3
                 for a in agg.values())
        none = all(share(a, "above_null") < 1 / 3 and share(a, "dens_above_null") < 1 / 3
                   for a in agg.values())
        h["H1"] = {"status": "supported" if ok else "not supported" if none else "inconclusive"}
    n2p = nl.DATA / "analysis" / "n2.json"
    if n2p.is_file():
        n2 = nl.read_json(n2p)
        out["n2"] = n2
        sp = n2["spearman"]
        pos = [k for k, v in sp.items() if k.startswith("best_r2~") and v["rho"] > 0 and v["p"] < 0.05]
        anypos = [k for k, v in sp.items() if v["rho"] > 0 and v["p"] < 0.05]
        neg = [k for k, v in sp.items() if v["rho"] < 0 and v["p"] < 0.05]
        h["H2"] = {"status": "supported" if len(pos) >= 2 else
                   "not supported" if not anypos else "inconclusive",
                   "n_sig": len(anypos) + len(neg), "n_pos": len(anypos), "n_neg": len(neg),
                   "neg": neg, "n_pairs": len(sp)}
    h.setdefault("H1", {"status": "not run"})
    h.setdefault("H2", {"status": "not run", "n_sig": 0, "n_pos": 0, "n_neg": 0, "n_pairs": 0})
    # hard arm and crossover of the best family
    if best:
        hv = []
        for d in designs:
            r = report.ratio(report.pick(data[d], "hard", best), report.pick(data[d], "baseline"),
                             "wirelength")
            if r is not None:
                hv.append(r)
        failed = []
        for d in designs:
            latest = {}
            for r in report.load_records(d):
                latest[str(r.get("tag"))] = r
            r = latest.get(f"hard-{best}")
            if r is not None and r.get("rc") != 0:
                failed.append(d)
        out["hard_best"] = {"n": len(hv), "gm": nl.geomean(hv) if hv else float("nan"),
                            "wins": sum(1 for v in hv if v < 1), "failed": failed}
        xs, r1s, rets, hotw, hotn = [], [], [], 0, 0
        for d in designs:
            p = nl.data_crossover(d, f"xover-{best}.json")
            q = nl.data_crossover(d, "crossover.json")
            if not (p.is_file() and q.is_file()):
                continue
            res, r1 = nl.read_json(p), nl.read_json(q)
            if res.get("crossover_scale") is None or r1.get("crossover_scale") is None:
                continue
            xs.append(float(res["crossover_scale"]))
            r1s.append(float(r1["crossover_scale"]))
            hs = float(res["crossover_scale"]) * 2
            hot = next((r for r in data[d] if r.get("tag") == f"hot-r2-{best}-{hs:g}"), None)
            un = report.pick(data[d], "unseeded", scale=hs)
            if hot and hot.get("retention") is not None:
                rets.append(float(hot["retention"]))
            if hot and un and hot.get("wirelength") and un.get("wirelength"):
                hotn += 1
                hotw += 1 if float(hot["wirelength"]) < float(un["wirelength"]) else 0
        out["xover"] = {"n": len(xs), "median": statistics.median(xs) if xs else None,
                        "r1_median": statistics.median(r1s) if r1s else None,
                        "ge_r1": sum(1 for a, b in zip(xs, r1s) if a >= b),
                        "hot_ret_median": statistics.median(rets) if rets else None,
                        "hot_wins": [hotw, hotn]}
    return out


def f3(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def f2(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def pfmt(p):
    return "n/a" if p is None or (isinstance(p, float) and math.isnan(p)) else (
        "<0.001" if p < 0.001 else f"{p:.3f}")
