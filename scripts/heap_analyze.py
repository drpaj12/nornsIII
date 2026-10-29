"""Critical-heap lane: all questions Q1-Q6 -> data/analysis/heap-*.json and docs/figures/critical-heap/*.png.

  PYTHONPATH=scripts python3 scripts/heap_analyze.py --mimir DIR --sweep ROOT --census ROOT [--runs PKL] [--out data/analysis]
Needs numpy (and matplotlib for the figures); read-only on the Mimir stores.
"""
from __future__ import annotations

import argparse
import collections
import json
import pickle
import sys
from pathlib import Path

import numpy as np

import heap_lib as hl

KINDS = ("adder", "multiplier", "mux", "relational", "equality", "logic", "register_word", "fsm", "counter", "shifter", "memory", "unknown", "none")
MIN_BASE, MIN_NEAR = 5, 10  # a design counts for a kind with >= 5 atoms of the kind and >= 10 heap atoms


def by_design(runs):
    d = collections.defaultdict(list)
    for r in runs:
        d[r["design"]].append(r)
    return d


def heap_set(r, thr):
    return {a for a, v in r["atoms"].items() if (v["rc"] or 0.0) >= thr}


def summarize(vals):
    m, lo, hi, n = hl.boot_median(vals)
    return {"median": m, "lo90": lo, "hi90": hi, "n_designs": n}


# ---------------------------------------------------------------------------------------
def q1(runs):
    out = {}
    for view in ("op", "blk", "det"):
        for thr in hl.THRS:
            per = collections.defaultdict(lambda: collections.defaultdict(list))  # kind -> design -> [ratios per seed]
            perd = collections.defaultdict(lambda: collections.defaultdict(list))
            absent = collections.defaultdict(int)  # kind -> designs where present, qualified, and zero heap atoms
            for d, rs in by_design(runs).items():
                for r in rs:
                    at = r["atoms"]
                    hs = heap_set(r, thr)
                    base = collections.Counter(v[view] for v in at.values())
                    nk = collections.Counter(at[a][view] for a in hs)
                    dk = collections.defaultdict(float)
                    for a in hs:
                        dk[at[a][view]] += at[a]["w"]
                    dtot = sum(dk.values())
                    if len(hs) < MIN_NEAR:
                        continue
                    for k in base:
                        if base[k] < MIN_BASE:
                            continue
                        per[k][d].append(hl.enrichment(nk[k], len(hs), base[k], len(at)))
                        if dtot > 0:
                            perd[k][d].append(hl.enrichment(dk[k], dtot, base[k], len(at)))
            rows = {}
            for k in per:
                dv = [float(np.mean(v)) for v in per[k].values()]
                dd = [float(np.mean(v)) for v in perd[k].values()]
                seedsd = [float(np.std(v)) for v in per[k].values() if len(v) > 1]
                rows[k] = {"atoms": summarize(dv), "delay": summarize(dd), "never_in_heap_designs": int(sum(1 for x in dv if x == 0.0)),
                           "mean_seed_sd": float(np.mean(seedsd)) if seedsd else None, "per_design": {d: float(np.mean(v)) for d, v in per[k].items()}}
            out[f"{view}@{thr}"] = rows
    return out


def q1_lines(runs, top=8):
    out = {}
    for d, rs in by_design(runs).items():
        r = rs[0]
        at = r["atoms"]
        hs = heap_set(r, 0.90)
        base = collections.Counter(v["line"] for v in at.values() if v["line"])
        near = collections.Counter(at[a]["line"] for a in hs if at[a]["line"])
        n = sum(near.values())
        rows = [{"line": ln, "heap_atoms": c, "atoms": base[ln], "enrichment": hl.enrichment(c, n, base[ln], sum(base.values()))} for ln, c in near.most_common(top)]
        out[d] = {"heap_atoms_with_line": n, "heap_atoms": len(hs), "top": rows}
    return out


