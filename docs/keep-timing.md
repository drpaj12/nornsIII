# Keep timing (purpose: hub W Q3.3, speed = critical + near-critical paths)

Every VPR run made through `scripts/nornlib.py` helpers keeps, beside its other outputs:

- `report_timing.setup.rpt.gz`: VPR's setup timing report, `--timing_report_npaths 1000` (was 200).
- `attribution.json.xz`: `odin3-timing` output (paths joined to Odin III provenance), when the netlist has a name map.
- `keep-timing.json`: what was kept (paths requested and kept, attribution yes/no and why not, blif and map sha256).
- The input blif and its `.blif.names` map, once per (design, blif sha256), as xz under `$NORNS_KEEP_STORE`
  (default `$NORNS_RUNS/_keep-inputs/<design>/<sha256>/`).

`NORNS_KEEP_TIMING=0` turns all of it off (and the paths count goes back to each script's own number).
`NORNS_ODIN_TREE` names the Odin III checkout whose `tools/flow/odin3-timing` runs (default `$ODIN3_ROOT`).

Call sites wired: r7, r7net, r8, placers_main (E10 and the placers sweeps), placers_gate. Not wired (older
rounds, their raw outputs are not mined): r5, r6, round4, matrix.run_one. The name map is `<blif>.names`
beside the blif; a call site whose blif has none keeps the report only (`attribution_note` says so).
r7 and r7net still analyse the first 200 paths (`lib.NPATHS`), so their numbers are unchanged.
