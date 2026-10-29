"""Seed-signal feature extractor (docs/plan/seed-signal.md, amendments 1 and 2). Offline: no VPR.

For one round 9 build directory (`<r9-out>/<design>/<own|foreign>`) it parses a shuffle of D' (design.blif), maps atoms to the
vertices and clusters of C, builds a Mimir `Netlist` (one node per atom; an adder is two nodes), and measures local regions
with the Mimir code imported from the Mimir checkout (never copied): `mimir.hutton.characterise`, `levels`, `seq_levels`,
`mimir.rent.fit` / `measure`. Rows: one per cluster and one per LUT. Labels are not computed here (see seed_signal.py).

Regions (cluster rows): R1r cluster real atoms, R1a with dummies, R2d1/2/4 fan-in cone of depth 1/2/4 (through combinational
nodes, stop at FFs, hard blocks, pads), R3d1/2/4 fan-out cone, R4k1/2 k-hop ball (undirected, not through pads or nets of more
than 32 sinks). LUT rows: its own fan-in cone and fan-out cone of depth 1/2/4. A region is a sub-netlist: nodes inside keep
their kind; a fan-in from outside becomes a PI; nodes read from outside or by a PO are the outputs.
Only scalar rows of `characterise` (bin "") are kept; histogram bins are not columns.
"""

from __future__ import annotations

import collections
import csv
import gzip
import json
import math
import os
import sys
from pathlib import Path

MIMIR = Path(os.environ.get("MIMIR_ROOT", str(Path.home() / "odin3-ws" / "mimir")))
if str(MIMIR) not in sys.path:
    sys.path.insert(0, str(MIMIR))
from mimir import hutton, rent  # noqa: E402
from mimir.netlist import COMB, CONST, HARD, LATCH, PI, Netlist  # noqa: E402

NET_D, LUT_D, ADD_D, CARRY_D = 1.338, 0.261, 0.15, 0.1  # proxy timing (plan)
BALL_FANOUT_CAP = 32
SKIP_NETS = {"gnd", "vcc", "unconn"}
DEPTHS = (1, 2, 4)


class Parsed:
    """The statements of design.blif up to the first `.end`."""

    def __init__(self, path: Path):
        self.pis: list = []
        self.pos: list = []
        self.stm: list = []  # (kind, ins, outs, atom, rows)
        lines = []
        buf = ""
        for raw in path.read_text(errors="replace").splitlines():
            raw = raw.split("#")[0].rstrip()
            if raw.endswith("\\"):
                buf += raw[:-1] + " "
                continue
            lines.append(buf + raw)
            buf = ""
        cur = None
        for ln in lines:
            t = ln.split()
            if not t:
                continue
            if t[0] == ".end":
                break
            if t[0] == ".inputs":
                self.pis += t[1:]
            elif t[0] == ".outputs":
                self.pos += t[1:]
            elif t[0] == ".names":
                cur = ["lut", t[1:-1], [t[-1]], t[-1], []]
                self.stm.append(cur)
            elif t[0] == ".latch":
                self.stm.append(["ff", [t[1]], [t[2]], t[2], []])
                cur = None
            elif t[0] == ".subckt":
                ports = dict(x.split("=", 1) for x in t[2:])
                if t[1] == "adder":
                    self.stm.append(["add", [ports["a"], ports["b"], ports["cin"]], [ports["sumout"], ports["cout"]],
                                     ports["cout"], []])
                else:
                    self.stm.append(["hard", [], [], t[1], list(ports.values())])
                cur = None
            elif t[0] == ".model":
                if self.stm or self.pis:
                    break
            elif cur is not None and not t[0].startswith("."):
                cur[4].append(t)


def tt_bits(rows: list, k: int) -> int:
    """Truth table as an int over 2**k minterms (bit m: input i = bit i of m)."""
    on = 0
    off_rows = False
    for r in rows:
        cube, val = (r[0], r[1]) if len(r) == 2 else ("", r[0])
        if val == "0":
            off_rows = True
        free = [i for i, ch in enumerate(cube) if ch == "-"]
        base = sum(1 << i for i, ch in enumerate(cube) if ch == "1")
        for m in range(1 << len(free)):
            x = base
            for j, i in enumerate(free):
                if m >> j & 1:
                    x |= 1 << i
            on |= 1 << x
    if off_rows:
        on = ((1 << (1 << k)) - 1) & ~on
    return on


