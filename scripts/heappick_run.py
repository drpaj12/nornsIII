"""Heap-picking lane: the per-run measurements P1 to P7 (one run = design x seed). Pure functions of the loaded run (heap_data), the full
census, the packed .net and the BLIF-derived extras (heappick_data); no file access here except through the arguments.

  analyze_run(run, cen, net, ex) -> dict of scalars and small lists
"""
from __future__ import annotations

import collections

import heap_lib as hl
import heappick_groups as pg
import heappick_lib as pl

HEAP = 0.90


def _ctx(run, cen, net, ex):
    atom_loc, clbs, _others = net
    A = run["atoms"]
    loc = {a: l for a, l in atom_loc.items() if a in A}
    votes = collections.defaultdict(collections.Counter)
    for a, (clb, _f) in loc.items():
        votes[clb][A[a]["cseq"]] += 1
    cseq_of_clb = {c: v.most_common(1)[0][0] for c, v in votes.items()}
    mol = pl.molecule_of(cen)
    root = {a: m["root"] for a, m in mol.items()}
    fail = {}
    queued = set()
    for pos, cseq, r, src, st in cen["fails"]:
        fail[(cseq, r)] = st
    for _pos, t, cseq, r, _x, _g in cen["events"]:
        if t == "Q":
            queued.add((cseq, r))
    g = ex["g"]
    hard_after = set()
    for a, (_k, ins) in g["comb"].items():
        if any(g["net_atom"].get(hl._resolve(n, g["alias"])) in g["hard"] for n in ins):
            hard_after.add(a)
    for q, dnet in g["seq"].items():
        if g["net_atom"].get(hl._resolve(dnet, g["alias"])) in g["hard"]:
            hard_after.add(q)
    qinfo = {}
    picks = collections.defaultdict(list)
    for pos, t, cseq, r_, x, gain in cen["events"]:
        if t == "Q" and (cseq, r_) not in qinfo:
            qinfo[(cseq, r_)] = (pos, gain, x)
        elif t == "M":
            picks[cseq].append((pos, gain, r_))
    return {"hard_after": hard_after, "qinfo": qinfo, "picks": picks, "loc": loc, "cseq_of_clb": cseq_of_clb, "fles": {c: v["fles"] for c, v in clbs.items()}, "root": root, "fail": fail,
            "queued": queued, "chain": ex["chains"], "mol": mol, "clbs": clbs,
            "clb_mixed": sum(1 for v in votes.values() if len(v) > 1)}


def _heap_sets(run):
    A = run["atoms"]
    R = {a for a, v in A.items() if v["rc"] is not None and v["rc"] >= HEAP}
    Pk = {a for a, v in A.items() if v["pc"] is not None and v["pc"] >= HEAP}
    return R, Pk


def near_paths(run, thr=HEAP):
    """Reported paths with crit >= thr whose atom sequence is distinct, as lists of atom names."""
    seen, out = set(), []
    for pi in sorted(run["paths"]):
        p = run["paths"][pi]
        if (p["crit"] or 0) < thr:
            continue
        key = tuple(p["atoms"])
        if key in seen:
            continue
        seen.add(key)
        out.append(p["atoms"])
    return out


# ---------------------------------------------------------------------------------------------------
def ex_hard_after(ctx):
    """Atoms with an input net driven by a hard block (set by analyze_run)."""
    return ctx.get("hard_after", set())


