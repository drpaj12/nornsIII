"""Round-7 library (protocol: docs/plan/round7.md): timing-report parser, run summaries, the hindsight re-clustering,
duplication candidates, HDL relations. Stdlib plus numpy; no file is ever deleted.
"""

from __future__ import annotations

import collections
import gzip
import json
import random
import re
from pathlib import Path
from typing import Any

import nornlib as nl

R7 = nl.RUNS / "r7"
DATA7 = nl.DATA / "r7"
SEEDS = tuple(range(1, 11))
MAX_ROUNDS = 5
STOP_GAIN = 0.01
NPATHS = 200
FANOUT_COST = 32
CRIT_W = 4.0
RADIUS = 2
MAX_SWEEPS = 30
CAP_LUT, CAP_FF, CAP_IN, CAP_OUT = 10, 20, 40, 20
RNG_SEED = 20261026
PCRIT_NEAR = (0.95, 0.90)
AFF_BETA = 100.0

MAIN = ("ch_intrinsics", "stereovision3", "diffeq2", "diffeq1", "mkPktMerge", "raygentop", "sha", "boundtop",
        "mkSMAdapter4B", "or1200", "stereovision0", "stereovision1", "mkDelayWorker32B", "stereovision2", "blob_merge")
CALIB = tuple(f"n5_{t}_{s}_{b}" for b in (16, 64, 256) for t in ("mesh", "tree") for s in ("dp", "ctl"))


def run_dir(design: str, arm: str, seed: int) -> Path:
    return R7 / design / f"{arm}.s{seed}"


def base_name(atom: str) -> str:
    """Atom name with the directory part of the source file removed (no absolute paths in committed data)."""
    m = re.match(r"^(.*?)@(.*?)([^/:]+):(\d+)$", atom)
    return f"{m.group(1)}@{m.group(3)}:{m.group(4)}" if m else atom


# ---------------------------------------------------------------------------------------
# timing report

_NODE = re.compile(r"^(?P<name>\S.*?)\.(?P<port>[A-Za-z_0-9$]+)\[(?P<idx>\d+)\] \((?P<type>[^)]*)\)(?P<rest>.*)$")
_NUMS = re.compile(r"(-?[0-9.]+)\s+(-?[0-9.]+)\s*$")
_LAST = re.compile(r"(-?[0-9.]+)\s*$")


def parse_report(path: Path) -> list[dict[str, Any]]:
    """Paths of a VPR setup timing report: [{'arrival', 'slack', 'nodes': [(atom, port, type, incr)]}]."""
    paths: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_data = False
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#Path"):
                cur = {"arrival": None, "slack": None, "nodes": []}
                paths.append(cur)
                in_data = False
                continue
            if cur is None:
                continue
            if line.startswith("Point"):
                in_data = True
                continue
            if line.startswith("data arrival time"):
                m = _LAST.search(line)
                if m:
                    cur["arrival"] = abs(float(m.group(1)))
                in_data = False
                continue
            if line.startswith("slack"):
                m = _LAST.search(line)
                if m:
                    cur["slack"] = float(m.group(1))
                continue
            if not in_data or line.startswith("-"):
                continue
            m = _NODE.match(line.rstrip())
            if not m:
                continue
            nums = _NUMS.search(m.group("rest"))
            incr = float(nums.group(1)) if nums else 0.0
            cur["nodes"].append((m.group("name"), m.group("port"), m.group("type"), incr))
    return [p for p in paths if p["arrival"] is not None]


def path_crit(paths: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float], float]:
    """(atom -> pcrit, atom -> worst slack, cpd) over the reported paths. pcrit = max arrival(p)/CPD over paths through the atom."""
    cpd = max((p["arrival"] for p in paths), default=0.0)
    pcrit: dict[str, float] = {}
    slack: dict[str, float] = {}
    for p in paths:
        c = p["arrival"] / cpd if cpd else 0.0
        s = p["slack"] if p["slack"] is not None else 0.0
        for atom in {n[0] for n in p["nodes"]}:
            if c > pcrit.get(atom, -1.0):
                pcrit[atom] = c
            if s < slack.get(atom, 1e30):
                slack[atom] = s
    return pcrit, slack, cpd


