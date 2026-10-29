"""Heap-picking lane (docs/plan/heap-picking.md): pure helpers for the questions P1 to P8. Reuses heap_lib (bootstrap, Spearman,
census parser, BLIF graph) and adds: the full census parser (M/A/P/Q/F/K in file order), the packed-netlist (.net) cluster reader,
crossing and cause classification along a path, queue-tie simulation, net fan-out, and HDL-graph word tie shares.

Terms. cseq = cluster number of the census; clb = cluster index of the packed .net; FLE = one fracturable logic element slot
(10 per clb). Heap at t = atoms with crit >= t (pc: pack-time, static; rc: post-route, from the 1000-path report).
"""
from __future__ import annotations

import collections
import math
import re
from pathlib import Path

CLB_FLES = 10
HF_THRESHOLD = 32  # VPR packing high-fanout threshold of the clb type in this architecture (vpr.out: "clb:32")
SRC_NAMES = {-1: "unknown", 0: "seed", 1: "conn/timing", 2: "affinity", 3: "transitive", 4: "high fanout", 5: "attraction", 6: "ram", 7: "unrelated"}


# ---------------------------------------------------------------------------------------------------
# census (full)

def parse_census_full(path):
    """Full census of one run, in file order.
    Returns dict:
      mols  list of dict(cseq, idx, kind, src, n, qgain, bonus, attr, base, dom, root, pos)  (M records)
      atoms {atom: dict(cseq, idx, sharing, conn, tg, gain)}  (A records; the atom's last record of a closed cluster)
      pins  {(cseq, atom): [(net, crit)]}
      events list of (pos, 'Q'|'M'|'F', cseq, root, src_or_status, gain)  in file order
      closed {cseq: dict(pos, n_added, n_proposed, queue_left)}
      fails list of (pos, cseq, root, src, status)
    """
    mols, atoms, pins, events, closed, fails = [], {}, collections.defaultdict(list), [], {}, []
    cur_m = None
    with Path(path).open(encoding="utf-8", errors="replace") as fh:
        for pos, line in enumerate(fh):
            f = line.rstrip("\n").split("\t")
            t = f[0]
            if t == "M":
                m = {"cseq": int(f[1]), "idx": int(f[2]), "kind": f[3], "src": int(f[4]), "n": int(f[5]), "qgain": float(f[6]),
                     "bonus": float(f[7]), "attr": float(f[8]), "base": float(f[9]), "dom": int(f[10]), "root": f[11], "pos": pos, "atoms": []}
                mols.append(m)
                cur_m = m
                events.append((pos, "M", m["cseq"], m["root"], m["src"], m["qgain"]))
            elif t == "A":
                a = {"cseq": int(f[1]), "idx": int(f[2]), "sharing": float(f[4]), "conn": float(f[5]), "tg": float(f[6]), "gain": float(f[7])}
                atoms[f[3]] = a
                if cur_m is not None and cur_m["cseq"] == a["cseq"] and cur_m["idx"] == a["idx"]:
                    cur_m["atoms"].append(f[3])
            elif t == "P":
                pins[(int(f[1]), f[2])].append((f[3], float(f[4])))
            elif t == "Q":
                events.append((pos, "Q", int(f[1]), f[2], int(f[3]), float(f[4])))
            elif t == "F":
                events.append((pos, "F", int(f[1]), f[2], int(f[4]), 0.0))
                fails.append((pos, int(f[1]), f[2], int(f[3]), int(f[4])))
            elif t == "K":
                closed[int(f[1])] = {"pos": pos, "n_added": int(f[2]), "n_proposed": int(f[3]), "queue_left": int(f[4])}
    return {"mols": mols, "atoms": atoms, "pins": pins, "events": events, "closed": closed, "fails": fails}


def molecule_of(census):
    """{atom: molecule dict} for the molecules of closed clusters."""
    out = {}
    for m in census["mols"]:
        if m["cseq"] not in census["closed"]:
            continue
        for a in m["atoms"]:
            out[a] = m
    return out


# ---------------------------------------------------------------------------------------------------
# packed netlist (.net)

_BLK = re.compile(r'^(\t*)<block name="([^"]*)" instance="([a-zA-Z0-9_]+)\[(\d+)\]"')
_LEAVES = {"lut", "adder", "ff", "latch"}


