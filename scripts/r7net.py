"""Round-7 fix round, Part A: the hindsight clustering written as a VPR `.net` (docs/plan/round7.md, entry 2026-10-27).

A clustering is a partition of the stock `.net`'s logic elements (fle) into logic CLBs. Each fle is an indivisible unit: its
subtree (mode, LUT/FF blocks, port maps) is copied from the stock `.net`; only its crossbar inputs are rewritten, because
the CLB crossbar is complete (`clb.I` and every `fle.out` reach every `fle.in`). A cluster is legal when it holds <= 10 fles,
<= 40 distinct external input nets and <= 1 clock; CLBs with a carry chain (arithmetic mode) are copied unchanged.
VPR is run with packing off (`--net_file`, `--place --route`): the clustering VPR sees is the one written, so the
fidelity is 1.0 by construction (asserted from the flat placement).

  python scripts/r7net.py run [design ...]      net0, net_h1.., net_known for each design (runs/r7f/)
  python scripts/r7net.py status

Nothing is deleted: the module only adds files.
"""

from __future__ import annotations

import collections
import copy
import gzip
import json
import os
import random
import re
import statistics
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import nornlib as nl
import r7lib as lib

R7F = nl.RUNS / "r7f"
SPLIT_TRAIN = (1, 2, 3, 4, 5)   # the clustering and the arm are chosen on these seeds
SPLIT_TEST = (6, 7, 8, 9, 10)   # and evaluated on these
CAP_FLE, CAP_IN = 10, 40
TIMEOUT = 7200
NEW_KEY = 10 ** 6               # cluster keys at or above this are new (not in the stock file)

_REF = re.compile(r"^([^\[\s]+)\[(\d+)\]\.([^\[\s]+)\[(\d+)\]->")
_INST = re.compile(r"^(\w+)\[(\d+)\]$")
_LEAF = ("lut", "ff", "adder", "latch")


# ---------------------------------------------------------------------------------------
# .net parsing

def _tokens(block: ET.Element, kind: str, name: str) -> list[str]:
    for p in block.findall(f"{kind}/port"):
        if p.get("name") == name:
            return (p.text or "").split()
    return []


def _child(block: ET.Element, inst: str) -> ET.Element | None:
    for c in block.findall("block"):
        if c.get("instance") == inst:
            return c
    return None


def resolve_out(block: ET.Element, port: str, idx: int) -> str | None:
    """Net name that leaves `block` on output pin port[idx] (follows the `child[i].port[j]->conn` references to the leaf)."""
    toks = _tokens(block, "outputs", port)
    if idx >= len(toks) or toks[idx] == "open":
        return None
    t = toks[idx]
    if "->" not in t:
        return t
    m = _REF.match(t)
    if not m:
        return None
    c = _child(block, f"{m.group(1)}[{m.group(2)}]")
    return None if c is None else resolve_out(c, m.group(3), int(m.group(4)))


def leaf_atoms(block: ET.Element) -> list[str]:
    """Names of the primitive blocks (no child block, a name other than open) below `block`."""
    out: list[str] = []
    for b in block.iter("block"):
        if b is block or b.get("name") == "open":
            continue
        if not b.findall("block") and _INST.match(b.get("instance", "")) and _INST.match(b.get("instance", "")).group(1) in _LEAF:
            out.append(b.get("name", ""))
    return out


class Unit:
    """One logic element (fle) of the stock `.net`, with the nets at its pins."""

    __slots__ = ("uid", "elem", "atoms", "in_nets", "out_nets", "clk", "orig_key", "orig_slot", "name")

    def __init__(self, uid: int, elem: ET.Element, atoms: list[str], in_nets: list[str | None],
                 out_nets: list[str | None], clk: str | None, orig_key: int, orig_slot: int):
        self.uid, self.elem, self.atoms = uid, elem, atoms
        self.in_nets, self.out_nets, self.clk = in_nets, out_nets, clk
        self.orig_key, self.orig_slot = orig_key, orig_slot
        self.name = elem.get("name", "")


