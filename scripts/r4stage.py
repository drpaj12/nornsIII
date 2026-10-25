"""N16 stage x bit floorplan seed (`stagebit`; construction in docs/plan/round4.md, with the dated entry that
fixes the slot pool).

  python scripts/r4stage.py DESIGN BASE_RUN_DIR OUT.place     BASE_RUN_DIR holds initial.place, final.flat_place

Partial seed like round 2's `words_partial`: only logic CLBs that get a (stage, bit) pair, or are control, move;
every other CLB (pads, memories, multipliers, carry-chain CLBs, CLBs without a bit) keeps its analytic
position. The moved CLBs permute among the slots they occupy in the analytic placement.
"""

from __future__ import annotations

import collections
import statistics
import sys
from pathlib import Path

import numpy as np

import build_seeds as bs
import nornlib as nl

BROADCAST = 32
BIT_SHARE = 1 / 3


def atom_graph(design: str, atom_names: set[str]) -> tuple[list[str], dict[str, list[str]], set[str], dict[str, str], dict[str, int]]:
    """(nodes in BLIF order, out-edges, FF nodes, net driver, net fanout) of the atom graph; clock nets
    are left out. Primary inputs are nodes named after their net."""
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    arch = nl.arch_output_ports(nl.ARCH)
    parsed = nl.parse_blif(blif, atom_names, arch)
    clocks: set[str] = set()
    for line in nl.logical_lines(blif):
        tok = line.split()
        if tok and tok[0] == ".latch" and len(tok) >= 5 and tok[3] in ("re", "fe", "ah", "al", "as"):
            clocks.add(tok[4])
        elif tok and tok[0] == ".subckt":
            for item in tok[2:]:
                if "=" in item and item.split("=", 1)[0].lower().startswith("clk"):
                    clocks.add(item.split("=", 1)[1])
    nodes: list[str] = list(parsed["inputs"])
    driver: dict[str, str] = {n: n for n in parsed["inputs"]}
    ins: dict[str, list[str]] = {}
    ffs: set[str] = set()
    for b in parsed["blocks"]:
        name = str(b["name"])
        nodes.append(name)
        if b["kind"] == "hard":
            outputs = arch.get(b.get("model", ""), set())
            ins[name] = [n for f, n in b.get("pins", {}).items() if f.split("[")[0] not in outputs]
            for f, n in b.get("pins", {}).items():
                if f.split("[")[0] in outputs:
                    driver[n] = name
        else:
            ins[name] = list(b["inputs"])
            driver[name] = name
            if b["kind"] == "latch":
                ffs.add(name)
    out: dict[str, list[str]] = collections.defaultdict(list)
    fanout: dict[str, int] = collections.defaultdict(int)
    for name, nets in ins.items():
        for net in nets:
            if net in clocks or net not in driver or net in ("gnd", "vcc", "unconn"):
                continue
            fanout[net] += 1
            d = driver[net]
            if d != name:
                out[d].append(name)
    return nodes, out, ffs, driver, fanout


def stages(nodes: list[str], out: dict[str, list[str]], ffs: set[str]) -> dict[str, int]:
    """stage(v) = max over in-edges (u, v) of stage(u) + [u is an FF]; back edges (found by a DFS from the
    primary inputs, then from the remaining nodes in BLIF order) are dropped. Iterative."""
    color: dict[str, int] = {}
    back: set[tuple[str, str]] = set()
    for root in nodes:
        if color.get(root):
            continue
        color[root] = 1
        stack = [(root, iter(out.get(root, [])))]
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = 2
                stack.pop()
                continue
            c = color.get(nxt, 0)
            if c == 1:
                back.add((node, nxt))
            elif c == 0:
                color[nxt] = 1
                stack.append((nxt, iter(out.get(nxt, []))))
    indeg: dict[str, int] = collections.defaultdict(int)
    for u in nodes:
        for v in out.get(u, []):
            if (u, v) not in back:
                indeg[v] += 1
    stage = {n: 0 for n in nodes}
    ready = [n for n in nodes if indeg[n] == 0]
    while ready:
        u = ready.pop()
        for v in out.get(u, []):
            if (u, v) in back:
                continue
            stage[v] = max(stage[v], stage[u] + (1 if u in ffs else 0))
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
    return stage