# ---------------------------------------------------------------------------------------
def q2(runs):
    """Bit level: words (module/word) with >= 8 bits seen; kind of the word = most common op-view kind of its atoms (else blk)."""
    res = collections.defaultdict(lambda: {"bits": [], "rho": [], "words": 0})
    pts = collections.defaultdict(list)  # kind -> (relative bit position, crit)
    for r in runs:
        words = collections.defaultdict(list)
        for a, v in r["atoms"].items():
            if "word" in v and v["rc"] is not None:
                k = v["op"] if v["op"] != "none" else v["blk"]
                words[v["word"]].append((v["bit"], v["rc"], k, v["width"]))
        for w, items in words.items():
            width = max(i[3] for i in items)
            if width < 8:
                continue
            kind = collections.Counter(i[2] for i in items).most_common(1)[0][0]
            bits = collections.defaultdict(float)
            for b, c, _k, _w in items:
                bits[b] = max(bits[b], c)
            if len(bits) < 8:
                continue
            xs = sorted(bits)
            rho = hl.spearman(xs, [bits[b] for b in xs])
            res[kind]["words"] += 1
            if rho is not None:
                res[kind]["rho"].append(rho)
            for b in xs:
                rel = b / (width - 1)
                pts[kind].append((rel, bits[b]))
                res[kind]["bits"].append((rel, bits[b] >= 0.90))
    # adder atoms carry no word/bit in the Odin III attribution: their bit index is the position along the carry chain (netlist)
    for r in runs:
        for v in r["atoms"].values():
            if "cpos" in v and v["clen"] >= 8:
                rel = v["cpos"] / (v["clen"] - 1)
                res["adder carry chain"]["bits"].append((rel, (v["rc"] or 0.0) >= 0.90))
                if v["rc"] is not None:
                    pts["adder carry chain"].append((rel, v["rc"]))
    out = {}
    for k, v in res.items():
        q = collections.defaultdict(lambda: [0, 0])
        for rel, hit in v["bits"]:
            i = min(int(rel * 4), 3)
            q[i][0] += 1
            q[i][1] += int(hit)
        out[k] = {"words": v["words"], "bits_seen": len(v["bits"]), "mean_spearman_bit_vs_crit": float(np.mean(v["rho"])) if v["rho"] else None,
                  "heap_rate_by_position_quartile": {str(i): (q[i][1] / q[i][0] if q[i][0] else None) for i in range(4)},
                  "bits_per_quartile": {str(i): q[i][0] for i in range(4)}}
    return out, pts


# ---------------------------------------------------------------------------------------
def q3(runs):
    rows = []
    for r in runs:
        t = r["timing"]
        crits = sorted((p["crit"] or 0.0) for p in r["paths"].values())
        n = len(crits)
        rows.append({"design": r["design"], "seed": r["seed"], "cpd_ns": t["cpd"], "paths": t["n_paths"], "last_crit": t["last_crit"],
                     "ne90": t["ne90"], "ne95": t["ne95"], "ne99": t["ne99"], "trunc90": t["trunc90"], "trunc95": t["trunc95"], "trunc99": t["trunc99"],
                     "paths_ge90": sum(c >= 0.90 for c in crits), "paths_ge95": sum(c >= 0.95 for c in crits), "paths_ge99": sum(c >= 0.99 for c in crits),
                     "crit_p10": hl.quantile(crits, 0.1), "crit_p50": hl.quantile(crits, 0.5), "crit_p90": hl.quantile(crits, 0.9),
                     "atoms": len(r["atoms"]), "heap_atoms_90": len(heap_set(r, 0.90)), "heap_atoms_95": len(heap_set(r, 0.95)), "heap_atoms_99": len(heap_set(r, 0.99))})
    return rows