class NetModel:
    """The stock `.net`: kept top-level blocks, movable fle units, the stock clustering."""

    def __init__(self, path: Path):
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rb") as fh:  # type: ignore[operator]
            self.tree = ET.parse(fh)
        self.root = self.tree.getroot()
        self.top: list[tuple[str, int, ET.Element | None]] = []   # (type, key, kept element or None for a movable CLB)
        self.units: dict[int, Unit] = {}
        self.stock: dict[int, int] = {}      # unit id -> stock cluster key
        self.frozen_keys: set[int] = set()
        self.fixed_consumed: set[str] = set()   # nets read by blocks that are never rebuilt (pads, memories, frozen CLBs)
        self.clb_header: ET.Element | None = None
        self.stock_ipins: dict[int, dict[str, int]] = {}   # stock cluster key -> net -> input pin
        self.stock_name: dict[int, str] = {}               # stock cluster key -> block name
        uid = 0
        for i, b in enumerate(self.root.findall("block")):
            m = _INST.match(b.get("instance", ""))
            typ = m.group(1) if m else "?"
            if typ == "clb" and b.find(".//block[@mode='arithmetic']") is None and "open" == (_tokens(b, "inputs", "cin") or ["open"])[0] \
                    and "open" == (_tokens(b, "outputs", "cout") or ["open"])[0]:
                self.top.append((typ, i, None))
                if self.clb_header is None:
                    self.clb_header = b
                uid = self._read_clb(b, i, uid)
            else:
                self.top.append((typ, i, b))
                if typ == "clb":
                    self.frozen_keys.add(i)
                for p in b.findall("inputs/port"):
                    self.fixed_consumed.update(t for t in (p.text or "").split() if "->" not in t and t != "open")
                for p in b.findall("clocks/port"):
                    self.fixed_consumed.update(t for t in (p.text or "").split() if "->" not in t and t != "open")
        self.consumers: dict[str, set[int]] = collections.defaultdict(set)
        for u in self.units.values():
            for n in u.in_nets:
                if n:
                    self.consumers[n].add(u.uid)

    def _read_clb(self, clb: ET.Element, key: int, uid: int) -> int:
        ipins = _tokens(clb, "inputs", "I")
        self.stock_name[key] = clb.get("name", "")
        self.stock_ipins[key] = {t: i for i, t in enumerate(ipins) if t != "open"}
        clk = (_tokens(clb, "clocks", "clk") or ["open"])[0]
        fles = {}
        for f in clb.findall("block"):
            m = _INST.match(f.get("instance", ""))
            if m and m.group(1) == "fle":
                fles[int(m.group(2))] = f
        for slot in sorted(fles):
            f = fles[slot]
            if f.get("name") == "open":
                continue
            ins: list[str | None] = []
            for t in _tokens(f, "inputs", "in"):
                if t == "open":
                    ins.append(None)
                elif t.startswith("clb.I["):
                    ins.append(ipins[int(t[len("clb.I["):t.index("]")])])
                else:
                    m = _REF.match(t)
                    src = fles.get(int(m.group(2))) if m else None
                    ins.append(resolve_out(src, m.group(3), int(m.group(4))) if src is not None and m else None)
            outs = [resolve_out(f, "out", o) for o in (0, 1)]
            fclk = _tokens(f, "clocks", "clk")
            atoms = leaf_atoms(f)
            self.units[uid] = Unit(uid, f, atoms, ins, outs, None if not fclk or fclk[0] == "open" or clk == "open" else clk, key, slot)
            self.stock[uid] = key
            uid += 1
        return uid

    def movable_keys(self) -> list[int]:
        return [k for typ, k, e in self.top if typ == "clb" and e is None]


# ---------------------------------------------------------------------------------------
# legality

def external_inputs(model: NetModel, uids: set[int]) -> set[str]:
    driven = {n for u in uids for n in model.units[u].out_nets if n}
    return {n for u in uids for n in model.units[u].in_nets if n and n not in driven}


