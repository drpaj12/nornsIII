# First Norns sweep with kept timing (E10 `base`, 2026-10-29)

Purpose: Mímir is the dataset to mine and Wyrd shows why a line is hot (hub RQ W Q3.3; measure: speed = critical + near-critical paths). This is the first real sweep through the chain of nornsIII #21/#22 (keep the 1000-path report, the Odin III attribution, the blif and name map) and mimirIII #18 (`mimir import ... norns --runs`). It is new data with paths, not a re-run of the lost E10 raw files.

## Run

* nornsIII main at ef17745 (+ the one-line fix below). Config `base` of `scripts/e10_main.py` (vpr_sa, K6, norns architecture, default ABC), seeds 1, 2, 3, all 35 designs (20 MCNC from blif, 15 Norns from Verilog), smallest first by LUT count. `NORNS_KEEP_TIMING` unset (on). VPR held the Norns VPR lock (the runner passes it to `placers_main.py`).
* Tool commits: nornsIII ef17745, Odin III b01a8034, VPR 3c9a4d23 (dirty overlay, as in E10). The E10 `base` rows were made with nornsIII f9a45f32; Odin III and VPR are the same commits.
* Result: 105 runs (35 designs x 3 seeds), 105 rc 0 and legally routed, 0 failed, 0 retried. Total VPR flow time 1055 s.
* Import: new store `norns-keep.db` (Mímir schema 7), 105 run records, 0 refused; kept timing: 45 imported, 60 skipped (the 20 MCNC designs x 3 seeds, below).

## Per design

| design | LUTs | CLBs | CPD (ns, seed 1) | paths kept (seed 1) | matched share | matched share excl. ports | hdl edges | hdl ports | runs imported with paths | equal to e10 base |
|---|---|---|---|---|---|---|---|---|---|---|
| stereovision3 | 171 | 15 | 2.634 | 201 | 0.880 | 1.000 | 88 | 52 | 3 | yes |
| ch_intrinsics | 192 | 12 | 2.121 | 163 | 0.638 | 1.000 | 181 | 166 | 3 | yes |
| diffeq2 | 198 | 22 | 13.545 | 192 | 0.930 | 1.000 | 518 | 162 | 3 | yes |
| diffeq1 | 294 | 31 | 17.204 | 289 | 0.908 | 1.000 | 428 | 258 | 3 | yes |
| mkPktMerge | 329 | 19 | 4.098 | 1000 | 0.872 | 1.000 | 1269 | 314 | 3 | yes |
| tseng | 407 | 34 | 4.629 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| clma | 450 | 82 | 5.416 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| ex5p | 467 | 39 | 5.347 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| bigkey | 572 | 52 | 2.599 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| boundtop | 572 | 41 | 3.064 | 758 | 0.854 | 1.000 | 642 | 460 | 3 | yes |
| diffeq | 580 | 53 | 4.915 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| s298 | 661 | 58 | 6.322 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| dsip | 686 | 66 | 2.728 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| misex3 | 714 | 62 | 4.817 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| alu4 | 818 | 68 | 5.071 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| seq | 855 | 75 | 4.951 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| apex4 | 865 | 80 | 5.746 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| des | 901 | 77 | 4.684 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| apex2 | 992 | 92 | 5.891 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| raygentop | 1195 | 127 | 5.431 | 1000 | 0.923 | 1.000 | 1059 | 486 | 3 | yes |
| mkSMAdapter4B | 1200 | 118 | 6.197 | 1000 | 0.969 | 1.000 | 1076 | 392 | 3 | yes |
| sha | 1290 | 142 | 9.861 | 929 | 0.994 | 1.000 | 136 | 74 | 3 | yes |
| spla | 1445 | 131 | 6.391 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| elliptic | 1463 | 137 | 7.599 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| frisc | 1668 | 153 | 8.694 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| pdc | 1973 | 176 | 7.428 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| mkDelayWorker32B | 2057 | 63 | 6.823 | 1000 | 0.751 | 1.000 | 6770 | 1043 | 3 | yes |
| s38417 | 2189 | 179 | 4.968 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| s38584.1 | 2190 | 182 | 4.651 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| or1200 | 2473 | 237 | 8.746 | 1000 | 0.994 | 1.000 | 2400 | 739 | 3 | yes |
| ex1010 | 2777 | 314 | 9.802 | (kept in run dir, not imported) | n/a | n/a | n/a | n/a | 0 | yes |
| blob_merge | 6015 | 486 | 14.668 | 636 | 0.960 | 1.000 | 740 | 194 | 3 | yes |
| stereovision1 | 6462 | 758 | 5.726 | 1000 | 1.000 | 1.000 | 531 | 267 | 3 | yes |
| stereovision0 | 6887 | 702 | 3.828 | 1000 | 0.996 | 1.000 | 732 | 335 | 3 | yes |
| stereovision2 | 8426 | 1689 | 13.265 | 1000 | 1.000 | 1.000 | 770 | 320 | 3 | yes |