# ---------------------------------------------------------------------------------------
def q4(runs):
    per = []
    for r in runs:
        at = r["atoms"]
        la = [v for v in at.values() if v["pc"] is not None]
        pc = [v["pc"] for v in la]
        row = {"design": r["design"], "seed": r["seed"], "atoms": len(la), "trunc90": r["timing"]["trunc90"], "last_crit": r["timing"]["last_crit"]}
        row["rho_crank_pc"] = hl.spearman([v["crank"] for v in la], pc)
        row["rho_seq_pc"] = hl.spearman([v["seq"] for v in la], pc)
        ph = [v for v in la if v["pc"] >= 0.90]
        row["pack_heap"] = len(ph)
        row["pack_heap_in_first_quartile"] = (sum(v["crank"] <= 0.25 for v in ph) / len(ph)) if ph else None
        row["pack_heap_median_crank"] = hl.median([v["crank"] for v in ph]) if ph else None
        row["other_median_crank"] = hl.median([v["crank"] for v in la if v["pc"] < 0.90]) if len(ph) < len(la) else None
        row["pack_heap_median_idx"] = hl.median([v["idx"] for v in ph]) if ph else None
        row["other_median_idx"] = hl.median([v["idx"] for v in la if v["pc"] < 0.90]) if len(ph) < len(la) else None
        rh = [v for v in la if (v["rc"] or 0) >= 0.90]
        row["route_heap"] = len(rh)
        seen = [v for v in la if v["rc"] is not None]
        row["rho_pc_rc_seen"] = hl.spearman([v["pc"] for v in seen], [v["rc"] for v in seen])
        mat = collections.Counter()
        for v in la:
            mat[(hl.crit_bin(v["pc"]) if v["pc"] >= 0.5 else "<0.50", hl.crit_bin(v["rc"]))] += 1
        row["matrix"] = {f"{a}|{b}": c for (a, b), c in mat.items()}
        in_both = sum(1 for v in ph if (v["rc"] or 0) >= 0.90)
        row["stay"] = in_both / len(ph) if ph else None
        row["from_pack_heap"] = in_both / len(rh) if rh else None
        row["new_arrival_pc_lt_090"] = sum(1 for v in rh if v["pc"] < 0.90) / len(rh) if rh else None
        row["new_arrival_pc_lt_050"] = sum(1 for v in rh if v["pc"] < 0.50) / len(rh) if rh else None
        row["pack_heap_unseen"] = sum(1 for v in ph if v["rc"] is None) / len(ph) if ph else None
        # floor: logic-depth lower bound (cell delays only)
        ps = list(r["paths"].values())
        cpd = r["timing"]["cpd"]
        maxcell = max((p["cell"] for p in ps), default=0.0)
        near = [p for p in ps if (p["crit"] or 0) >= 0.90]
        ld = [p for p in ps if p["cell"] >= 0.90 * maxcell]
        ids_near = {id(p) for p in near}
        ids_ld = {id(p) for p in ld}
        row["cpd"] = cpd
        row["max_cell_sum"] = maxcell
        row["floor_ratio"] = maxcell / cpd if cpd else None
        row["near_paths"] = len(near)
        row["near_net_share"] = (sum(p["net"] for p in near) / max(sum(p["net"] + p["cell"] for p in near), 1e-9)) if near else None
        row["near_median_cell_over_cpd"] = hl.median([p["cell"] / cpd for p in near]) if near and cpd else None
        row["logic_heap_paths"] = len(ld)
        row["logic_vs_route_jaccard"] = len(ids_near & ids_ld) / len(ids_near | ids_ld) if (ids_near | ids_ld) else None
        row["logic_heap_recall_of_route"] = len(ids_near & ids_ld) / len(ids_near) if ids_near else None
        per.append(row)
    return per


def q4_summary(per):
    keys = ["rho_crank_pc", "rho_seq_pc", "pack_heap_in_first_quartile", "stay", "from_pack_heap", "new_arrival_pc_lt_090", "new_arrival_pc_lt_050",
            "pack_heap_unseen", "rho_pc_rc_seen", "floor_ratio", "near_net_share", "near_median_cell_over_cpd", "logic_vs_route_jaccard", "logic_heap_recall_of_route"]
    dd = collections.defaultdict(list)
    for p in per:
        dd[p["design"]].append(p)
    out = {}
    for k in keys:
        vals = []
        for d, ps in dd.items():
            x = [p[k] for p in ps if p[k] is not None]
            if x:
                vals.append(float(np.mean(x)))
        out[k] = summarize(vals)
    return out