def legal(model: NetModel, uids: set[int]) -> bool:
    if len(uids) > CAP_FLE:
        return False
    if len({model.units[u].clk for u in uids if model.units[u].clk}) > 1:
        return False
    return len(external_inputs(model, uids)) <= CAP_IN


# ---------------------------------------------------------------------------------------
# writing

def _build_clb(model: NetModel, key: int, uids: list[int], index: int) -> ET.Element:
    units = [model.units[u] for u in uids]
    assert len(units) <= CAP_FLE
    slots: dict[int, Unit] = {}
    rest = []
    for u in sorted(units, key=lambda x: (x.orig_slot, x.uid)):
        if u.orig_key == key and u.orig_slot not in slots:
            slots[u.orig_slot] = u
        else:
            rest.append(u)
    free = [s for s in range(CAP_FLE) if s not in slots]
    for u in rest:
        slots[free.pop(0)] = u
    driver_at: dict[str, tuple[int, int]] = {}
    for s, u in slots.items():
        for o, n in enumerate(u.out_nets):
            if n:
                driver_at[n] = (s, o)
    clk = next((u.clk for u in units if u.clk), None)
    ext = []
    for s in sorted(slots):
        for n in slots[s].in_nets:
            if n and n not in driver_at and n not in ext:
                ext.append(n)
    assert len(ext) <= CAP_IN, (key, len(ext))
    # keep the stock pin of a net that was already an input pin of this cluster, then fill the free pins
    pin: dict[str, int] = {}
    used: set[int] = set()
    stock_i = model.stock_ipins.get(key, {})
    for n in ext:
        p = stock_i.get(n)
        if p is not None and p not in used:
            pin[n] = p
            used.add(p)
    free_pins = [p for p in range(CAP_IN) if p not in used]
    for n in ext:
        if n not in pin:
            pin[n] = free_pins.pop(0)
            used.add(pin[n])
    ipins = ["open"] * CAP_IN
    for n, p in pin.items():
        ipins[p] = n
    consumers_out = {}
    for s, u in slots.items():
        for o, n in enumerate(u.out_nets):
            if n:
                cons = model.consumers.get(n, set())
                consumers_out[(s, o)] = n in model.fixed_consumed or any(c not in uids for c in cons)
    opins = ["open"] * 20
    for (s, o), need in consumers_out.items():
        if need:
            opins[10 * o + s] = f"fle[{s}].out[{o}]->clbouts{o + 1}"
    first = slots[min(slots)]
    names = {a for u in units for a in u.atoms} | {u.name for u in units}
    cname = model.stock_name.get(key, "")
    clb = ET.Element("block", {"name": cname if cname in names else first.name, "instance": f"clb[{index}]", "mode": "default"})
    ins = ET.SubElement(clb, "inputs")
    ET.SubElement(ins, "port", {"name": "I"}).text = " ".join(ipins)
    ET.SubElement(ins, "port", {"name": "cin"}).text = "open"
    outs = ET.SubElement(clb, "outputs")
    ET.SubElement(outs, "port", {"name": "O"}).text = " ".join(opins)
    ET.SubElement(outs, "port", {"name": "cout"}).text = "open"
    cl = ET.SubElement(clb, "clocks")
    ET.SubElement(cl, "port", {"name": "clk"}).text = clk or "open"
    for s in range(CAP_FLE):
        if s not in slots:
            ET.SubElement(clb, "block", {"name": "open", "instance": f"fle[{s}]"})
            continue
        u = slots[s]
        f = copy.deepcopy(u.elem)
        f.set("instance", f"fle[{s}]")
        toks = []
        for n in u.in_nets:
            if n is None:
                toks.append("open")
            elif n in driver_at:
                toks.append(f"fle[{driver_at[n][0]}].out[{driver_at[n][1]}]->crossbar")
            else:
                toks.append(f"clb.I[{pin[n]}]->crossbar")
        for p in f.findall("inputs/port"):
            if p.get("name") == "in":
                p.text = " ".join(toks)
        clb.append(f)
    return clb


