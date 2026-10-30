"""Q-N3 (docs/plan/q-n3-rank-right-atom.md): labels and C-free features at every pick of the stock packer where a free member of the
seed's known cluster was queued. Read only on the round 9 run roots; no VPR run.

For each pack (design, cons, shuffle): replay with q2gap.analyse_run(on_pick=...), and for each event compute, for the pick and every queued
unclustered molecule, the features of the plan from D' and the cluster built so far (never C). Two views: `full` (D' as is) and `real`
(dummy atoms of Step B deleted from the cluster state and the nets).

Usage: python q3feat.py <r9 root> <out dir> [design,design,...]
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

import heap_lib as hl
import heappick_lib as hp
import q2gap

NEAR = 0.90
FEATS = ("shared_nets", "common_nbrs", "members_2hop", "absorbed", "d_pins", "fanout", "seq_gap", "nearcrit_shared")
# +1: higher is better for the right atom; -1: lower is better (score is the negative)
SIGN = {"shared_nets": 1, "common_nbrs": 1, "members_2hop": 1, "absorbed": 1, "d_pins": -1, "fanout": -1, "seq_gap": -1, "nearcrit_shared": 1}
SAMPLE_OK = 3  # keep 1 in 3 right picks


def keep_ok(design, cons, sh, cseq, idx):
    h = hashlib.sha256(f"{design}|{cons}|{sh}|{cseq}|{idx}".encode()).digest()
    return h[0] % SAMPLE_OK == 0


class Ctx:
    """Netlist indices of D' for one view. `drop` = atoms left out (dummies) in the real view."""

    def __init__(self, g, pins_by_atom, drop=frozenset()):
        al, na = g["alias"], g["net_atom"]
        self.drop = drop
        ins = {}
        for a, (_k, nets) in g["comb"].items():
            ins[a] = [hl._resolve(n, al) for n in nets]
        for q, d in g["seq"].items():
            ins[q] = [hl._resolve(d, al)]
        self.driver = {}
        for r, a in na.items():
            self.driver[r] = a
        self.ins = {}
        for a, nets in ins.items():
            if a in drop:
                continue
            self.ins[a] = [n for n in nets if self.driver.get(n) not in drop]
        sinks = collections.defaultdict(set)
        for a, nets in self.ins.items():
            for n in nets:
                sinks[n].add(a)
        self.sink_n = {n: len(s) for n, s in sinks.items()}
        self.pos = {hl._resolve(p, al) for p in g["pos"]}
        self.net_atoms, self.atom_nets = {}, collections.defaultdict(set)
        for n, s in sinks.items():
            if len(s) > q2gap.HF:
                continue
            mem = set(s)
            d = self.driver.get(n)
            if d is not None and d not in drop:
                mem.add(d)
            self.net_atoms[n] = mem
            for a in mem:
                self.atom_nets[a].add(n)
        self.adj = {}
        self.adj2 = {}
        self.pins = pins_by_atom
        self.sinks = sinks
        # sequential level: fewest flip-flops on a path from a primary input (0-1 BFS)
        self.lvl = self._levels(g)

    def nbrs(self, a):
        r = self.adj.get(a)
        if r is None:
            r = set()
            for n in self.atom_nets.get(a, ()):
                r |= self.net_atoms[n]
            r.discard(a)
            self.adj[a] = r
        return r

    def nbrs2(self, a):
        r = self.adj2.get(a)
        if r is None:
            r = set(self.nbrs(a))
            for b in list(r):
                r |= self.nbrs(b)
            r.discard(a)
            self.adj2[a] = r
        return r

    def _levels(self, g):
        INF = 10 ** 9
        dist = {}
        dq = collections.deque()
        seq = set(g["seq"])
        succ = collections.defaultdict(list)
        for a, nets in self.ins.items():
            for n in nets:
                d = self.driver.get(n)
                if d is None or d not in self.ins and d not in seq:
                    # primary input or hard block output: a source
                    w = 1 if a in seq else 0
                    if dist.get(a, INF) > w:
                        dist[a] = w
                        dq.append(a)
                else:
                    succ[d].append(a)
        # Dijkstra with 0/1 weights
        import heapq
        h = [(d, a) for a, d in dist.items()]
        heapq.heapify(h)
        while h:
            d, a = heapq.heappop(h)
            if dist.get(a, INF) < d:
                continue
            for b in succ.get(a, ()):
                w = d + (1 if b in seq else 0)
                if dist.get(b, INF) > w:
                    dist[b] = w
                    heapq.heappush(h, (w, b))
        return dist