def p1(run, cen, R, Pk, ctx):
    """Stale criticality: pack-time crit against post-route crit, picks and order."""
    A = run["atoms"]
    mols = [m for m in cen["mols"] if m["cseq"] in cen["closed"]]
    heap_picks = leave = seed_heap = seed_leave = 0
    cand_heap = cand_leave = 0
    for m in mols:
        atoms = [a for a in m["atoms"] if a in A]
        if not atoms:
            continue
        mpc = max((A[a]["pc"] for a in atoms if A[a]["pc"] is not None), default=None)
        if mpc is None or mpc < HEAP:
            continue
        gone = not any(a in R for a in atoms)
        heap_picks += 1
        leave += gone
        if m["kind"] == "seed":
            seed_heap += 1
            seed_leave += gone
        else:
            cand_heap += 1
            cand_leave += gone
    # post-route heap: late and filler
    mol = ctx["mol"]
    late = filler_unrel = gainless = tot = lowpc = 0
    for a in R:
        m = mol.get(a)
        if m is None:
            continue
        tot += 1
        if A[a]["crank"] > 0.5:
            late += 1
        if m["kind"] == "cand" and m["src"] == 7:
            filler_unrel += 1
        if m["kind"] == "cand" and m["qgain"] <= 0:
            gainless += 1
        if A[a]["pc"] is None or A[a]["pc"] < 0.5:
            lowpc += 1
    # static criticality: how pc and rc relate on atoms seen in a report
    seen = [(A[a]["pc"], A[a]["rc"]) for a in A if A[a]["rc"] is not None and A[a]["pc"] is not None]
    rho = hl.spearman([x for x, _ in seen], [y for _, y in seen]) if len(seen) > 3 else None
    cats = collections.defaultdict(lambda: [0, 0])
    hard = ex_hard_after(ctx)
    for a in Pk:
        v = A[a]
        keys = ["typ=" + v["typ"], "op=" + v["op"], "blk=" + v["blk"], "lvl=" + ("1-3" if v["lvl"] <= 3 else "4-6" if v["lvl"] <= 6 else "7-10" if v["lvl"] <= 10 else "11+")]
        if a in hard:
            keys.append("after_hard_block")
        if ctx["chain"].get(a, (0, 1))[1] > 1:
            keys.append("carry_chain")
        for k in keys:
            cats[k][0] += 1
            cats[k][1] += a in R
    return {"cats": {k: v for k, v in cats.items()}, "heap_picks": heap_picks, "heap_picks_leave": leave, "seed_heap": seed_heap, "seed_leave": seed_leave,
            "cand_heap": cand_heap, "cand_leave": cand_leave, "n_picks": len(mols),
            "route_heap_n": tot, "route_late": late, "route_unrelated": filler_unrel, "route_gainless": gainless, "route_lowpc": lowpc,
            "rho_pc_rc": rho}