# ---------------------------------------------------------------------------------------
# netlist view

def netlist(design: str):
    """r4census.Netlist, tolerant of designs without a word file (the netlist-level constructions)."""
    import r4census as rc

    class _NL(rc.Netlist):
        @staticmethod
        def _words(d: str) -> dict[str, str]:
            p = nl.runs_dir(d, "words", "members.json")
            return super(_NL, _NL)._words(d) if p.is_file() else {}

    return _NL(design)


class NetView:
    """Atoms (LUT, FF, adder), nets, input and output nets per atom, from r4census.Netlist."""

    def __init__(self, design: str):
        self.design = design
        n = netlist(design)
        self.nlist = n
        self.kind = n.kind
        self.driver = n.driver
        self.clock: set[str] = set()
        self.sinks: dict[str, list[str]] = {}
        for net, ss in n.sinks.items():
            self.sinks[net] = [(f"out:{net}" if s == "<pad>" else s) for s in ss]
        self.ins: dict[str, list[str]] = collections.defaultdict(list)
        for net, ss in self.sinks.items():
            for s in ss:
                self.ins[s].append(net)
        self.outs: dict[str, list[str]] = collections.defaultdict(list)
        for net, d in self.driver.items():
            self.outs[d].append(net)

    def terminals(self, net: str) -> list[str]:
        d = self.driver.get(net)
        return ([d] if d else [net]) + self.sinks[net]  # a net without a driver atom is a primary input: its pad is named by the net


def hdl_table(design: str, atoms: list[str]) -> dict[str, dict[str, Any]]:
    """Per atom: kind, construct (file:line, base file), instance path components, word, bit, bus."""
    mem_path = nl.runs_dir(design, "words", "members.json")
    members = nl.read_json(mem_path) if mem_path.is_file() else {}
    spec = None
    if design.startswith("n5_"):
        import r5lib as rl
        spec = rl.read_spec(design)
    out: dict[str, dict[str, Any]] = {}
    for a in atoms:
        path, leaf, file, line = nl.provenance_parts(a)
        m = members.get(a, {})
        word, bit, bus = m.get("word"), m.get("bit"), m.get("bus")
        if design.startswith("n5_"):
            import r5lib as rl
            k, _ = rl.label_of(a, spec)
            mm = re.match(r"^b(\d+)_[lq](\d+)$", a)
            if k is not None:
                path = f"b{k}"
                if mm:
                    bit = int(mm.group(2))
                    word = f"b{k}"
        out[a] = {"construct": f"{Path(file).name}:{line}" if file else "", "inst": [c for c in path.split("/") if c],
                  "word": word, "bit": bit, "bus": bus, "leaf": leaf}
    return out


# ---------------------------------------------------------------------------------------
# hindsight re-clustering

def _metrics(view: NetView, atoms: set[str]) -> tuple[float, int, int, int]:
    """(LUT weight, FFs, distinct input nets from outside, output nets leaving) of a CLB holding `atoms`.
    A LUT of >= 6 distinct inputs weighs 1, a smaller LUT 0.5 (two 5-LUTs share a logic element)."""
    lutw = 0.0
    ffs = 0
    nin: set[str] = set()
    nout = 0
    for a in atoms:
        k = view.kind[a]
        ins = view.ins.get(a, ())
        if k == "lut":
            lutw += 1.0 if len(set(ins)) >= 6 else 0.5
        elif k == "latch":
            ffs += 1
        for n in ins:
            if n in view.clock:
                continue
            d = view.driver.get(n)
            if d is None or d not in atoms:
                nin.add(n)
        for n in view.outs.get(a, ()):
            if any(s not in atoms for s in view.sinks.get(n, ())):
                nout += 1
    return lutw, ffs, len(nin), nout


