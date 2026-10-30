"""Q-N3 step 4 (docs/plan/q-n3-rank-right-atom.md): are the Q-N1b oracle seeds special?

The Q-N1b log (`NORNS_ORACLE c candidates trials exact jaccard outsiders missing |c|`) does not name the winning seed. For a cluster rebuilt
exactly (exact = 1) the winner is the `trials`-th candidate, candidates being the molecules of the known cluster c in ascending root-atom id
(plan of Q-N1b, Overlay item 2); every molecule of c is unclustered at that moment because the trial reproduced c. The molecules come from the
stock pack census of the same D' (ordered shuffle sh0), the root-atom id order is the order of the root's statement in `design.blif` (the BLIF
reader numbers atoms in file order). Reconstruction check: the number of molecules of c must equal the logged `candidates`; clusters where it
does not are dropped and counted. Non-exact clusters have no recoverable winner (best Jaccard); they are not used.

Features of a molecule's root atom (netlist only): fan-in (distinct inputs), pack-time criticality (largest P-record pin criticality),
closeness in the graph of the cluster's molecules (nets of at most 32 sinks), sequential level (fewest flip-flops from a primary input),
fan-out. Compared: the winning seed against the other molecules of c (pairwise AUC, share of members it beats, ties half) and against the stock
seed of c (first stock cluster whose seed is a molecule of c).

Usage: python q3seed.py <r9 root> <n1b runs> <out json> [all|real] [min trials]
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

import numpy as np

import heap_lib as hl
import heappick_lib as hp
import q2gap
import q3feat

FEATS = ("fanin", "crit", "closeness", "seq_level", "fanout")
NB, SEED = 10000, 20261030


def statement_order(blif_text):
    """{atom name: position} of the statements of a BLIF in file order (.names and .latch outputs; .subckt: every pin net, first wins)."""
    pos = {}
    k = 0
    cur = ""
    for raw in blif_text.splitlines():
        s = raw.split("#")[0].rstrip()
        if s.endswith("\\"):
            cur += s[:-1] + " "
            continue
        line = cur + s
        cur = ""
        f = line.split()
        if not f:
            continue
        if f[0] == ".names":
            pos.setdefault(f[-1], k)
            k += 1
        elif f[0] == ".latch":
            pos.setdefault(f[2], k)
            k += 1
        elif f[0] == ".subckt":
            for p in f[2:]:
                if "=" in p:
                    pos.setdefault(p.split("=", 1)[1], k)
            k += 1
    return pos


def closeness(nodes, adj):
    """Closeness (mean inverse distance to the other nodes) of every node in the induced graph."""
    nodes = list(nodes)
    ns = set(nodes)
    out = {}
    for s in nodes:
        dist = {s: 0}
        dq = collections.deque([s])
        while dq:
            u = dq.popleft()
            for v in adj.get(u, ()):
                if v in ns and v not in dist:
                    dist[v] = dist[u] + 1
                    dq.append(v)
        out[s] = sum(1.0 / d for d in dist.values() if d > 0) / (len(nodes) - 1) if len(nodes) > 1 else 0.0
    return out


def design_clusters(root, runs, design, real_only=False, min_trials=1):
    d = Path(root) / design / "own" / "sh0"
    lines = []
    for ln in (Path(runs) / design / "oracle.s1" / "oracle.log").read_text().splitlines():
        f = ln.split("\t")
        if len(f) >= 9 and f[0] == "NORNS_ORACLE":
            lines.append({"c": int(f[1]), "cands": int(f[2]), "trials": int(f[3]), "exact": int(f[4]), "jac": float(f[5])})
    census = hp.parse_census_full(d / "census.tsv")
    cmap = q2gap.read_c(d / "affinity.tsv")
    g = hl.parse_blif_graph((d / "design.blif").read_text(), set(cmap))
    order = statement_order((d / "design.blif").read_text())
    pins = collections.defaultdict(list)
    for (_cs, atom), lst in census["pins"].items():
        pins[atom].extend(lst)
    ctx = q3feat.Ctx(g, pins)
    build = json.loads((d.parent / "build.json").read_text())
    vat = json.loads((d / "vatoms.json").read_text())
    lo, hi = build["cells_real"], build["cells_real"] + build["dummies"]
    dummies = {a for i in range(lo, min(hi, len(vat))) for a in vat[i]}
    mols = [m for m in census["mols"] if m["cseq"] in census["closed"]]
    by_c = collections.defaultdict(list)
    for m in mols:
        labs = collections.Counter(cmap[a] for a in m["atoms"] if a in cmap)
        if labs:
            by_c[labs.most_common(1)[0][0]].append(m)
    stock_seed = {}
    for m in mols:
        if m["idx"] == 0:
            labs = collections.Counter(cmap[a] for a in m["atoms"] if a in cmap)
            if labs:
                stock_seed.setdefault(labs.most_common(1)[0][0], m)

    def feat_of(m, clos):
        r = m["root"]
        fanin = len(set(ctx.ins.get(r, ())))
        crit = max([c for _n, c in ctx.pins.get(r, ())] or [0.0])
        return [fanin, crit, clos.get(r, 0.0), ctx.lvl.get(r, float("nan")), ctx.sink_n.get(r, 0)]

    rows = []
    stats = collections.Counter()
    for ln in lines:
        c = ln["c"]
        ms = sorted(by_c.get(c, []), key=lambda m: order.get(m["root"], 10 ** 9))
        n_all = len(ms)
        if real_only:
            ms = [m for m in ms if not any(a in dummies for a in m["atoms"])]
        stats["clusters"] += 1
        stats["exact"] += ln["exact"]
        if not ln["exact"]:
            continue
        if n_all != ln["cands"] or not (1 <= ln["trials"] <= n_all):
            stats["exact_dropped_count_mismatch"] += 1
            continue
        if len(ms) < 2:
            stats["exact_single_molecule"] += 1
            continue
        if ln["trials"] < min_trials:
            stats["exact_skipped_min_trials"] += 1
            continue
        stats["used"] += 1
        full = sorted(by_c.get(c, []), key=lambda m: order.get(m["root"], 10 ** 9))
        win = full[ln["trials"] - 1]
        if win not in ms:
            stats["winner_is_dummy_dropped"] += 1
            continue
        # closeness within the cluster's molecules
        adj = collections.defaultdict(set)
        owner = {}
        for m in ms:
            for a in m["atoms"]:
                owner[a] = m["root"]
        for m in ms:
            for a in m["atoms"]:
                for b in ctx.nbrs(a):
                    if b in owner and owner[b] != m["root"]:
                        adj[m["root"]].add(owner[b])
        clos = closeness([m["root"] for m in ms], adj)
        fw = feat_of(win, clos)
        fo = [feat_of(m, clos) for m in ms if m is not win]
        ss = stock_seed.get(c)
        stats["trials1"] += ln["trials"] == 1
        row = {"c": c, "n": len(ms), "trials": ln["trials"], "win": fw, "others": fo, "stock": None, "win_is_stock": ss is not None and ss["root"] == win["root"]}
        if ss is not None and ss["root"] != win["root"] and ss in ms:
            row["stock"] = feat_of(ss, clos)
        rows.append(row)
    return rows, dict(stats)


def cmp(a, b):
    if a != a or b != b:
        return 0.5
    return 1.0 if a > b else (0.5 if a == b else 0.0)


def main(argv):
    root, runs, out = argv[0], argv[1], Path(argv[2])
    real_only = len(argv) > 3 and argv[3] == "real"
    min_trials = int(argv[4]) if len(argv) > 4 else 1
    per = {}
    tot = collections.Counter()
    for design in sorted(p.name for p in Path(runs).iterdir() if (p / "oracle.s1" / "oracle.log").exists()):
        rows, st = design_clusters(root, runs, design, real_only, min_trials)
        tot.update(st)
        vs_mem = [[] for _ in FEATS]
        vs_stock = [[] for _ in FEATS]
        wis = 0
        for r in rows:
            for i in range(len(FEATS)):
                vs_mem[i].append(np.mean([cmp(r["win"][i], o[i]) for o in r["others"]]))
                if r["stock"] is not None:
                    vs_stock[i].append(cmp(r["win"][i], r["stock"][i]))
            wis += r["win_is_stock"]
        per[design] = {"n": len(rows), "vs_members": [float(np.mean(v)) if v else None for v in vs_mem],
                       "vs_stock": [float(np.mean(v)) if v else None for v in vs_stock], "n_stock": len(vs_stock[0]), "win_is_stock": wis, "stats": st}
    rng = np.random.default_rng(SEED)
    res = {}
    for name, key in (("winner_vs_members", "vs_members"), ("winner_vs_stock_seed", "vs_stock")):
        for i, f in enumerate(FEATS):
            vals = np.array([v[key][i] for v in per.values() if v[key][i] is not None])
            if len(vals) == 0:
                continue
            bs = np.array([vals[rng.integers(0, len(vals), len(vals))].mean() for _ in range(NB)])
            res[f"{name}|{f}"] = {"mean": float(vals.mean()), "lo": float(np.quantile(bs, 0.05)), "hi": float(np.quantile(bs, 0.95)), "n_designs": int(len(vals)),
                                  "p": float(max(2 * min((bs <= 0.5).mean(), (bs >= 0.5).mean()), 1 / NB))}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"features": FEATS, "totals": dict(tot), "results": res, "per_design": per,
                               "win_is_stock_total": sum(v["win_is_stock"] for v in per.values()), "n_used": sum(v["n"] for v in per.values())}, indent=1))
    print("wrote", out, dict(tot))


if __name__ == "__main__":
    main(sys.argv[1:])