Paths kept is the number of paths in the stored 1000-path VPR report of seed 1 (1000 is the cap; a smaller value is all VPR reported). The three seeds of every Norns design are in the store (45 runs with paths, 33,504 paths, 228,244 path nodes, 52,020 hdl edges, 15,786 hdl ports).

* **MCNC (20 designs, 60 runs): report kept, no attribution.** They are read from blif, so Odin III has no name map: `keep-timing.json` says `attribution: false` ("no name map for this call site: report kept only"), the gzipped report sits in the run directory with 289 to 1000 paths, but nothing reaches the store. Expected for the runner; finding for Mímir: `import_kept` decides on the attribution file only (`skipped: no kept timing`), so the MCNC reports are not imported as a path list without hdl links. Not changed here (Mímir code, out of this lane).
* **Matched share.** Every Norns design has matched share excluding ports of 1.000 and `unmatched_atoms_total` 0. The share including ports is 0.638 to 1.000; no HDL design is below 0.5. The lowest, `ch_intrinsics` (0.638: 263 matched, 149 port, 0 unmatched of 412 nodes) and `mkDelayWorker32B` (0.751: 1814 matched, 601 port, 0 unmatched of 2415 nodes), are low only because port nodes (primary inputs and outputs) are counted apart from matched nodes; unmatched is 0. This holds because #22 gives `odin3-timing` the top module Odin III reports (`diffeq1`: `diffeq_paj_convert`).

## Cross-check against E10 `base` (`e10.db`, read only)

For all 35 designs x 3 seeds (105 runs), CPD (`vpr.cpd`), wirelength (`vpr.wirelength`), CLBs (`vpr.blocks`), channel width (`vpr.chan_width`) and LUTs (`struct.n_comb`) of this sweep equal the `norns-placers-e10-base` / `vpr_sa` rows of `e10.db` exactly: 525 of 525 values equal, 0 differences. The nornsIII commit differs (ef17745 against f9a45f32; the difference is the kept-timing code of #21/#22 and the 1000-path report request); Odin III (b01a8034) and VPR (3c9a4d23, dirty overlay) are the same commits. VPR is deterministic per seed, so equality is the expected outcome and shows that keeping timing did not change a result.

## Privacy

`mimir privacy-check --db norns-keep.db --db lane3-structures.db --db mimir-structures.db --db structures.db --blobs <blobs>`: 4 stores, 897 blobs scanned, 166 withheld scrubbed originals, 2 private strings, 0 hits. The kept-input store (`_keep-inputs`) alone: 0 hits. The raw run directories (VPR logs, `keep-flow/`) hold absolute paths by design; they stay in the run root, are not imported and are not committed.

## Wyrd

`wyrd.mimirview.MimirView` opens `norns-keep.db` read only (schema 7): `has_timing`, `has_paths` and `has_graph` are true, 45 timing runs listed, `paths_through(blob_merge seed 1)` returns 636 paths (the 636 stored), `hdl_graph` 740 edges and 194 ports, `path_detail` works. Headless model call with a private HOME; no window or `~/.config/wyrd` touched.

## Sizes

| item | bytes |
|---|---|
| run root | 2,090,995,113 (vpr 2,011,900,751; netlists 73,498,284) |
| keep store (`_keep-inputs`, blif + name map once per design) | 5,462,188 |
| `norns-keep.db` (new; includes the Norns result corpus) | 188,858,368 |
| shared blob dir growth | 16,872,224 to 23,882,260 (+7,010,036) |

`/mnt/c` had 69 GB free before and 68 GB after. No existing store was written (`e10.db`, `lane3-structures.db` and the others keep their 2026-10-27/28 modification times).

## Runner bug found and fixed in this PR

`placers_main.py` saved `NORNS_DATA/placers/<tag>_<design>.json` without creating the directory. A new sweep root has no `data/placers`, so every design crashed with `FileNotFoundError` after its first VPR run (the first launch of this sweep; the log is kept in the run root as `runs-aborted-nodatadir.log`, the run was repeated from scratch). `save()` now creates the parent; `tests/test_placers_data_dir.py` checks it.

Tests (local; nornsIII has no CI): `test_check_register`, `test_keep_timing`, `test_placers_data_dir`, `test_runrecord` OK; `test_check_terms` prints one pre-existing note; `test_r5` (5 errors) and `test_r7` (1 error) fail on main without this change too (they need the Loki analysis venv, which the VM restart removed); `test_r6` skipped (scipy missing).