def _legal(view: NetView, atoms: set[str], orig: tuple[float, int, int, int]) -> bool:
    """Capacity of one CLB holding `atoms` (approximation of the CLB legality; VPR checks the real one). A limit the
    CLB already exceeds in the input placement (the approximation is coarser than VPR) may not get worse."""
    m = _metrics(view, atoms)
    caps = (CAP_LUT, CAP_FF, CAP_IN, CAP_OUT)
    return all(x <= max(c, o) for x, c, o in zip(m, caps, orig))


def recluster(view: NetView, flat: nl.Flat, pcrit: dict[str, float], seed: int = RNG_SEED) -> tuple[dict[str, int], dict[str, Any]]:
    """Hindsight re-clustering of the logic CLBs of a placement (docs/plan/round7.md, Stage 2, steps 1-2).

    Returns (atom -> group id for every logic atom, statistics). Group ids are the CLB ids of the input placement, so an
    unchanged atom keeps its id. Cost = sum over nets (fanout <= 32) of (1 + 4 pcrit(driver)) * HPWL of the CLB coordinates of the pins.
    """
    rng = random.Random(f"{seed}:{view.design}")
    pos: dict[str, tuple[float, float]] = {}
    clb_of: dict[str, int] = {}
    pbt: dict[str, str] = {}
    clb_types: dict[str, set[str]] = collections.defaultdict(set)
    for a, (x, y, _l, _s, clb, pb) in flat.atoms.items():
        pos[a] = (x, y)
        clb_types[clb].add(pb)
        pbt[a] = pb
    logic = {c for c, t in clb_types.items() if t <= {"lut", "ff", "adder"} and t}
    frozen = {c for c in logic if "adder" in clb_types[c]}
    for a, row in flat.atoms.items():
        if a in view.kind and row[4] in logic:
            clb_of[a] = int(row[4].lstrip("#")) if isinstance(row[4], str) else int(row[4])
    members: dict[int, set[str]] = collections.defaultdict(set)
    for a, c in clb_of.items():
        members[c].add(a)
    cxy: dict[int, tuple[float, float]] = {}
    for a, c in clb_of.items():
        cxy[c] = pos[a]
    frozen_ids = {int(str(c).lstrip("#")) for c in frozen}
    # units: LUT plus the FF it alone drives, else single atoms
    unit_of: dict[str, int] = {}
    units: dict[int, list[str]] = {}
    nu = 0
    for c in sorted(members):
        if c in frozen_ids:
            continue
        mem = members[c]
        done: set[str] = set()
        for a in sorted(mem):
            if a in done:
                continue
            grp = [a]
            if view.kind[a] == "lut":
                outn = view.outs.get(a, [])
                if len(outn) == 1 and len(view.sinks.get(outn[0], [])) == 1:
                    f = view.sinks[outn[0]][0]
                    if f in mem and view.kind.get(f) == "latch" and f not in done and len(view.ins.get(f, [])) <= 2:
                        grp.append(f)
            done.update(grp)
            for g in grp:
                unit_of[g] = nu
            units[nu] = grp
            nu += 1
    cost_nets = {n for n, ss in view.sinks.items() if len(ss) <= FANOUT_COST and n not in view.clock}
    weight = {n: 1.0 + CRIT_W * pcrit.get(view.driver.get(n, ""), 0.0) for n in cost_nets}
    term_cache: dict[str, list[str]] = {}

    def terms(n: str) -> list[str]:
        t = term_cache.get(n)
        if t is None:
            t = [x for x in view.terminals(n) if x in pos]
            term_cache[n] = t
        return t

    def loc(a: str, ov: dict[str, tuple[float, float]]) -> tuple[float, float]:
        if a in ov:
            return ov[a]
        c = clb_of.get(a)
        return cxy[c] if c is not None else pos[a]

    def ncost(n: str, ov: dict[str, tuple[float, float]]) -> float:
        t = terms(n)
        if len(t) < 2:
            return 0.0
        xs = [loc(a, ov) for a in t]
        return weight[n] * ((max(p[0] for p in xs) - min(p[0] for p in xs)) + (max(p[1] for p in xs) - min(p[1] for p in xs)))

    def unit_nets(us: list[int]) -> set[str]:
        s: set[str] = set()
        for u in us:
            for a in units[u]:
                s.update(n for n in view.ins.get(a, ()) if n in cost_nets)
                s.update(n for n in view.outs.get(a, ()) if n in cost_nets)
        return s

    movable = [c for c in members if c not in frozen_ids]
    neigh: dict[int, list[int]] = {}
    byxy: dict[tuple[float, float], int] = {cxy[c]: c for c in movable}
    for c in movable:
        x, y = cxy[c]
        neigh[c] = [byxy[(x + dx, y + dy)] for dx in range(-RADIUS, RADIUS + 1) for dy in range(-RADIUS, RADIUS + 1)
                    if 0 < abs(dx) + abs(dy) <= RADIUS and (x + dx, y + dy) in byxy]
    orig = {c: _metrics(view, members[c]) for c in movable}
    total0 = sum(ncost(n, {}) for n in cost_nets if len(terms(n)) > 1)
    moves = swaps = sweeps = 0
    order = sorted(units)
    unit_clb = {u: clb_of[units[u][0]] for u in units}

    def with_change(clb: int, add: list[str], rem: list[str]) -> set[str]:
        return (members[clb] - set(rem)) | set(add)

    for sweeps in range(1, MAX_SWEEPS + 1):
        rng.shuffle(order)
        changed = 0
        for u in order:
            a_clb = unit_clb[u]
            ua = units[u]
            nets_u = unit_nets([u])
            if not nets_u:
                continue
            base = sum(ncost(n, {}) for n in nets_u)
            best = (-1e-9, None, None)
            for b_clb in neigh.get(a_clb, ()):
                ov = {a: cxy[b_clb] for a in ua}
                d_move = sum(ncost(n, ov) for n in nets_u) - base
                if d_move >= -1e-9:
                    continue
                dst_after = with_change(b_clb, ua, [])
                if _legal(view, dst_after, orig[b_clb]) and _legal(view, with_change(a_clb, [], ua), orig[a_clb]):
                    if d_move < best[0]:
                        best = (d_move, b_clb, None)
                    continue
                # target full: swap with the unit of b_clb whose move to a_clb costs least
                cand: list[tuple[float, int]] = []
                for v in {unit_of[a] for a in members[b_clb] if a in unit_of}:
                    uv = units[v]
                    nets_uv = unit_nets([u, v])
                    ov2 = {a: cxy[b_clb] for a in ua}
                    ov2.update({a: cxy[a_clb] for a in uv})
                    d = sum(ncost(n, ov2) for n in nets_uv) - sum(ncost(n, {}) for n in nets_uv)
                    cand.append((d, v))
                cand.sort()
                for d, v in cand[:3]:
                    if d >= best[0]:
                        break
                    uv = units[v]
                    if _legal(view, with_change(b_clb, ua, uv), orig[b_clb]) and _legal(view, with_change(a_clb, uv, ua), orig[a_clb]):
                        best = (d, b_clb, v)
                        break
            if best[1] is None:
                continue
            _d, b_clb, v = best
            for a in ua:
                members[a_clb].discard(a)
                members[b_clb].add(a)
                clb_of[a] = b_clb
            unit_clb[u] = b_clb
            if v is not None:
                for a in units[v]:
                    members[b_clb].discard(a)
                    members[a_clb].add(a)
                    clb_of[a] = a_clb
                unit_clb[v] = a_clb
                swaps += 1
            else:
                moves += 1
            changed += 1
        if not changed:
            break
    total1 = sum(ncost(n, {}) for n in cost_nets if len(terms(n)) > 1)
    group = {a: c for a, c in clb_of.items()}
    # atoms in CLBs the packer sees but outside `view.kind` (none) are not labelled
    changed_atoms = sum(1 for a, c in group.items() if int(str(flat.atoms[a][4]).lstrip("#")) != c)
    stats = {"sweeps": sweeps, "moves": moves, "swaps": swaps, "cost_before": total0, "cost_after": total1,
             "units": len(units), "frozen_clbs": len(frozen_ids), "movable_clbs": len(movable),
             "atoms_moved": changed_atoms, "clbs_before": len(logic), "clbs_after": len({c for c in group.values() if members[c]})}
    return group, stats


