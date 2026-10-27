"""Print the Dispatch 3 gate table per family from data/placers/gate_<design>.json (docs/plan/placers.md section 9.4).

Usage: python3 scripts/placers_gate_table.py DESIGN [DESIGN ...]
Per design, per family, per arm and seed: rc, legal route, WL, W, CPD, VPR placement seconds, nextpnr placer seconds; then
the 2x stop-rule check (external WL against the same family's reread control, same seed).
"""
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "placers"
FAMILY = {"vpr_ap": "analytic", "vpr_ap_reread": "analytic", "ext_nextpnr_heap": "analytic",
          "vpr_sa": "annealing", "vpr_sa_reread": "annealing", "ext_nextpnr_sa": "annealing"}
CONTROL = {"ext_nextpnr_heap": "vpr_ap_reread", "ext_nextpnr_sa": "vpr_sa_reread"}
for design in sys.argv[1:]:
    d = json.loads((DATA / f"gate_{design}.json").read_text())
    ext = {(e["arm"], e["seed"]): e for e in d["nextpnr"]}
    runs = {(r["arm"], r["seed"]): r for r in d["runs"]}
    print(f"\n{design}  grid {d['reference']['grid']}  converter: {d['converter']['luts']} LUT, {d['converter']['dffs']} FF, {d['converter']['pads']} pads, {d['converter']['seconds']:.2f} s")
    for fam in ("analytic", "annealing"):
        print(f" family {fam}")
        print("  arm                 seed rc routed   WL     W   CPD_ns  vpr_place_s  nextpnr_s(heap+sa|init+sa)")
        for arm in [a for a in FAMILY if FAMILY[a] == fam]:
            for s in d["seeds"]:
                r = runs.get((arm, s))
                if not r:
                    print(f"  {arm:19s} {s:4d} missing")
                    continue
                e = ext.get((arm, s))
                npn = "" if not e else f"{(e['heap_s'] or e['init_s'] or 0) + (e['sa_s'] or 0):.2f}"
                vp = r["ap_s"] if r["ap_s"] is not None else r["sa_place_s"]
                print(f"  {arm:19s} {s:4d} {r['rc']:2d} {str(r['routed_ok']):6s} {r['wl'] or 0:6.0f} {r['W'] or 0:4.0f} {r['cpd_ns'] or 0:7.3f}  {vp if vp is not None else 0:10.2f}  {npn}")
    for (arm, s), r in sorted(runs.items()):
        c = CONTROL.get(arm)
        if c and r["wl"] and runs.get((c, s)) and runs[(c, s)]["wl"]:
            ratio = r["wl"] / runs[(c, s)]["wl"]
            print(f" stop-rule {arm} s{s}: WL / {c} = {ratio:.2f}" + ("  > 2x STOP" if ratio > 2 else ""))
