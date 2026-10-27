"""nextpnr placement (`--write` JSON) to a VPR flat-place file (`--read_flat_place`).

Usage: python3 scripts/nextpnr_readback.py --json PLACED.json --ref REF.flat_place --out EXT.flat_place [--stats S.json]

Every atom of REF gets one line `<atom> <x> <y> 0 <sub_tile>`: x and y from the `NEXTPNR_BEL` attribute
(`X<x>/Y<y>/BLE<k>|IO<z>`), layer 0, sub tile 0 for logic (the flat-place format has no in-CLB
slot; VPR's reader parses sub_tile as an integer and the AP legaliser repacks, base/load_flat_place.cpp:140-213)
and the pad's own sub tile for pads. Pads must come back at their REF position (they are fixed anchors): a
mismatch is counted. Hard-block atoms (REF atom type not lut, ff, inpad or outpad: adder, mult, memory) are fixed under
rule H0 (docs/plan/placers.md section 10.3) and written VERBATIM from the REF line (x, y, layer, sub tile); an ANCHOR cell
that came back at another location is counted (anchor_moved). Any other atom without a placed cell is written at its REF
position and counted in fallback_ref (must be 0).
"""
import argparse
import json
import re
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--json", required=True)
ap.add_argument("--ref", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--stats")
ap.add_argument("--fixed", help="file of atom names written verbatim from REF (hard blocks, chain flip-flops, constants)")
a = ap.parse_args()
cells = json.loads(Path(a.json).read_text())["modules"]["top"]["cells"]
# pack() of the k6 uarch merges a LUT and its single-sink FF into one BLE cell named after the LUT, with the FF name in
# the attribute FF_ATOM: both atoms get the BLE's location (a VPR molecule must sit at one location).
for _name, _c in list(cells.items()):
    _ff = _c.get("attributes", {}).get("FF_ATOM")
    if _ff:
        cells[_ff] = _c
rx = re.compile(r"^X(\d+)/Y(\d+)/(\w+)$")
out = ["# Flat placement written from a nextpnr placement (Norns scripts/nextpnr_readback.py)",
       "# <atom_name> <x> <y> <layer> <sub_tile>"]
st = {"atoms": 0, "from_nextpnr": 0, "fallback_ref": 0, "pad_moved": 0, "hard_verbatim": 0, "const_verbatim": 0, "anchor_moved": 0}
BASIC = {"lut", "ff", "inpad", "outpad"}
FIXED = set(Path(a.fixed).read_text().split("\n")) if a.fixed else set()
for line in Path(a.ref).read_text().splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    body, _, comment = line.partition("#")
    t = body.split()
    name, rx_, ry_, rsub = t[0], int(float(t[1])), int(float(t[2])), int(t[4])
    typ = comment.split()[1] if len(comment.split()) > 1 else ""
    st["atoms"] += 1
    attr = cells.get(name, {}).get("attributes", {}).get("NEXTPNR_BEL")
    m = rx.match(attr) if attr else None
    if typ not in BASIC or name in FIXED:
        st["hard_verbatim"] += 1
        if m and (int(m.group(1)), int(m.group(2))) != (rx_, ry_):
            st["anchor_moved"] += 1
        out.append(f"{name} {rx_} {ry_} {t[3]} {rsub}")
        continue
    if not m and typ == "lut" and name in ("gnd", "vcc", "unconn"):
        # constant-driver LUT atoms are not emitted by the converter (no inputs, sinks left open): verbatim
        st["const_verbatim"] += 1
        out.append(f"{name} {rx_} {ry_} {t[3]} {rsub}")
        continue
    if not m:
        st["fallback_ref"] += 1
        out.append(f"{name} {rx_} {ry_} 0 {rsub}")
        continue
    x, y, slot = int(m.group(1)), int(m.group(2)), m.group(3)
    st["from_nextpnr"] += 1
    if slot.startswith("IO"):
        if (x, y, int(slot[2:])) != (rx_, ry_, rsub):
            st["pad_moved"] += 1
        out.append(f"{name} {x} {y} 0 {int(slot[2:])}")
    else:
        out.append(f"{name} {x} {y} 0 0")
Path(a.out).write_text("\n".join(out) + "\n")
if a.stats:
    Path(a.stats).write_text(json.dumps(st) + "\n")
print(json.dumps(st))