def ext_inputs(ctx, atoms):
    out = set()
    for a in atoms:
        for n in ctx.ins.get(a, ()):
            if ctx.driver.get(n) not in atoms:
                out.add(n)
    return out


class EventState:
    """Per event cluster state (Cl before the pick) for one view."""

    def __init__(self, ctx, cl_atoms):
        self.ctx = ctx
        self.cl = {a for a in cl_atoms if a not in ctx.drop}
        self.ncl = set()
        for a in self.cl:
            self.ncl |= ctx.nbrs(a)
        self.ext = ext_inputs(ctx, self.cl)
        lv = [ctx.lvl[a] for a in self.cl if a in ctx.lvl]
        self.lvl_mean = sum(lv) / len(lv) if lv else None

    def feats(self, atoms, root):
        ctx = self.ctx
        M = {a for a in atoms if a not in ctx.drop}
        if not M:
            return None
        cl = self.cl
        nets = set()
        for a in M:
            nets |= ctx.atom_nets.get(a, set())
        f1 = sum(1 for n in nets if ctx.net_atoms[n] & cl)
        nm = set()
        for a in M:
            nm |= ctx.nbrs(a)
        nm -= M
        f2 = len((nm & self.ncl) - cl - M)
        h2 = set()
        for a in M:
            h2 |= ctx.nbrs2(a)
        f3 = len(cl & h2)
        both = cl | M
        f4 = sum(1 for n in nets if ctx.net_atoms[n] <= both and n not in ctx.pos and ctx.net_atoms[n] & M)
        # pin pressure
        outs = {n for n, d in ((n, ctx.driver.get(n)) for n in self.ext) if d in M}
        newin = set()
        for a in M:
            for n in ctx.ins.get(a, ()):
                if ctx.driver.get(n) not in both:
                    newin.add(n)
        f5 = len((self.ext - outs) | newin) - len(self.ext)
        f6 = ctx.sink_n.get(root, 0) if root not in ctx.drop else 0
        lv = [ctx.lvl[a] for a in M if a in ctx.lvl]
        f7 = abs(sum(lv) / len(lv) - self.lvl_mean) if lv and self.lvl_mean is not None else float("nan")
        f8 = 0
        for a in M:
            for n, c in ctx.pins.get(a, ()):
                if c >= NEAR and ctx.driver.get(n) in cl:
                    f8 += 1
        for b in cl:
            for n, c in ctx.pins.get(b, ()):
                if c >= NEAR and ctx.driver.get(n) in M:
                    f8 += 1
        return [f1, f2, f3, f4, f5, f6, f7, f8]


def timing_gain(ctx, cl, root):
    """VPR's timing gain of the root atom against the cluster: largest pin criticality over nets joining it to the cluster
    (greedy_candidate_selector.cpp update_timing_gain_values)."""
    best = 0.0
    # nets driven by cluster atoms that the root reads
    for n, c in ctx.pins.get(root, ()):
        if ctx.driver.get(n) in cl and c > best:
            best = c
    # nets read by cluster atoms that the root drives: all sink pins of that net
    for b in cl:
        for n, _c in ctx.pins.get(b, ()):
            if ctx.driver.get(n) == root:
                for s in ctx.sinks.get(n, ()):
                    for n2, c2 in ctx.pins.get(s, ()):
                        if n2 == n and c2 > best:
                            best = c2
    return best