def write_affinity(path: Path, group: dict[str, int]) -> int:
    nl.ensure_dir(path.parent)
    ids = {g: i for i, g in enumerate(sorted(set(group.values())))}
    path.write_text("".join(f"{a}\t{ids[g]}\n" for a, g in sorted(group.items())), encoding="utf-8")
    return len(group)


def read_aff(path: Path) -> dict[str, int]:
    return {ln.split("\t")[0]: int(ln.split("\t")[1]) for ln in path.read_text().splitlines() if ln}


def realised_groups(flat_path: Path, atoms: set[str]) -> dict[str, int]:
    """atom -> CLB id of a run's flat placement, for the logic atoms in `atoms` that sit in logic CLBs."""
    import r3lib
    groups = r3lib.logic_groups(flat_path)
    out: dict[str, int] = {}
    for clb, mem in groups.items():
        for a in mem:
            if a in atoms:
                out[a] = int(str(clb).lstrip("#"))
    return out


def fidelity(target: dict[str, int], realised: dict[str, int]) -> dict[str, float]:
    """Share of the target's groups (>= 2 atoms) that the packer put into one CLB, and the atom-weighted share."""
    by: dict[int, list[str]] = collections.defaultdict(list)
    for a, g in target.items():
        by[g].append(a)
    whole = tot = atoms_whole = atoms_tot = 0
    for g, mem in by.items():
        if len(mem) < 2:
            continue
        tot += 1
        atoms_tot += len(mem)
        if len({realised.get(a) for a in mem}) == 1 and realised.get(mem[0]) is not None:
            whole += 1
            atoms_whole += len(mem)
    return {"groups": tot, "groups_whole": whole, "share": whole / tot if tot else float("nan"),
            "atom_share": atoms_whole / atoms_tot if atoms_tot else float("nan")}


