"""BLIF (mapped Odin/ABC netlist, K=6) to a nextpnr JSON netlist for the Norns k6 viaduct uarch.

Usage: python3 scripts/nextpnr_blif2json.py --blif B --ref REF.flat_place --out OUT.json [--stats STATS.json]

Cell types (placers/nextpnr_k6/k6.cc): LUT6 (parameter INIT, 64 chars, MSB first, bit i = f with
input j = bit j of i; a `.names` with k < 6 inputs repeats its table), DFF (a `.latch`), IOB (a pad).
Names are the VPR atom names: LUT and DFF carry their output net name, an input pad its net name, an
output pad `out:<net>`. REF is a VPR flat-place file of the same design (a `vpr_ap` seed-1 run): it
supplies the atom list (atoms VPR swept are dropped) and the fixed pad positions, written as the
`BEL` attribute `X<x>/Y<y>/IO<sub_tile>` so that HeAP has anchors. Clock nets (latch control) are not
connected: the DFF CLK pin stays open, like VPR's placer ignores clocks. Constant drivers (a `.names`
with no inputs) are not emitted; their sinks are left open (counted in the stats). Carry, multiplier and
memory `.subckt` atoms (models adder, multiply, single_port_ram, dual_port_ram) follow rule H0 (docs/plan/placers.md
section 10.3): each becomes a fixed ANCHOR cell at the exact (x, y) of its REF line, with one port per net that also touches a
movable (LUT or DFF) cell; clock pins and constant or unconnected nets are not connected. The tiles holding anchors are written
to --anchors (lines `x y count`, read by the uarch through `--vopt anchors=FILE`). Any other `.subckt` model is refused.
A subckt atom is named like VPR names it: the net of its first output pin in line order (vpr/src/base/read_blif.cpp:236-250).
"""
import argparse
import json
import re
import sys
from pathlib import Path

import flatplace_chains


def read_blif(path):
    lines, cur = [], ""
    for raw in Path(path).read_text().splitlines():
        s = raw.split("#", 1)[0].rstrip()
        if s.endswith("\\"):
            cur += s[:-1] + " "
            continue
        cur += s
        if cur.strip():
            lines.append(cur.strip())
        cur = ""
    return lines


def parse(lines):
    inputs, outputs, names, latches, subckts = [], [], [], [], []
    i = 0
    while i < len(lines):
        t = lines[i].split()
        if t[0] == ".inputs":
            inputs += t[1:]
        elif t[0] == ".outputs":
            outputs += t[1:]
        elif t[0] == ".names":
            cover = []
            j = i + 1
            while j < len(lines) and not lines[j].startswith("."):
                cover.append(lines[j].split())
                j += 1
            names.append((t[1:-1], t[-1], cover))
            i = j - 1
        elif t[0] == ".latch":
            latches.append(t[1:])
        elif t[0] == ".subckt":
            subckts.append(t[1:])
        i += 1
    return inputs, outputs, names, latches, subckts


HARD_MODELS = {"adder", "multiply", "single_port_ram", "dual_port_ram"}
OUT_PORTS = {"out", "out1", "out2", "sumout", "cout"}  # output ports of those models (arch XML <models>)
NO_NET = {"unconn", "gnd", "vcc"}


def split_pin(pin):
    base, _, idx = pin.partition("[")
    return base, idx


def parse_subckt(tokens):
    model = tokens[0]
    pins = []
    for t in tokens[1:]:
        p, _, n = t.partition("=")
        pins.append((p, n))
    first_out = next((n for p, n in pins if split_pin(p)[0] in OUT_PORTS), None)
    return model, first_out, pins


def truth_table(ins, cover):
    k = len(ins)
    on_set = True
    cubes = []
    for row in cover:
        if k == 0:
            cubes.append(("", row[0]))
        else:
            cubes.append((row[0], row[1]))
    if cubes and all(o == "0" for _, o in cubes):
        on_set = False
    f = []
    for idx in range(1 << k):
        hit = False
        for cube, _ in cubes:
            if all(c == "-" or int(c) == ((idx >> j) & 1) for j, c in enumerate(cube)):
                hit = True
                break
        f.append(int(hit == on_set) if cubes else 0)
    bits = [f[idx & ((1 << k) - 1)] for idx in range(64)]
    return "".join(str(b) for b in reversed(bits))


