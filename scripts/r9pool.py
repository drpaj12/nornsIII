"""Round 9 full-set statistics (docs/plan/round9-tpeko-real.md, entry 2026-10-29 (b)). The design is the unit.

  python scripts/r9pool.py [--json data/r9/full-summary.json] [DESIGN ...]

Per design and construction: ratios over the (shuffle 1 to 3) x (VPR seed 1 to 3) pairs, as geometric means:
  CLB   stock / N_C            (N_C = exact bound, as in the pilot), stock / exact, stock / known, known / N_C
  WL    stock / exact, stock / known
  CPD   stock / exact, stock / known
Pooled over designs: geometric mean, 90 percent bootstrap over designs (10000, seed 20261029, percentile), Holm over the three
metrics, room rule of round 5. Self-bias: per design log(ratio on own) - log(ratio on foreign), pooled the same way.

Corrected N_C (entry 2026-10-30 (b)): N_C is the counting bound on the generator's demand. The netlist VPR packs (the written D'
file, shuffle 1) can hold other atoms: constant generators and constant-driven output buffers (LUT atoms that are not cells of C)
and, in stereovision1, adders VPR sweeps. N_C(corrected) = ceil(fle demand of the packed netlist / 10), demand = 6-input LUTs +
adder fle (ceil(surviving adders of a chain / 2)) + the small LUTs, each counted 1 fle (`Kc`, the plan's rule) or 0.5 fle (`Kc_half`,
valid even if VPR pairs two small LUTs in one fle). stock/Kc = stock/N_C x N_C/Kc. Pooled also without the designs whose build
check flagged a mismatch (`vpr_atoms_match` false on D, or the D' check false).
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import random
import sys
from pathlib import Path

import r9run as rr

BOOT, SEED = rr.BOOT, rr.BOOT_SEED
R5 = {"logic_clbs": 1.073, "wirelength": 1.220, "cpd_ns": 1.093}  # round 5, stock/known, 72 synthetic designs, same architecture and flags
METRICS = ("logic_clbs", "wirelength", "cpd_ns")


def load(designs: list) -> dict:
    runs = rr.read_runs()
    keep = collections.defaultdict(dict)
    drop = collections.Counter()
    for r in runs:
        if designs and r["design"] not in designs:
            continue
        drop["considered"] += 1
        if r["rc"] != 0:
            drop["failed (rc != 0)"] += 1
            continue
        if r.get("shuffle", -1) == 0 and r["arm"] != "stock":
            drop["ordered control, not stock (unused)"] += 1
            continue
        try:
            if r["sha"] != rr.blif_sha(r["design"], r["cons"], r["shuffle"]):
                drop["dropped: sha differs from the current build"] += 1
                continue
        except (KeyError, FileNotFoundError, ValueError):
            drop["dropped: sha or build.json missing"] += 1
            continue
        keep[(r["design"], r["cons"])][(r["shuffle"], r["arm"], r["vseed"])] = r
    load.dropped = dict(drop)  # type: ignore[attr-defined]
    return keep


def ceil_div(a: float, b: int) -> int:
    return int(-(-a // b))


def chain_survivors(blif_text: str, net_adders: set) -> list:
    """Per carry chain of the written BLIF (adders linked cout -> cin): (adders written, adders VPR kept, in the .net by cout name)."""
    ad = []
    for line in blif_text.replace("\\\n", " ").splitlines():
        if line.startswith(".subckt adder"):
            ad.append(dict(x.split("=", 1) for x in line.split()[2:]))
    by_cin = {a["cin"]: a for a in ad if a["cin"] not in ("gnd", "vcc")}
    nxt = {a["cout"]: by_cin[a["cout"]] for a in ad if a["cout"] in by_cin}
    heads = [a for a in ad if a["cin"] in ("gnd", "vcc") or a["cin"] not in {x["cout"] for x in ad}]
    out = []
    for h in heads:
        n = kept = 0
        a = h
        while a is not None:
            n += 1
            kept += a["cout"] in net_adders
            a = nxt.get(a["cout"])
        out.append((n, kept))
    return out


def corrected_bound(blif_text: str, net_counts: dict, net_adders: set) -> dict:
    """Counting lower bound on the logic CLBs of the netlist VPR packed. net_counts: atoms by type in the .net (r9build.read_net)."""
    n6 = sum(1 for line in blif_text.replace("\\\n", " ").splitlines() if line.startswith(".names") and len(line.split()) == 8)
    luts = net_counts.get("lut", 0)
    small = max(0, luts - n6)
    chains = chain_survivors(blif_text, net_adders)
    adder_fle = sum(ceil_div(kept, 2) for _n, kept in chains)
    written = sum(ceil_div(n, 2) for n, _k in chains)
    return {"luts": luts, "luts6": min(n6, luts), "small_luts": small, "adder_fle": adder_fle, "adder_fle_written": written,
            "adders_swept": sum(n - k for n, k in chains), "Kc": ceil_div(luts + adder_fle, 10),
            "Kc_half": ceil_div(2 * (luts - small) + small + 2 * adder_fle, 20)}


def net_adder_names(net: Path) -> set:
    import xml.etree.ElementTree as ET
    return {x.get("name") for x in ET.parse(net).getroot().iter("block") if x.get("instance", "").startswith("adder") and x.get("name") != "open"}


def bound_of(design: str, cons: str) -> dict:
    """Corrected N_C of one build, from the shuffle-1 file and the .net stock packed it into (read only)."""
    import r9build as rb
    base = rr.OUT / design / cons
    sha = json.loads((base / "build.json").read_text())["shuffles"]["1"]["sha256"]
    net = base / "sh1" / f"pack.{sha[:10]}" / "design.net"
    counts = rb.read_net(net)[1]
    rec = corrected_bound((base / "sh1" / "design.blif").read_text(), counts, net_adder_names(net))
    return rec


def gm(xs: list) -> float:
    return math.exp(sum(xs) / len(xs))


def per_design(keep: dict) -> dict:
    res: dict = {}
    for (d, c), recs in sorted(keep.items()):
        build = json.loads((rr.OUT / d / c / "build.json").read_text())
        row = {"design": d, "cons": c, "K": build["K"], "K_vpr": build["K_vpr"], "dummies": build["dummies"]}
        row["flag_D"] = not build["vpr_atoms_match"]
        row["flag_Dprime"] = not build["vpr_check_dprime"]["match"]
        bd = bound_of(d, c)
        row.update({"Kc": bd["Kc"], "Kc_half": bd["Kc_half"], "extra_small_luts": bd["small_luts"], "adders_swept": bd["adders_swept"]})
        pairs = [(sh, s) for sh in (1, 2, 3) for s in (1, 2, 3) if all((sh, a, s) in recs for a in ("stock", "known"))]
        row["n_pairs"] = len(pairs)
        if not pairs:
            continue
        ex = [(sh, s) for sh, s in pairs if (sh, "exact", s) in recs]
        row["n_exact"] = len(ex)
        logs: dict = {}
        logs["clb_over_K"] = [math.log(recs[(sh, "stock", s)]["logic_clbs"] / build["K"]) for sh, s in pairs]
        logs["known_over_K"] = [math.log(recs[(sh, "known", s)]["logic_clbs"] / build["K"]) for sh, s in pairs]
        for m, tag in (("logic_clbs", "clb"), ("wirelength", "wl"), ("cpd_ns", "cpd")):
            logs[f"{tag}_over_known"] = [math.log(recs[(sh, "stock", s)][m] / recs[(sh, "known", s)][m]) for sh, s in pairs]
            if ex:
                logs[f"{tag}_over_exact"] = [math.log(recs[(sh, "stock", s)][m] / recs[(sh, "exact", s)][m]) for sh, s in ex]
        logs["clb_over_Kc"] = [x + math.log(build["K"] / row["Kc"]) for x in logs["clb_over_K"]]
        logs["clb_over_Kc_half"] = [x + math.log(build["K"] / row["Kc_half"]) for x in logs["clb_over_K"]]
        for k, v in logs.items():
            row[k] = gm(v)
        for arm in ("stock", "known", "exact"):
            sel = [recs[(sh, arm, s)] for sh, s in (ex if arm == "exact" else pairs) if (sh, arm, s) in recs]
            if sel:
                row[f"{arm}_purity"] = sum(r["purity"] for r in sel) / len(sel)
                row[f"{arm}_clbs"] = sum(r["logic_clbs"] for r in sel) / len(sel)
        row["_logs"] = logs
        res[(d, c)] = row
    return res


def boot(vals: list, rnd: random.Random) -> tuple:
    n = len(vals)
    means = sorted(sum(vals[rnd.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    lo, hi = means[int(0.05 * BOOT)], means[int(0.95 * BOOT) - 1]
    p = min(1.0, 2 * min(sum(1 for m in means if m <= 0) / BOOT, sum(1 for m in means if m >= 0) / BOOT))
    return sum(vals) / n, lo, hi, p


def fmt_p(p: float) -> str:
    """A bootstrap p of 0 means no resample crossed 0; the resolution is 1 / BOOT."""
    return f"< {1 / BOOT:g}" if p < 1 / BOOT else f"{p:.4f}"


def pooled(rows: dict, cons: str, keys: dict, rnd: random.Random, skip: frozenset = frozenset()) -> dict:
    """keys: label -> ratio key, e.g. {'CLB': 'clb_over_exact', ...}. Holm over the labels. skip: designs left out."""
    rs = [r for (d, c), r in rows.items() if c == cons and d not in skip and all(k in r for k in keys.values())]
    out: dict = {"n": len(rs)}
    if len(rs) < 2:
        return out
    ps, tmp = [], {}
    for lab, k in keys.items():
        vals = [math.log(r[k]) for r in rs]
        mean, lo, hi, p = boot(vals, rnd)
        tmp[lab] = (mean, lo, hi, p)
        ps.append(p)
    adj = rr.holm(ps)
    for (lab, (mean, lo, hi, _p)), pa in zip(tmp.items(), adj):
        out[lab] = {"gm": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi), "p_holm": pa, "p_holm_str": fmt_p(pa),
                    "status": rr.status(math.exp(mean), lo, hi, pa) if len(rs) >= 12 else "inconclusive (n < 12)"}
    return out


def self_bias(rows: dict, keys: dict, rnd: random.Random) -> dict:
    ds = sorted({d for d, _c in rows})
    out: dict = {}
    both = [d for d in ds if (d, "own") in rows and (d, "foreign") in rows]
    out["n"] = len(both)
    if len(both) < 2:
        return out
    ps, tmp = [], {}
    for lab, k in keys.items():
        vals = [math.log(rows[(d, "own")][k]) - math.log(rows[(d, "foreign")][k]) for d in both
                if k in rows[(d, "own")] and k in rows[(d, "foreign")]]
        mean, lo, hi, p = boot(vals, rnd)
        tmp[lab] = (mean, lo, hi, p, len(vals))
        ps.append(p)
    for (lab, (mean, lo, hi, _p, n)), pa in zip(tmp.items(), rr.holm(ps)):
        out[lab] = {"own_over_foreign": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi), "p_holm": pa, "p_holm_str": fmt_p(pa), "n": n}
    return out


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    rows = per_design(load(a.designs))
    rnd = random.Random(SEED)
    res: dict = {"designs": [{k: v for k, v in r.items() if k != "_logs"} for r in rows.values()], "pooled": {}, "self_bias": {}}
    sets = {"stock_over_exact": {"CLB": "clb_over_exact", "WL": "wl_over_exact", "CPD": "cpd_over_exact"},
            "stock_over_known": {"CLB": "clb_over_known", "WL": "wl_over_known", "CPD": "cpd_over_known"},
            "stock_over_K_clb": {"CLB": "clb_over_K"}}
    new_sets = {"stock_over_Kc_clb": {"CLB": "clb_over_Kc"}, "stock_over_Kc_half_clb": {"CLB": "clb_over_Kc_half"}}
    rnd2 = random.Random(SEED)  # separate stream: the numbers of the first results entry do not move
    flagged = frozenset(d for (d, _c), r in rows.items() if r["flag_D"] or r["flag_Dprime"])
    res["flagged_designs"] = {"vpr_atoms_match_false_on_D": sorted({d for (d, _c), r in rows.items() if r["flag_D"]}),
                              "D_prime_check_false": sorted({d for (d, _c), r in rows.items() if r["flag_Dprime"]}),
                              "union": sorted(flagged)}
    res["load"] = getattr(load, "dropped", {})
    for cons in ("own", "foreign"):
        for name, keys in sets.items():
            res["pooled"][f"{name}/{cons}"] = pooled(rows, cons, keys, rnd)
    res["self_bias"]["stock_over_exact"] = self_bias(rows, sets["stock_over_exact"], rnd)
    res["self_bias"]["stock_over_known"] = self_bias(rows, sets["stock_over_known"], rnd)
    res["self_bias"]["stock_over_K_clb"] = self_bias(rows, sets["stock_over_K_clb"], rnd)
    for cons in ("own", "foreign"):
        for name, keys in new_sets.items():
            res["pooled"][f"{name}/{cons}"] = pooled(rows, cons, keys, rnd2)
        for name, keys in {**new_sets, "stock_over_K_clb": sets["stock_over_K_clb"]}.items():
            res["pooled"][f"{name}/{cons}/excl_flagged"] = pooled(rows, cons, keys, rnd2, flagged)
    res["self_bias"]["stock_over_Kc_clb"] = self_bias(rows, new_sets["stock_over_Kc_clb"], rnd2)
    res["round5_stock_over_known"] = R5
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, indent=1, sort_keys=True))
    print("LOAD", json.dumps(res["load"]))
    print("FLAGGED", json.dumps(res["flagged_designs"]))
    print("design cons N_C N_Cc N_Cc_half N_Cvpr n/ne | stock/N_C known/N_C | CLB s/e s/k | WL s/e s/k | CPD s/e s/k | purity stock known exact")
    f = lambda r, k: f"{r[k]:.3f}" if k in r else "  -  "  # noqa: E731
    for r in res["designs"]:
        print(f"{r['design']} {r['cons']} {r['K']} {r['Kc']} {r['Kc_half']} {r['K_vpr']} {r['n_pairs']}/{r.get('n_exact', 0)} | {f(r, 'clb_over_K')} {f(r, 'clb_over_Kc')} {f(r, 'clb_over_Kc_half')} {f(r, 'known_over_K')} | "
              f"{f(r, 'clb_over_exact')} {f(r, 'clb_over_known')} | {f(r, 'wl_over_exact')} {f(r, 'wl_over_known')} | "
              f"{f(r, 'cpd_over_exact')} {f(r, 'cpd_over_known')} | {f(r, 'stock_purity')} {f(r, 'known_purity')} {f(r, 'exact_purity')}")
    for k, v in res["pooled"].items():
        print("POOLED", k, json.dumps({a_: (round(b["gm"], 3), round(b["lo"], 3), round(b["hi"], 3), b["p_holm_str"], b["status"], v["n"]) if isinstance(b, dict) else b
                                       for a_, b in v.items()}))
    for k, v in res["self_bias"].items():
        print("SELFBIAS", k, json.dumps({a_: (round(b["own_over_foreign"], 3), round(b["lo"], 3), round(b["hi"], 3), b["p_holm_str"], "n=%d" % b["n"]) if isinstance(b, dict) else b
                                         for a_, b in v.items()}))
    print("ROUND5 stock/known", R5)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