def build_tree(model: NetModel, assign: dict[int, int]) -> ET.ElementTree:
    """The `.net` of the clustering `assign` (unit id -> cluster key). Keys of stock movable CLBs keep their position."""
    members: dict[int, list[int]] = collections.defaultdict(list)
    for u, k in assign.items():
        members[k].append(u)
    new_root = ET.Element(model.root.tag, dict(model.root.attrib))
    for ch in model.root:
        if ch.tag != "block":
            new_root.append(copy.deepcopy(ch))
    index = 0
    stock_keys = {k for typ, k, e in model.top if typ == "clb" and e is None}
    for typ, key, el in model.top:
        if el is not None:
            b = copy.deepcopy(el)
            b.set("instance", f"{typ}[{index}]")
            new_root.append(b)
            index += 1
        elif members.get(key):
            new_root.append(_build_clb(model, key, sorted(members[key]), index))
            index += 1
    for key in sorted(k for k in members if k not in stock_keys and members[k]):
        new_root.append(_build_clb(model, key, sorted(members[key]), index))
        index += 1
    ET.indent(new_root, space="\t")
    return ET.ElementTree(new_root)


def write_net(model: NetModel, assign: dict[int, int], path: Path) -> None:
    tree = build_tree(model, assign)
    nl.ensure_dir(path.parent)
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "wb") as fh:  # type: ignore[operator]
        tree.write(fh, encoding="UTF-8", xml_declaration=True)


def load_model(path: Path) -> NetModel:
    return NetModel(path)


# ---------------------------------------------------------------------------------------
# hindsight re-clustering over fle units