def lower_median(values: list[int]) -> int:
    s = sorted(values)
    return s[(len(s) - 1) // 2]


def build(design: str, base: Path, out_path: Path) -> dict:
    flat = nl.Flat(base / "final.flat_place")
    place = nl.Place(base / "initial.place")
    members = nl.read_json(nl.runs_dir(design, "words", "members.json"))
    nodes, out, ffs, driver, fanout = atom_graph(design, set(flat.atoms))
    stage = stages(nodes, out, ffs)
    id2name = {r["num"]: r["name"] for r in place.rows}
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    blocks = nl.parse_blif(blif, set(flat.atoms), nl.arch_output_ports(nl.ARCH))["blocks"]
    chains = bs.adder_chains(blocks, flat, id2name)
    chain_clbs = {c for ch in chains for c in ch["clbs"]}
    clb_types = {clb: bs.classify(t) for clb, t in flat.clb_types().items()}
    clb_atoms: dict[str, list[str]] = collections.defaultdict(list)
    for atom, row in flat.atoms.items():
        clb_atoms[row[4]].append(atom)
    base_xy = place.coords()
    control_drivers = {driver[n] for n, f in fanout.items() if f > BROADCAST and n in driver}
    cand: dict[str, dict] = {}
    for r in place.rows:
        num, name = r["num"], r["name"]
        if clb_types.get(num) != "logic" or name in chain_clbs:
            continue
        atoms = clb_atoms.get(num, [])
        st = [stage[a] for a in atoms if a in stage]
        bits = [members[a]["bit"] for a in atoms if a in members and members[a].get("word") and members[a]["bit"] >= 0]
        ctrl = any(a in control_drivers for a in atoms)
        has_bit = bool(bits) and len(bits) / max(len(atoms), 1) >= BIT_SHARE - 1e-9
        if st and (has_bit or ctrl):
            cand[name] = {"stage": lower_median(st), "bit": lower_median(bits) if has_bit else None, "control": ctrl}
    res = {"design": design, "moved": len(cand), "stages": 0, "bits": 0, "control": sum(1 for c in cand.values() if c["control"]),
           "logic_clbs": sum(1 for r in place.rows if clb_types.get(r["num"]) == "logic"), "chain_clbs": len(chain_clbs)}
    n_bit = sum(1 for c in cand.values() if c["bit"] is not None)
    if len(cand) < 8 or n_bit < 8 or max((c["stage"] for c in cand.values()), default=0) == 0:
        res["status"] = "no stagebit arm (fewer than 8 CLBs with stage and bit, or one stage)"
        return res
    pool = [base_xy[n] for n in cand]
    xs = sorted({p[0] for p in pool})
    ys = sorted({p[1] for p in pool})
    smax = max(c["stage"] for c in cand.values())
    bmax = max((c["bit"] for c in cand.values() if c["bit"] is not None), default=0)
    res["stages"], res["bits"] = smax, bmax
    nx, ny = len(xs), len(ys)

    def target(c: dict) -> tuple[int, int]:
        if c["control"]:
            return xs[nx // 2], ys[ny // 2]
        xi = (nx - 1) // 2 if smax == 0 else round(c["stage"] / smax * (nx - 1))
        yi = (ny - 1) // 2 if bmax == 0 else round(c["bit"] / bmax * (ny - 1))
        return xs[xi], ys[yi]

    order = sorted(cand, key=lambda n: (cand[n]["stage"], -1 if cand[n]["bit"] is None else cand[n]["bit"], n))
    slots = sorted(pool)
    sx = np.array([s[0] for s in slots])
    sy = np.array([s[1] for s in slots])
    free = np.ones(len(slots), dtype=bool)
    new_xy: dict[str, tuple[int, int, int, int]] = {}
    for n in order:
        tx, ty = target(cand[n])
        dist = np.abs(sx - tx) + np.abs(sy - ty)
        dist = np.where(free, dist, 1 << 30)
        i = int(np.argmin(dist))  # first minimum: slots are sorted by (x, y, sub, layer)
        free[i] = False
        new_xy[n] = slots[i]
    for r in place.rows:
        if r["name"] in new_xy:
            r["x"], r["y"], r["sub"], r["layer"] = (str(v) for v in new_xy[r["name"]])
    place.write(out_path)
    res["status"] = "ok"
    res["mean_displacement"] = statistics.fmean(abs(new_xy[n][0] - base_xy[n][0]) + abs(new_xy[n][1] - base_xy[n][1]) for n in cand)
    return res


if __name__ == "__main__":
    print(build(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