def read_ref(path):
    atoms = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        body, _, comment = line.partition("#")
        t = body.split()
        typ = comment.split()[1] if len(comment.split()) > 1 else ""
        atoms[t[0]] = (int(float(t[1])), int(float(t[2])), int(t[4]), typ)
    return atoms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stats")
    ap.add_argument("--anchors", help="write the ANCHOR tile list (x y count) here; default OUT.anchors.txt")
    a = ap.parse_args()
    inputs, outputs, names, latches, subckts = parse(read_blif(a.blif))
    ref = read_ref(a.ref)
    stats = {"blif_names": len(names), "blif_latches": len(latches), "unsupported": {}, "hard_models": {}}
    hard = []
    for sk in subckts:
        if sk[0] in HARD_MODELS:
            stats["hard_models"][sk[0]] = stats["hard_models"].get(sk[0], 0) + 1
            hard.append(parse_subckt(sk))
        else:
            stats["unsupported"][sk[0]] = stats["unsupported"].get(sk[0], 0) + 1
    ref_types = {}
    for _, _, _, typ in ref.values():
        ref_types[typ] = ref_types.get(typ, 0) + 1
    stats["ref_atom_types"] = ref_types
    if stats["unsupported"]:
        stats["ok"] = False
        if a.stats:
            Path(a.stats).write_text(json.dumps(stats, indent=1) + "\n")
        sys.exit("unsupported .subckt models: " + json.dumps(stats["unsupported"]))
    netid, nets = {}, 2

    def net(n):
        nonlocal nets
        if n not in netid:
            netid[n] = nets
            nets += 1
        return netid[n]

    const_nets = {out for ins, out, _ in names if not ins}
    clocks = {l[3] for l in latches if len(l) >= 4}
    cells, dropped = {}, {"lut": 0, "ff": 0, "pad": 0}
    for ins, out, cover in names:
        if not ins:
            continue
        if out not in ref:
            dropped["lut"] += 1
            continue
        if len(ins) > 6:
            sys.exit(f"LUT {out} has {len(ins)} inputs")
        conn = {f"I{j}": [net(n)] for j, n in enumerate(ins) if n not in const_nets}
        dirs = {f"I{j}": "input" for j in range(len(ins)) if ins[j] not in const_nets}
        conn["F"], dirs["F"] = [net(out)], "output"
        cells[out] = {"hide_name": 0, "type": "LUT6", "parameters": {"INIT": truth_table(ins, cover)},
                      "attributes": {}, "port_directions": dirs, "connections": conn}
    _head, chain_ffs = flatplace_chains.chains(a.blif)
    chain_ff_d = {}
    for l in latches:
        d, q = l[0], l[1]
        if q in chain_ffs and q in ref:
            chain_ff_d[q] = d  # flip-flop fed by an adder sumout: part of the carry-chain molecule, fixed with it (section 10.7)
            continue
        if q not in ref:
            dropped["ff"] += 1
            continue
        conn, dirs = {"Q": [net(q)]}, {"Q": "output"}
        if d not in const_nets:
            conn["D"], dirs["D"] = [net(d)], "input"
        cells[q] = {"hide_name": 0, "type": "DFF", "parameters": {}, "attributes": {},
                    "port_directions": dirs, "connections": conn}
    for n in inputs:
        if n not in ref:
            dropped["pad"] += 1
            continue
        x, y, z, _ = ref[n]
        cells[n] = {"hide_name": 0, "type": "IOB", "parameters": {}, "attributes": {"BEL": f"X{x}/Y{y}/IO{z}"},
                    "port_directions": {"O": "output"}, "connections": {"O": [net(n)]}}
    for n in outputs:
        pad = "out:" + n
        if pad not in ref:
            dropped["pad"] += 1
            continue
        x, y, z, _ = ref[pad]
        cells[pad] = {"hide_name": 0, "type": "IOB", "parameters": {}, "attributes": {"BEL": f"X{x}/Y{y}/IO{z}"},
                      "port_directions": {"I": "input"}, "connections": {"I": [net(n)]}}
    movable = set()
    for c in cells.values():
        if c["type"] in ("LUT6", "DFF"):
            for v in c["connections"].values():
                movable.update(v)
    tiles, n_anchor, hard_missing, hard_unemitted = {}, 0, 0, 0
    hard = hard + [("dff", q, [("D", d), ("Q", q)]) for q, d in chain_ff_d.items()]
    for model, first_out, pins in hard:
        if first_out is None or first_out not in ref:
            hard_missing += 1
            continue
        x, y, sub, _typ = ref[first_out]
        ports, conn, dirs = 0, {}, {}
        for p, n in pins:
            base = split_pin(p)[0]
            if base == "clk" or n in NO_NET or n in const_nets or n in clocks or n not in netid or netid[n] not in movable:
                continue
            nm = f"P{ports}"
            ports += 1
            conn[nm] = [netid[n]]
            dirs[nm] = "output" if (base in OUT_PORTS or (model == "dff" and base == "Q")) else "input"
        if not ports:
            hard_unemitted += 1
            continue
        i = tiles.get((x, y), 0)
        tiles[(x, y)] = i + 1
        cells[first_out] = {"hide_name": 0, "type": "ANCHOR", "parameters": {}, "attributes": {"BEL": f"X{x}/Y{y}/AN{i}"},
                            "port_directions": dirs, "connections": conn}
        n_anchor += 1
    apath = Path(a.anchors or (a.out + ".anchors.txt"))
    apath.write_text("".join(f"{x} {y} {n}\n" for (x, y), n in sorted(tiles.items())))
    hard_names = set()
    for model, first_out, pins in hard:
        if first_out in ref:
            hard_names.add(first_out)
    hard_names |= {n for n in ref if n in NO_NET}
    Path(a.out + ".fixed.txt").write_text("".join(n + "\n" for n in sorted(hard_names)))  # constant-driver LUT atoms: written verbatim by the readback
    missing = sorted(set(ref) - set(cells) - hard_names)
    stats.update(ok=True, cells=len(cells), luts=sum(c["type"] == "LUT6" for c in cells.values()),
                 dffs=sum(c["type"] == "DFF" for c in cells.values()), pads=sum(c["type"] == "IOB" for c in cells.values()),
                 constant_drivers_dropped=len(const_nets), swept_by_vpr_dropped=dropped, clock_nets=sorted(clocks),
                 anchors=n_anchor, anchor_tiles=len(tiles), hard_atoms=len(hard), chain_ffs=len(chain_ff_d), hard_atoms_not_in_ref=hard_missing,
                 hard_atoms_without_movable_net=hard_unemitted, ref_atoms=len(ref), ref_atoms_without_cell=missing[:20], n_ref_atoms_without_cell=len(missing))
    mod = {"attributes": {"top": 1}, "ports": {}, "cells": cells, "netnames": {}}
    Path(a.out).write_text(json.dumps({"creator": "norns nextpnr_blif2json", "modules": {"top": mod}}) + "\n")
    if a.stats:
        Path(a.stats).write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps({k: v for k, v in stats.items() if k != "ref_atoms_without_cell"}))


main()