def run_pack(args):
    root, outdir, design, cons, sh = args
    d = Path(root) / design / cons / sh
    runs = sorted(d.glob("run-*/stock.s1/design.net"))
    dst = Path(outdir) / f"{design}.{cons}.{sh}.jsonl.gz"
    if not runs or dst.exists():
        return design, cons, sh, None
    census = hp.parse_census_full(d / "census.tsv")
    cmap = q2gap.read_c(d / "affinity.tsv")
    atom_loc, clbs, _o = hp.parse_net_clusters(runs[0])
    g = hl.parse_blif_graph((d / "design.blif").read_text(), set(cmap))
    build = json.loads((d.parent / "build.json").read_text())
    vat = json.loads((d / "vatoms.json").read_text())
    lo, hi = build["cells_real"], build["cells_real"] + build["dummies"]
    dummies = {a for i in range(lo, min(hi, len(vat))) for a in vat[i]}
    pins_by_atom = collections.defaultdict(list)
    for (_cs, atom), lst in census["pins"].items():
        pins_by_atom[atom].extend(lst)
    full = Ctx(g, pins_by_atom)
    real = Ctx(g, pins_by_atom, drop=frozenset(dummies))
    events = []

    def cb(kind, info):
        # the replay mutates `clustered` afterwards: decide here which queued molecules are still free
        info["free_roots"] = {r for r in info["snap"] if r in info["root_mol"] and id(info["root_mol"][r]) not in info["clustered"]}
        info["clustered"] = None
        events.append((kind, info))
    res = q2gap.analyse_run(census, cmap, atom_loc, clbs, g, want_edges=False, on_pick=cb)
    out = []
    n_b = n_ok = 0
    for kind, info in events:
        pm = info["pick"]
        if kind == "ok" and not keep_ok(design, cons, sh, info["cseq"], info["idx"]):
            continue
        n_b += kind == "b"
        n_ok += kind == "ok"
        snap = dict(info["snap"])
        snap[pm["root"]] = pm["qgain"]
        rm = info["root_mol"]
        cands = []
        for r, gain in snap.items():
            m = rm.get(r)
            if m is None or (r not in info["free_roots"] and r != pm["root"]):
                continue
            cands.append((r, gain, m))
        sf = EventState(full, info["cl_atoms"])
        sr = EventState(real, info["cl_atoms"])
        rows = []
        for r, gain, m in cands:
            ff = sf.feats(m["atoms"], r)
            isd = any(a in dummies for a in m["atoms"])
            fr = None if isd else sr.feats(m["atoms"], r)
            rows.append({"r": r, "gain": gain, "pick": r == pm["root"], "right": r in info["right"], "dummy": isd,
                         "tg": timing_gain(full, sf.cl, r), "f": ff, "fr": fr, "w": m["w"]})
        a_rec = census["atoms"].get(pm["root"])
        out.append({"kind": kind, "design": design, "cons": cons, "sh": sh, "cseq": info["cseq"], "idx": info["idx"], "n_cl": len(sf.cl),
                    "pick_src": pm["src"], "tg_A": a_rec["tg"] if a_rec else None, "cands": rows})
    with gzip.open(dst, "wt") as fh:
        for o in out:
            fh.write(json.dumps(o) + "\n")
    return design, cons, sh, (n_b, n_ok, res["events"].get("b", 0))


def main(argv):
    root, outdir = argv[0], Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    only = set(argv[2].split(",")) if len(argv) > 2 else None
    nproc = int(argv[3]) if len(argv) > 3 else 6
    jobs = []
    for p in Path(root).iterdir():
        if not (p.is_dir() and (p / "own").is_dir()) or (only and p.name not in only):
            continue
        for cons in ("own", "foreign"):
            for sh in ("sh0", "sh1", "sh2", "sh3"):
                c = p / cons / sh / "census.tsv"
                if c.exists():
                    jobs.append((c.stat().st_size, (str(root), str(outdir), p.name, cons, sh)))
    jobs = [j for _s, j in sorted(jobs)]
    with Pool(nproc) as pool:
        for design, cons, sh, r in pool.imap_unordered(run_pack, jobs):
            print(design, cons, sh, r, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
