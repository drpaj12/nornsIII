# Verified VTR interfaces (pinned build v8.0.0+18416, VPR 9.0.0-dev)

Checked on the pinned build `/home/jamiespa/odin3-ws/external/vtr-verilog-to-routing/build/vpr/vpr`
(2026-10-23) by reading `vpr --help` and the source; every flag below was exercised on
`ch_intrinsics` before the matrix runs. Read-only checkout; nothing here changes VTR.

## Seed injection

| Flag | Meaning (verified) |
|---|---|
| `--read_initial_place_file FILE` | Reads a CLB-level `.place` file (same format `print_place` writes: `Netlist_File:`/`Array size:` header, one `name x y subblk layer #num` line per packed block) and continues placement from it (`vpr/src/place/initial_placement.cpp:2054`). Header digest checks are warnings (`verify_file_digests=false`). All blocks must be listed at legal sites; read failures are fatal. |
| `--read_vpr_constraints FILE.xml` | Floorplanning constraints read before packing (`vpr/src/base/vpr_constraints_reader.cpp`); a `<partition>` holds `<add_atom name_pattern="..."/>` (exact atom name; `is_regex` defaults false) and one or more `<add_region x_low y_low x_high y_high/>`. Packing and placement must keep the partition inside its region (`vpr/src/base/vpr_constraints_serializer.h:341`). Regions that leave no legal site class (e.g. a memory region without a memory column) fail packing with "Failed to find pack clusters densely enough". |
| `--write_initial_place_file FILE` | Dumps the initial placement (the seed when `--read_initial_place_file` is given, else VPR's analytic start) before the anneal (`vpr/src/place/placer.cpp:119`). Used for the baseline study and to obtain the CLB name/coordinate slots. |
| `--write_flat_place FILE` | Dumps the final placement per atom: `<atom> <x> <y> <layer> <sub_tile> #<clb> <pb_type>` (`vpr/src/base/load_flat_place.cpp`). Used for retention/displacement and for P\*. |
| `--write_legalized_flat_place FILE` | Same format after legalization, before the anneal. |
| `--read_flat_place FILE` | Atom-level soft seed (`atom x y layer sub_tile`), reconstructs clustering. Available but not used by this experiment (the paper's soft interface is `--read_initial_place_file`); noted here because it is the finer-grained option. |

## Annealing schedule

* `--anneal_auto_init_t_scale S` scales the automatic schedule's estimated initial temperature
  by `S` (`vpr/src/base/read_options.cpp:791`). The first row of the placement cost table (VPR
  log, `Tnum Time T AvCost ...`) records the actual start temperature; the matrix records it as
  `init_t`.
* `--anneal_auto_init_t_estimator {cost_variance, equilibrium}` picks the estimate (default
  `equilibrium`).
* Manual schedule: specifying any of `--init_t`, `--exit_t`, `--alpha_t` switches to
  `USER_SCHED` (`read_options.cpp:4169`); the automatic schedule is the default and is what the
  matrix uses so the cooling shape is unchanged across scales.
* `--save_placement_per_temperature FILE` saves per-temperature placements (debugging); there is
  no mid-anneal stop/resume flag, so checkpointing cannot be emulated from the command line
  (see `patches/`).

## Metrics in the log

* `Total wirelength: N, average net length: ...` (routed; after routing completes).
* `Final critical path delay (least slack): X ns, Fmax: ...` (post-route timing analysis).
* `Best routing used a channel width factor of W` - the binary-search minimum channel width the
  default flow finds (the log shows each `Attempting to route at W channels` step).
* `Analytical Placement took X seconds`, `# Routing took X seconds`, `The entire flow of VPR took
  X seconds`.
* `Initial placement BB estimate of wirelength` / `BB estimate of min-dist (placement) wire
  length` (placement cost before/after the anneal).
* Cost curve: rows `Tnum  Time  T  AvCost  Av BB Cost ...` (one per annealing temperature).

## Definitions used by the matrix

* Soft arm: `--read_initial_place_file seeds/<seed>-<full|inter>.place`.
* Hard arm: `--read_vpr_constraints seeds/<seed>-hard.xml` (regions only; the intra-cluster
  arrangement is VPR's own, so there is one hard variant, not full/inter - agent default).
* Cold-start sweep: `--read_initial_place_file Pstar.place --anneal_auto_init_t_scale S`, S in
  {1, 2, 4, 8, 16}, against an unseeded run at the same S. Crossover = the largest S at which the
  cold start still routes shorter than the unseeded run; the temperature is S x the recorded
  automatic start temperature.
