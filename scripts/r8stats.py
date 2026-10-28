"""H22' re-run statistics (decision rules of docs/plan/round8-h22.md). Needs scipy (the Loki venv python, $NR_PY).

  python scripts/r8stats.py   reads $NORNS_DATA/r8/keep.json + runs.jsonl (and the committed data/r6 for H37 per level),
                              writes data/analysis/r8-results.json and prints the tables of the results section.
"""

from __future__ import annotations

import json
import math
import statistics
import sys

import nornlib as nl
import r5lib as rl  # noqa: F401  (puts gen/ on sys.path)
import r5stats as s5
import r6stats as s6
import r8gen

METRICS = {"WL": "wirelength", "CLB": "logic_clbs", "CPD": "cpd_ns"}
WIDTHS = r8gen.WIDTHS
HEADROOM = ("mesh", "tree")


def load(data) -> tuple[dict, dict]:
    keep = nl.read_json(data / "keep.json")
    runs: dict = {}
    for line in (data / "runs.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["rc"] == 0:
                runs[(r["design"], r["arm"], r["vseed"])] = r
    return keep, runs


def per_design(keep: dict, runs: dict, arm: str, ref: str, metric: str, names) -> dict[str, float]:
    """design -> ln of the geometric mean over matched seeds (>= 2) of arm / ref, kept designs in `names`."""
    out = {}
    for d in names:
        if not keep.get(d, {}).get("kept"):
            continue
        ls = []
        for s in (1, 2, 3):
            a, r = runs.get((d, arm, s)), runs.get((d, ref, s))
            if a and r and a.get(METRICS[metric]) and r.get(METRICS[metric]):
                ls.append(math.log(a[METRICS[metric]] / r[METRICS[metric]]))
        if len(ls) >= 2:
            out[d] = sum(ls) / len(ls)
    return out


def decide_widths(logs_by_w: dict[int, list[float]]) -> dict:
    """The round-6 benefit rule (CONFIRMED = supported), Holm over the widths."""
    res = s6.decide_benefit(logs_by_w)
    for v in res.values():
        v["verdict"] = {"supported": "CONFIRMED", "not supported": "NOT CONFIRMED"}.get(v["status"], "INCONCLUSIVE")
    return res


def chain_control(logs: list[float]) -> dict:
    r = s6.ratio_summary(logs)
    r["inside_0.98_1.02"] = bool(logs) and 0.98 <= r["gmean"] <= 1.02
    return r


def analyse() -> dict:
    keep, runs = load(nl.DATA / "r8")
    names = r8gen.names()
    sel = lambda topos, w: [d for d in names if r8gen.parse_name(d)[0] in topos and r8gen.parse_name(d)[1] == w]  # noqa: E731
    res: dict = {"kept": {"main": sum(1 for d in names if keep.get(d, {}).get("kept")), "of": len(names)}}
    res["purity"] = {}
    for t in r8gen.TOPOLOGIES:
        for w in WIDTHS:
            v = [keep[d]["word_purity"] for d in sel((t,), w) if keep.get(d, {}).get("kept")]
            res["purity"][f"{t}_w{w}"] = {"n": len(v), "median": statistics.median(v) if v else None,
                                          "min": min(v) if v else None, "max": max(v) if v else None}
    for m in METRICS:
        pd = {w: per_design(keep, runs, "norns", "stock", m, sel(HEADROOM, w)) for w in WIDTHS}
        res[f"test_{m}"] = decide_widths({w: list(v.values()) for w, v in pd.items()})
        cd = {w: per_design(keep, runs, "norns", "stock", m, sel(("chain",), w)) for w in WIDTHS}
        res[f"chain_{m}"] = {str(w): chain_control(list(v.values())) for w, v in cd.items()}
        for t in HEADROOM:
            res[f"topo_{t}_{m}"] = {str(w): s6.ratio_summary(list(per_design(keep, runs, "norns", "stock", m, sel((t,), w)).values()))
                                    for w in WIDTHS}
    res["known_over_stock_WL"] = {str(w): s6.ratio_summary(list(per_design(keep, runs, "known", "stock", "WL", sel(HEADROOM, w)).values()))
                                  for w in WIDTHS}
    ctl = [f"r6_chain_a100_{b}" for b in r8gen.SIZES]
    k6 = nl.read_json(nl.DATA / "r8" / "keep.json")
    res["control_ii_chain_a100"] = {m: chain_control(list(per_design(k6, runs, "norns", "stock", m, ctl).values())) for m in METRICS}
    return res


def h37_per_level() -> dict:
    """H37 restated per designed alignment level from the committed round-6 data (chain, norns / stock WL, n per level)."""
    keep = nl.read_json(nl.REPO_NORNS / "data" / "r6" / "keep.json")
    runs: dict = {}
    for line in (nl.REPO_NORNS / "data" / "r6" / "runs.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["rc"] == 0:
                runs[(r["design"], r["arm"], r["vseed"])] = r
    out = {}
    for lv in (0, 25, 50, 75, 100):
        names = [f"r6_chain_a{lv}_{b}" for b in s6.r6gen.SIZES]
        pd = per_design(keep, runs, "norns", "stock", "WL", names)
        r = s6.ratio_summary(list(pd.values()))
        r["median_word_purity"] = statistics.median([keep[d]["word_purity"] for d in pd]) if pd else None
        out[str(lv)] = r
    return out


def fmt(r: dict) -> str:
    return f"{r['gmean']:.3f} [{r['ci90'][0]:.3f}, {r['ci90'][1]:.3f}] n={r['n']}"


def main() -> int:
    res = analyse()
    res["h37_per_level"] = h37_per_level()
    out = nl.REPO_NORNS / "data" / "analysis" / "r8-results.json"
    nl.write_json(out, res)
    print(f"kept {res['kept']}")
    for m in METRICS:
        for w in WIDTHS:
            t = res[f"test_{m}"][str(w)]
            c = res[f"chain_{m}"][str(w)]
            print(f"{m} w={w}: mesh+tree {fmt(t)} p={t['p']:.4f} holm={t['p_holm']:.4f} {t['verdict']} | chain {fmt(c)} "
                  f"in_band={c['inside_0.98_1.02']}")
    for lv, r in res["h37_per_level"].items():
        print(f"H37 a={lv}: chain WL norns/stock {fmt(r)} word purity median {r['median_word_purity']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
