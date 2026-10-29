"""Heap-picking lane: runs P1 to P9 on the 45 census runs and writes data/analysis/heappick.json.

  PYTHONPATH=scripts python3 scripts/heappick_analyze.py --mimir DIR --sweep ROOT --census ROOT --runs PKL [--out data/analysis]

--runs is the pickle of heap_data.load_all (scripts/heap_data.py; work/heap-out/runs.pkl of the heap lane). Read only on all stores.
Summary rule (as in the heap lane): per design the mean over its 3 seeds, then the median over designs with a 90% percentile bootstrap.
"""
from __future__ import annotations

import argparse
import collections
import json
import pickle
from pathlib import Path

import heap_lib as hl
import heappick_data as pd
import heappick_lib as pl
import heappick_run as pr

CAUSES = ("full", "refused_pins", "refused_route", "queued_not_taken", "not_proposed", "unknown")


def by_design(results):
    d = collections.defaultdict(list)
    for r in results:
        d[r["design"]].append(r)
    return d


def design_values(results, f):
    """{design: mean over seeds of f(run result)}, None values skipped."""
    out = {}
    for d, rs in by_design(results).items():
        v = [f(r) for r in rs]
        v = [x for x in v if x is not None]
        out[d] = sum(v) / len(v) if v else None
    return out


def summarize(vals):
    """Median over designs with a 90% bootstrap interval; n = designs with a value."""
    m, lo, hi, n = hl.boot_median(list(vals.values()))
    return {"median": m, "lo90": lo, "hi90": hi, "n": n, "per_design": {k: v for k, v in sorted(vals.items())}}


def rate(a, b):
    return (a / b) if b else None


def summ(results, f):
    return summarize(design_values(results, f))


def pooled_counts(results, getter):
    """Per design, the sum over seeds of a Counter-like dict from getter(result)."""
    out = {}
    for d, rs in by_design(results).items():
        c = collections.Counter()
        for r in rs:
            for k, v in getter(r).items():
                c[k] += v
        out[d] = c
    return out


def source_line(bench, design, line):
    """Text of 'file.v:N' in the VTR benchmark source (stripped, 100 chars), '' when unavailable."""
    try:
        n = int(line.split(":")[1])
        return Path(bench, f"{design}.v").read_text(errors="replace").splitlines()[n - 1].strip()[:100]
    except (OSError, ValueError, IndexError, AttributeError):
        return ""


def analyze(runs, mimir, sweep, census, bench=None):
    designs = sorted({r["design"] for r in runs})
    res = []
    for d in designs:
        ex = pd.load_extra(mimir, sweep, census, [d])[d]
        for run in [x for x in runs if x["design"] == d]:
            hd_dir = Path(census) / d / f"s{run['seed']}"
            cen = pl.parse_census_full(hd_dir / "census.tsv")
            net = pl.parse_net_clusters(hd_dir / f"{d}.net")
            out, _ctx, _R, _Pk = pr.analyze_run(run, cen, net, ex)
            lst = out["p7"].pop("hf_list")
            if run["seed"] == 1:
                out["p7_nets"] = [{"atom": u, "fanout": f, "typ": run["atoms"][u]["typ"], "op": run["atoms"][u]["op"], "blk": run["atoms"][u]["blk"],
                                   "line": run["atoms"][u].get("line"), "text": source_line(bench, d, run["atoms"][u].get("line")) if bench else ""} for u, f in lst]
            res.append(out)
    return res