# ---------------------------------------------------------------------------------------
def q5(q1res, runs):
    out = {}
    for view in ("op", "blk", "det"):
        for thr in (0.90,):
            rows = q1res[f"{view}@{thr}"]
            out[view] = {k: {"designs": v["atoms"]["n_designs"], "never_in_heap_designs": v["never_in_heap_designs"], "median_enrichment": v["atoms"]["median"]}
                         for k, v in rows.items()}
    # share of atoms of each kind that appear in no reported path at all
    unseen = collections.defaultdict(lambda: [0, 0])
    for r in runs:
        for v in r["atoms"].values():
            u = unseen[v["op"]]
            u[0] += 1
            u[1] += int(v["rc"] is None)
    out["unseen_share_op"] = {k: (u[1] / u[0], u[0]) for k, u in unseen.items()}
    return out


# ---------------------------------------------------------------------------------------
# Q6: HDL hints known before packing -> heap membership
NUM = ("opd", "muxd", "size", "lvl")


def features(r, which):
    """Rows (atom order fixed) of the Q6 features. kind one-hot from the op view, else blk view, else none."""
    rows, names = [], None
    for a, v in r["atoms"].items():
        info = v["op_info"]
        kind = v["op"] if info else v["blk"]
        if info:
            opd, muxd, size = info[1], info[2], np.log2(max(info[3], 1))
        else:
            binfo = v["blk_info"]
            opd, muxd, size = (binfo[1], binfo[2], np.log2(max(binfo[3], 1))) if binfo else (0, 0, 0.0)
        rows.append((a, kind, opd, muxd, size, v["lvl"], v["typ"]))
    return rows


def design_matrix(rows, which):
    ks = [k for k in KINDS]
    cols = []
    X = []
    for _a, kind, opd, muxd, size, lvl, typ in rows:
        x = []
        if "kind" in which:
            x += [1.0 if kind == k else 0.0 for k in ks]
        if "ops" in which:
            x += [opd, muxd, size, 1.0 if kind != "none" else 0.0]
        if "net" in which:
            x += [lvl, 1.0 if typ == "ff" else 0.0, 1.0 if typ == "adder" else 0.0]
        X.append(x)
    return np.array(X, dtype=float)


def fit_logistic(X, y, w, lam=1.0, it=30):
    mu = (X * w[:, None]).sum(0) / w.sum()
    sd = np.sqrt((((X - mu) ** 2) * w[:, None]).sum(0) / w.sum())
    sd[sd == 0] = 1.0
    Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    b = np.zeros(Z.shape[1])
    reg = np.eye(Z.shape[1]) * lam
    reg[0, 0] = 0
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(Z @ b, -30, 30)))
        g = Z.T @ (w * (p - y)) + reg @ b
        h = (Z * (w * p * (1 - p))[:, None]).T @ Z + reg + 1e-6 * np.eye(Z.shape[1])
        step = np.linalg.solve(h, g)
        b -= step
        if np.abs(step).max() < 1e-7:
            break
    return mu, sd, b


def predict(model, X):
    mu, sd, b = model
    Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    return 1 / (1 + np.exp(-np.clip(Z @ b, -30, 30)))


