"""nextpnr placement (`--write` JSON) to a VPR flat-place file (`--read_flat_place`).

Usage: python3 scripts/nextpnr_readback.py --json PLACED.json --ref REF.flat_place --out EXT.flat_place [--stats S.json]

Every atom of REF gets one line `<atom> <x> <y> 0 <sub_tile>`: x and y from the `NEXTPNR_BEL` attribute
(`X<x>/Y<y>/BLE<k>_LUT|BLE<k>_FF|IO<z>`), layer 0, sub tile 0 for logic (the flat-place format has no in-CLB
slot; VPR's reader parses sub_tile as an integer and the AP legaliser repacks, base/load_flat_place.cpp:140-213)
and the pad's own sub tile for pads. Pads must come back at their REF position (they are fixed anchors): a
mismatch is counted. An atom without a placed cell is written at its REF position and counted.
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
a = ap.parse_args()
cells = json.loads(Path(a.json).read_text())["modules"]["top"]["cells"]
rx = re.compile(r"^X(\d+)/Y(\d+)/(\w+)$")
out = ["# Flat placement written from a nextpnr placement (Norns scripts/nextpnr_readback.py)",
       "# <atom_name> <x> <y> <layer> <sub_tile>"]
st = {"atoms": 0, "from_nextpnr": 0, "fallback_ref": 0, "pad_moved": 0}
for line in Path(a.ref).read_text().splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    body, _, comment = line.partition("#")
    t = body.split()
    name, rx_, ry_, rsub = t[0], int(float(t[1])), int(float(t[2])), int(t[4])
    st["atoms"] += 1
    attr = cells.get(name, {}).get("attributes", {}).get("NEXTPNR_BEL")
    m = rx.match(attr) if attr else None
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