def parse_net_clusters(path):
    """Cluster structure of a VPR packed netlist (.net).
    Returns (atom_loc, clbs): atom_loc {atom: (clb_index, fle_index)} for the primitives of clb clusters (lut, adder, ff);
    clbs {clb_index: dict(fles=<used fle count>, type='clb')} for clb type clusters. Other cluster types (io, memory, mult) are
    returned in `others` as {index: (type, [atoms])}.
    """
    atom_loc, clbs, others = {}, {}, {}
    cur_type, cur_idx, cur_fle = None, None, None
    fle_used = set()
    with Path(path).open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _BLK.match(line)
            if not m:
                continue
            dep = len(m.group(1))
            name, inst, idx = m.group(2), m.group(3), int(m.group(4))
            if dep == 1:
                cur_type, cur_idx, cur_fle = inst, (inst, idx), None
                if inst == "clb":
                    clbs[cur_idx] = {"fles": 0, "type": "clb"}
                else:
                    others[cur_idx] = (inst, [])
                continue
            if cur_type is None:
                continue
            if cur_type == "clb":
                if dep == 2 and inst == "fle":
                    cur_fle = idx
                    if name != "open":
                        clbs[cur_idx]["fles"] += 1
                elif inst in _LEAVES and name != "open":
                    atom_loc[name] = (cur_idx, cur_fle)
            elif name != "open" and inst not in ("inpad", "outpad"):
                others[cur_idx][1].append(name)
            elif cur_type == "io" and name != "open":
                others[cur_idx][1].append(name)
    return atom_loc, clbs, others


# ---------------------------------------------------------------------------------------------------
# paths: crossings and causes

def path_cores(atoms, loc, typ):
    """Split a path into the runs of logic atoms (lut, adder, ff of clb clusters) between pads and hard blocks; a launching register
    at the head of the path is dropped (it is packed with the logic of the previous stage, not with this path).
    atoms: path atom names; loc {atom: (clb, fle)}; typ {atom: 'lut'|'adder'|'ff'|...}. Returns a list of atom lists."""
    subs, cur = [], []
    for a in atoms:
        if a in loc and typ.get(a) in ("lut", "adder", "ff"):
            if not cur or cur[-1] != a:
                cur.append(a)
        elif cur:
            subs.append(cur)
            cur = []
    if cur:
        subs.append(cur)
    if subs and atoms and atoms[0] in loc and typ.get(atoms[0]) == "ff" and subs[0] and subs[0][0] == atoms[0]:
        subs[0] = subs[0][1:]
    return [s for s in subs if s]


def segments(seq, loc):
    """Runs of consecutive atoms in the same clb: list of (clb, [atoms])."""
    segs = []
    for a in seq:
        c = loc[a][0]
        if segs and segs[-1][0] == c:
            segs[-1][1].append(a)
        else:
            segs.append((c, [a]))
    return segs


def path_floor(blen, per_cluster=CLB_FLES):
    """Fewest clusters a path of `blen` BLEs (LUT or adder atoms) can touch: ceil(blen / capacity), at least 1."""
    return max(1, math.ceil(blen / per_cluster))


def crossing_cause(u, v, ctx):
    """Why u and v (consecutive on a path, different clusters) are apart. ctx keys:
      loc {atom: (clb, fle)}, cseq_of_clb {clb: cseq}, fles {clb: used fle count}, root {atom: molecule root}, fail {(cseq, root): status},
      queued {(cseq, root)}.
    The earlier-packed cluster of the two closed without taking the other atom; the cause is read from that cluster:
      full              it closed with all CLB_FLES slots used (a capacity cut), even if the atom was also refused earlier
      refused_pins      not full; the other atom's molecule was refused with legalizer status 1 (pin feasibility)
      refused_route     not full; refused with status 2 (intra-cluster routing)
      queued_not_taken  not full; the molecule was queued but never taken before the cluster closed
      not_proposed      not full; the molecule never entered the queue (not reachable through the search)
    Returns (cause, refused_too) with refused_too True when a full cluster had also refused the molecule."""
    cu, cv = ctx["loc"][u][0], ctx["loc"][v][0]
    su, sv = ctx["cseq_of_clb"].get(cu), ctx["cseq_of_clb"].get(cv)
    if su is None or sv is None:
        return ("unknown", False)
    if su <= sv:
        early, late, eclb = su, v, cu
    else:
        early, late, eclb = sv, u, cv
    root = ctx["root"].get(late)
    st = ctx["fail"].get((early, root))
    if ctx["fles"].get(eclb, 0) >= CLB_FLES:
        return ("full", st is not None)
    if st == 1:
        return ("refused_pins", True)
    if st == 2:
        return ("refused_route", True)
    if (early, root) in ctx["queued"]:
        return ("queued_not_taken", False)
    return ("not_proposed", False)


# ---------------------------------------------------------------------------------------------------
# queue ties (P4)