def auc(y, s):
    y = np.asarray(y)
    if y.sum() == 0 or y.sum() == len(y):
        return None
    r = np.array(hl._ranks(list(s)))
    n1, n0 = y.sum(), len(y) - y.sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def q6(runs):
    designs = sorted({r["design"] for r in runs})
    data = {}
    for r in runs:
        rows = features(r, None)
        ids = [x[0] for x in rows]
        yr = np.array([1.0 if (r["atoms"][a]["rc"] or 0) >= 0.90 else 0.0 for a in ids])
        yp = np.array([1.0 if (r["atoms"][a]["pc"] or 0) >= 0.90 else 0.0 for a in ids])
        data[(r["design"], r["seed"])] = (rows, yr, yp)
    res = {"model_sets": {}, "univariate": {}, "mux_depth": {}, "bit_position": {}}
    for target, ti in (("route", 1), ("pack", 2)):
        for name, which in (("kind", ("kind",)), ("kind+ops", ("kind", "ops")), ("kind+ops+netlist", ("kind", "ops", "net")), ("netlist only", ("net",))):
            aucs = {}
            for hold in designs:
                tr = [(k, v) for k, v in data.items() if k[0] != hold]
                X = np.vstack([design_matrix(v[0], which) for _k, v in tr])
                y = np.concatenate([v[ti] for _k, v in tr])
                w = np.concatenate([np.full(len(v[0]), 1.0 / len(v[0])) for _k, v in tr])
                w = w / w.sum() * len(w)
                m = fit_logistic(X, y, w)
                for k, v in data.items():
                    if k[0] == hold:
                        a = auc(v[ti], predict(m, design_matrix(v[0], which)))
                        if a is not None:
                            aucs.setdefault(hold, []).append(a)
            per = {d: float(np.mean(x)) for d, x in aucs.items()}
            res["model_sets"][f"{target}:{name}"] = {"auc_per_design": per, **{f"auc_{k}": v for k, v in summarize(list(per.values())).items()}, "auc_mean": float(np.mean(list(per.values())))}
        for fname, col in (("op depth", 2), ("mux depth", 3), ("log2 structure size", 4), ("comb level", 5)):
            per = {}
            for d in designs:
                a = []
                for (dd, _s), v in data.items():
                    if dd == d:
                        s = np.array([x[col] for x in v[0]], dtype=float)
                        x = auc(v[ti], s)
                        if x is not None:
                            a.append(x)
                if a:
                    per[d] = float(np.mean(a))
            res["univariate"][f"{target}:{fname}"] = {"auc_per_design": per, **{f"auc_{k}": v for k, v in summarize(list(per.values())).items()}}
    # heap membership rate by mux depth (per design rate, then median over designs having atoms at that depth)
    for tgt, ti in (("route", 1), ("pack", 2)):
        for depth in range(0, 5):
            vals = []
            for d in designs:
                n = h = 0
                for (dd, _s), v in data.items():
                    if dd == d:
                        for x, y in zip(v[0], v[ti]):
                            md = min(x[3], 4)
                            if md == depth and x[1] != "none":
                                n += 1
                                h += int(y)
                if n >= MIN_BASE:
                    vals.append(h / n)
            res["mux_depth"][f"{tgt}:{depth}{'+' if depth == 4 else ''}"] = summarize(vals)
    # bit position (atoms with a word/bit from the Odin III attribution: only atoms in a reported path)
    for q in range(4):
        vals = []
        valsc = []
        for d in designs:
            nc = hc = 0
            for r in runs:
                if r["design"] == d:
                    for v in r["atoms"].values():
                        if "cpos" in v and v["clen"] >= 8 and min(int(v["cpos"] / (v["clen"] - 1) * 4), 3) == q:
                            nc += 1
                            hc += int((v["rc"] or 0) >= 0.90)
            if nc >= MIN_BASE:
                valsc.append(hc / nc)
        res["bit_position"][f"adder chain position quartile {q}"] = summarize(valsc)
        for d in designs:
            n = h = 0
            for r in runs:
                if r["design"] != d:
                    continue
                for v in r["atoms"].values():
                    if "word" in v and v["width"] >= 8:
                        rel = v["bit"] / (v["width"] - 1)
                        if min(int(rel * 4), 3) == q:
                            n += 1
                            h += int((v["rc"] or 0) >= 0.90)
            if n >= MIN_BASE:
                vals.append(h / n)
        res["bit_position"][f"word bit quartile {q} (atoms in a reported path)"] = summarize(vals)
    res["cones"] = q6_cones(runs)
    return res


