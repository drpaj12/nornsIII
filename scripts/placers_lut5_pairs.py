"""LUT5-pair counts per design from the packed netlists (docs/plan/placers.md section 10.10 item 7; bias statement in 10.8).

Usage: python3 scripts/placers_lut5_pairs.py --work WORKDIR [--out data/placers/main_lut5_pairs.json]
Reads WORKDIR/<design>/vpr_ap.s1/<design>.net (the packed netlist of the shared vpr_ap seed-1 run; read only). In the k6_frac_N10
architecture a fracturable logic element (fle) in mode n1_lut6 holds one LUT6; in mode n2_lut5 it holds two ble5, each a LUT5 (mode
blut5) or an adder (mode arithmetic). The k6 uarch (placers/nextpnr_k6/k6.cc) gives every LUT one BLE slot. A pair of LUT5 in one fle
therefore costs the model 2 slots where VPR uses 1: the slot excess of the model over the packed netlist is the number of pairs.
Columns: clbs, fles (non-empty), lut6 fles, lut5 pairs, lut5 singles, arithmetic fles, excess = pairs, excess_pct_of_slots = pairs / (10 x clbs).
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

DESIGNS = ["ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B",
           "sha", "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2"]
ap = argparse.ArgumentParser()
ap.add_argument("--work", required=True)
ap.add_argument("--out")
a = ap.parse_args()
res = {}
for d in DESIGNS:
    p = Path(a.work) / d / "vpr_ap.s1" / f"{d}.net"
    c = {"clbs": 0, "fles": 0, "lut6": 0, "lut5_pairs": 0, "lut5_singles": 0, "arithmetic": 0}
    for _ev, el in ET.iterparse(p, events=("end",)):
        if el.tag != "block":
            continue
        inst = el.get("instance", "")
        if inst.startswith("fle[") and el.get("name") != "open":
            c["fles"] += 1
            mode = el.get("mode")
            if mode == "n1_lut6":
                c["lut6"] += 1
            elif mode == "n2_lut5":
                modes = [b.get("mode") for b in el.iter("block") if b.get("instance", "").startswith("ble5[") and b.get("name") != "open"]
                luts, ariths = modes.count("blut5"), modes.count("arithmetic")
                if ariths:
                    c["arithmetic"] += 1
                elif luts == 2:
                    c["lut5_pairs"] += 1
                elif luts == 1:
                    c["lut5_singles"] += 1
        elif inst.startswith("clb["):
            c["clbs"] += 1
            el.clear()
    c["excess_slots"] = c["lut5_pairs"]
    c["excess_pct_of_slots"] = round(100.0 * c["lut5_pairs"] / (10 * c["clbs"]), 2) if c["clbs"] else None
    res[d] = c
print(f"{'design':17s} {'clbs':>6s} {'fles':>7s} {'lut6':>6s} {'pairs':>6s} {'single':>7s} {'arith':>6s} {'excess % of slots':>18s}")
for d, c in res.items():
    print(f"{d:17s} {c['clbs']:6d} {c['fles']:7d} {c['lut6']:6d} {c['lut5_pairs']:6d} {c['lut5_singles']:7d} {c['arithmetic']:6d} {c['excess_pct_of_slots']:18}")
if a.out:
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