def recluster(model: NetModel, view: lib.NetView, assign: dict[int, int], flat: nl.Flat, pcrit: dict[str, float],
              seed: int = lib.RNG_SEED) -> tuple[dict[int, int], dict[str, Any]]:
    """Move or swap whole fles between logic CLBs within Manhattan distance <= lib.RADIUS (cluster positions from `flat`).

    Same cost and sweep rule as docs/plan/round7.md Stage 2 (net weight 1 + 4 pcrit, fanout <= 32), but the unit is the fle
    and the capacity test is the exact one above. Frozen (carry-chain) CLBs are not touched. Returns (new assign, stats)."""
    rng = random.Random(f"{seed}:{view.design}:net")
    assign = dict(assign)
    pos: dict[str, tuple[float, float]] = {a: (r[0], r[1]) for a, r in flat.atoms.items()}
    members: dict[int, set[int]] = collections.defaultdict(set)
    for u, k in assign.items():
        members[k].add(u)
    cxy: dict[int, tuple[float, float]] = {}
    for k, us in members.items():
        pts = {pos[a] for u in us for a in model.units[u].atoms if a in pos}
        if len(pts) != 1:
            raise RuntimeError(f"cluster {k}: atoms at {len(pts)} places; the source placement does not match the clustering")
        cxy[k] = next(iter(pts))
    unit_of_atom = {a: u for u, un in model.units.items() for a in un.atoms}
    cost_nets = {n for n, ss in view.sinks.items() if len(ss) <= lib.FANOUT_COST and n not in view.clock}
    weight = {n: 1.0 + lib.CRIT_W * pcrit.get(view.driver.get(n, ""), 0.0) for n in cost_nets}
    term_cache: dict[str, list[str]] = {}

    def terms(n: str) -> list[str]:
        t = term_cache.get(n)
        if t is None:
            t = [x for x in view.terminals(n) if x in pos]
            term_cache[n] = t
        return t

    def loc(a: str, ov: dict[int, tuple[float, float]]) -> tuple[float, float]:
        u = unit_of_atom.get(a)
        if u is None:
            return pos[a]
        if u in ov:
            return ov[u]
        k = assign.get(u)
        return cxy[k] if k is not None and k in cxy else pos[a]

    def ncost(n: str, ov: dict[int, tuple[float, float]]) -> float:
        t = terms(n)
        if len(t) < 2:
            return 0.0
        xs = [loc(a, ov) for a in t]
        return weight[n] * ((max(p[0] for p in xs) - min(p[0] for p in xs)) + (max(p[1] for p in xs) - min(p[1] for p in xs)))

    def unit_nets(us: list[int]) -> set[str]:
        s: set[str] = set()
        for u in us:
            for a in model.units[u].atoms:
                s.update(n for n in view.ins.get(a, ()) if n in cost_nets)
                s.update(n for n in view.outs.get(a, ()) if n in cost_nets)
        return s

    movable = [k for k in members if k not in model.frozen_keys]
    byxy = {cxy[k]: k for k in movable}
    neigh: dict[int, list[int]] = {}
    for k in movable:
        x, y = cxy[k]
        neigh[k] = [byxy[(x + dx, y + dy)] for dx in range(-lib.RADIUS, lib.RADIUS + 1) for dy in range(-lib.RADIUS, lib.RADIUS + 1)
                    if 0 < abs(dx) + abs(dy) <= lib.RADIUS and (x + dx, y + dy) in byxy]
    total0 = sum(ncost(n, {}) for n in cost_nets if len(terms(n)) > 1)
    order = sorted(u for u in assign if assign[u] in neigh)
    moves = swaps = sweeps = 0
    for sweeps in range(1, lib.MAX_SWEEPS + 1):
        rng.shuffle(order)
        changed = 0
        for u in order:
            a = assign[u]
            nets_u = unit_nets([u])
            if not nets_u:
                continue
            base = sum(ncost(n, {}) for n in nets_u)
            best: tuple[float, int | None, int | None] = (-1e-9, None, None)
            for b in neigh.get(a, ()):
                d_move = sum(ncost(n, {u: cxy[b]}) for n in nets_u) - base
                if d_move >= -1e-9:
                    continue
                if legal(model, members[b] | {u}) and legal(model, members[a] - {u}):
                    if d_move < best[0]:
                        best = (d_move, b, None)
                    continue
                cand: list[tuple[float, int]] = []
                for v in members[b]:
                    nets_uv = unit_nets([u, v])
                    ov = {u: cxy[b], v: cxy[a]}
                    d = sum(ncost(n, ov) for n in nets_uv) - sum(ncost(n, {}) for n in nets_uv)
                    cand.append((d, v))
                cand.sort()
                for d, v in cand[:3]:
                    if d >= best[0]:
                        break
                    if legal(model, (members[b] - {v}) | {u}) and legal(model, (members[a] - {u}) | {v}):
                        best = (d, b, v)
                        break
            if best[1] is None:
                continue
            _d, b, v = best
            members[a].discard(u)
            members[b].add(u)
            assign[u] = b
            if v is not None:
                members[b].discard(v)
                members[a].add(v)
                assign[v] = a
                swaps += 1
            else:
                moves += 1
            changed += 1
        if not changed:
            break
    total1 = sum(ncost(n, {}) for n in cost_nets if len(terms(n)) > 1)
    stats = {"sweeps": sweeps, "moves": moves, "swaps": swaps, "cost_before": total0, "cost_after": total1,
             "units": len(model.units), "movable_units": len(order),
             "units_moved": sum(1 for u in assign if assign[u] != model.stock[u]),
             "clbs_before": len(set(model.stock.values())), "clbs_after": len(set(assign.values()))}
    return assign, stats


def known_assign(model: NetModel, view: lib.NetView, group_of_atom: dict[str, int]) -> tuple[dict[int, int] | None, str]:
    """Clustering `known` of a calibration design from its atom -> block labels; None plus a reason when a block is not a legal CLB."""
    assign: dict[int, int] = {}
    for u, un in model.units.items():
        labs = {group_of_atom[a] for a in un.atoms if a in group_of_atom}
        if len(labs) != 1:
            return None, f"fle {un.name} holds atoms of {len(labs)} blocks"
        assign[u] = NEW_KEY + next(iter(labs))
    for k in set(assign.values()):
        if not legal(model, {u for u, kk in assign.items() if kk == k}):
            return None, f"block {k - NEW_KEY} is not a legal CLB"
    return assign, ""