def classify(rows: list, k: int) -> tuple:
    """(used inputs, function class) from the truth table."""
    if k == 0:
        return 0, "const"
    n = 1 << k
    tt = tt_bits(rows, k)

    def bit(m: int) -> int:
        return tt >> m & 1

    used = [i for i in range(k) if any(bit(m) != bit(m ^ (1 << i)) for m in range(n))]
    if not used:
        return 0, "const"
    if len(used) == 1:
        return 1, "buf_inv"
    # reduce to the used inputs
    seen = {}
    for m in range(n):
        key = tuple(m >> i & 1 for i in used)
        seen[key] = bit(m)
    ones = sum(seen.values())
    tot = len(seen)
    parity_ok = all(v == (sum(key) & 1) for key, v in seen.items()) or all(v != (sum(key) & 1) for key, v in seen.items())
    if parity_ok:
        return len(used), "xor_like"
    if ones == 1 or tot - ones == 1:
        return len(used), "and_or_like"
    if len(used) >= 3:
        for s in used:
            lits = []
            for sv in (0, 1):
                f = {tuple(v for j, v in zip(used, key) if j != s): val for key, val in seen.items() if key[used.index(s)] == sv}
                cand = set()
                rest = [j for j in used if j != s]
                for ix, j in enumerate(rest):
                    if all(val == key[ix] for key, val in f.items()):
                        cand.add((j, 0))
                    if all(val != key[ix] for key, val in f.items()):
                        cand.add((j, 1))
                lits.append(cand)
            if lits[0] and lits[1] and any(a[0] != b[0] for a in lits[0] for b in lits[1]):
                return len(used), "mux_like"
    return len(used), "other"