# ---------------------------------------------------------------------------------------
# duplication candidates

def dup_candidates(view: NetView, clb_of: dict[str, int]) -> list[str]:
    """LUT atoms whose output net has sinks in >= 2 distinct CLBs (the driver's own CLB counts when it holds a sink)."""
    out = []
    for a, k in view.kind.items():
        if k != "lut":
            continue
        for n in view.outs.get(a, ()):
            cl = {clb_of.get(s, ("pad", s)) for s in view.sinks.get(n, ()) if s != a}
            if len(cl) >= 2:
                out.append(a)
                break
    return out


def dup_saving(paths: list[dict[str, Any]], cands: set[str], clb_of: dict[str, int]) -> dict[str, float]:
    """Upper estimate of the delay a copy could save: hops that leave a candidate to another CLB become free."""
    cpd = max((p["arrival"] for p in paths), default=0.0)
    if not paths:
        return {"cpd": 0.0, "cpd_after": 0.0, "saved": 0.0, "paths_with_hop": 0}
    floor = min(p["arrival"] for p in paths)
    best = floor
    with_hop = 0
    for p in paths:
        cut = 0.0
        hit = False
        nodes = p["nodes"]
        for prev, cur in zip(nodes, nodes[1:]):
            if prev[0] in cands and cur[0] != prev[0] and prev[1] not in ("clk",) and clb_of.get(prev[0]) != clb_of.get(cur[0]):
                cut += cur[3]
                hit = True
        with_hop += hit
        best = max(best, p["arrival"] - cut)
    return {"cpd": cpd, "cpd_after": best, "saved": cpd - best, "paths_with_hop": with_hop}


# ---------------------------------------------------------------------------------------
# run bookkeeping

def read_metrics(design: str, arm: str, seed: int) -> dict[str, Any] | None:
    p = run_dir(design, arm, seed) / "metrics.json"
    if not p.is_file():
        return None
    try:
        return nl.read_json(p)
    except ValueError:
        return None


def objective(m: dict[str, Any]) -> float:
    return float(m["wirelength"]) * float(m["cpd_ns"])


def jsonl_append(path: Path, rec: dict[str, Any]) -> None:
    nl.ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def gz_write(path: Path, text: str) -> None:
    nl.ensure_dir(path.parent)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(text)