# ---------------------------------------------------------------------------------------
# realised clustering

def realised_fidelity(model: NetModel, assign: dict[int, int], flat_path: Path) -> dict[str, float]:
    """Share of the written clusters (>= 2 atoms) whose atoms VPR placed in one CLB, and the converse (no two written
    clusters in one CLB). 1.0 and 1.0 are expected: VPR read the clustering."""
    groups = lib.realised_groups(flat_path, {a for un in model.units.values() for a in un.atoms})
    by: dict[int, list[str]] = collections.defaultdict(list)
    for u, k in assign.items():
        by[k].extend(model.units[u].atoms)
    tgt = {a: k for k, atoms in by.items() for a in atoms}
    fid = lib.fidelity(tgt, groups)
    inv: dict[int, set[int]] = collections.defaultdict(set)
    for a, c in groups.items():
        inv[c].add(tgt[a])
    fid["clbs_mixed"] = sum(1 for s in inv.values() if len(s) > 1)
    return fid


# ---------------------------------------------------------------------------------------
# driver

def scratch_root() -> Path:
    p = R7F / "scratch_path.txt"
    if p.is_file():
        root = Path(p.read_text().strip())
        if root.is_dir():
            return root
    nl.ensure_dir(R7F)
    root = Path(tempfile.mkdtemp(prefix="nr7f-", dir="/tmp/claude-1000"))
    p.write_text(str(root) + "\n", encoding="utf-8")
    return root


def run_dir(design: str, arm: str, seed: int) -> Path:
    return R7F / design / f"{arm}.s{seed}"


def read_metrics(design: str, arm: str, seed: int) -> dict[str, Any] | None:
    p = run_dir(design, arm, seed) / "metrics.json"
    if not p.is_file():
        return None
    try:
        return nl.read_json(p)
    except ValueError:
        return None


def vpr_net_run(design: str, arm: str, seed: int, net_path: Path, model: NetModel, assign: dict[int, int]) -> dict[str, Any]:
    """One VPR run on a written `.net` (packing off). Under the heavy lock; kept files in runs/r7f/<d>/<arm>.s<seed>/."""
    done = read_metrics(design, arm, seed)
    if done is not None and done.get("rc") == 0:
        return done
    import shutil
    rd = run_dir(design, arm, seed)
    sc = scratch_root() / design / f"{arm}.s{seed}"
    nl.ensure_dir(sc)
    nl.ensure_dir(rd)
    sc_net = sc / f"{design}.net"
    shutil.copy(net_path, sc_net) if not str(net_path).endswith(".gz") else _gunzip(net_path, sc_net)
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    flags = ["--place", "--route", "--net_file", str(sc_net), "--seed", str(seed), "--timing_report_npaths", str(lib.NPATHS),
             "--route_file", "/dev/null", "--write_initial_place_file", str(sc / "initial.place"),
             "--write_flat_place", str(sc / "final.flat_place")]
    nornsvpr = os.environ.get("NORNS_VPR", "")
    cmd = ["flock", "-x", str(nl.LOCK), nornsvpr, str(nl.ARCH), str(blif)] + flags
    rc = nl.run(cmd, cwd=sc, stdout=sc / "vpr.out", timeout=TIMEOUT)
    rec: dict[str, Any] = {"design": design, "arm": arm, "seed": seed, "rc": rc}
    if rc == 0:
        text = (sc / "vpr.out").read_text(errors="replace")
        rec.update(nl.Metrics(sc / "vpr.out").values)
        for k in ("curve", "init_t"):
            rec.pop(k, None)
        m = re.search(r"The entire flow of VPR took [0-9.]+ seconds \(max_rss ([0-9.]+) MiB", text)
        rec["max_rss_mib"] = float(m.group(1)) if m else None
        rec["packed_by_vpr"] = "### Packing took" in text
        shutil.copy(sc / f"{design}.place", rd / f"{design}.place")
        shutil.copy(sc / "final.flat_place", rd / "final.flat_place")
        shutil.copy(sc / "vpr.out", rd / "vpr.out")
        import r3lib
        rec["logic_clbs"] = len(r3lib.logic_groups(rd / "final.flat_place"))
        paths = lib.parse_report(sc / "report_timing.setup.rpt")
        rec["paths_in_report"] = len(paths)
        with gzip.open(rd / "paths.json.gz", "wt") as fh:
            json.dump([{"arrival": p["arrival"], "slack": p["slack"], "nodes": p["nodes"]} for p in paths], fh)
        fid = realised_fidelity(model, assign, rd / "final.flat_place")
        rec["fidelity"] = fid
        assert fid["share"] == 1.0 and fid["clbs_mixed"] == 0, f"{design}/{arm}.s{seed}: clustering not read as written {fid}"
        rec["objective"] = lib.objective(rec)
    else:
        rec["error"] = (sc / "vpr.out").read_text(errors="replace")[-400:] if (sc / "vpr.out").is_file() else ""
    nl.write_json(rd / "metrics.json", rec)
    lib.jsonl_append(R7F / "runs.jsonl", rec)
    print(f"{design}/{arm}.s{seed}: rc={rc} wl={rec.get('wirelength')} cpd={rec.get('cpd_ns')} W={rec.get('chan_width')} "
          f"clbs={rec.get('logic_clbs')} flow_s={rec.get('flow_s')}", flush=True)
    return rec