def summary(res):
    S = {}
    # P1
    S["p1"] = {
        "heap_picks_leave": summ(res, lambda r: rate(r["p1"]["heap_picks_leave"], r["p1"]["heap_picks"])),
        "seed_picks_leave": summ(res, lambda r: rate(r["p1"]["seed_leave"], r["p1"]["seed_heap"])),
        "cand_picks_leave": summ(res, lambda r: rate(r["p1"]["cand_leave"], r["p1"]["cand_heap"])),
        "heap_picks_share": summ(res, lambda r: rate(r["p1"]["heap_picks"], r["p1"]["n_picks"])),
        "route_heap_late": summ(res, lambda r: rate(r["p1"]["route_late"], r["p1"]["route_heap_n"])),
        "route_heap_gainless": summ(res, lambda r: rate(r["p1"]["route_gainless"], r["p1"]["route_heap_n"])),
        "route_heap_unrelated": summ(res, lambda r: rate(r["p1"]["route_unrelated"], r["p1"]["route_heap_n"])),
        "route_heap_pc_lt_050": summ(res, lambda r: rate(r["p1"]["route_lowpc"], r["p1"]["route_heap_n"])),
        "rho_pc_rc": summ(res, lambda r: r["p1"]["rho_pc_rc"]),
    }
    cats = pooled_counts(res, lambda r: {f"{k}|n": v[0] for k, v in r["p1"]["cats"].items()} | {f"{k}|s": v[1] for k, v in r["p1"]["cats"].items()})
    keys = sorted({k.split("|")[0] for c in cats.values() for k in c})
    stay = {}
    for k in keys:
        vals = {d: rate(c.get(k + "|s", 0), c.get(k + "|n", 0)) for d, c in cats.items() if c.get(k + "|n", 0) >= 10}
        if vals:
            stay[k] = summarize(vals)
            stay[k]["atoms"] = sum(c.get(k + "|n", 0) for c in cats.values())
    S["p1"]["stay_by_category"] = stay
    # P2
    p2 = {n: summ(res, lambda r, n=n: r["p235"].get(n)) for n in ("n_paths", "mean_visits", "mean_floor10", "mean_floor20", "share_over_floor10", "share_over_floor20",
                                                                  "share_at_floor10", "mean_excess10", "short_split", "long_extra", "chain_excess", "nochain_excess", "n_cross_edges", "blen_mean")}
    for c in CAUSES:
        p2["cause_" + c] = summ(res, lambda r, c=c: rate(r["p235"]["cause"].get(c, 0), r["p235"]["n_cross_edges"]))
    p2["full_also_refused"] = summ(res, lambda r: rate(r["p235"]["full_also_refused"], r["p235"]["cause"].get("full", 0)))
    p2["cross_chain_pairs"] = summ(res, lambda r: rate(r["p235"]["cross_chain_pairs"], r["p235"]["n_cross_edges"]))
    for cat in ("never_queued", "queued_outranked", "queued_then_dropped", "queued_cluster_closed_next"):
        for who in ("heap", "other"):
            p2[f"full_{cat}_{who}"] = summ(res, lambda r, cat=cat, who=who: rate(r["p235"]["full_detail"].get(f"{cat}|{who}", 0), sum(r["p235"]["full_detail"].values())))
    S["p2"] = p2
    # P3
    def fork_total(r):
        return sum(v for k, v in r["p235"]["branch"].items() if k.startswith("fork"))

    def join_total(r):
        return sum(v for k, v in r["p235"]["branch"].items() if k.startswith("join"))

    S["p3"] = {
        "fork_split": summ(res, lambda r: rate(r["p235"]["branch"].get("fork_split", 0), fork_total(r))),
        "fork_all": summ(res, lambda r: rate(r["p235"]["branch"].get("fork_all", 0), fork_total(r))),
        "fork_none": summ(res, lambda r: rate(r["p235"]["branch"].get("fork_none", 0), fork_total(r))),
        "join_split": summ(res, lambda r: rate(r["p235"]["branch"].get("join_split", 0), join_total(r))),
        "join_all": summ(res, lambda r: rate(r["p235"]["branch"].get("join_all", 0), join_total(r))),
        "branch_cross_share": summ(res, lambda r: rate(r["p235"]["branch_cross_edges"], r["p235"]["n_cross_edges"])),
        "atoms_on_ge2": summ(res, lambda r: rate(r["p235"]["atoms_on_ge2_paths"], r["p235"]["atoms_on_paths"])),
        "forks": summ(res, lambda r: fork_total(r)),
    }
    # P4
    p4 = {"not_top": summ(res, lambda r: rate(r["p4"]["not_top"], r["p4"]["n_choice"])), "stale_gain": summ(res, lambda r: rate(r["p4"]["stale_gain"]["differs_10pct"], r["p4"]["stale_gain"]["cand"])),
          "n_choice": summ(res, lambda r: r["p4"]["n_choice"])}
    for e in ("0.0", "0.01", "0.05"):
        k = "e" + e
        p4[k] = {
            "tie_rate": summ(res, lambda r, k=k: rate(r["p4"][k]["ties"], r["p4"]["n_choice"])),
            "zero_gain_share": summ(res, lambda r, k=k: rate(r["p4"][k]["ties_zero_gain"], r["p4"][k]["ties"])),
            "hot_share": summ(res, lambda r, k=k: rate(r["p4"][k]["hot"], r["p4"][k]["ties"])),
            "hot_lost": summ(res, lambda r, k=k: rate(r["p4"][k]["picked_lower_rc_than_heap_competitor"], r["p4"][k]["hot"])),
            "hot_won": summ(res, lambda r, k=k: rate(r["p4"][k]["picked_higher_rc"], r["p4"][k]["hot"])),
            "earliest_queued": summ(res, lambda r, k=k: rate(r["p4"][k]["picked_earliest_queued"], r["p4"][k]["ties"])),
            "hot_n": summ(res, lambda r, k=k: r["p4"][k]["hot"]),
        }
        src = pooled_counts(res, lambda r, k=k: r["p4"][k]["src"])
        tot = collections.Counter()
        for c in src.values():
            tot.update(c)
        p4[k]["src_pooled"] = {pl.SRC_NAMES.get(int(s), s): n for s, n in sorted(tot.items(), key=lambda kv: -kv[1])}
    S["p4"] = p4
    # P5
    def p5(r, key):
        return r["p235"]["p5"][key]

    S["p5"] = {
        "nonheap_fle_share": summ(res, lambda r: (1 - p5(r, "heap_fles") / p5(r, "fles_in_heap_clusters")) if p5(r, "fles_in_heap_clusters") else None),
        "heap_clusters_over_min": summ(res, lambda r: rate(p5(r, "heap_clusters"), p5(r, "min_clusters"))),
        "heap_clusters_share": summ(res, lambda r: rate(p5(r, "heap_clusters"), p5(r, "clusters_total"))),
        "full_cross_with_filler": summ(res, lambda r: rate(p5(r, "full_cross_with_filler"), p5(r, "full_cross"))),
        "heap_fle_per_heap_cluster": summ(res, lambda r: rate(p5(r, "heap_fles"), p5(r, "heap_clusters"))),
    }
    src = pooled_counts(res, lambda r: r["p235"]["p5"]["filler_src"])
    tot = collections.Counter()
    for c in src.values():
        tot.update(c)
    S["p5"]["filler_source_pooled"] = dict(tot.most_common())
    # P6
    S["p6"] = {
        "single_share": summ(res, lambda r: rate(r["p6"]["single_pin"], r["p6"]["heap_multi_pin"])),
        "single_stay": summ(res, lambda r: rate(r["p6"]["single_stay"], r["p6"]["single_pin"])),
        "multi_stay": summ(res, lambda r: rate(r["p6"]["multi_stay"], r["p6"]["multi_pin"])),
        "auc_max_pin": summ(res, lambda r: r["p6"]["auc_max"]),
        "auc_mean_pin": summ(res, lambda r: r["p6"]["auc_mean"]),
        "inherited_share": summ(res, lambda r: rate(r["p6"]["tg_inherited"]["inh"], r["p6"]["tg_inherited"]["inh"] + r["p6"]["tg_inherited"]["own"])),
        "inherited_stay": summ(res, lambda r: rate(r["p6"]["tg_inherited"]["inh_stay"], r["p6"]["tg_inherited"]["inh"])),
        "own_stay": summ(res, lambda r: rate(r["p6"]["tg_inherited"]["own_stay"], r["p6"]["tg_inherited"]["own"])),
        "inherited_n": summ(res, lambda r: r["p6"]["tg_inherited"]["inh"]),
    }
    # P7
    S["p7"] = {
        "hf_net_share": summ(res, lambda r: rate(r["p7"]["hf_nets"], r["p7"]["near_nets"])),
        "hf_edge_share": summ(res, lambda r: rate(r["p7"]["edges_on_hf"], r["p7"]["near_edges"])),
        "all_hf_driver_share": summ(res, lambda r: rate(r["p7"]["all_hf_drivers"], r["p7"]["all_drivers"])),
        "gt16_net_share": summ(res, lambda r: rate(r["p7"]["bands"]["16"], r["p7"]["near_nets"])),
        "gt8_net_share": summ(res, lambda r: rate(r["p7"]["bands"]["8"], r["p7"]["near_nets"])),
        "hf_nets": summ(res, lambda r: r["p7"]["hf_nets"]),
        "near_nets": summ(res, lambda r: r["p7"]["near_nets"]),
    }
    # P8
    rows = []
    for r in res:
        if r["seed"] != 1:
            continue
        for w in r["p8"]:
            rows.append(dict(w, design=r["design"]))
    S["p8_rows"] = rows
    S["p7_nets"] = [dict(n, design=r["design"]) for r in res if r["seed"] == 1 for n in r.get("p7_nets", ())]
    # P9 detector counts
    p9 = {}
    for name, f in (("chain_atoms", lambda r: rate(r["p9"]["chain"]["atoms"], r["p9"]["logic_atoms"])),
                    ("chain_count", lambda r: r["p9"]["chain"]["chains"]),
                    ("chain_in_heap", lambda r: rate(r["p9"]["chain"]["in_heap"], r["p9"]["chain"]["atoms"])),
                    ("collector_ff", lambda r: rate(r["p9"]["collector"]["collector"], r["p9"]["collector"]["ff"])),
                    ("collector_count", lambda r: r["p9"]["collector"]["collector"]),
                    ("collector_in_heap", lambda r: rate(r["p9"]["collector"]["collector_in_heap"], r["p9"]["collector"]["collector"])),
                    ("other_ff_in_heap", lambda r: rate(r["p9"]["collector"]["other_ff_in_heap"], r["p9"]["collector"]["ff"] - r["p9"]["collector"]["collector"])),
                    ("deep_atoms", lambda r: r["p9"]["deep"]["atoms"]),
                    ("deep_in_heap", lambda r: rate(r["p9"]["deep"]["in_heap"], r["p9"]["deep"]["atoms"])),
                    ("deep_pack_heap", lambda r: r["p9"]["deep"]["pack_heap_deep"]),
                    ("max_level", lambda r: r["p9"]["deep"]["max_level"]),
                    ("fork_atoms", lambda r: r["p9"]["fork"]["atoms"]),
                    ("fork_split", lambda r: rate(r["p9"]["fork"]["outcome"].get("split", 0), r["p9"]["fork"]["atoms"])),
                    ("fork_none", lambda r: rate(r["p9"]["fork"]["outcome"].get("none", 0), r["p9"]["fork"]["atoms"])),
                    ("fork_all", lambda r: rate(r["p9"]["fork"]["outcome"].get("all", 0), r["p9"]["fork"]["atoms"])),
                    ("hf_nets", lambda r: r["p9"]["hf"]["nets"]),
                    ("hf_critical", lambda r: r["p9"]["hf"]["pre_pack_critical"]),
                    ("mid_nets", lambda r: r["p9"]["mid"]["nets"]),
                    ("mid_critical", lambda r: r["p9"]["mid"]["pre_pack_critical"]),
                    ("sibling_nets", lambda r: r["p9"]["siblings"]["nets"]),
                    ("after_hard", lambda r: rate(r["p9"]["hard"]["after_hard"], r["p9"]["logic_atoms"])),
                    ("after_hard_in_heap", lambda r: rate(r["p9"]["hard"]["after_hard_in_heap"], r["p9"]["hard"]["after_hard"])),
                    ("logic_atoms", lambda r: r["p9"]["logic_atoms"])):
        p9[name] = summ(res, f)
    S["p9"] = p9
    mk = collections.Counter()
    for r in res:
        if r["seed"] == 1:
            mk.update(r["p9"]["mid"]["driver_kind"])
    S["p9_mid_driver_kinds"] = dict(mk.most_common())
    S["designs"] = sorted(by_design(res))
    S["runs"] = len(res)
    return S


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mimir", required=True)
    ap.add_argument("--sweep", required=True)
    ap.add_argument("--census", required=True)
    ap.add_argument("--runs", required=True, help="pickle of heap_data.load_all")
    ap.add_argument("--bench", help="directory of the VTR benchmark Verilog sources (for the source text of near-critical high-fanout nets)")
    ap.add_argument("--raw", help="optional pickle to keep the per-run results")
    ap.add_argument("--out", default="data/analysis")
    a = ap.parse_args()
    with open(a.runs, "rb") as fh:
        runs = pickle.load(fh)
    res = analyze(runs, a.mimir, a.sweep, a.census, a.bench)
    if a.raw:
        with open(a.raw, "wb") as fh:
            pickle.dump(res, fh)
    S = summary(res)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "heappick.json").write_text(json.dumps(S, indent=1, sort_keys=True, default=str) + "\n")
    print(f"wrote {out / 'heappick.json'} ({S['runs']} runs, {len(S['designs'])} designs)")


if __name__ == "__main__":
    main()
