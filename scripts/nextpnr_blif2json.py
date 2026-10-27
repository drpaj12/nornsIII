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
memory `.subckt` atoms are not supported: the converter refuses a design that has any (stats `unsupported`).
"""
import argparse
import json
import re
import sys
from pathlib import Path


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
    a = ap.parse_args()
    inputs, outputs, names, latches, subckts = parse(read_blif(a.blif))
    ref = read_ref(a.ref)
    stats = {"blif_names": len(names), "blif_latches": len(latches), "unsupported": {}}
    for s in subckts:
        stats["unsupported"][s[0]] = stats["unsupported"].get(s[0], 0) + 1
    ref_types = {}
    for _, _, _, typ in ref.values():
        ref_types[typ] = ref_types.get(typ, 0) + 1
    stats["ref_atom_types"] = ref_types
    if subckts or set(ref_types) - {"lut", "ff", "inpad", "outpad"}:
        stats["ok"] = False
        if a.stats:
            Path(a.stats).write_text(json.dumps(stats, indent=1) + "\n")
        sys.exit("unsupported atoms (carry/mult/memory): " + json.dumps(stats["unsupported"]) + " ref " + json.dumps(ref_types))
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
    for l in latches:
        d, q = l[0], l[1]
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
    missing = sorted(set(ref) - set(cells))
    stats.update(ok=True, cells=len(cells), luts=sum(c["type"] == "LUT6" for c in cells.values()),
                 dffs=sum(c["type"] == "DFF" for c in cells.values()), pads=sum(c["type"] == "IOB" for c in cells.values()),
                 constant_drivers_dropped=len(const_nets), swept_by_vpr_dropped=dropped, clock_nets=sorted(clocks),
                 ref_atoms=len(ref), ref_atoms_without_cell=missing[:20], n_ref_atoms_without_cell=len(missing))
    mod = {"attributes": {"top": 1}, "ports": {}, "cells": cells, "netnames": {}}
    Path(a.out).write_text(json.dumps({"creator": "norns nextpnr_blif2json", "modules": {"top": mod}}) + "\n")
    if a.stats:
        Path(a.stats).write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps({k: v for k, v in stats.items() if k != "ref_atoms_without_cell"}))


main()