def _gunzip(src: Path, dst: Path) -> None:
    import shutil
    with gzip.open(src, "rb") as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)


def stock_net_path(design: str) -> Path:
    return lib.R7 / design / "stock.s1" / f"{design}.net.gz"


def clustering_of_run(model: NetModel, flat_path: Path) -> dict[int, int]:
    """unit id -> cluster key from the CLB each unit's atoms sit in, in a run's flat placement (keys are the run's CLB ids + NEW_KEY)."""
    groups = lib.realised_groups(flat_path, {a for un in model.units.values() for a in un.atoms})
    out: dict[int, int] = {}
    for u, un in model.units.items():
        cl = {groups.get(a) for a in un.atoms}
        if len(cl) != 1 or None in cl:
            raise RuntimeError(f"unit {un.name} split over {cl}")
        out[u] = NEW_KEY + next(iter(cl))
    return out


def objective_of(design: str, arm: str, seeds: tuple[int, ...]) -> list[float]:
    out = []
    for s in seeds:
        m = read_metrics(design, arm, s)
        if m and m.get("rc") == 0:
            out.append(m["objective"])
    return out


def source_pcrit(design: str, arm: str, seed: int) -> dict[str, float]:
    with gzip.open(run_dir(design, arm, seed) / "paths.json.gz", "rt") as fh:
        pc, _sl, _cpd = lib.path_crit(json.load(fh))
    return pc


