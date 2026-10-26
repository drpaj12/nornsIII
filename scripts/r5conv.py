"""Review fix (round-5 fix brief, item 5): rerun the netlist check with the local search run to convergence and merge the
new fields (ls_rounds, ls_converged_within_cap, cut_local_search_converged, slack_converged) into data/r5/keep.json.
Existing fields are checked unchanged (cut_local_search and slack still read after the protocol's 8 rounds).

  python scripts/r5conv.py
"""

from __future__ import annotations

import sys

import nornlib as nl
import r5lib as rl
import r5gen  # noqa: E402  (r5lib puts gen/ on sys.path)
import r5nl  # noqa: E402

KEEP_JSON = rl.DATA5 / "keep.json"


def main() -> int:
    keep = nl.read_json(KEEP_JSON)
    for d in sorted(k for k in keep if k.startswith("n5_")):
        spec = r5gen.build_spec(r5nl.hdl_name(d))
        spec["name"] = d
        ex = r5nl.check(spec)
        for f in ("cut", "cut_local_search", "slack", "swap_violations", "move_violations"):
            if ex[f] != keep[d][f]:
                print(f"CHANGED {d} {f}: {keep[d][f]} -> {ex[f]}", flush=True)
                return 1
        for f in ("ls_rounds", "ls_converged_within_cap", "cut_local_search_converged", "slack_converged"):
            keep[d][f] = ex[f]
        nl.write_json(KEEP_JSON, keep)
        print(d, ex["ls_rounds"], ex["ls_converged_within_cap"], round(ex["slack"], 4), round(ex["slack_converged"], 4), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