class Build:
    def __init__(self, build_dir: Path, shuffle: int = 1):
        self.dir = Path(build_dir)
        self.name = f"{self.dir.parent.name}/{self.dir.name}"
        self.shuffle = shuffle
        self.rec = json.loads((self.dir / "build.json").read_text())
        self.struct = json.loads((self.dir / "struct.json").read_text())
        sh = self.dir / f"sh{shuffle}"
        self.shdir = sh
        self.vatoms = json.loads((sh / "vatoms.json").read_text())
        self.aff = {}
        for line in (sh / "affinity.tsv").read_text().splitlines():
            a, c = line.split("\t")
            self.aff[a] = int(c)
        self.cl = self.struct["cl"]
        self.w = self.struct["w"]
        self.K = self.struct["K"]
        nreal = self.rec["cells_real"] + self.rec["const_generators"]
        self.is_dummy = [nreal <= i < nreal + self.rec["dummies"] for i in range(len(self.cl))]
        self.is_const = [v in (["gnd"], ["vcc"]) for v in self.vatoms]
        self.vertex_of_atom = {a: v for v, atoms in enumerate(self.vatoms) for a in atoms}
        self.parsed = Parsed(sh / "design.blif")
        self._netlist()
        self._timing()

    # ---- netlist of atoms
    def _netlist(self) -> None:
        p = self.parsed
        nl = Netlist(self.name)
        self.nl = nl
        driver: dict = {}
        clk = "clk"
        for s in p.pis:
            driver[s] = nl.add(PI)
        if clk in driver:
            nl.clocks = {driver[clk]}
        for c in ("gnd", "vcc"):
            driver[c] = nl.add(CONST)
        self.tag: list = [""] * len(nl)
        self.node_vertex: list = [-1] * len(nl)
        self.node_stm: list = [None] * len(nl)
        pend = []

        def mk(kind: str, tag: str, vtx: int, stm) -> int:
            n = nl.add(kind)
            self.tag.append(tag)
            self.node_vertex.append(vtx)
            self.node_stm.append(stm)
            return n

        hard_nets = collections.Counter()
        for si, (kind, ins, outs, atom, extra) in enumerate(p.stm):
            if kind == "hard":
                continue
            v = self.vertex_of_atom.get(atom, -1)
            if kind == "lut" and not ins:
                continue  # constant generators (gnd, vcc) are the CONST nodes
            if kind == "add":
                ns = mk(COMB, "add", v, si)
                nc = mk(COMB, "add", v, si)
                driver[outs[0]] = ns
                driver[outs[1]] = nc
                pend += [(ns, ins), (nc, ins)]
            else:
                n = mk(LATCH if kind == "ff" else COMB, kind, v, si)
                driver[outs[0]] = n
                pend.append((n, ins))
        self.hard_nodes = []
        for si, (kind, ins, outs, atom, extra) in enumerate(p.stm):
            if kind != "hard":
                continue
            n = mk(HARD, "hard", -1, si)
            self.hard_nodes.append(n)
            ins_n = []
            for net in extra:
                if net in SKIP_NETS:
                    continue
                if net in driver:
                    ins_n.append(net)
                else:
                    driver[net] = n  # an output of the hard block (net with no other driver)
            pend.append((n, ins_n))

        def res(net: str):
            if net in SKIP_NETS and net not in driver:
                return None
            return driver.get(net)

        for n, ins in pend:
            nl.fanin[n] = tuple(d for d in (res(x) for x in ins if x != clk) if d is not None and d != n)
        nl.po_drivers = [d for d in (res(x) for x in p.pos) if d is not None]
        self.driver = driver
        self.loop_edges_cut = self._cut_loops()
        self.sinks = nl.sinks()
        self.po = set(nl.po_drivers)
        self.lvl = hutton.levels(nl)
        self.slvl = hutton.seq_levels(nl)
        self.depth = max((self.lvl[v] for v in range(len(nl)) if nl.kind[v] == COMB), default=1) or 1
        self.sdepth = max(max(self.slvl), 1)
        self.vnodes: list = [[] for _ in self.vatoms]
        for n, v in enumerate(self.node_vertex):
            if v >= 0:
                self.vnodes[v].append(n)

    def _cut_loops(self) -> int:
        """D' can hold combinational loops (found in the pilot); Mimir's `levels` rejects them. Cut each back edge found by an
        iterative depth-first search over COMB nodes (the edge is removed from the fan-in) and count them."""
        nl = self.nl
        color = [0] * len(nl)
        cut = 0
        for root in range(len(nl)):
            if nl.kind[root] != COMB or color[root]:
                continue
            color[root] = 1
            stack = [(root, 0)]
            while stack:
                u, i = stack[-1]
                fan = nl.fanin[u]
                if i < len(fan):
                    stack[-1] = (u, i + 1)
                    v = fan[i]
                    if nl.kind[v] != COMB:
                        continue
                    if color[v] == 1:
                        nl.fanin[u] = tuple(x for j, x in enumerate(nl.fanin[u]) if j != i)
                        cut += 1
                        stack[-1] = (u, i)
                    elif color[v] == 0:
                        color[v] = 1
                        stack.append((v, 0))
                else:
                    color[u] = 2
                    stack.pop()
        return cut

    # ---- proxy pack-time criticality (no census in the pilot)
    def _timing(self) -> None:
        nl, n = self.nl, len(self.nl)
        arr = [0.0] * n
        indeg = [0] * n
        comb_sinks: list = [[] for _ in range(n)]
        for v in range(n):
            if nl.kind[v] == COMB:
                for u in set(nl.fanin[v]):
                    if nl.kind[u] == COMB:
                        indeg[v] += 1
                        comb_sinks[u].append(v)
        order = []
        ready = [v for v in range(n) if nl.kind[v] == COMB and indeg[v] == 0]
        while ready:
            u = ready.pop()
            order.append(u)
            for v in comb_sinks[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    ready.append(v)

        def edge(u: int, v: int) -> float:
            return CARRY_D if self.tag[u] == "add" and self.tag[v] == "add" else NET_D

        def dly(v: int) -> float:
            return ADD_D if self.tag[v] == "add" else LUT_D

        for v in order:
            arr[v] = max((arr[u] + edge(u, v) for u in nl.fanin[v]), default=0.0) + dly(v)
        end = 0.0
        for v in range(n):
            if nl.kind[v] in (LATCH, HARD):
                end = max([end] + [arr[u] + edge(u, v) for u in nl.fanin[v]])
        for u in self.po:
            end = max(end, arr[u] + NET_D)
        dmax = end or 1.0
        req = [dmax] * n  # required time at the output of v
        for u in reversed(order):
            r = dmax
            for v in self.sinks[u]:
                if nl.kind[v] == COMB:
                    r = min(r, req[v] - dly(v) - edge(u, v))
                else:
                    r = min(r, dmax - edge(u, v))
            if u in self.po:
                r = min(r, dmax - NET_D)
            req[u] = r
        self.crit = [0.0] * n
        for v in order:
            self.crit[v] = max(0.0, min(1.0, 1 - (req[v] - arr[v]) / dmax))
        for v in range(n):
            if nl.kind[v] == LATCH:
                d = max((arr[u] + edge(u, v) for u in nl.fanin[v]), default=0.0)
                r = dmax
                for s in self.sinks[v]:
                    r = min(r, (req[s] - dly(s) - edge(v, s)) if nl.kind[s] == COMB else dmax - edge(v, s))
                if v in self.po:
                    r = min(r, dmax - NET_D)
                self.crit[v] = max(0.0, min(1.0, 1 - min(dmax - d, r) / dmax))

    # ---- regions
    def cluster_nodes(self, c: int, real_only: bool) -> set:
        s = set()
        for v, cv in enumerate(self.cl):
            if cv == c and not self.is_const[v] and not (real_only and self.is_dummy[v]):
                s.update(self.vnodes[v])
        return s

    def cone(self, base: set, depth: int, forward: bool) -> set:
        nl = self.nl
        seen = set(base)
        frontier = set(base)
        for _ in range(depth):
            nxt = set()
            for u in frontier:
                if u not in base and nl.kind[u] != COMB:
                    continue
                for w in (self.sinks[u] if forward else nl.fanin[u]):
                    if w not in seen and nl.kind[w] in (COMB, LATCH, HARD):
                        seen.add(w)
                        nxt.add(w)
            frontier = nxt
        return seen

    def ball(self, base: set, k: int) -> set:
        nl = self.nl
        seen = set(base)
        frontier = set(base)
        for _ in range(k):
            nxt = set()
            for u in frontier:
                nb = list(nl.fanin[u]) + (self.sinks[u] if len(self.sinks[u]) <= BALL_FANOUT_CAP else [])
                for w in nb:
                    if w not in seen and nl.kind[w] in (COMB, LATCH, HARD):
                        seen.add(w)
                        nxt.add(w)
            frontier = nxt
        return seen

    def sub(self, nodes: set) -> Netlist:
        nl = self.nl
        out = Netlist(self.name)
        new: dict = {}
        ext: dict = {}
        for v in sorted(nodes):
            new[v] = out.add(nl.kind[v])
        for v in sorted(nodes):
            fan = []
            for u in nl.fanin[v]:
                if u in new:
                    fan.append(new[u])
                else:
                    if u not in ext:
                        ext[u] = out.add(CONST if nl.kind[u] == CONST else PI)
                    fan.append(ext[u])
            out.fanin[new[v]] = tuple(fan)
        pos = []
        for v in sorted(nodes):
            if v in self.po or any(s not in nodes for s in self.sinks[v]):
                pos.append(new[v])
        out.po_drivers = pos
        return out

    def metrics(self, nodes: set, prefix: str) -> dict:
        """Scalar Mimir structural rows of the region, plus the sequential-level depth."""
        res: dict = {}
        if not nodes:
            return res
        sn = self.sub(nodes)
        try:
            for metric, b, val in hutton.characterise(sn):
                if b == "":
                    res[f"{prefix}.{metric}"] = val
        except Exception as exc:  # noqa: BLE001 (a region the measurer rejects is a missing value, kept visible)
            res[f"{prefix}.error"] = str(exc)[:40]
        return res

    def grow_rent(self, base: set, prefix: str, radii=(1, 2, 3, 4)) -> dict:
        """Local Rent on growing balls around `base`: terminals T against nodes B, fitted by Mimir's own `fit`.
        low_confidence is kept (points < 5 is always the case for four radii)."""
        nl = self.nl
        pts_b, pts_t = [], []
        prev = -1
        for r in radii:
            blk = self.ball(base, r)
            if len(blk) == prev:
                continue
            prev = len(blk)
            t = 0
            drivers = set(blk) | {d for v in blk for d in nl.fanin[v]}
            for u in drivers:
                if nl.kind[u] == CONST:
                    continue
                pins = ([u] if u in blk else []) + [s for s in self.sinks[u] if s in blk]
                allp = ([u] if nl.kind[u] in (COMB, LATCH, HARD) else []) + self.sinks[u]
                ext = nl.kind[u] in (PI,) or u in self.po
                if pins and (ext or len(set(pins)) < len(set(allp))):
                    t += 1
            pts_b.append(float(len(blk)))
            pts_t.append(float(t))
        out = {f"{prefix}.rent_points": float(len(pts_b)), f"{prefix}.rent_lowconf": float(len(pts_b) < rent.LOW_POINTS)}
        if pts_b:
            out[f"{prefix}.rent_T_over_B"] = pts_t[0] / pts_b[0]
        c = rent.Curve(seed=0, depth=list(range(len(pts_b))), blocks=[1] * len(pts_b), size=pts_b, terminals=pts_t)
        f = rent.fit(c, sum(1 for k in nl.kind if k in (COMB, LATCH, HARD)))
        # Mimir's fit window (4 <= B <= N/32) is kept as it is; small designs give None, kept as a missing value
        out[f"{prefix}.rent_p"] = f.p if f else float("nan")
        out[f"{prefix}.rent_r2"] = f.r2 if f else float("nan")
        return out

    def reconv_excess(self, node: int, depth: int = 4) -> float:
        """Independent reconvergences in the fan-in cone (edges - nodes + 1 inside the cone; 0 for a tree)."""
        cone = self.cone({node}, depth, False)
        e = sum(1 for v in cone for u in set(self.nl.fanin[v]) if u in cone)
        return float(max(0, e - len(cone) + 1))

    # ---- atom (LUT) level
    def lut_nodes(self) -> list:
        return [n for n in range(len(self.nl)) if self.tag[n] == "lut" and self.node_vertex[n] >= 0 and not self.is_const[self.node_vertex[n]]]

    def lut_row(self, n: int, with_mimir: bool = True) -> dict:
        nl = self.nl
        v = self.node_vertex[n]
        stm = self.parsed.stm[self.node_stm[n]]
        k_decl = len(stm[1])
        used, fclass = classify(stm[4], k_decl)
        out_node = next((m for m in self.vnodes[v] if nl.kind[m] == LATCH), n)
        sinks_out = [s for s in self.sinks[out_node]]
        drives_ff = any(nl.kind[s] == LATCH for s in self.sinks[n])
        chain_adj = any(self.tag[s] == "add" for s in self.sinks[out_node]) or any(self.tag[u] == "add" for u in nl.fanin[n])
        row = {"build": self.name, "vertex": v, "cluster": self.cl[v], "atom": self.parsed.stm[self.node_stm[n]][3],
               "is_dummy": int(self.is_dummy[v]), "fn_class": fclass, "used_inputs": used, "inputs_declared": k_decl,
               "fanout": len(set(sinks_out)), "drives_ff": int(drives_ff), "chain_adjacent": int(chain_adj),
               "level": self.lvl[n], "level_frac": self.lvl[n] / self.depth, "seq_level": self.slvl[n],
               "seq_level_frac": self.slvl[n] / self.sdepth, "crit": self.crit[out_node] if out_node != n else self.crit[n],
               "crit_lut": self.crit[n], "reconv_excess4": self.reconv_excess(n, 4),
               "po_driver": int(out_node in self.po)}
        for d in DEPTHS:
            fi = self.cone({n}, d, False)
            fo = self.cone({out_node}, d, True)
            row[f"fanin_cone_d{d}"] = len(fi)
            row[f"fanout_cone_d{d}"] = len(fo)
            row[f"fanin_dummy_share_d{d}"] = sum(1 for x in fi if self.node_vertex[x] >= 0 and self.is_dummy[self.node_vertex[x]]) / len(fi)
            row[f"fanout_dummy_share_d{d}"] = sum(1 for x in fo if self.node_vertex[x] >= 0 and self.is_dummy[self.node_vertex[x]]) / len(fo)
            if with_mimir:
                row.update(self.metrics(fi, f"L2d{d}"))
                row.update(self.metrics(fo, f"L3d{d}"))
        if with_mimir:
            row.update(self.grow_rent({n}, "L4"))
        return row

    # ---- cluster level
    def cluster_rows(self, with_mimir: bool = True) -> list:
        nl = self.nl
        cl = self.cl
        K = self.K
        # vertex-level nets (logic nets of D', with pads and hard blocks as external)
        nets = []
        for u in range(len(nl)):
            if nl.kind[u] == CONST or self.tag[u] == "" and nl.kind[u] == PI and u in nl.clocks:
                continue
            vs = {self.node_vertex[u]} if self.node_vertex[u] >= 0 else set()
            sk = {self.node_vertex[s] for s in self.sinks[u] if self.node_vertex[s] >= 0}
            ext_sink = any(self.node_vertex[s] < 0 for s in self.sinks[u]) or u in self.po
            nets.append((self.node_vertex[u], sk - vs, ext_sink, nl.kind[u]))
        rows = []
        for real_only in (True, False):
            view = "r" if real_only else "a"

            def inview(x: int) -> bool:
                return x >= 0 and not self.is_const[x] and not (real_only and self.is_dummy[x])

            ext_in = collections.defaultdict(set)
            ext_out = collections.defaultdict(set)
            internal = collections.defaultdict(set)
            nb = collections.defaultdict(set)
            vnets = collections.defaultdict(set)
            vint = collections.defaultdict(set)
            vin = collections.defaultdict(set)
            vfan = collections.defaultdict(set)
            adj = collections.defaultdict(set)
            for ni, (d, sk, ext_sink, kind) in enumerate(nets):
                if d >= 0 and not inview(d):
                    continue
                sk = {x for x in sk if inview(x)}
                if not sk and not ext_sink:
                    continue
                if d < 0 and not sk:
                    continue
                pins = ([d] if d >= 0 else []) + sorted(sk)
                cs = {cl[x] for x in sk}
                dc = cl[d] if d >= 0 else None
                for c in cs:
                    if c != dc:
                        ext_in[c].add(ni)
                if d >= 0:
                    if ext_sink or any(c != dc for c in cs):
                        ext_out[dc].add(ni)
                    elif sk:
                        internal[dc].add(ni)
                        for x in pins:
                            vint[x].add(ni)
                allc = cs | ({dc} if dc is not None else set())
                for c in allc:
                    nb[c].update(allc - {c})
                for x in pins:
                    vnets[x].add(ni)
                for x in sk:
                    vin[x].add(ni)
                if d >= 0:
                    vfan[d].update(sk)
                grp = collections.defaultdict(list)
                for x in pins:
                    grp[cl[x]].append(x)
                for g in grp.values():
                    for a in g:
                        adj[a].update(set(g) - {a})
            for c in range(K):
                mem = [v for v in range(len(cl)) if cl[v] == c and inview(v)]
                memset = set(mem)
                has_const = int(any(cl[v] == c and self.is_const[v] for v in range(len(cl))))
                r = {"build": self.name, "cluster": c, "view": view, "K": K, "n_vertices": len(mem),
                     "has_const_generator": has_const,  # gnd/vcc are LUT atoms VPR instantiates itself: a construction artefact
                     "weight": sum(self.w[v] for v in mem) + (has_const if view == "a" else 0), "dummies": sum(1 for v in range(len(cl)) if cl[v] == c and self.is_dummy[v])}
                r["pin_pressure"] = len(ext_in[c]) / 40
                r["ext_nets"] = len(ext_in[c]) + len(ext_out[c])
                r["internal_nets"] = len(internal[c])
                r["tightness"] = r["ext_nets"] / max(1, len(internal[c]))
                r["real_fill"] = (r["weight"] - (has_const if view == "a" else 0)) / 10
                r["neighbours"] = len(nb[c])
                r["chain"] = int(any(self.w[v] > 1 for v in mem))
                # largest internal component
                seen: set = set()
                best = 0
                for s in mem:
                    if s in seen:
                        continue
                    comp = {s}
                    st = [s]
                    while st:
                        x = st.pop()
                        for y in adj[x]:
                            if y in memset and y not in comp:
                                comp.add(y)
                                st.append(y)
                    seen |= comp
                    best = max(best, len(comp))
                r["lcc"] = best
                nodes = [m for v in mem for m in self.vnodes[v]]
                cr = [max(self.crit[m] for m in self.vnodes[v]) for v in mem if self.vnodes[v]]
                r["crit_max"] = max(cr, default=float("nan"))
                r["crit_mean"] = sum(cr) / len(cr) if cr else float("nan")
                r["max_inputs"] = max((len(vin[v]) for v in mem), default=0)
                # atom features, best (max) and mean over members
                loy = [len(vint[v]) / len(vnets[v]) for v in mem if vnets[v]]
                r["loyalty_max"] = max(loy, default=float("nan"))
                r["loyalty_mean"] = sum(loy) / len(loy) if loy else float("nan")
                deg = [len(adj[v] & memset) for v in mem]
                r["intdeg_max"] = max(deg, default=0)
                clo = []
                for s in mem:
                    dist = {s: 0}
                    q = collections.deque([s])
                    while q:
                        x = q.popleft()
                        for y in adj[x]:
                            if y in memset and y not in dist:
                                dist[y] = dist[x] + 1
                                q.append(y)
                    tot = sum(dist.values())
                    clo.append((len(dist) - 1) / tot * (len(dist) - 1) / max(1, len(mem) - 1) if tot else 0.0)
                r["closeness_max"] = max(clo, default=0.0)
                r["fanout_max"] = max((len(vfan[v]) for v in mem), default=0)
                lv = [self.lvl[m] for m in nodes if nl.kind[m] == COMB]
                r["level_min"] = min(lv, default=0)
                r["level_max"] = max(lv, default=0)
                r["level_spread"] = r["level_max"] - r["level_min"]
                r["level_frac_mean"] = sum(lv) / len(lv) / self.depth if lv else 0.0
                sl = [self.slvl[m] for m in nodes]
                r["seq_level_mean_frac"] = sum(sl) / len(sl) / self.sdepth if sl else 0.0
                r["seq_level_spread"] = (max(sl) - min(sl)) if sl else 0
                fic = [len(self.cone({m}, 4, False)) for m in nodes if nl.kind[m] == COMB]
                foc = [len(self.cone({m}, 4, True)) for m in nodes if nl.kind[m] == COMB]
                r["atom_fanin_cone4_max"] = max(fic, default=0)
                r["atom_fanout_cone4_max"] = max(foc, default=0)
                r["atom_fanin_cone4_mean"] = sum(fic) / len(fic) if fic else 0.0
                r["atom_reconv4_max"] = max((self.reconv_excess(m, 4) for m in nodes if nl.kind[m] == COMB), default=0.0)
                nodeset = set(nodes)
                if with_mimir and nodeset:
                    r.update(self.metrics(nodeset, "R1"))
                    for d in DEPTHS:
                        r.update(self.metrics(self.cone(nodeset, d, False), f"R2d{d}"))
                        r.update(self.metrics(self.cone(nodeset, d, True), f"R3d{d}"))
                    for k in (1, 2):
                        r.update(self.metrics(self.ball(nodeset, k), f"R4k{k}"))
                    r.update(self.grow_rent(nodeset, "R4g"))
                rows.append(r)
        return rows


def write_csv_gz(path: Path, rows: list) -> None:
    cols: list = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, restval="")
        w.writeheader()
        w.writerows(rows)


def extract(build_dir: Path, shuffle: int = 1, with_mimir: bool = True, luts: bool = True) -> tuple:
    b = Build(build_dir, shuffle)
    cr = b.cluster_rows(with_mimir)
    lr = [b.lut_row(n, with_mimir) for n in b.lut_nodes()] if luts else []
    return cr, lr


def main(argv: list) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("builds", nargs="+", help="build dirs <r9-out>/<design>/<own|foreign>")
    ap.add_argument("--out", required=True, help="output prefix; writes <out>-clusters.csv.gz and <out>-luts.csv.gz")
    ap.add_argument("--no-mimir", action="store_true")
    ap.add_argument("--no-luts", action="store_true")
    a = ap.parse_args(argv)
    cr_all, lr_all = [], []
    for d in a.builds:
        cr, lr = extract(Path(d), 1, not a.no_mimir, not a.no_luts)
        cr_all += cr
        lr_all += lr
        print(d, len(cr), len(lr), flush=True)
    write_csv_gz(Path(a.out + "-clusters.csv.gz"), cr_all)
    if lr_all:
        write_csv_gz(Path(a.out + "-luts.csv.gz"), lr_all)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