def hindsight(design: str) -> dict[str, Any]:
    """net0 (the stock clustering written by this module), net_h1..h5, net_known (calibration designs)."""
    out_path = R7F / design / "rounds.json"
    model = load_model(stock_net_path(design))
    view = lib.NetView(design)
    rec: dict[str, Any] = {"design": design, "units": len(model.units), "frozen_clbs": len(model.frozen_keys),
                           "movable_clbs": len(model.movable_keys()), "rounds": [], "stopped": None}
    stock_assign = dict(model.stock)
    assert all(legal(model, {u for u, k in stock_assign.items() if k == c}) for c in set(stock_assign.values()) if c not in model.frozen_keys), \
        "a stock CLB fails the legality test: the rule is not the architecture's"

    def run_arm(arm: str, assign: dict[int, int]) -> list[dict[str, Any]]:
        netp = R7F / design / f"{arm}.net.gz"
        if not netp.is_file():
            write_net(model, assign, netp)
        return [vpr_net_run(design, arm, s, netp, model, assign) for s in lib.SEEDS]

    base = run_arm("net0", stock_assign)
    if sum(1 for m in base if m.get("rc") == 0) < 8:
        rec["stopped"] = "fewer than 8 net0 runs"
        nl.write_json(out_path, rec)
        return rec
    if design.startswith("n5_"):
        import r5lib as rl
        spec = rl.read_spec(design)
        lab = {}
        for a in {a for un in model.units.values() for a in un.atoms}:
            k, _ = rl.label_of(a, spec)
            if k is not None:
                lab[a] = int(k)
        ka, why = known_assign(model, view, lab)
        if ka is None:
            rec["known"] = {"built": False, "why": why}
        else:
            run_arm("net_known", ka)
            rec["known"] = {"built": True, "clbs": len(set(ka.values()))}
    med = {"net0": statistics.median(objective_of(design, "net0", SPLIT_TRAIN))}
    src_arm, cur = "net0", stock_assign
    for k in range(1, lib.MAX_ROUNDS + 1):
        arm = f"net_h{k}"
        train = [(m["objective"], m["seed"]) for m in (read_metrics(design, src_arm, s) for s in SPLIT_TRAIN) if m and m.get("rc") == 0]
        b_obj, b_seed = min(train)
        rc_path = R7F / design / f"{arm}.recluster.json"
        asg_path = R7F / design / f"{arm}.assign.json"
        if asg_path.is_file():
            new = {int(u): int(c) for u, c in nl.read_json(asg_path).items()}
            stats = nl.read_json(rc_path)
        else:
            flat = nl.Flat(run_dir(design, src_arm, b_seed) / "final.flat_place")
            cur_keys = clustering_of_run(model, run_dir(design, src_arm, b_seed) / "final.flat_place")
            # the run's own clustering must be the one we wrote
            same = {}
            for u, c in cur_keys.items():
                same.setdefault(c, set()).add(cur[u])
            if any(len(v) != 1 for v in same.values()):
                raise RuntimeError(f"{design} {src_arm}: realised clustering differs from the written one")
            new, stats = recluster(model, view, cur, flat, source_pcrit(design, src_arm, b_seed))
            stats.update({"source_arm": src_arm, "source_seed": b_seed})
            nl.write_json(rc_path, stats)
            nl.write_json(asg_path, {str(u): c for u, c in new.items()})
            print(f"{design} {arm}: recluster {stats}", flush=True)
        runs = run_arm(arm, new)
        ok = [m for m in runs if m.get("rc") == 0]
        r: dict[str, Any] = {"arm": arm, "ok": len(ok), "recluster": stats}
        if len(ok) < 8:
            r["note"] = "fewer than 8 runs"
            rec["rounds"].append(r)
            rec["stopped"] = f"{arm}: fewer than 8 runs"
            break
        tr = objective_of(design, arm, SPLIT_TRAIN)
        r["median_objective_train"] = statistics.median(tr)
        rec["rounds"].append(r)
        prev = min(med.values())
        med[arm] = r["median_objective_train"]
        nl.write_json(out_path, rec)
        print(f"{design} {arm}: train median obj {med[arm]:.1f} vs best earlier {prev:.1f}", flush=True)
        if med[arm] > (1.0 - lib.STOP_GAIN) * prev:
            rec["stopped"] = f"{arm}: train median objective not >= 1% below the best earlier arm"
            break
        src_arm, cur = arm, new
    else:
        rec["stopped"] = "K = 5 rounds"
    rec["medians_train"] = med
    rec["hindsight_arm"] = min(med, key=lambda a: med[a])
    nl.write_json(out_path, rec)
    return rec


def status() -> int:
    p = R7F / "runs.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []
    print(f"runs logged: {len(rows)}, failed: {sum(1 for r in rows if r['rc'] != 0)}")
    for d in list(lib.CALIB) + list(lib.MAIN):
        rp = R7F / d / "rounds.json"
        if rp.is_file():
            r = nl.read_json(rp)
            print(d, r.get("hindsight_arm"), r.get("stopped"))
    return 0


def main(argv: list[str]) -> int:
    mode, designs = argv[0], argv[1:]
    if mode == "status":
        return status()
    if mode == "run":
        for d in designs:
            hindsight(d)
        return 0
    nl.die(f"unknown mode {mode}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