# ---------------------------------------------------------------------------------------------------
def p2_p3_p5(run, cen, R, ctx, ex):
    """Capacity cuts (P2), reconvergence (P3), filler (P5) on the near-critical paths."""
    A = run["atoms"]
    loc = ctx["loc"]
    typ = {a: v["typ"] for a, v in A.items()}
    paths = near_paths(run)
    path_rows = []
    edges = {}  # (u, v) -> (cause, refused_too)
    succ, pred = collections.defaultdict(set), collections.defaultdict(set)
    for atoms in paths:
        subs = pl.path_cores(atoms, loc, typ)
        blen = visits = floor10 = floor20 = 0
        for seq in subs:
            b = sum(1 for a in seq if typ[a] in ("lut", "adder"))
            if b == 0:
                continue
            blen += b
            visits += len(pl.segments(seq, loc))
            floor10 += pl.path_floor(b)
            floor20 += pl.path_floor(b, 20)
            for u, v in zip(seq, seq[1:]):
                succ[u].add(v)
                pred[v].add(u)
                if loc[u][0] != loc[v][0] and (u, v) not in edges:
                    edges[(u, v)] = pl.crossing_cause(u, v, ctx)
        if blen == 0:
            continue
        has_chain = any(a in ex["chains"] and ex["chains"][a][1] > 1 for seq in subs for a in seq)
        path_rows.append({"blen": blen, "visits": visits, "floor10": floor10, "floor20": floor20, "chain": has_chain, "hard": len(subs) > 1})
    n = len(path_rows)
    out = {"n_paths": n}
    if n:
        out["mean_visits"] = sum(r["visits"] for r in path_rows) / n
        out["mean_floor10"] = sum(r["floor10"] for r in path_rows) / n
        out["mean_floor20"] = sum(r["floor20"] for r in path_rows) / n
        out["share_over_floor10"] = sum(r["visits"] > r["floor10"] for r in path_rows) / n
        out["share_over_floor20"] = sum(r["visits"] > r["floor20"] for r in path_rows) / n
        out["share_at_floor10"] = sum(r["visits"] <= r["floor10"] for r in path_rows) / n
        out["mean_excess10"] = sum(r["visits"] - r["floor10"] for r in path_rows) / n
        short = [r for r in path_rows if r["blen"] <= 10 and not r["hard"]]
        out["n_short"] = len(short)
        out["short_split"] = (sum(r["visits"] > 1 for r in short) / len(short)) if short else None
        lng = [r for r in path_rows if r["blen"] > 10]
        out["n_long"] = len(lng)
        out["long_extra"] = (sum(r["visits"] - r["floor10"] for r in lng) / len(lng)) if lng else None
        ch = [r for r in path_rows if r["chain"]]
        nch = [r for r in path_rows if not r["chain"]]
        out["chain_excess"] = (sum(r["visits"] - r["floor10"] for r in ch) / len(ch)) if ch else None
        out["nochain_excess"] = (sum(r["visits"] - r["floor10"] for r in nch) / len(nch)) if nch else None
        out["n_chain_paths"] = len(ch)
        out["blen_mean"] = sum(r["blen"] for r in path_rows) / n
    cause = collections.Counter(c for c, _r in edges.values())
    out["n_cross_edges"] = len(edges)
    out["cause"] = dict(cause)
    out["full_also_refused"] = sum(1 for c, rf in edges.values() if c == "full" and rf)
    chain_pair = sum(1 for (u, v) in edges if u in ex["chains"] and v in ex["chains"])
    out["cross_chain_pairs"] = chain_pair
    # P3 branch atoms: atoms with >= 2 distinct successors (fork) or predecessors (join) on the near-critical paths
    br = collections.Counter()
    branch_edges = set()
    for role, nb in (("fork", succ), ("join", pred)):
        for a, ns in nb.items():
            if len(ns) < 2 or a not in loc:
                continue
            inc = [x for x in ns if loc[x][0] == loc[a][0]]
            kind = "all" if len(inc) == len(ns) else ("none" if not inc else "split")
            br[(role, kind)] += 1
            for x in ns:
                key = (a, x) if role == "fork" else (x, a)
                if key in edges:
                    branch_edges.add(key)
    out["branch"] = {f"{r}_{k}": v for (r, k), v in br.items()}
    out["branch_cross_edges"] = len(branch_edges)
    multi = collections.Counter()
    for atoms in paths:
        for a in set(atoms):
            multi[a] += 1
    out["atoms_on_ge2_paths"] = sum(1 for a, c in multi.items() if c >= 2 and a in loc)
    out["atoms_on_paths"] = sum(1 for a in multi if a in loc)
    cause_branch = collections.Counter(edges[e][0] for e in branch_edges)
    out["cause_at_branch"] = dict(cause_branch)
    # P5: filler in clusters holding heap atoms
    by_clb = collections.defaultdict(lambda: {"heap": set(), "all": set()})
    for a, (clb, fle) in loc.items():
        by_clb[clb]["all"].add(fle)
        if a in R:
            by_clb[clb]["heap"].add(fle)
    tot_f = heap_f = n_hc = 0
    for clb, d in by_clb.items():
        if not d["heap"]:
            continue
        n_hc += 1
        tot_f += ctx["fles"].get(clb, len(d["all"]))
        heap_f += len(d["heap"])
    all_f = sum(ctx["fles"].values())
    out["p5"] = {"heap_clusters": n_hc, "heap_fles": heap_f, "fles_in_heap_clusters": tot_f, "all_fles": all_f,
                 "min_clusters": -(-heap_f // pl.CLB_FLES), "clusters_total": len(by_clb)}
    srcs = collections.Counter()
    mol = ctx["mol"]
    for a, (clb, fle) in loc.items():
        if a in R or not by_clb[clb]["heap"]:
            continue
        m = mol.get(a)
        srcs["seed" if (m and m["kind"] == "seed") else (pl.SRC_NAMES.get(m["src"], "unknown") if m else "unknown")] += 1
    out["p5"]["filler_src"] = dict(srcs)
    # crossings whose earlier cluster closed full: how many of those clusters still hold a non-heap FLE
    avoid = 0
    nfull = 0
    for (u, v), (c, _rf) in edges.items():
        if c != "full":
            continue
        nfull += 1
        su, sv = ctx["cseq_of_clb"][loc[u][0]], ctx["cseq_of_clb"][loc[v][0]]
        eclb = loc[u][0] if su <= sv else loc[v][0]
        if len(by_clb[eclb]["heap"]) < ctx["fles"].get(eclb, 0):
            avoid += 1
    out["p5"]["full_cross"] = nfull
    # for each capacity cut: was the atom left behind (the one in the later cluster) ever queued in the earlier cluster, and did the
    # picks that followed outrank it by queue-time gain?
    det = collections.Counter()
    for (u, v), (c, _rf) in edges.items():
        if c != "full":
            continue
        su, sv = ctx["cseq_of_clb"][loc[u][0]], ctx["cseq_of_clb"][loc[v][0]]
        early, late = (su, v) if su <= sv else (sv, u)
        root = ctx["root"].get(late)
        q = ctx["qinfo"].get((early, root))
        if q is None:
            cat = "never_queued"
        else:
            after = [g for pos, g, _r in ctx["picks"].get(early, ()) if pos > q[0]]
            cat = "queued_outranked" if all(g >= q[1] - 1e-9 for g in after) else "queued_then_dropped"
            if not after:
                cat = "queued_cluster_closed_next"
        det[(cat, "heap" if late in R else "other")] += 1
    out["full_detail"] = {f"{k[0]}|{k[1]}": v for k, v in det.items()}
    out["p5"]["full_cross_with_filler"] = avoid
    # heap atoms of a cluster whose path neighbours are elsewhere: share of heap FLEs in heap clusters that hold a single heap path atom only
    return out


# ---------------------------------------------------------------------------------------------------
def p4(run, cen, ctx, eps_list=(0.0, 0.01, 0.05)):
    A = run["atoms"]
    evs = pl.tie_events(cen["events"], eps_list)
    root_atom = {m["root"]: m["root"] for m in cen["mols"]}
    n = len(evs)
    res = {"n_choice": n, "not_top": sum(1 for e in evs if not e["is_top"])}
    for eps in eps_list:
        tied = [e for e in evs if e["is_top"] and e["tied"][eps]]
        k = f"e{eps}"
        res[k] = {"ties": len(tied)}
        zero = sum(1 for e in tied if abs(e["gain"]) < 1e-9)
        res[k]["ties_zero_gain"] = zero
        lost = better = early = hot = 0
        for e in tied:
            comp = [r for r in e["tied"][eps] if r != e["root"]]
            roots = [e["root"]] + comp
            pcs = [A[r]["pc"] if r in A and A[r]["pc"] is not None else 0.0 for r in roots]
            rcs = [A[r]["rc"] if r in A and A[r]["rc"] is not None else 0.0 for r in roots]
            if max(pcs) >= HEAP:
                hot += 1
                # picked is less post-route-critical than some tied competitor
                if rcs[0] < max(rcs[1:]) - 1e-9 and max(rcs[1:]) >= HEAP:
                    lost += 1
                if rcs[0] > max(rcs[1:]) + 1e-9:
                    better += 1
            qp = e["qpos"]
            if all(qp.get(e["root"], 0) <= qp.get(r, 0) for r in comp):
                early += 1
        res[k].update({"hot": hot, "picked_lower_rc_than_heap_competitor": lost, "picked_higher_rc": better, "picked_earliest_queued": early})
        srcc = collections.Counter(e["src"] for e in tied)
        res[k]["src"] = {str(s): c for s, c in srcc.items()}
    # queue-time gain against the gain at pick time (staleness): A-record sums
    stale = tot = 0
    mols = {(m["cseq"], m["idx"]): m for m in cen["mols"]}
    for m in cen["mols"]:
        if m["kind"] != "cand" or m["cseq"] not in cen["closed"] or not m["atoms"]:
            continue
        now = sum(cen["atoms"][a]["gain"] for a in m["atoms"] if a in cen["atoms"]) + m["bonus"] + m["attr"]
        tot += 1
        if abs(now - m["qgain"]) > 0.1 * max(abs(m["qgain"]), 1e-6):
            stale += 1
    res["stale_gain"] = {"cand": tot, "differs_10pct": stale}
    return res


# ---------------------------------------------------------------------------------------------------
def p6(run, cen, R, Pk, ctx):
    """Max over pins: how many pins carry the timing gain, and what the timing gain inherited from a net's other sinks does."""
    A = run["atoms"]
    pins = cen["pins"]
    rows = []
    for a, v in A.items():
        m = ctx["mol"].get(a)
        if m is None:
            continue
        pl_ = pins.get((m["cseq"], a))
        if not pl_:
            continue
        crits = sorted({n: c for n, c in pl_}.values(), reverse=True)  # distinct nets
        if len(crits) < 2:
            continue
        rows.append((a, crits[0], crits[1], sum(crits) / len(crits), len(crits)))
    heap = [r for r in rows if r[1] >= HEAP]
    single = [r for r in heap if r[2] < 0.5]
    multi = [r for r in heap if r[2] >= HEAP]
    out = {"atoms_multi_pin": len(rows), "heap_multi_pin": len(heap), "single_pin": len(single), "multi_pin": len(multi),
           "single_stay": sum(1 for r in single if r[0] in R), "multi_stay": sum(1 for r in multi if r[0] in R)}
    # predictors of post-route heap membership among atoms with >=2 distinct input nets
    pm = [r[1] for r in rows]
    pmean = [r[3] for r in rows]
    y = [1 if r[0] in R else 0 for r in rows]
    out["auc_max"] = pl.auc([x for x, t in zip(pm, y) if t], [x for x, t in zip(pm, y) if not t])
    out["auc_mean"] = pl.auc([x for x, t in zip(pmean, y) if t], [x for x, t in zip(pmean, y) if not t])
    # timing gain inheritance: a candidate chosen on tg >= 0.9 whose own input pins are all below 0.5
    inh = inh_stay = own = own_stay = 0
    for a, c in cen["atoms"].items():
        if a not in A or c["idx"] == 0 or c["cseq"] not in cen["closed"]:
            continue
        if c["tg"] < HEAP:
            continue
        pl_ = pins.get((c["cseq"], a), [])
        own_max = max((x for _n, x in pl_), default=0.0)
        if own_max < 0.5:
            inh += 1
            inh_stay += a in R
        elif own_max >= HEAP:
            own += 1
            own_stay += a in R
    out["tg_inherited"] = {"inh": inh, "inh_stay": inh_stay, "own": own, "own_stay": own_stay}
    return out


# ---------------------------------------------------------------------------------------------------
def p7(run, R, ex, ctx, thr=pl.HF_THRESHOLD):
    """Near-critical nets (edges of the reported near-critical paths) against the pack high-fanout threshold."""
    A = run["atoms"]
    g = ex["g"]
    fo = ex["fo"]
    alias = g["alias"]
    drv = ex["drv_nets"]
    edges = {}
    for atoms in near_paths(run):
        for u, v in zip(atoms, atoms[1:]):
            if (u, v) in edges or u not in A:
                continue
            best = None
            cand_in = []
            if v in g["comb"]:
                cand_in = g["comb"][v][1]
            elif v in g["seq"]:
                cand_in = [g["seq"][v]]
            drives = set(drv.get(u, ()))
            for n in cand_in:
                r = hl._resolve(n, alias)
                if r in drives or g["net_atom"].get(r) == u:
                    f = fo.get(r, 0)
                    best = f if best is None else max(best, f)
            if best is not None:
                edges[(u, v)] = best
    nets = {}
    for (u, v), f in edges.items():
        nets.setdefault(u, f)
        nets[u] = max(nets[u], f)
    n_edges = len(edges)
    hf = {u: f for u, f in nets.items() if f > thr}
    # baseline: share of all driver atoms with a net above the threshold
    allf = {}
    for a, nl in drv.items():
        if a in A:
            allf[a] = max((fo.get(hl._resolve(n, alias), 0) for n in nl), default=0)
    out = {"near_edges": n_edges, "near_nets": len(nets), "hf_nets": len(hf), "edges_on_hf": sum(1 for (u, _v), f in edges.items() if f > thr),
           "bands": {str(b): sum(1 for f in nets.values() if f > b) for b in (8, 16, 32, 64)},
           "all_drivers": len(allf), "all_hf_drivers": sum(1 for f in allf.values() if f > thr),
           "max_fanout": max(nets.values()) if nets else 0}
    out["hf_list"] = [(u, f) for u, f in sorted(nets.items(), key=lambda kv: -kv[1]) if f > 8]
    return out


def analyze_run(run, cen, net, ex):
    ctx = _ctx(run, cen, net, ex)
    R, Pk = _heap_sets(run)
    out = {"design": run["design"], "seed": run["seed"], "atoms": len(run["atoms"]), "R": len(R), "Pk": len(Pk), "clb_mixed": ctx["clb_mixed"]}
    out["p1"] = p1(run, cen, R, Pk, ctx)
    out["p235"] = p2_p3_p5(run, cen, R, ctx, ex)
    out["p4"] = p4(run, cen, ctx)
    out["p6"] = p6(run, cen, R, Pk, ctx)
    out["p7"] = p7(run, R, ex, ctx)
    out["p8"] = pg.group_rows(run, ex, ctx["loc"], R, seed=run["seed"])
    out["p9"] = p9(run, cen, R, ctx, ex)
    return out, ctx, R, Pk


# ---------------------------------------------------------------------------------------------------
def p9(run, cen, R, ctx, ex):
    """Detector counts for the exception-pattern catalogue (before packing: netlist, levels, pre-pack pin criticality) and, for the
    seed's packing, what happened to the atoms the detector flags."""
    A = run["atoms"]
    g = ex["g"]
    al, na, fo = g["alias"], g["net_atom"], ex["fo"]
    loc = ctx["loc"]
    logic = {a for a, v in A.items() if v["typ"] in ("lut", "adder", "ff")}
    out = {"logic_atoms": len(logic)}
    # R1 carry chains of >= 8 adders
    ch = ex["chains"]
    chain_atoms = {a for a, (_p, ln) in ch.items() if ln >= 8 and a in A}
    heads = [a for a, (p, ln) in ch.items() if p == 0 and ln >= 8]
    out["chain"] = {"chains": len(heads), "atoms": len(chain_atoms), "in_heap": len(chain_atoms & R), "max_len": max((ln for _p, ln in ch.values()), default=0)}
    # R3 collector registers: flip-flops whose output feeds no logic atom (only pads, or nothing)
    sinks = collections.Counter()
    for a, (_k, ins) in g["comb"].items():
        for n in ins:
            sinks[na.get(hl._resolve(n, al))] += 1
    for q, dnet in g["seq"].items():
        sinks[na.get(hl._resolve(dnet, al))] += 1
    ffs = [a for a in logic if A[a]["typ"] == "ff"]
    coll = [a for a in ffs if sinks.get(a, 0) == 0]
    out["collector"] = {"ff": len(ffs), "collector": len(coll), "collector_in_heap": sum(1 for a in coll if a in R), "other_ff_in_heap": sum(1 for a in ffs if sinks.get(a, 0) > 0 and a in R)}
    # R4 deep logic: non-adder atoms at LUT level >= 11
    deep = {a for a in logic if A[a]["lvl"] >= 11 and a not in ch}
    out["deep"] = {"atoms": len(deep), "in_heap": len(deep & R), "max_level": max((A[a]["lvl"] for a in logic), default=0),
                   "pack_heap_deep": sum(1 for a in deep if A[a]["pc"] is not None and A[a]["pc"] >= HEAP)}
    # R5 fork atoms with >= 2 pre-pack-critical consumers; R6 high-fanout nets with a pre-pack-critical sink; R9 equal-criticality siblings
    crit_cons = collections.defaultdict(dict)  # driver atom -> {consumer: crit}
    net_sinkcrit = collections.defaultdict(list)  # root net -> [crit of each sink pin]
    for (_cseq, c), pl_ in cen["pins"].items():
        for net, cr in pl_:
            r = hl._resolve(net, al)
            d = na.get(r)
            net_sinkcrit[r].append(cr)
            if d is not None and cr >= HEAP:
                crit_cons[d][c] = max(cr, crit_cons[d].get(c, 0.0))
    forks = [d for d, cs in crit_cons.items() if len(cs) >= 2 and d in loc]
    fk = collections.Counter()
    for d in forks:
        same = [c for c in crit_cons[d] if c in loc and loc[c][0] == loc[d][0]]
        tot = len([c for c in crit_cons[d] if c in loc])
        fk["all" if len(same) == tot else ("none" if not same else "split")] += 1
    out["fork"] = {"atoms": len(forks), "outcome": dict(fk), "in_heap": sum(1 for d in forks if d in R)}
    hf = [n for n, f in fo.items() if f > pl.HF_THRESHOLD and n not in al]
    hfc = [n for n in hf if net_sinkcrit.get(n) and max(net_sinkcrit[n]) >= HEAP]
    out["hf"] = {"nets": len(hf), "pre_pack_critical": len(hfc), "max_fanout": max((fo[n] for n in hf), default=0)}
    mid = [n for n, f in fo.items() if 8 < f <= pl.HF_THRESHOLD and n not in al]
    midc = [n for n in mid if net_sinkcrit.get(n) and max(net_sinkcrit[n]) >= HEAP]
    mk = collections.Counter()
    for n in midc:
        d = na.get(n)
        if d in A:
            mk[A[d]["op"] if A[d]["op"] != "none" else "reg" if A[d]["typ"] == "ff" else "other"] += 1
    out["mid"] = {"nets": len(mid), "pre_pack_critical": len(midc), "driver_kind": dict(mk)}
    sib = 0
    for n, cs in net_sinkcrit.items():
        top = [c for c in cs if c >= HEAP]
        if len(top) >= 3 and max(top) - min(top) < 1e-3:
            sib += 1
    out["siblings"] = {"nets": sib}
    # R10 hard-block neighbours
    out["hard"] = {"after_hard": len(ctx["hard_after"] & logic), "after_hard_in_heap": len(ctx["hard_after"] & R)}
    return out