def tie_events(events, eps_list=(0.0, 0.01, 0.05)):
    """Replays the census in file order. Pending queue per cluster = molecules with a Q record, not yet added (M) and not refused (F);
    the queue is cleared when a cluster changes. For each candidate pick (M, kind cand) with another molecule pending: records
    dict(cseq, root, src, gain, second, second_root, n_pending, is_top, tied={eps: [roots]}, qpos {root: pos}).
    The gains are the queue-time gains the heap holds (VPR never refreshes the gain of a molecule already in the queue)."""
    pend, cur, out = {}, None, []
    qpos = {}
    for pos, t, cseq, root, x, gain in events:
        if cseq != cur:
            pend, cur, qpos = {}, cseq, {}
        if t == "Q":
            pend[root] = (gain, x)
            qpos[root] = pos
        elif t == "F":
            pend.pop(root, None)
        elif t == "M":
            if root in pend:
                g, src = pend.pop(root)
                if pend:
                    top2 = max(pend.items(), key=lambda kv: kv[1][0])
                    ev = {"cseq": cseq, "root": root, "src": src, "gain": g, "second": top2[1][0], "second_root": top2[0], "n_pending": len(pend) + 1,
                          "is_top": g >= top2[1][0] - 1e-9, "tied": {}, "qpos": {root: qpos.get(root, -1)}}
                    for eps in eps_list:
                        lim = g - eps * abs(g) - (1e-9 if eps == 0.0 else 0.0)
                        tied = [r for r, (gg, _s) in pend.items() if gg >= lim]
                        ev["tied"][eps] = tied
                        for r in tied:
                            ev["qpos"][r] = qpos.get(r, -1)
                    out.append(ev)
            else:
                pass
    return out


# ---------------------------------------------------------------------------------------------------
# netlist fan-out

_OUTPINS = ("cout", "sumout", "out", "data_out", "q")


def net_fanout(blif_text):
    """{net: number of sink pins} of a VTR-dialect BLIF (.names inputs, .latch input, subckt non-output pins; clock pins left out)."""
    cur = ""
    lines = []
    for raw in blif_text.splitlines():
        s = raw.split("#")[0].rstrip()
        if s.endswith("\\"):
            cur += s[:-1] + " "
            continue
        lines.append(cur + s)
        cur = ""
    fo = collections.Counter()
    for ln in lines:
        f = ln.split()
        if not f:
            continue
        if f[0] == ".names":
            for n in f[1:-1]:
                fo[n] += 1
        elif f[0] == ".latch":
            fo[f[1]] += 1
        elif f[0] == ".subckt":
            for p in f[2:]:
                if "=" not in p:
                    continue
                pin, net = p.split("=", 1)
                base = pin.split("[")[0]
                if base in _OUTPINS or base in ("clk", "clock"):
                    continue
                fo[net] += 1
    return fo


# ---------------------------------------------------------------------------------------------------
# pair ties (P8)

def build_adjacency(g, fo, resolve, hub=HF_THRESHOLD):
    """Atom adjacency of a BLIF graph (heap_lib.parse_blif_graph) for the pair tests: (succ, pred), {atom: set of atoms}. A connection through
    a net with more than `hub` sinks is left out (VPR's packer gives no attraction through such nets)."""
    succ, pred = collections.defaultdict(set), collections.defaultdict(set)
    na, al = g["net_atom"], g["alias"]

    def link(n, consumer):
        r = resolve(n, al)
        d = na.get(r)
        if d is None or d == consumer or fo.get(r, 0) > hub:
            return
        succ[d].add(consumer)
        pred[consumer].add(d)

    for a, (_k, ins) in g["comb"].items():
        for n in ins:
            link(n, a)
    for q, dnet in g["seq"].items():
        link(dnet, q)
    return succ, pred


def pair_tied(i, j, succ, pred):
    """(flow, any) for a pair of atoms. flow: a net joins them, or one atom feeds the other through a single atom in between.
    any: flow, or they feed a common atom, or a common atom feeds both."""
    e = frozenset()
    si, sj, pi, pj = succ.get(i, e), succ.get(j, e), pred.get(i, e), pred.get(j, e)
    flow = j in si or i in sj or (not si.isdisjoint(pj)) or (not sj.isdisjoint(pi))
    anyp = flow or (not si.isdisjoint(sj)) or (not pi.isdisjoint(pj))
    return flow, anyp


def sample_pairs(items, k, rng):
    """All pairs of `items` when there are at most k, else k distinct random pairs."""
    n = len(items)
    total = n * (n - 1) // 2
    if total <= k:
        return [(items[a], items[b]) for a in range(n) for b in range(a + 1, n)]
    seen = set()
    out = []
    while len(out) < k:
        a, b = rng.randrange(n), rng.randrange(n)
        if a == b:
            continue
        key = (a, b) if a < b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        out.append((items[key[0]], items[key[1]]))
    return out


# ---------------------------------------------------------------------------------------------------
# small stats

def share(num, den):
    return (num / den) if den else None


def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def auc(pos, neg):
    """Probability that a random positive scores above a random negative (ties 1/2). None if either list is empty."""
    if not pos or not neg:
        return None
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks = {}
    i = 0
    n = len(allv)
    rsum = 0.0
    while i < n:
        j = i
        while j + 1 < n and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            if allv[k][1] == 1:
                rsum += avg
        i = j + 1
    npos, nneg = len(pos), len(neg)
    return (rsum - npos * (npos + 1) / 2.0) / (npos * nneg)
