"""CLB-resident H0 anchors and their BLE slots (docs/plan/placers.md section 10.10 item 6; bias statement in 10.3).

Usage: python3 scripts/placers_anchor_slots.py --work WORKDIR --lut5 data/placers/main_lut5_pairs.json [--out data/placers/main_anchor_slots.json]
Under rule H0 the adders and the carry-chain flip-flops are ANCHOR cells that take no BLE slot (k6.cc init_anchors; nextpnr_blif2json.py).
In VPR an adder sits in an fle (mode n2_lut5, ble5 mode arithmetic: up to two adders per fle) and a chain flip-flop shares the fle of its
adder. Per design this reports the CLB-resident anchor atoms (adders and chain flip-flops of the shared reference file) and the fle count
they take in the packed netlist (column `arithmetic` of main_lut5_pairs.json), and, for the external placements of seeds 4-6 in WORKDIR,
the number of CLB tiles where the nextpnr BLE cells plus the slots the adders of that tile would take exceed the tile's BLE slots
(n = 10: an adder takes half a slot; n = 20: slots count LUT5, an adder takes one). Multipliers and RAMs sit in their own columns, not in CLBs.
Reads WORKDIR/<design>/{ref.collapsed.flat_place, ext_nextpnr_{heap,sa.s?.t100}/placed.json}; read only.
"""
import argparse
import json
import math
import re
import statistics as st
from pathlib import Path

DESIGNS = ["ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B",
           "sha", "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2"]
ap = argparse.ArgumentParser()
ap.add_argument("--work", required=True)
ap.add_argument("--lut5", required=True)
ap.add_argument("--data", default=str(Path(__file__).resolve().parent.parent / "data" / "placers"))
ap.add_argument("--out")
a = ap.parse_args()
lut5 = json.loads(Path(a.lut5).read_text())
rx = re.compile(r"^X(\d+)/Y(\d+)/BLE(\d+)$")
res = {}
for d in DESIGNS:
    w = Path(a.work) / d
    meta = json.loads((Path(a.data) / f"main_{d}.json").read_text())
    n = meta.get("ble_per_tile") or 10  # designs run before section 10.8 carry no value: n = 10
    adders, ffs, per_tile = 0, 0, {}
    for ln in (w / "ref.collapsed.flat_place").read_text().splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        body, _, comment = ln.partition("#")
        t = body.split()
        typ = comment.split()[1] if len(comment.split()) > 1 else ""
        if typ == "adder":
            adders += 1
            k = (int(float(t[1])), int(float(t[2])))
            per_tile[k] = per_tile.get(k, 0) + 1
    chain_ffs = meta["converter"].get("chain_ffs")
    row = {"ble_per_tile": n, "adders": adders, "chain_ffs": chain_ffs, "adder_tiles": len(per_tile),
           "fles_taken_by_adders": lut5[d]["arithmetic"], "clbs": lut5[d]["clbs"], "overfull_tiles": {}, "excess_slots": {}}
    for tag in ("ext_nextpnr_heap.s{}", "ext_nextpnr_sa.s{}.t100"):
        counts, excess = [], []
        for s in (4, 5, 6):
            p = w / tag.format(s) / "placed.json"
            if not p.exists():
                continue
            cells = json.loads(p.read_text())["modules"]["top"]["cells"]
            ble = {}
            for c in cells.values():
                m = rx.match(c.get("attributes", {}).get("NEXTPNR_BEL", ""))
                if m:
                    k = (int(m.group(1)), int(m.group(2)))
                    ble[k] = ble.get(k, 0) + 1
            over, ex = 0, 0
            for k, na in per_tile.items():
                need = ble.get(k, 0) + (math.ceil(na / 2) if n == 10 else na)
                if need > n:
                    over += 1
                    ex += need - n
            counts.append(over)
            excess.append(ex)
        arm = tag.split(".")[0]
        if counts:
            row["overfull_tiles"][arm] = {"median": st.median(counts), "seeds": counts}
            row["excess_slots"][arm] = {"median": st.median(excess), "seeds": excess}
    res[d] = row
print(f"{'design':17s} {'n':>3s} {'adders':>7s} {'chainFF':>8s} {'adder tiles':>12s} {'fles of adders':>15s} {'clbs':>6s} {'overfull tiles heap/sa (seeds 4-6 med)':>40s} {'excess slots heap/sa':>22s}")
for d, r in res.items():
    o, e = r["overfull_tiles"], r["excess_slots"]
    print(f"{d:17s} {r['ble_per_tile']:3d} {r['adders']:7d} {r['chain_ffs']:8d} {r['adder_tiles']:12d} {r['fles_taken_by_adders']:15d} {r['clbs']:6d} "
          f"{o.get('ext_nextpnr_heap', {}).get('median', '-')!s:>20} / {o.get('ext_nextpnr_sa', {}).get('median', '-')!s:<15} "
          f"{e.get('ext_nextpnr_heap', {}).get('median', '-')!s:>10} / {e.get('ext_nextpnr_sa', {}).get('median', '-')!s}")
if a.out:
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
