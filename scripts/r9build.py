"""Round 9 generator (docs/plan/round9-tpeko-real.md): a known-optimum clustering built from a REAL design.

  python scripts/r9build.py DESIGN [--cons own|foreign|both] [--shuffles 1,2,3] [--no-check]

Needs `pymetis` for the foreign construction and the independent partitioner check (the Mimir venv python has it).
Everything is deterministic (fixed seeds derived from the design name). Stdlib otherwise. Nothing is deleted.

Pipeline: BLIF of D -> clean-up like VPR (buffers absorbed, dead logic swept) -> cells and carry-chain macros ->
clustering C0 (own: `vpr --pack` AAPack; foreign: METIS) -> legalise to 10 logic elements and 40 pins per cluster
(Step A) -> pad with dummy cells to exactly 10 (Step B) -> add intra-cluster sinks (Step C) -> check (margin,
independent partitioners) -> write shuffled BLIF + affinity file (Step D).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

CONST = ("gnd", "vcc", "unconn")
CONST_VAL = {"gnd": 0, "unconn": 0, "vcc": 1}
CLK = "clk"
CAP = 10  # logic elements per CLB
MAX_IN = 32  # external input nets of a cluster VPR's default flow forms: 0.8 of the 40 CLB input pins (target_external_pin_util auto)
MAX_OUT = 12  # external output nets: 0.6 of the 20 output pins
CHAIN_MAX = 2 * CAP  # adders per CLB
CHAIN_SEG = 12  # adders per macro segment: <= 24 input nets (limit 32) and <= 12 sumout nets (limit 12) keep a segment reachable in VPR's default flow

WS_ROOT = Path(os.environ.get("WS_ROOT", str(Path.home() / "odin3-ws")))
OUT_ROOT = Path(os.environ.get("R9_OUT", str(WS_ROOT / "work" / "r9-out")))
NET_BASE = WS_ROOT / "work" / "norns-keep-sweep-out" / "netlists" / "base"
VTR_ROOT = Path(os.environ.get("VTR_ROOT", str(WS_ROOT / "external" / "vtr-verilog-to-routing")))
ARCH = VTR_ROOT / "vtr_flow" / "arch" / "timing" / "k6_frac_N10_frac_chain_mem32K_40nm.xml"
STOCK_VPR = VTR_ROOT / "build" / "vpr" / "vpr"
LOCK = os.environ.get("NORNS_LOCK", "/tmp/claude-1000/norns-vpr.lock")
BLIF_DIRS = (NET_BASE, VTR_ROOT / "vtr_flow" / "benchmarks" / "blif")


# ---------------------------------------------------------------------------------------
# BLIF model

@dataclass
class Sub:
    model: str
    ports: list  # [(port, net)]
    name: str = ""

    def is_out(self, port: str) -> bool:
        if self.model == "adder":
            return port in ("cout", "sumout")
        return port.split("[")[0].startswith("out")

    def outs(self) -> list:
        return [n for p, n in self.ports if self.is_out(p)]

    def ins(self) -> list:
        return [n for p, n in self.ports if not self.is_out(p)]


@dataclass
class Blif:
    model: str = "top"
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    luts: dict = field(default_factory=dict)  # out net -> (ins list, tt int over len(ins) inputs)
    ffs: dict = field(default_factory=dict)  # q net -> d net
    subs: list = field(default_factory=list)
    consts: list = field(default_factory=list)  # const nets that D defines with `.names` (kept verbatim)
    clk: str = "clk"  # the clock net (ctrl of the latches)
    const_pos: dict = field(default_factory=dict)  # primary output driven by a constant -> 0/1
    tail: str = ""  # the black-box model definitions that follow the main model (kept verbatim)


def logical_lines(text: str) -> list:
    out, pend = [], ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if line.endswith("\\"):
            pend += line[:-1] + " "
            continue
        pend += line
        if pend.strip():
            out.append(pend.strip())
        pend = ""
    if pend.strip():
        out.append(pend.strip())
    return out


def cover_tt(k: int, rows: list) -> int:
    if k == 0:
        return 1 if any(v == "1" for _c, v in rows) else 0
    if not rows:
        return 0
    on = rows[0][1] == "1"
    bits = 0
    for m in range(1 << k):
        hit = any(all(c == "-" or int(c) == ((m >> j) & 1) for j, c in enumerate(cube)) for cube, _v in rows)
        if hit == on:
            bits |= 1 << m
    return bits


def parse_blif(text: str) -> Blif:
    b = Blif()
    lines = text.splitlines()
    for k, ln in enumerate(lines):
        if ln.strip() == ".end":
            rest = "\n".join(lines[k + 1:]).strip()
            if ".model" in rest:
                b.tail = rest + "\n"
            break
    cur = None  # (ins, out, rows)

    def flush() -> None:
        nonlocal cur
        if cur is None:
            return
        ins, out, rows = cur
        if not ins and out in CONST:
            b.consts.append(out)
        else:
            b.luts[out] = (ins, cover_tt(len(ins), rows))
        cur = None

    for line in logical_lines(text):
        tok = line.split()
        if not tok[0].startswith("."):
            if cur is None:
                raise ValueError(f"cover row outside .names: {line}")
            if len(cur[0]) == 0:
                cur[2].append(("", tok[0]))
            else:
                cur[2].append((tok[0], tok[1]))
            continue
        flush()
        h = tok[0]
        if h == ".model":
            b.model = tok[1]
        elif h == ".inputs":
            b.inputs += tok[1:]
        elif h == ".outputs":
            b.outputs += tok[1:]
        elif h == ".names":
            cur = (tok[1:-1], tok[-1], [])
        elif h == ".latch":
            b.ffs[tok[2]] = tok[1]
            if len(tok) >= 5:
                b.clk = tok[4]
        elif h == ".subckt":
            b.subs.append(Sub(tok[1], [tuple(x.split("=", 1)) for x in tok[2:]]))
        elif h == ".cname":
            b.subs[-1].name = tok[1]
        elif h == ".end":
            break
    flush()
    return b


def tt_rows(k: int, tt: int) -> list:
    if k == 0:
        return ["1"] if tt else []
    return ["".join(str((m >> j) & 1) for j in range(k)) + " 1" for m in range(1 << k) if (tt >> m) & 1]


def reduce_lut(ins: list, tt: int) -> tuple:
    """Remove constant inputs and duplicated nets from a LUT (the function is kept)."""
    ins = list(ins)
    changed = True
    while changed:
        changed = False
        for j, n in enumerate(ins):
            if n in CONST:
                v = CONST_VAL[n]
                tt = _restrict(tt, len(ins), j, v)
                ins.pop(j)
                changed = True
                break
            if n in ins[:j]:
                i = ins.index(n)
                k = len(ins)
                new = 0
                for m in range(1 << k):
                    if ((m >> i) & 1) == ((m >> j) & 1) and (tt >> m) & 1:
                        new |= 1 << _drop_bit(m, j)
                tt = new
                ins.pop(j)
                changed = True
                break
    return ins, tt


def _drop_bit(m: int, j: int) -> int:
    return (m & ((1 << j) - 1)) | ((m >> (j + 1)) << j)


def _restrict(tt: int, k: int, j: int, v: int) -> int:
    new = 0
    for m in range(1 << k):
        if ((m >> j) & 1) == v and (tt >> m) & 1:
            new |= 1 << _drop_bit(m, j)
    return new


def find_blif(design: str) -> Path:
    for d in BLIF_DIRS:
        for p in (d / design / "netlist" / f"{design}.blif", d / f"{design}.blif"):
            if p.is_file():
                return p
    raise FileNotFoundError(f"no BLIF for {design}")


# ---------------------------------------------------------------------------------------
# clean-up like VPR (buffers absorbed, dead logic swept); checked against VPR's atom counts

def clean(b: Blif) -> Blif:
    """Mimic VPR's netlist clean-up: constants propagate into LUT inputs, buffer LUTs are absorbed (a buffer chain
    ending in a primary output renames its source net to the output name; a buffer from a primary input to a primary
    output renames the output), then dangling blocks and unused primary inputs are swept. Whether this equals VPR's
    own clean-up is CHECKED per design (atom counts of `vpr --pack` on the written file)."""
    pis = set(b.inputs)
    outputs = list(b.outputs)
    luts = {o: (list(i), t) for o, (i, t) in b.luts.items()}
    repl: dict = {}
    const_pos: dict = {}
    keep_buf: set = set()

    def find(x: str) -> str:
        while x in repl:
            x = repl[x]
        return x

    for _pass in range(50):
        changed = False
        for o in list(luts):
            ins, tt = luts[o]
            ins2, tt2 = reduce_lut([find(x) for x in ins], tt)
            luts[o] = (ins2, tt2)
            if not ins2:
                if o in outputs:
                    const_pos[o] = tt2 & 1
                repl[o] = "vcc" if tt2 & 1 else "gnd"
                del luts[o]
                changed = True
        pos = set(outputs)
        bufmap = {o: ins[0] for o, (ins, tt) in luts.items() if len(ins) == 1 and tt == 0b10 and o not in keep_buf}

        def root(x: str, bufmap=bufmap) -> str:
            while x in bufmap:
                x = bufmap[x]
            return x

        chains: dict = collections.defaultdict(list)
        for o in bufmap:
            chains[root(o)].append(o)
        for src, outs in chains.items():
            po_outs = [o for o in outs if o in pos]
            if not po_outs:
                for o in outs:
                    repl[o] = src
                    del luts[o]
                changed = True
            elif src in pis and len(po_outs) == 1 and src not in pos:
                p = po_outs[0]
                for o in outs:
                    repl[o] = src
                    del luts[o]
                outputs = [src if x == p else x for x in outputs]
                changed = True
            elif src not in pis and src not in pos and src not in CONST:
                p = po_outs[0]
                repl[src] = p
                for o in outs:
                    if o != p:
                        repl[o] = p
                    del luts[o]
                changed = True
            else:
                for o in outs:
                    if o in pos:
                        keep_buf.add(o)
                    else:
                        repl[o] = src
                        del luts[o]
                        changed = True
        if not changed:
            break
    n = Blif(model=b.model, inputs=list(b.inputs), outputs=[find(x) if x not in const_pos else x for x in outputs],
             consts=list(b.consts), clk=b.clk, const_pos=const_pos, tail=b.tail)
    for o, (ins, tt) in luts.items():
        n.luts[find(o)] = ([find(x) for x in ins], tt)
    for q, d in b.ffs.items():
        n.ffs[find(q)] = find(d)
    for s in b.subs:
        n.subs.append(Sub(s.model, [(p, find(x)) for p, x in s.ports], s.name))
    changed = True
    while changed:
        changed = False
        used = set(n.outputs)
        for ins, _tt in n.luts.values():
            used.update(ins)
        used.update(n.ffs.values())
        for s in n.subs:
            used.update(s.ins())
        for o in [o for o in n.luts if o not in used]:
            del n.luts[o]
            changed = True
        for q in [q for q in n.ffs if q not in used]:
            del n.ffs[q]
            changed = True
        keep = []
        for s in n.subs:
            outs = [x for x in s.outs() if x not in CONST and x != "open"]
            if outs and not any(x in used for x in outs):
                changed = True
            else:
                keep.append(s)
        n.subs = keep
    used = set(n.outputs)
    for ins, _tt in n.luts.values():
        used.update(ins)
    used.update(n.ffs.values())
    for s in n.subs:
        used.update(s.ins())
    n.inputs = [x for x in n.inputs if x in used or x == n.clk]
    return n


def write_plain(b: Blif) -> str:
    out = [f".model {b.model}", ".inputs " + " ".join(b.inputs), ".outputs " + " ".join(b.outputs)]
    out += [f".names {c}" + ("\n1" if c == "vcc" else "") for c in b.consts]
    out += [f".names {'vcc' if v else 'gnd'} {o}\n1 1" for o, v in b.const_pos.items()]
    for o, (ins, tt) in b.luts.items():
        out.append(".names " + " ".join(ins + [o]))
        out += tt_rows(len(ins), tt)
    for q, d in b.ffs.items():
        out.append(f".latch {d} {q} re {b.clk} 2")
    for s in b.subs:
        out.append(".subckt " + s.model + " " + " ".join(f"{p}={x}" for p, x in s.ports))
        if s.name:
            out.append(f".cname {s.name}")
    out.append(".end")
    return "\n".join(out) + "\n" + b.tail


# ---------------------------------------------------------------------------------------
# cells and macros

@dataclass
class Cell:
    cid: int
    kind: str  # LF, L, W (wrapper over a lone flip-flop), D (dummy)
    ins: list
    tt: int
    lut_net: str
    out: str
    ff: bool
    k0: int = 0  # inputs before widening


@dataclass
class Macro:
    adders: list  # list of dict(port -> net), chain order
    weight: int = 0
    link_cut_before: bool = False


@dataclass
class Design:
    name: str
    cells: list
    macros: list
    hard: list  # Sub
    pis: list
    pos: list
    consts: list
    n_chains: int = 0
    chain_lens: list = field(default_factory=list)
    n_wrappers: int = 0
    clk: str = "clk"
    const_pos: dict = field(default_factory=dict)
    tail: str = ""


def build_design(name: str, b: Blif) -> tuple:
    """(Design with macros not yet formed, adder chains as lists of Sub, atom lookup)."""
    luts = {}
    for o, (ins, tt) in b.luts.items():
        luts[o] = reduce_lut(ins, tt)
    readers = collections.defaultdict(list)
    for o, (ins, _t) in luts.items():
        for x in ins:
            readers[x].append(("lut", o))
    for q, d in b.ffs.items():
        readers[d].append(("ff", q))
    for i, s in enumerate(b.subs):
        for x in s.ins():
            readers[x].append(("sub", i))
    for x in b.outputs:
        readers[x].append(("po", x))
    paired: dict = {}
    for q, d in b.ffs.items():
        if d in luts and readers[d] == [("ff", q)]:
            paired[q] = d
    cells = []
    atom_cell: dict = {}  # atom name -> cell id
    lut_has_ff = {d: q for q, d in paired.items()}
    for o, (ins, tt) in luts.items():
        q = lut_has_ff.get(o)
        c = Cell(len(cells), "LF" if q else "L", list(ins), tt, o, q if q else o, bool(q), len(ins))
        cells.append(c)
        atom_cell[o] = c.cid
        if q:
            atom_cell[q] = c.cid
    wrappers = 0
    for q, d in b.ffs.items():
        if q in paired:
            continue
        ins = [] if d in CONST else [d]
        tt = 0b10 if ins else (CONST_VAL.get(d, 0) and 1)
        c = Cell(len(cells), "W", ins, tt, "w$" + q, q, True, len(ins))
        cells.append(c)
        atom_cell[q] = c.cid
        wrappers += 1
    adders = [s for s in b.subs if s.model == "adder"]
    hard = [s for s in b.subs if s.model != "adder"]
    by_cin = {dict(s.ports)["cin"]: s for s in adders if dict(s.ports)["cin"] not in CONST}
    heads = []
    couts = {dict(s.ports)["cout"] for s in adders}
    for s in adders:
        if dict(s.ports)["cin"] not in couts:
            heads.append(s)
    chains = []
    for h in heads:
        ch, cur = [h], h
        while dict(cur.ports)["cout"] in by_cin:
            cur = by_cin[dict(cur.ports)["cout"]]
            ch.append(cur)
        chains.append(ch)
    des = Design(name, cells, [], hard, list(b.inputs), list(b.outputs), list(b.consts), len(chains),
                 sorted(len(c) for c in chains), wrappers, b.clk, dict(b.const_pos), b.tail)
    return des, chains, atom_cell


def pad_ok(x: str) -> bool:
    return x not in CONST and x != "open"


# ---------------------------------------------------------------------------------------
# vertices, nets, clusters

class Graph:
    """Logic vertices: cells (weight 1) and macros (weight ceil(L/2)); nets with their logic pins."""

    def __init__(self, des: Design):
        self.des = des
        self.clk = des.clk
        self.v: list = []  # ('c', Cell) or ('m', Macro)
        self.w: list = []
        for c in des.cells:
            self.v.append(("c", c))
            self.w.append(1)
        for m in des.macros:
            self.v.append(("m", m))
            self.w.append(m.weight)
        self.nc = len(des.cells)
        self.rebuild()

    def vin(self, i: int) -> list:
        kind, o = self.v[i]
        if kind == "c":
            return [x for x in o.ins if pad_ok(x)] if o.kind != "K" else []
        return [x for a in o.adders for x in (a["a"], a["b"]) if pad_ok(x)]

    def vout(self, i: int) -> list:
        kind, o = self.v[i]
        if kind == "c":
            return [o.out] if o.kind != "K" else []
        return [a["sumout"] for a in o.adders if pad_ok(a["sumout"])]

    def rebuild(self) -> None:
        self.drv: dict = {}
        self.rd: dict = collections.defaultdict(set)
        self.nonlogic: set = set()
        for i in range(len(self.v)):
            for x in self.vout(i):
                self.drv[x] = i
            for x in self.vin(i):
                self.rd[x].add(i)
        for x in self.des.pis:
            if x != self.clk:
                self.nonlogic.add(x)
        for x in self.des.pos:
            self.nonlogic.add(x)
        for s in self.des.hard:
            for p, x in s.ports:
                if pad_ok(x) and x != self.clk:
                    self.nonlogic.add(x)
        self.nonlogic.discard(self.clk)

    def verts(self, net: str) -> set:
        s = set(self.rd.get(net, ()))
        if net in self.drv:
            s.add(self.drv[net])
        return s

    def hstar(self) -> list:
        """Nets of the logic-only hypergraph: (net, tuple of vertices), at least 2 vertices, no pad or hard pin."""
        out = []
        for net in sorted(set(self.drv) | set(self.rd)):
            if net in self.nonlogic or net == self.clk:
                continue
            vs = self.verts(net)
            if len(vs) >= 2:
                out.append((net, tuple(sorted(vs))))
        return out

    def k0(self) -> int:
        n = 0
        for net in set(self.drv) | set(self.rd):
            if net in self.nonlogic and self.verts(net):
                n += 1
        return n


def ext_inputs(g: Graph, members: set) -> set:
    s = set()
    for i in members:
        for x in g.vin(i):
            d = g.drv.get(x)
            if d is None or d not in members:
                s.add(x)
    return s


def ext_outputs(g: Graph, members: set) -> set:
    s = set()
    for i in members:
        for x in g.vout(i):
            if x in g.nonlogic or any(r not in members for r in g.rd.get(x, ())):
                s.add(x)
    return s


def pin_excess(g: Graph, members: set) -> int:
    """How far a cluster is over the pin limits VPR's default flow applies (0.8 and 0.6 of the pins). A carry-chain macro is
    placed as a seed molecule and keeps its own pins: a cluster with macros may use as many as the macros alone need."""
    macros = {i for i in members if g.v[i][0] == "m"}
    li, lo = MAX_IN, MAX_OUT
    if macros:
        li = max(li, len(ext_inputs(g, macros)))
        lo = max(lo, len(ext_outputs(g, macros)))
    return max(0, len(ext_inputs(g, members)) - li) + max(0, len(ext_outputs(g, members)) - lo)


def legalise(g: Graph, assign: dict, reserve: int = 1) -> dict:
    """Step A: demand <= CAP - reserve (CAP for a cluster whose heaviest vertex does not fit otherwise) and <= 40 external
    input nets per cluster. Evict the least connected vertex, place the evicted ones where they connect, then merge
    small clusters. `reserve` keeps room for a dummy cell, the anchor of the strict cut margin (Step C)."""
    members: dict = collections.defaultdict(set)
    for v, c in assign.items():
        members[c].add(v)
    nets_of = {i: set(g.vin(i)) | set(g.vout(i)) for i in range(len(g.v))}

    def demand(c: int) -> int:
        return sum(g.w[i] for i in members[c])

    def limit(c: int, extra: int = 0) -> int:
        heavy = max([g.w[i] for i in members[c]] + [extra], default=0)
        return CAP if heavy > CAP - reserve else CAP - reserve

    def fits(c: int, i: int) -> bool:
        return demand(c) + g.w[i] <= limit(c, g.w[i])

    def score(i: int, c: int) -> int:
        n = 0
        for x in nets_of[i]:
            if g.verts(x) & (members[c] - {i}):
                n += 1
        return n

    def pins_with(c: int, i: int) -> int:
        members[c].add(i)
        n = pin_excess(g, members[c])
        members[c].discard(i)
        return n

    pool = []
    for c in sorted(members):
        while members[c] and (demand(c) > limit(c) or pin_excess(g, members[c]) > 0):
            if len(members[c]) == 1:
                raise ValueError("a single vertex violates the cluster limits")
            if demand(c) > limit(c):
                cand = sorted(members[c], key=lambda i: (g.w[i] > 1, score(i, c), -i))
            else:  # pins: evict the vertex whose removal leaves the fewest external inputs
                cand = sorted(members[c], key=lambda i: (pin_excess(g, members[c] - {i}), score(i, c), -i))
            i = cand[0]
            members[c].discard(i)
            pool.append(i)
    nxt = (max(members) + 1) if members else 0
    n_evicted = len(pool)
    for i in sorted(pool, key=lambda i: (-g.w[i], i)):
        best, bs = None, -1
        for c in sorted(members):
            if not members[c] or not fits(c, i):
                continue
            s = score(i, c)
            if not nets_of[i]:
                s = max(s, 0)
            if s <= bs or (s == 0 and nets_of[i]):
                continue
            if pins_with(c, i) == 0:
                best, bs = c, s
        if best is None:
            best = nxt
            nxt += 1
        members[best].add(i)
    merged = True
    n_merged = 0
    while merged:  # compaction: merge two clusters when their vertices fit one and the pins allow
        merged = False
        live = sorted((c for c in members if members[c]), key=lambda c: (demand(c), c))
        for a_ in live:
            best, bs = None, -1
            for b_ in live:
                if a_ == b_ or not members[a_] or not members[b_]:
                    continue
                if demand(a_) + demand(b_) > limit(b_, max(g.w[i] for i in members[a_])):
                    continue
                if limit(a_, max(g.w[i] for i in members[b_])) < demand(a_) + demand(b_):
                    continue
                sc = sum(1 for i in members[a_] for x in nets_of[i] if g.verts(x) & members[b_])
                if sc > bs:
                    members[b_] |= members[a_]
                    ok = pin_excess(g, members[b_]) == 0
                    members[b_] -= members[a_]
                    if ok:
                        best, bs = b_, sc
            if best is not None:
                members[best] |= members[a_]
                members[a_] = set()
                merged = True
                n_merged += 1
                break
    out = {}
    for k, c in enumerate(sorted(c for c in members if members[c])):
        for i in members[c]:
            out[i] = k
    legalise.last_evicted = n_evicted  # type: ignore[attr-defined]
    legalise.last_merged = n_merged  # type: ignore[attr-defined]
    return out


def seg_chain(L: int) -> list:
    """Segment lengths of a chain of L adders: <= 20 each, all but the last even, near equal."""
    if L <= CHAIN_SEG:
        return [L]
    n = -(-L // CHAIN_SEG)
    per = -(-L // n)
    first = min(2 * -(-per // 2), CHAIN_SEG)
    segs = [first] * (n - 1)
    segs.append(L - first * (n - 1))
    return segs


# ---------------------------------------------------------------------------------------
# clusterings: own (VPR AAPack) and foreign (METIS)

NORNS_VPR = Path(os.environ.get("NORNS_VPR", str(WS_ROOT / "work" / "norns-vtr" / "build" / "vpr" / "vpr")))


def run_vpr_pack(blif: Path, outdir: Path, affinity: Path | None = None) -> Path:
    """`vpr --pack` (AAPack) under the lock; with an affinity file the Norns binary, beta 100, queued proposals."""
    tag = hashlib.sha256(blif.read_bytes() + (affinity.read_bytes() if affinity else b"")).hexdigest()[:10]
    outdir = outdir.parent / f"{outdir.name}.{tag}"  # a changed input never reuses an earlier result
    outdir.mkdir(parents=True, exist_ok=True)
    net = outdir / (blif.stem + ".net")
    if not net.is_file():
        cmd = ["flock", "-x", LOCK, str(STOCK_VPR), str(ARCH), str(blif), "--pack", "--seed", "1"]
        if affinity is not None:
            cmd = ["flock", "-x", LOCK, str(NORNS_VPR), str(ARCH), str(blif), "--pack", "--seed", "1", "--norns_affinity", str(affinity),
                   "--norns_affinity_weight", "100", "--norns_proposal_count", "queued"]
        with (outdir / "pack.out").open("w") as fh:
            subprocess.run(cmd, cwd=outdir, stdout=fh, stderr=subprocess.STDOUT, check=True)
    return net


def read_net(path: Path) -> tuple:
    """(atom name -> logic cluster index, per-type atom counts over the whole netlist)."""
    root = ET.parse(path).getroot()
    atom_cl: dict = {}
    counts: collections.Counter = collections.Counter()
    k = 0
    for top in root.findall("block"):
        is_logic = top.get("instance", "").startswith("clb[")
        stack = [top]
        while stack:
            x = stack.pop()
            kids = x.findall("block")
            if kids:
                stack += kids
            elif x.get("name") != "open":
                t = x.get("instance", "").split("[")[0]
                counts["lut" if t.startswith("lut") else t] += 1
                if is_logic:
                    atom_cl[x.get("name")] = k
        if is_logic:
            k += 1
    return atom_cl, counts


FOREIGN_SEEDS = tuple(range(1001, 1041))  # construction seeds; the independent check uses 1..n (disjoint)


def polish_foreign(g: Graph, k: int, seeds) -> tuple:
    """Foreign C0: the lowest-cut partition over many METIS seeds, each refined by pair-swap descent."""
    hn = g.hstar()
    best, best_cut = None, None
    for sd in seeds:
        cl = metis_partition(g, k, sd, hn)
        cu = Cutter(g, cl)
        cu.local_search()
        c = cu.total()
        if best_cut is None or c < best_cut:
            best, best_cut = list(cl), c
    return best, best_cut, len(list(seeds))


def metis_partition(g: Graph, nparts: int, seed: int, hn: list | None = None) -> list:
    import pymetis

    hn = g.hstar() if hn is None else hn
    n = len(g.v)
    adj: list = [dict() for _ in range(n)]
    for _net, vs in hn:
        m = len(vs)
        w = max(1, 840 // (m - 1))
        pairs = [(a, b) for i, a in enumerate(vs) for b in vs[i + 1:]] if m <= 8 else [(vs[0], b) for b in vs[1:]]
        for a, b in pairs:
            adj[a][b] = adj[a].get(b, 0) + w
            adj[b][a] = adj[b].get(a, 0) + w
    xadj, adjncy, ew = [0], [], []
    for row in adj:
        for b in sorted(row):
            adjncy.append(b)
            ew.append(row[b])
        xadj.append(len(adjncy))
    opts = pymetis.Options()
    opts.seed = seed
    if not adjncy:
        return [i % nparts for i in range(n)]
    res = pymetis.part_graph(nparts, adjacency=pymetis.CSRAdjacency(xadj, adjncy), eweights=ew, vweights=list(g.w), options=opts)
    return list(res.vertex_part)


# ---------------------------------------------------------------------------------------
# Step B and C: pad, then add intra-cluster sinks

def widen(c: Cell, added: list) -> None:
    """Append `added` input nets to the cell; table = old function XOR parity of the added inputs."""
    k = len(c.ins)
    new_ins = c.ins + added
    kk = len(new_ins)
    tt = 0
    for m in range(1 << kk):
        par = 0
        for j in range(k, kk):
            par ^= (m >> j) & 1
        base = (c.tt >> (m & ((1 << k) - 1))) & 1
        if base ^ par:
            tt |= 1 << m
    c.ins, c.tt = new_ins, tt


class Strengthen:
    """Step C: only sinks inside a cluster are added; no new net leaves a cluster, no new cluster input pin."""

    def __init__(self, g: Graph, cl: list):
        self.g, self.cl = g, cl
        self.members: dict = collections.defaultdict(list)
        for i, c in enumerate(cl):
            self.members[c].append(i)
        self.unmet: list = []
        self.stats: collections.Counter = collections.Counter()

    def add_read(self, i: int, net: str) -> None:
        self.g.v[i][1].ins.append(net)
        self.g.rd[net].add(i)

    def spare(self, i: int) -> int:
        return 6 - len(self.g.v[i][1].ins)

    def a_and_trouble(self, i: int, c: int) -> tuple:
        """a = nets lying entirely inside cluster c that contain vertex i; trouble = (net, other cluster) for nets whose
        only pin in c is i and whose other pins are all in one other cluster (moving i there would uncut them)."""
        g, cl = self.g, self.cl
        a, trouble = 0, []
        for x in set(g.vin(i)) | set(g.vout(i)):
            if x in g.nonlogic or x == g.clk:
                continue
            vs = g.verts(x)
            if len(vs) < 2:
                continue
            cs = {cl[v] for v in vs}
            if cs == {c}:
                a += 1
            elif len(cs) == 2 and [v for v in vs if cl[v] == c] == [i]:
                trouble.append((x, next(iter(cs - {c}))))
        return a, trouble

    def internal_only(self, net: str, c: int) -> bool:
        g = self.g
        if net in g.nonlogic:
            return False
        vs = g.verts(net)
        return len(vs) >= 1 and all(self.cl[v] == c for v in vs)

    def run(self) -> None:
        g = self.g
        for c in sorted(self.members):
            cells = [i for i in self.members[c] if g.v[i][0] == "c" and g.v[i][1].kind != "K"]
            dummies = [i for i in cells if g.v[i][1].kind == "D"]
            for t, d in enumerate(dummies):  # a ring, so no dummy output is dangling
                src = dummies[t - 1] if len(dummies) > 1 else d
                net = g.v[src][1].out
                if net not in g.v[d][1].ins:
                    self.add_read(d, net)
                    self.stats["ring"] += 1
            for u in cells:  # doubling: a second reader inside the cluster for every net a single move could uncut
                _a, tr = self.a_and_trouble(u, c)
                for net, _j in tr:
                    cand = [v for v in cells if v != u and net not in g.v[v][1].ins and self.spare(v) > 0
                            and g.drv.get(net) != v]
                    if cand:
                        v = max(cand, key=lambda x: (self.spare(x), -x))
                        self.add_read(v, net)
                        self.stats["doubled"] += 1
            for u in cells:  # anchor: at least one more internal net than the best saving of a single move
                a, tr = self.a_and_trouble(u, c)
                gmax = max(collections.Counter(j for _n, j in tr).values(), default=0)
                while a - gmax < 1 and g.v[u][1].kind != "D":
                    ds = [d for d in dummies if d != u and g.v[d][1].out not in g.v[u][1].ins]
                    if not ds:
                        break
                    d = min(ds, key=lambda x: (len(g.rd.get(g.v[x][1].out, ())), x))
                    if self.spare(u) == 0:  # rewire an input that is a constant-cut net (pad or hard-block net) with other readers
                        cu_ = g.v[u][1]
                        j = next((j for j, x in enumerate(cu_.ins) if x in g.nonlogic and len(g.rd.get(x, ())) + (1 if x in g.drv else 0) >= 2
                                  and g.rd.get(x) and len(g.rd[x]) >= 2), None)
                        if j is None:
                            break
                        g.rd[cu_.ins[j]].discard(u)
                        cu_.ins[j] = g.v[d][1].out
                        g.rd[g.v[d][1].out].add(u)
                        self.stats["rewired_const_cut"] += 1
                    else:
                        self.add_read(u, g.v[d][1].out)
                    self.stats["anchored"] += 1
                    a, tr = self.a_and_trouble(u, c)
                    gmax = max(collections.Counter(j for _n, j in tr).values(), default=0)
            pool = [g.v[i][1].out for i in cells]
            pool += [x for i in self.members[c] if g.v[i][0] == "m" for x in g.vout(i)]
            pool += sorted(ext_inputs(g, set(self.members[c])))  # nets that already enter the cluster: no new pin
            pool = list(dict.fromkeys(pool))
            for u in cells:  # fill to six inputs, preferring nets that stay entirely inside the cluster
                cu = g.v[u][1]
                while len(cu.ins) < 6:
                    cand = [x for x in pool if x not in cu.ins and x != cu.out] or [x for x in pool if x not in cu.ins]
                    if not cand:
                        raise ValueError("cluster too small to give a LUT six distinct inputs")
                    cand.sort(key=lambda x: (not self.internal_only(x, c), len(g.rd.get(x, ())), x))
                    self.add_read(u, cand[0])
                    self.stats["filled"] += 1
        self.unmet = []
        for c in sorted(self.members):
            for u in self.members[c]:
                if g.v[u][0] != "c" or g.v[u][1].kind in ("K", "D"):
                    continue
                a, tr = self.a_and_trouble(u, c)
                gmax = max(collections.Counter(j for _n, j in tr).values(), default=0)
                if a - gmax < 1:
                    self.unmet.append(u)


# ---------------------------------------------------------------------------------------
# the cut, margins, independent checks

def cut_of(hn: list, cl) -> int:
    return sum(1 for _n, vs in hn if len({cl[v] for v in vs}) > 1)


class Cutter:
    def __init__(self, g: Graph, cl: list):
        self.g, self.cl = g, cl
        self.hn = [vs for _n, vs in g.hstar()]
        self.vnets: list = [[] for _ in g.v]
        for k, vs in enumerate(self.hn):
            for v in vs:
                self.vnets[v].append(k)
        self.w = g.w
        self.kinds = [o.kind if k == "c" else "M" for k, o in g.v]

    def flag(self, k: int) -> int:
        cl = self.cl
        it = iter(self.hn[k])
        c0 = cl[next(it)]
        return int(any(cl[v] != c0 for v in it))

    def delta_swap(self, u: int, v: int) -> int:
        cl = self.cl
        aff = set(self.vnets[u]) | set(self.vnets[v])
        before = sum(self.flag(k) for k in aff)
        cl[u], cl[v] = cl[v], cl[u]
        after = sum(self.flag(k) for k in aff)
        cl[u], cl[v] = cl[v], cl[u]
        return after - before

    def total(self) -> int:
        return sum(self.flag(k) for k in range(len(self.hn)))

    def adjacent(self) -> set:
        """Cluster pairs joined by a net that spans exactly those two clusters (only these can give a swap a saving)."""
        adj = set()
        for vs in self.hn:
            cs = sorted({self.cl[v] for v in vs})
            if len(cs) == 2:
                adj.add((cs[0], cs[1]))
        return adj

    def by_cluster(self) -> dict:
        d: dict = collections.defaultdict(list)
        for v, c in enumerate(self.cl):
            d[c].append(v)
        return d

    def a_of(self, v: int) -> int:
        n = 0
        c = self.cl[v]
        for k in self.vnets[v]:
            if all(self.cl[x] == c for x in self.hn[k]):
                n += 1
        return n

    def margin(self) -> dict:
        """Smallest increase of the cut over all swaps of two equal-weight vertices (exact for adjacent cluster pairs,
        the lower bound a(u)+a(v) for the others). Swaps that involve a constant-generator cell (no nets) are counted
        apart: they change nothing but the cell they swap with."""
        bc = self.by_cluster()
        mn, npairs, bad, bad_k = 10 ** 9, 0, 0, 0
        for ci, cj in sorted(self.adjacent()):
            for u in bc[ci]:
                for v in bc[cj]:
                    if self.w[u] != self.w[v]:
                        continue
                    d = self.delta_swap(u, v)
                    npairs += 1
                    if d <= 0:
                        bad += 1
                        bad_k += self.kinds[u] == "K" or self.kinds[v] == "K"
                    if d < mn and "K" not in (self.kinds[u], self.kinds[v]):
                        mn = d
        a = sorted(self.a_of(v) for v in range(len(self.cl)) if self.w[v] == 1 and self.kinds[v] != "K")
        lb = a[0] + a[1] if len(a) > 1 else 0
        return {"min_adjacent_swap_delta": None if mn == 10 ** 9 else mn, "adjacent_swaps": npairs,
                "swaps_with_delta_le_0": bad, "swaps_le_0_with_const_cell": bad_k, "swaps_le_0_other": bad - bad_k,
                "min_a_pair_bound": lb, "min_a": a[0] if a else 0,
                "min_margin": min(lb, mn) if mn != 10 ** 9 else lb}

    def local_search(self, rounds: int = 50) -> int:
        """Pair-swap descent over adjacent cluster pairs; returns the cut reached."""
        for _ in range(rounds):
            bc = self.by_cluster()
            changed = 0
            for ci, cj in sorted(self.adjacent()):
                for u in bc[ci]:
                    for v in bc[cj]:
                        if self.cl[u] != ci or self.cl[v] != cj or self.w[u] != self.w[v]:
                            continue
                        if self.delta_swap(u, v) < 0:
                            self.cl[u], self.cl[v] = cj, ci
                            changed += 1
            if not changed:
                break
        return self.total()


def repair_full(g: Graph, cl: list, k: int) -> bool:
    """Make every part weigh exactly CAP: move vertices from heavy to light parts (most connected first), else swap a heavy
    vertex for a lighter one."""
    nets_of = [set(g.vin(i)) | set(g.vout(i)) for i in range(len(g.v))]
    n = len(cl)

    def conn(i: int, t: int) -> int:
        sc = 0
        for x in nets_of[i]:
            for v in g.verts(x):
                if cl[v] == t:
                    sc += 1
                    break
        return sc

    for _ in range(20 * n):
        wt = [0] * k
        for i, c in enumerate(cl):
            wt[c] += g.w[i]
        heavy = [c for c in range(k) if wt[c] > CAP]
        if not heavy:
            return all(x == CAP for x in wt)
        light = [c for c in range(k) if wt[c] < CAP]
        best = None
        for i in range(n):
            if cl[i] not in heavy:
                continue
            for t in light:
                if wt[t] + g.w[i] <= CAP:
                    sc = conn(i, t)
                    if best is None or sc > best[0]:
                        best = (sc, i, t, None)
        if best is None:
            for i in range(n):
                if cl[i] not in heavy:
                    continue
                for t in light:
                    for j in range(n):
                        if cl[j] == t and g.w[j] < g.w[i] and wt[t] + g.w[i] - g.w[j] <= CAP:
                            sc = conn(i, t) + conn(j, cl[i])
                            if best is None or sc > best[0]:
                                best = (sc, i, t, j)
        if best is None:
            return False
        _sc, i, t, j = best
        if j is not None:
            cl[j] = cl[i]
        cl[i] = t
    return False


def pins_ok(g: Graph, cl: list, k: int) -> bool:
    mem: dict = collections.defaultdict(set)
    for i, c in enumerate(cl):
        mem[c].add(i)
    return all(pin_excess(g, m) == 0 for m in mem.values())


def independent_check(g: Graph, cl_c: list, k: int, n_metis: int, n_shake: int, seed: str) -> dict:
    """Independent partitioners and perturbation searches against cut*(C). Evidence, not a proof."""
    hn = g.hstar()
    base = Cutter(g, list(cl_c))
    cut_c = base.total()
    res = {"cut_star_C": cut_c, "metis_runs": 0, "metis_legal": 0, "metis_best_legal": None, "metis_best_after_ls": None,
           "metis_below_C": 0, "metis_equal_C": 0, "shake_runs": 0, "shake_best": None, "shake_below_C": 0,
           "shake_equal_C": 0, "below_C_found": False}
    for s in range(1, n_metis + 1):
        cl = metis_partition(g, k, s, hn)
        res["metis_runs"] += 1
        if not repair_full(g, cl, k):
            continue
        res["metis_full"] = res.get("metis_full", 0) + 1
        if not pins_ok(g, cl, k):
            c_any = Cutter(g, cl).total()
            if res.get("metis_best_pin_illegal") is None or c_any < res["metis_best_pin_illegal"]:
                res["metis_best_pin_illegal"] = c_any
            continue
        res["metis_legal"] += 1
        cu = Cutter(g, cl)
        c0 = cu.total()
        c1 = cu.local_search()
        best = min(c0, c1)
        if res["metis_best_legal"] is None or c0 < res["metis_best_legal"]:
            res["metis_best_legal"] = c0
        if res["metis_best_after_ls"] is None or best < res["metis_best_after_ls"]:
            res["metis_best_after_ls"] = best
        if best < cut_c:
            res["metis_below_C"] += 1
        elif best == cut_c:
            res["metis_equal_C"] += 1
    rnd = random.Random(f"{seed}:shake")
    for _ in range(n_shake):
        cl = list(cl_c)
        n = len(cl)
        for _s in range(max(2, n // 10)):
            u, v = rnd.randrange(n), rnd.randrange(n)
            if cl[u] != cl[v] and g.w[u] == g.w[v]:
                cl[u], cl[v] = cl[v], cl[u]
        cu = Cutter(g, cl)
        cu.local_search()
        c1 = cu.total()
        res["shake_runs"] += 1
        if res["shake_best"] is None or c1 < res["shake_best"]:
            res["shake_best"] = c1
        if c1 < cut_c:
            res["shake_below_C"] += 1
        elif c1 == cut_c:
            res["shake_equal_C"] += 1
    res["below_C_found"] = res["metis_below_C"] > 0 or res["shake_below_C"] > 0
    return res


# ---------------------------------------------------------------------------------------
# the build

def seed_of(*parts) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:12], 16)


def build(design: str, cons: str, check: bool = True, n_metis: int = 100, n_shake: int = 100, out_root: Path | None = None, reserve: int = 1) -> dict:
    root = (out_root or OUT_ROOT) / design
    root.mkdir(parents=True, exist_ok=True)
    raw = parse_blif(find_blif(design).read_text())
    cb = clean(raw)
    clean_path = root / f"{design}.clean.blif"
    clean_path.write_text(write_plain(cb))
    return build_from(design, cb, clean_path, cons, root, check, n_metis, n_shake, reserve)


def build_from(design: str, cb: Blif, clean_path: Path, cons: str, root: Path, check: bool, n_metis: int, n_shake: int, reserve: int = 1) -> dict:
    des, chains, atom_cell = build_design(design, cb)
    rec: dict = {"design": design, "construction": cons, "pis": len(des.pis), "pos": len(des.pos),
                 "luts_D": len(cb.luts), "ffs_D": len(cb.ffs), "adders_D": sum(len(c) for c in chains),
                 "hard_D": len(des.hard), "hard_models": dict(collections.Counter(s.model for s in des.hard)),
                 "chains": des.chain_lens, "wrappers": des.n_wrappers, "cells_real": len(des.cells)}
    # vpr --pack on the cleaned D: atom check and the own clustering
    net = run_vpr_pack(clean_path, root / "pack")
    atom_cl, counts = read_net(net)
    rec["vpr_atoms"] = dict(counts)
    rec["vpr_atoms_match"] = (0 <= counts.get("lut", 0) - len(cb.luts) <= 2 and counts.get("ff", 0) == len(cb.ffs)
                              and counts.get("adder", 0) == rec["adders_D"])
    rec["K_vpr"] = len(set(atom_cl.values()))
    extra = counts.get("lut", 0) - len(cb.luts)
    rec["const_generators"] = extra
    for nmk in [x for x in ("gnd", "vcc") if x in cb.consts][:extra]:
        cid = len(des.cells)
        des.cells.append(Cell(cid, "K", [], 0, nmk, nmk, False, 0))
        atom_cell[nmk] = cid
    # macros (carry-chain segments)
    own = cons == "own"
    seg_of_adder: dict = {}
    for ch in chains:
        segs, pos = [], 0
        for ln in seg_chain(len(ch)):
            segs.append(ch[pos:pos + ln])
            pos += ln
        for si, sg in enumerate(segs):
            ad = []
            for j, s in enumerate(sg):
                d = dict(s.ports)
                if j == 0:
                    d["cin"] = "gnd"
                ad.append(d)
            if si < len(segs) - 1:
                ad[-1]["cout"] = f"ck${len(des.macros)}"  # a fresh dangling net (VPR names an adder by its cout net)
            des.macros.append(Macro(ad, -(-len(sg) // 2), si > 0))
            seg_of_adder[len(des.macros) - 1] = sg
    rec["macros"] = len(des.macros)
    rec["carry_links_cut"] = sum(1 for m in des.macros if m.link_cut_before)
    g = Graph(des)
    nv0 = len(g.v)
    rec["demand_real"] = sum(g.w)
    # C0
    if own:
        assign = {}
        missing = 0
        for i in range(nv0):
            kind, o = g.v[i]
            if kind == "c":
                a = o.lut_net if o.kind in ("LF", "L", "K") else o.out
                cidx = atom_cl.get(a)
            else:
                cidx = atom_cl.get(dict(seg_of_adder[i - g.nc][0].ports)["cout"])
            if cidx is None:
                missing += 1
                cidx = -1
            assign[i] = cidx
        rec["atoms_not_in_clb"] = missing
        if missing:
            nxt = max(assign.values()) + 1
            for i in [i for i in assign if assign[i] == -1]:
                assign[i] = nxt
                nxt += 1
    else:
        k_own = build_k_own(root, design)
        cl0, cut0, tried = polish_foreign(g, k_own, FOREIGN_SEEDS)
        assign = {i: cl0[i] for i in range(nv0)}
        rec["K_target_foreign"] = k_own
        rec["foreign_seeds"] = tried
        rec["foreign_best_cut_star"] = cut0
    rec["cut_star_C0"] = Cutter(g, [assign[i] for i in range(nv0)]).total()
    assign = legalise(g, assign, reserve)
    rec["evicted"] = legalise.last_evicted  # type: ignore[attr-defined]
    rec["merged"] = legalise.last_merged  # type: ignore[attr-defined]
    rec["reserve"] = reserve
    k = max(assign.values()) + 1
    rec["K"] = k
    dem = collections.Counter()
    for i, c in assign.items():
        dem[c] += g.w[i]
    rec["max_demand"] = max(dem.values())
    rec["demand_total_real"] = sum(dem.values())
    rec["dummies"] = sum(CAP - dem[c] for c in dem)
    rec["bound_real_only"] = -(-sum(dem.values()) // CAP)
    # Step B: dummies
    rng = random.Random(seed_of(design, cons, "build"))
    for c in range(k):
        for t in range(CAP - dem[c]):
            cid = len(des.cells)
            cell = Cell(cid, "D", [], 0, f"dl{cid}", f"dq{cid}", True, 0)
            des.cells.append(cell)
    g2 = Graph(des)
    # vertex ids changed (cells first, macros after): remap the assignment
    new_cl = [0] * len(g2.v)
    ncell_old = g.nc
    for i, c in assign.items():
        new_cl[i if i < ncell_old else i - ncell_old + len(des.cells)] = c
    idx = ncell_old
    for c in range(k):
        for t in range(CAP - dem[c]):
            new_cl[idx] = c
            idx += 1
    g = g2
    # random dummy functions are set in widen via parity; k0 = 0
    st = Strengthen(g, new_cl)
    st.run()
    # widen all real and dummy cells to 6 inputs with the chosen nets
    for i in range(len(g.v)):
        kind, o = g.v[i]
        if kind != "c" or o.kind == "K":
            continue
        base = o.k0
        added = o.ins[base:]
        o.ins = o.ins[:base]
        if o.kind == "D":
            o.tt = 0
        widen(o, added)
        if o.kind == "D" and rng.random() < 0.5:
            o.tt ^= (1 << 64) - 1
    g.rebuild()
    cl = new_cl
    cu = Cutter(g, cl)
    rec["cut_star_C"] = cu.total()
    rec["K0"] = g.k0()
    rec["cut_C"] = rec["cut_star_C"] + rec["K0"]
    rec["hstar_nets"] = len(cu.hn)
    rec["strengthen"] = dict(st.stats)
    rec["unmet_cells"] = len(set(st.unmet))
    rec["margin"] = cu.margin()
    rec["max_pins"] = max(len(ext_inputs(g, {i for i in range(len(cl)) if cl[i] == c})) for c in range(k))
    rec["max_out_pins"] = max(len(ext_outputs(g, {i for i in range(len(cl)) if cl[i] == c})) for c in range(k))
    rec["pin_excess_clusters"] = sum(1 for c in range(k) if pin_excess(g, {i for i in range(len(cl)) if cl[i] == c}) > 0)
    rec["all_luts_6"] = all(len(o.ins) == 6 for kind, o in g.v if kind == "c" and o.kind != "K")
    rec["distinct_inputs"] = all(len(set(o.ins)) == len(o.ins) for kind, o in g.v if kind == "c")
    rec["demand_padded"] = sum(g.w)
    rec["clb_lower_bound"] = -(-sum(g.w) // CAP)
    rec["full_clusters"] = all(sum(g.w[i] for i in range(len(cl)) if cl[i] == c) == CAP for c in range(k))
    if check:
        rec["independent"] = independent_check(g, cl, k, n_metis, n_shake, f"{design}:{cons}")
        rec["legality"] = legality(g, cl, des, k, root / cons)
    rec["_graph"] = (g, cl)
    return rec


def build_k_own(root: Path, design: str) -> int:
    p = root / "own" / "build.json"
    if p.is_file():
        return json.loads(p.read_text())["K"]
    raise FileNotFoundError("build the own construction before the foreign one")


# ---------------------------------------------------------------------------------------
# Step D: write shuffled BLIF, affinity file, labels

def write_shuffled(g: Graph, cl: list, des: Design, outdir: Path, shuffle: int, design: str, cons: str) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed_of(design, cons, "shuffle", shuffle))
    nets = set()
    for kind, o in g.v:
        if kind == "c":
            nets.update(o.ins)
            nets.add(o.out)
            nets.add(o.lut_net)
        else:
            for a in o.adders:
                nets.update(x for x in (a["a"], a["b"], a["sumout"], a["cin"], a["cout"]))
    for s in des.hard:
        nets.update(x for _p, x in s.ports)
    nets.update(des.pis)
    nets.update(des.pos)
    nets = sorted(x for x in nets if pad_ok(x) and x != des.clk)
    ids = rnd.sample(range(10 ** 9), len(nets))
    name = {x: f"n{ids[i]:09d}" for i, x in enumerate(nets)}
    if shuffle == 0:  # the `ordered` control: names in order of first use, cluster by cluster
        name = {}
    name.update({x: x for x in CONST})
    name[des.clk] = des.clk
    counter = [0]

    def nm(x: str) -> str:
        if shuffle == 0 and x not in name and pad_ok(x) and x != des.clk:
            counter[0] += 1
            name[x] = f"n{counter[0]:09d}"
        return name.get(x, x)

    stm = []
    atom_cluster: dict = {}
    vatoms: list = [[] for _ in g.v]
    order = sorted(range(len(g.v)), key=lambda i: (cl[i], i)) if shuffle == 0 else range(len(g.v))
    for i in order:
        kind, o = g.v[i]
        if kind == "c" and o.kind == "K":
            atom_cluster[o.out] = cl[i]
            vatoms[i] = [o.out]
            continue
        if kind == "c":
            ins = [nm(x) for x in o.ins]
            body = [".names " + " ".join(ins + [nm(o.lut_net)])] + tt_rows(len(ins), o.tt)
            stm.append("\n".join(body))
            atom_cluster[nm(o.lut_net)] = cl[i]
            vatoms[i] = [nm(o.lut_net)]
            if o.ff:
                stm.append(f".latch {nm(o.lut_net)} {nm(o.out)} re {des.clk} 2")
                atom_cluster[nm(o.out)] = cl[i]
                vatoms[i].append(nm(o.out))
        else:
            for j, a in enumerate(o.adders):
                stm.append(".subckt adder " + " ".join(f"{p}={nm(a[p])}" for p in ("a", "b", "cin", "cout", "sumout")))
                atom_cluster[nm(a["cout"])] = cl[i]
                vatoms[i].append(nm(a["cout"]))
    for h, s in enumerate(des.hard):
        stm.append(".subckt " + s.model + " " + " ".join(f"{p}={nm(x)}" for p, x in s.ports))
    for c in des.consts:
        stm.append(f".names {c}" + ("\n1" if c == "vcc" else ""))
    pis = [nm(x) for x in des.pis]
    pos = [nm(x) for x in des.pos]
    if shuffle != 0:
        rnd.shuffle(pis)
        rnd.shuffle(pos)
    if des.clk in pis:
        pis.remove(des.clk)
    for o, v in des.const_pos.items():
        stm.append(f".names {'vcc' if v else 'gnd'} {nm(o)}\n1 1")
    if shuffle != 0:
        rnd.shuffle(stm)
    text = [f".model {design}_{cons}", ".inputs " + des.clk + " " + " ".join(pis), ".outputs " + " ".join(pos)] + stm + [".end"]
    blif = outdir / "design.blif"
    blif.write_text("\n".join(text) + "\n" + des.tail)
    (outdir / "affinity.tsv").write_text("".join(f"{a}\t{c}\n" for a, c in sorted(atom_cluster.items())))
    sha = hashlib.sha256(blif.read_bytes()).hexdigest()
    (outdir / "vatoms.json").write_text(json.dumps(vatoms))
    n_lut = sum(1 for kind, o in g.v if kind == "c" and o.kind != "K")
    return {"blif": str(blif.name), "sha256": sha, "atoms_labelled": len(atom_cluster), "expected_luts_excl_const_generators": n_lut,
            "expected_ffs": sum(1 for kind, o in g.v if kind == "c" and o.ff),
            "expected_adders": sum(len(o.adders) for kind, o in g.v if kind == "m")}


def cluster_blif(g: Graph, cl: list, c: int, des: Design) -> str:
    """One cluster of C as a netlist of its own: nets from outside become inputs, nets to outside become outputs."""
    mem = [i for i in range(len(g.v)) if cl[i] == c]
    mset = set(mem)
    pis, pos, body = set(), set(), []
    has_const = []
    for i in mem:
        kind, o = g.v[i]
        if kind == "c" and o.kind == "K":
            has_const.append(o.out)
            continue
        if kind == "c":
            for x in o.ins:
                if g.drv.get(x) not in mset:
                    pis.add(x)
            body.append(".names " + " ".join(o.ins + [o.lut_net]))
            body += tt_rows(len(o.ins), o.tt)
            if o.ff:
                body.append(f".latch {o.lut_net} {o.out} re {des.clk} 2")
            outs = [o.out]
        else:
            for a in o.adders:
                for x in (a["a"], a["b"]):
                    if pad_ok(x) and g.drv.get(x) not in mset:
                        pis.add(x)
                body.append(".subckt adder " + " ".join(f"{p}={a[p]}" for p in ("a", "b", "cin", "cout", "sumout")))
            outs = [a["sumout"] for a in o.adders if pad_ok(a["sumout"])]
        for x in outs:
            if x in g.nonlogic or any(r not in mset for r in g.rd.get(x, ())):
                pos.add(x)
            elif not g.rd.get(x):
                pos.add(x)
    consts = [f".names {x}" + ("\n1" if x == "vcc" else "") for x in has_const]
    pis_l = sorted(pis - {des.clk})
    return "\n".join([f".model c{c}", ".inputs " + des.clk + " " + " ".join(pis_l), ".outputs " + " ".join(sorted(pos))]
                      + consts + body + [".end"]) + "\n"


def count_clbs(net: Path) -> int:
    root = ET.parse(net).getroot()
    return sum(1 for b in root.findall("block") if b.get("instance", "").startswith("clb["))


def legality(g: Graph, cl: list, des: Design, k: int, root: Path) -> dict:
    """VPR itself packs every cluster of C alone: C is confirmed legal where that gives exactly one logic CLB."""
    d = root / "legal"
    d.mkdir(parents=True, exist_ok=True)
    bad = []
    for c in range(k):
        p = d / f"c{c}.blif"
        text = cluster_blif(g, cl, c, des)
        p.write_text(text)
        names = [ln.split()[-1] for ln in text.splitlines() if ln.startswith(".names")] + [ln.split()[2] for ln in text.splitlines() if ln.startswith(".latch")]
        names += [dict(x.split("=") for x in ln.split()[2:])["cout"] for ln in text.splitlines() if ln.startswith(".subckt")]
        aff = d / f"c{c}.aff"
        aff.write_text("".join(f"{x}\t0\n" for x in names))
        res = {}
        for tag, af in (("stock", None), ("norns", aff)):
            try:
                net = run_vpr_pack(p, d / f"c{c}.{tag}", af)
                res[tag] = count_clbs(net)
            except subprocess.CalledProcessError:
                res[tag] = -1
        if res["stock"] != 1 and res["norns"] != 1:
            bad.append((c, res["stock"], res["norns"]))
    return {"clusters": k, "one_clb": k - len(bad), "not_one_clb": bad}


def structure_signature(g: Graph, cl: list) -> str:
    """Hash of the graph independent of names and order (same for all shuffles by construction)."""
    items = sorted((tuple(sorted(cl[v] for v in vs)), len(vs)) for _n, vs in g.hstar())
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]


def run(design: str, cons_list: list, shuffles: list, check: bool, n_metis: int, n_shake: int) -> int:
    root = OUT_ROOT / design
    for cons in cons_list:
        rec = build(design, cons, check, n_metis, n_shake)
        g, cl = rec.pop("_graph")
        des = g.des
        rec["structure_sig"] = structure_signature(g, cl)
        rec["shuffles"] = {}
        for s in [0] + [x for x in shuffles if x != 0]:
            rec["shuffles"][str(s)] = write_shuffled(g, cl, des, root / cons / f"sh{s}", s, design, cons)
        # VPR reads the written file: its atom counts must be the generator's (nothing swept, nothing merged)
        sh1 = rec["shuffles"].get("1") or next(iter(rec["shuffles"].values()))
        key = "1" if "1" in rec["shuffles"] else next(iter(rec["shuffles"]))
        _a, counts = read_net(run_vpr_pack(root / cons / f"sh{key}" / sh1["blif"], root / cons / f"sh{key}" / "pack"))
        rec["vpr_check_dprime"] = {"vpr": dict(counts), "expected_lut": sh1["expected_luts_excl_const_generators"] + rec["const_generators"],
                                   "expected_ff": sh1["expected_ffs"], "expected_adder": sh1["expected_adders"],
                                   "match": counts.get("lut", 0) == sh1["expected_luts_excl_const_generators"] + rec["const_generators"]
                                   and counts.get("ff", 0) == sh1["expected_ffs"] and counts.get("adder", 0) == sh1["expected_adders"]}
        (root / cons).mkdir(parents=True, exist_ok=True)
        (root / cons / "struct.json").write_text(json.dumps({"hn": [list(vs) for _n, vs in g.hstar()], "cl": cl, "K": rec["K"],
                                                             "K0": rec["K0"], "w": g.w}))
        (root / cons / "build.json").write_text(json.dumps(rec, indent=1, sort_keys=True))
        print(design, cons, "K", rec["K"], "K_vpr", rec["K_vpr"], "dummies", rec["dummies"], "cut*", rec["cut_star_C"],
              "margin", rec["margin"]["min_margin"], "unmet", rec["unmet_cells"], "match", rec["vpr_atoms_match"],
              "Dprime_match", rec["vpr_check_dprime"]["match"], flush=True)
    return 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--cons", default="both")
    ap.add_argument("--shuffles", default="1,2,3")
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--metis", type=int, default=100)
    ap.add_argument("--shake", type=int, default=100)
    a = ap.parse_args(argv)
    cons = ["own", "foreign"] if a.cons == "both" else [a.cons]
    return run(a.design, cons, [int(x) for x in a.shuffles.split(",") if x], not a.no_check, a.metis, a.shake)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