def q6_cones(runs):
    per = []
    for r in runs:
        at = r["atoms"]
        gs = [s for s in r["gsize"].values() if s > 0]
        near = [p for p in r["paths"].values() if (p["crit"] or 0) >= 0.90]
        inside = outside = noend = 0
        atom_ok = collections.defaultdict(lambda: True)
        for p in near:
            end = p["end"]
            key = end if end in r["gsize"] else ("out:" + end if "out:" + end in r["gsize"] else None)
            comb = [a for a in p["atoms"][1:-1] if a in at and at[a]["grp"] is not None]
            if key is None:
                noend += 1
                continue
            ok = all(at[a]["grp"] == key for a in comb)
            inside += int(ok)
            outside += int(not ok)
            for a in comb:
                if at[a]["grp"] != key:
                    atom_ok[a] = False
                else:
                    atom_ok[a] = atom_ok[a] and True
        heap_comb = [a for a in heap_set(r, 0.90) if at[a]["grp"] is not None]
        stay_atoms = sum(1 for a in heap_comb if atom_ok.get(a, True)) / len(heap_comb) if heap_comb else None
        comb_total = sum(1 for v in at.values() if v["grp"] is not None)
        hg = {at[a]["grp"] for a in heap_comb}
        cov = sum(r["gsize"][g] for g in hg) / comb_total if comb_total else None
        per.append({"design": r["design"], "seed": r["seed"], "groups": len(gs), "comb_atoms": comb_total,
                    "size_p50": hl.quantile(sorted(gs), 0.5) if gs else None, "size_p90": hl.quantile(sorted(gs), 0.9) if gs else None,
                    "size_max": max(gs) if gs else None, "size_mean": float(np.mean(gs)) if gs else None,
                    "near_paths": len(near), "paths_inside_one_group": inside / (inside + outside) if inside + outside else None, "paths_unresolved_endpoint": noend,
                    "heap_comb_atoms": len(heap_comb), "heap_atoms_staying": stay_atoms, "groups_holding_heap": len(hg),
                    "comb_share_in_heap_groups": cov})
    dd = collections.defaultdict(list)
    for p in per:
        dd[p["design"]].append(p)
    summ = {}
    for k in ("groups", "size_p50", "size_p90", "size_max", "size_mean", "paths_inside_one_group", "heap_atoms_staying", "groups_holding_heap", "comb_share_in_heap_groups"):
        vals = []
        for d, ps in dd.items():
            x = [p[k] for p in ps if p[k] is not None]
            if x:
                vals.append(float(np.mean(x)))
        summ[k] = summarize(vals)
    return {"per_run": per, "summary": summ}


# ---------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mimir")
    ap.add_argument("--sweep")
    ap.add_argument("--census")
    ap.add_argument("--runs", default="")
    ap.add_argument("--out", default="data/analysis")
    ap.add_argument("--figs", default="docs/figures/critical-heap")
    a = ap.parse_args()
    if a.runs and Path(a.runs).is_file():
        runs = pickle.load(open(a.runs, "rb"))
    else:
        import heap_data
        runs = heap_data.load_all(a.mimir, a.sweep, a.census)
        if a.runs:
            pickle.dump(runs, open(a.runs, "wb"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    R1 = q1(runs)
    R2, pts = q2(runs)
    R3 = q3(runs)
    R4 = q4(runs)
    R6 = q6(runs)
    docs = {"heap-q1.json": R1, "heap-q1-lines.json": q1_lines(runs), "heap-q2.json": R2, "heap-q3.json": R3, "heap-q4.json": {"per_run": R4, "summary": q4_summary(R4)},
            "heap-q5.json": q5(R1, runs), "heap-q6.json": R6}
    for name, obj in docs.items():
        (out / name).write_text(json.dumps(obj, indent=1, sort_keys=True, default=float) + "\n")
    try:
        import heap_figs
        heap_figs.make(Path(a.figs), runs, R1, pts, R3, R4, R6)
    except ImportError as e:
        print("figures skipped:", e)


if __name__ == "__main__":
    main()
