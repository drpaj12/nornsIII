# Norns placers protocol: other placers in the VTR flow without changing VTR (written 2026-10-27, before any comparison run)

This file is committed and pushed before any placer-comparison run. Its commit SHA is the "rule provenance" of this experiment.
A rule changes only by a NEW dated entry at the end of this file that keeps the old rule. Dispatch 1 (this entry) does the
feasibility work and this pre-registration; it runs no external placer. The only VPR runs before this commit are the seven
round-trip runs of Section 2 (VPR's own flat-place files, `ch_intrinsics`, seed 1, `data/placers/rt_ch_intrinsics_s1.json`); they
define no arm result and are not comparison data.

Purpose (hub docs/purpose.md): Norns **N Q2.2** (what is reliably true of placements) extended across placers, and the data-first
corpus of **N Q2.4**: a finding that holds only for the VPR placer may be a VPR artefact. Measures: routed wirelength (WL), minimum
channel width (W), critical-path delay (CPD) from the VPR router and timing analysis for every arm, and placement runtime.
Peter (2026-10-26): "If easy 3 and 4 and 5 as different placement techniques; the question is how will they link into the VTR flow
(without changing it hard such that others can do this)". There are no hypotheses with statuses in this experiment.

## 1. VTR entry points (commit 3c9a4d23b2, 9.0.0-dev; read only, under `vpr/src/` of the VTR checkout)

Stock VPR needs no change: an external placement enters through two routes.

**Atom level, `--read_flat_place FILE`.**
* Option: `base/read_options.cpp:2134-2137` (help text: reads VPR's or a reconstructed external placement in flat placement file
  format). The writer option `--write_flat_place FILE` is `base/read_options.cpp:2139-2142`; `--write_legalized_flat_place` is
  `base/read_options.cpp:2144` (the same format after legalization, before the anneal).
* Reader: `read_flat_placement()`, `base/load_flat_place.cpp:140-213`. Writer: `write_flat_placement()`,
  `base/load_flat_place.cpp:110-137`; per-atom line printer `print_flat_cluster()`, `base/load_flat_place.cpp:71-107`.
* Call sites that load the file when `--read_flat_place` is given: packing `base/vpr_api.cpp:725-728`, the AP flow
  `base/vpr_api.cpp:460-463`, placement `base/vpr_api.cpp:958-961`. The result is `g_vpr_ctx.atom().flat_placement_info()`
  (`base/flat_placement_types.h`: `blk_x_pos`, `blk_y_pos`, `blk_layer` are float, `blk_sub_tile` is int, undefined = -1).
* **Flat-place format, exactly.** One atom per line, whitespace-separated (space or tab): `<atom_name> <x> <y> <layer> <sub_tile>`,
  with optional trailing tokens ignored (`base/load_flat_place.cpp:207`). VPR's writer adds `#<clb_block_id> <atom_pb_type>`
  (verbosity >= 1, `load_flat_place.cpp:90-100`) and, at `--flat_place_verbosity 2`, the primitive path; its header is `#` comment lines
  (`load_flat_place.cpp:38-52`). Reader rules (`load_flat_place.cpp:150-207`: too few tokens line 171, atom lookup 179, duplicate 191): empty lines and lines whose first token starts with
  `#` are skipped; fewer than 5 tokens = warning and skipped; an atom name not in the atom netlist = warning and skipped
  (`AtomNetlist::find_block`, so a name must match exactly and must contain no whitespace); a second line for the same atom = warning and
  skipped (first wins); x, y and layer are parsed as floats ("to allow for reading in more global atom positions", lines 197-205), the sub tile as an int.
  `x`, `y` are the tile anchor coordinates of the grid (the same numbers the `.place` file carries); `layer` is 0 for the single-layer
  architecture; `sub_tile` is the IO sub tile slot (0 for logic).
* **Coverage requirement.** Packing, and therefore the default flow, aborts if any atom has an undefined position:
  `pack/verify_flat_placement.cpp:32-37` ("Atom block %s has an undefined position in the flat placement") gives
  `VPR_ERROR(VPR_ERROR_PACK, ... Aborting program)` at `pack/pack.cpp:281-295` (the error at line 291). A converter must therefore write every atom of the
  VPR atom netlist (LUTs, FFs, adders, pads, hard blocks), with the VPR atom names.
* **What VPR does with it.** Default flow (no stage flag) = analytical placement flow (`base/setup_vpr.cpp:285-297`: packing and
  placement SKIP, AP DO, routing DO). With a valid flat placement the global placer is skipped (log line "Flat Placement is provided in
  the AP flow, skipping the Global Placement", `analytical_place/analytical_placement_flow.cpp:194-202`), the positions become the
  partial placement (`convert_flat_to_partial_placement`; molecules with no atom in the file go to the device centre with a warning,
  `analytical_placement_flow.cpp:~130-165`, warning at line 140), and APPack/the full legalizer packs and places legally, followed by VPR's annealing
  refinement and routing. With `--pack --place --route --analysis` and `--read_flat_place`, the packer is guided by the positions
  (APPack, `pack/pack.cpp:332`) and `try_centroid_placement` takes the initial placement from the atom positions
  (`place/initial_placement.cpp:887-910`), then the anneal runs.
* **The `--legalize` stage is a stub in this commit.** `--legalize` (`base/read_options.cpp:1721`) sets `packerOpts->load_flat_placement`
  (`base/setup_vpr.cpp:336-339`) and calls `vpr_load_flat_placement` (`base/vpr_api.cpp:704-706, 843-871`), whose worker
  `load_flat_placement()` (`base/load_flat_place.cpp:217-225`) only logs "when implemented, this function" and returns false. It is
  not an entry point here.

**Cluster level, `--net_file` + `--place_file` with stage switches.**
* Options `--net_file` (`base/read_options.cpp:2071`), `--place_file` (`:2079`); the stage switches `--pack`, `--place`, `--route`,
  `--analysis` are on/off flags (`:1716-1743`). Stage logic (`base/setup_vpr.cpp:299-340`): giving `--route` alone sets packing and
  placement to LOAD, so VPR reads the `.net` and the `.place` and only routes (`--analysis` adds the timing and wirelength report).
  The loader is `read_place()` (`base/read_place.cpp:28-48`, called `base/vpr_api.cpp:1007`).
* **`.place` format, exactly** (writer `print_place()`, `base/read_place.cpp:357-400`; reader `read_place_header()` /
  `read_place_body()`, `base/read_place.cpp:82-192, 205-350`). Header: line `Netlist_File: <net file> Netlist_ID: <digest>`
  (4 tokens, digest mismatch is a warning, `verify_file_digests` false) and `Array size: <W> x <H> logic blocks` (7 tokens; a size
  mismatch is a warning/fatal as `verify_file_digests` decides). Body, one cluster per line:
  `<cluster name> <x> <y> <sub_tile> <layer> #<cluster id>` (5 data tokens, optional `#` comment; the 4-token form without layer is accepted for
  2D files). The block name may also be an atom name (the reader maps it to the cluster of that atom, `read_place.cpp:271-281`). All
  clusters must be listed at legal sites; read failures are fatal. This route needs a `.net` of the same packing, so an external
  placer working on atoms cannot use it unless the packing is VPR's own; it fits a placer that places VPR's clusters.
* Two further soft hooks used by earlier rounds: `--read_initial_place_file` (`.place` format, `place/initial_placement.cpp:2056`)
  and `--read_vpr_constraints` (docs/plan/vtr-interfaces.md).

The consequence for the design of converters: **atom-level `--read_flat_place` is the primary interface**; the cluster-level route is the
fallback for a placer that takes VPR's packed clusters.

## 2. VPR-only round trip (Dispatch 1, step 2)

Script `scripts/placers_rt.py`, metrics `data/placers/rt_ch_intrinsics_s1.json`; design `ch_intrinsics` (13 logic CLBs, grid 10x10),
seed 1, `$NORNS_VPR` (the Norns VPR; with no affinity file it equals stock VPR, rounds 3 and 4), arch
`k6_frac_N10_frac_chain_mem32K_40nm`, every run under `/tmp/claude-1000/norns-vpr.lock`, one at a time, `--route_file /dev/null`,
minimum-channel-width search on. Stage flags need `--analysis` to print the final WL and CPD (without it the log has W only).

| run (flags beyond `--seed 1`) | logic CLBs | WL | W | CPD ns | pack s | placement s | route s | flow s |
|---|---|---|---|---|---|---|---|---|
| `sa_write`: `--pack --place --route --analysis --write_flat_place` | 12 | 1484 | 38 | 2.12094 | 0.05 | 0.07 (SA) | 0.21 | 0.49 |
| `ap_default_write`: no stage flag, `--write_flat_place` | 13 | 1461 | 38 | 2.09041 | 0.05 | 0.22 (AP) | 0.22 | 0.50 |
| `ap_flag_write`: `--analytical_place --route --analysis` | 13 | 1461 | 38 | 2.09041 | 0.05 | 0.22 (AP) | 0.22 | 0.49 |
| `ap_read_in_ap`: default flow `--read_flat_place` of the `ap_default` file | 13 | 1359 | 40 | 1.96491 | 0.05 | 0.15 (AP) | 0.23 | 0.43 |
| `sa_read_in_sa`: `--pack --place --route --analysis --read_flat_place` of the `sa` file | 12 | 1483 | 38 | 1.99267 | 0.05 | 0.02 (SA) | 0.22 | 0.44 |
| `sa_read_in_ap`: default flow, `sa` file | 12 | 1483 | 38 | 1.99267 | 0.04 | 0.14 (AP) | 0.21 | 0.40 |
| `ap_read_in_sa`: `--pack --place --route --analysis`, `ap_default` file | 13 | 1359 | 40 | 1.96491 | 0.06 | 0.02 (SA) | 0.23 | 0.47 |

Findings (one design, one seed; not general):
1. The default flow and `--analytical_place --route --analysis` are the same flow (identical WL, CPD, W, CLBs): in this VTR **VPR's
   "default placer" is analytical placement**. The classical packer plus simulated-annealing flow is `--pack --place --route --analysis`.
   "VPR default" and "VPR `--analytical_place`" of the brief therefore name the same arm; the second VPR arm is the SA flow.
2. Reading a flat placement into VPR works end to end in both interfaces and is **not the identity**: reading VPR's own final file back
   gives a different (here better, WL 1461 to 1359) result, because VPR legalizes the positions again and refines again. The
   reading-back control arm below makes the external arms comparable (same number of refinement passes).
3. In both read modes the result depended only on the file (`sa_read_in_sa` = `sa_read_in_ap`; `ap_read_in_ap` = `ap_read_in_sa`);
   the file also fixes the clustering (12 versus 13 CLBs). Whether this holds on larger designs is checked in the comparison (it is
   why mode A below is primary and mode B is run only if A fails).
4. The converter path works: names, coordinates and the reader accepted every line (0 reader warnings).

## 3. Feasibility notes for the external placers (read only: nothing built, installed or run)

Sources read: `external/nextpnr` (new shallow clone, commit 9691ce8c, 2026-10-26), `external/DREAMPlaceFPGA` (0044943, 2025-04-30),
`external/OpenPARF` (793cac2, 2025-04-25). This VM: Python 3.12.3, CMake 3.28.3, g++ 13.3, 12 cores, 23 GB RAM, no GPU
(`nvidia-smi` absent), no PyTorch, no conda/mamba, no Docker; installed dev packages include Boost headers, `libboost-filesystem-dev`,
`libboost-system-dev`, `libboost-python-dev`, bison, flex, `python3-dev`; **not installed:** Eigen3, Boost program_options, iostreams
and thread dev packages (checked with `dpkg -l`).

The target grid, from the architecture file (`k6_frac_N10_frac_chain_mem32K_40nm.xml`): auto-sized square layout (`<auto_layout aspect_ratio="1.0">`,
lines 227-239); `io` on the perimeter, capacity 8 per tile (line 162); `clb` fill with 10 fracturable logic elements (40 input pins, 20
outputs, carry in and out; lines 183-187); `mult_36` columns (height 4, start x 6, repeat 8); `memory` columns (start x 2, repeat 8).

| | nextpnr | DREAMPlaceFPGA | OpenPARF |
|---|---|---|---|
| Model the k6_frac_N10 grid? | Yes in principle: the generic/viaduct back end builds an arbitrary grid of bels from code (`generic/viaduct/`, `docs/viaduct.md`: `addBel`, `addWire`, `addPip` per tile). A Viaduct "uarch" in C++ with a CLB tile of 10 LUT+FF bel pairs, IO tiles with 8 pad bels, and mult/memory column bels would match; the VPR grid for a design is read from a VPR run (`.place` header). Placement only is needed, so routing wires can be a minimal dummy fabric. | No natively. The legalizer and database hard-code the Xilinx UltraScale slice: `SLICE_CAPACITY = 16` (`ops/lut_ff_legalization/src/lut_ff_legalization.cpp:22`), 16 LUT/FF per slice (`PlaceDB.py:376`), a fixed IO site map (`PlaceDB.py:455-472`), cell kinds LUT1-6, FDRE, CARRY8, DSP48E2, RAMB36E2 (`ops/place_io/src/Enums.h`). Only global placement (`legalize_flag` 0, writes `<design>.gp.pl`, `Placer.py:60-67`) can be used, on a Bookshelf device whose `.scl` SITE is one UltraScale SLICE per N10 CLB; the result is a continuous position scaled to the VPR grid. | Partly. The Flexshelf layout is an XML (`arch/tile_blocks/tile`, with `width`, `height`, `resource num=`; `database.cpp:962-1010`) so tile resources are data, but the packer-legalizer and the database are SLICEL/SLICEM-specific (`ops/direct_lg/src/dl_problem.h:65`, `database/placedb.cpp:765-772`). Global placement only, as for DREAMPlaceFPGA. |
| CPU only? | Yes, no GPU code. HeAP's solver can use OpenMP (`USE_OPENMP`, `CMakeLists.txt:33`). | CPU multi-threaded when no GPU (README: "If installed on a machine without GPU, multi-threaded CPU support is available"; `gpu` JSON flag 0, `num_threads`). | CUDA optional: CMake enables it only `if(CUDA_FOUND)` (`CMakeLists.txt:104`); `gpu` default 0 (`openparf/params.json`, BENCHMARKS.md). CPU runs are possible; their speed is unknown. |
| Build dependencies and size | CMake >= 3.25, C++17, Boost (filesystem, thread, program_options, iostreams), Eigen3, Python dev unless `BUILD_PYTHON=OFF` (the generic viaduct arch does not need the Python API). Source 22 MB; a single-arch build is minutes. Missing here: Eigen3 and 3 Boost libs (apt, needs sudo, or a local Eigen/Boost under /tmp). Submodules not needed for a no-GUI, no-Python build (to be confirmed at build). | Python 2.7 or 3.5-3.7 with PyTorch **1.6-1.8 ("Version 2.0 or higher is not compatible")**, GCC, Boost, Flex, Bison, cmdline, Limbo (167 MB, present) and submodules `cub`, `munkres-cpp`, `pybind11` that are empty in the clone (need `git submodule update`), `pycapnp`, `igraph`. The shipped `thirdparty/elfPlace_LG_DP` is a prebuilt binary (not to be run). **No supported Python or PyTorch exists on this VM; a conda/pip env with Python 3.7 and torch 1.8 (about 1-2 GB) must be created first.** | Python 3.7, PyTorch 1.7.1, CMake, Boost, Bison, `hummingbird-ml`, `pyyaml`, `networkx`, `tqdm`, git submodules (blend2d, lemon, pugixml, pybind11, yaml-cpp, rapidcsv, googletest); optional Gurobi; Docker image provided. Same missing-environment problem as DREAMPlaceFPGA (no conda/mamba here). |
| Input format | Yosys JSON netlist only (`--json`, `frontend/json_frontend.cc`; no BLIF reader). Chip definition from the uarch code (or a Python script for the generic arch). Packing is minimal (LUT4/DFF/IO in `generic/pack.cc`); cells are placed on bels by type. Needs fixed IO or constrained cells as HeAP anchors (`generic/arch.cc:610-625`: otherwise it silently falls back to SA). | ISPD 2016 Bookshelf: `.aux .nodes .nets .pl .scl .lib .wts`. IOs must be fixed in `.pl`. Timing mode needs the UltraScale timing model in `timing/` (not applicable). | Flexshelf: XML layout, **structural Verilog netlist**, XML placement file for fixed cells (`readFlexshelfDesign`, `database.cpp:1406-1430`); or ISPD Bookshelf. |
| Converter needed | (a) BLIF/atom netlist to Yosys JSON (LUT cell type with k=6 and a truth-table parameter, DFF, carry/adder cells, IO pads, mult/mem cells; names = VPR atom names); (b) the viaduct uarch for the VPR grid of each design; (c) result: the JSON written with `--write` carries `NEXTPNR_BEL` per cell (`common/kernel/basectx.cc:190`), parsed to `x y z`, then to the flat-place line (layer 0, sub tile = z for IO). Pads fixed by a deterministic spread (see fairness). | (a) atoms to Bookshelf (LUT -> LUTn by input count, FF -> FDRE, adders -> CARRY8 or logic, mult/mem -> DSP/RAM, pads -> fixed IO with a deterministic spread); (b) a `.scl` with a fabricated site map; (c) `.gp.pl` continuous x,y scaled to the VPR grid, written as `atom x y 0 0`. Float coordinates are accepted by the reader. | As DREAMPlaceFPGA but the layout is an XML tile description; the netlist converter writes structural Verilog; the result `.pl` is converted back. |
| Fairness concerns | HeAP is wirelength-driven; the generic arch has **no cell timing** (`docs/generic.md`: "At present there is no support for cell timing"), so it gets no criticality while VPR's AP and SA are timing-driven. Same algorithm family as VPR's analytical placer (HeAP is Gort and Anderson 2012, VPR AP is a B2B-quadratic solver with partial legalization). LUT6 fracturing, carry chains (need relative constraints) and N10 input-sharing legality are not modelled in placement: VPR's APPack does the real packing afterwards. The `static` electrostatic placer exists only for himbaechel (`himbaechel/arch.cc:412`), not generic. | The Xilinx slice (16 LUT, 2 half slices, control-set rules) differs from the N10 CLB; density and legalization targets are wrong for k6_frac, so global positions are a "wirelength-and-density-aware spread" on a different fabric; heterogeneous DSP/RAM columns are not the VTR columns. Timing-driven mode is unusable (UltraScale delays). Wirelength-only, GPU-free speed not representative of the published GPU numbers. Result enters VPR as a soft position, then VPR repacks and refines, so the measured effect is "DREAMPlaceFPGA global placement as VPR's start". | Same as DREAMPlaceFPGA, plus multi-die (SLR) machinery that is off for one die; the electrostatic density model is the same family as DREAMPlaceFPGA (both descend from elfPlace), so the two are not independent evidence of "different placement techniques". |
| Effort (agent estimate, not measured) | Converter, uarch and glue: 3 to 5 agent-days after the packages are available; low environment risk. | 5 to 8 agent-days; high environment risk (Python and PyTorch versions, empty submodules); fairness caveats largest. | 6 to 10 agent-days; same environment risk plus an unfamiliar Flexshelf format that is not documented in the repo (only benchmark downloads). |
| Licence | ISC (`COPYING`; GitHub API SPDX ISC). | BSD-3-Clause (`LICENSE`; GitHub API). The sample ISPD benchmark files carry a Xilinx copyright notice: not to be vendored. | BSD-3-Clause (`LICENSE`; GitHub API). Sample benchmark README carries the same Xilinx notice. |

Third-party code is not vendored into any Norns repository. Converters are our own scripts, written from the file-format descriptions; each
README entry and paper passage that uses a placer credits it (Section 7).

**Recommendation (ranked, build order if Peter approves):** 1. nextpnr HeAP (cheapest, no PyTorch, no GPU question, the only one with a
documented way to describe a custom fabric by code, ISC licence); 2. OpenPARF global placement (its XML layout can hold an N10 tile as data, so
the fabric mismatch is smaller than for DREAMPlaceFPGA; needs a Python 3.7 + PyTorch 1.7.1 environment); 3. DREAMPlaceFPGA global placement
(hard-coded UltraScale slice, the largest fabric mismatch, same environment problem). Items 2 and 3 are not independent techniques (both
electrostatic, elfPlace lineage), so one of them is enough for a "different technique" claim; the second adds a replication.

## 4. Arms, designs, seeds, measures

**Arms** (all use the same BLIF per design, `runs/<d>/netlist/<d>.blif`, the same architecture, the same VPR binary `$NORNS_VPR`):
* `vpr_ap`: default flow (no stage flag; analytical placement, APPack, anneal refinement, routing with the W search); flags
  `--seed s --timing_report_npaths 200 --write_flat_place F` plus `--route_file /dev/null`.
* `vpr_sa`: `--pack --place --route --analysis`, same other flags. The classical greedy packer and annealing placer.
* `vpr_ap_reread` (control): `vpr_ap` seed s, then the default flow with `--read_flat_place` of that run's own `final.flat_place`
  (Section 2, finding 2: the reread is itself a second refinement). This is the baseline an external placer must be compared with, since its
  positions enter VPR the same way.
* `ext_<placer>` for each external placer that is built after approval: the placer's global placement (seed s as the placer seed where it has
  one), converted to a flat-place file with every VPR atom, then the default flow with `--read_flat_place` (mode A, primary). Mode B
  (`--pack --place --route --analysis --read_flat_place`) is run on a design only if mode A errors on it.
Pads are placed by the external placer's own IO handling where it has one; where a placer needs fixed IO, the converter assigns pads by a
deterministic rule written down before use (perimeter slots in the order of a fixed hash of the pad name), and the same rule is a recorded
caveat. Hard blocks (mult_36, memory) are given to the placer if it has a matching site type, otherwise written at the VPR column positions
nearest the centroid of their neighbours; designs where this cannot be done are listed as ineligible, not silently dropped.

**Designs**, smallest first by logic CLBs (`data/benchmark-sizes.json`; this is the CLB order, which differs from `nornlib.DESIGN_ORDER`):

| design | logic CLBs | IO | memory | mult_36 | grid |
|---|---|---|---|---|---|
| ch_intrinsics | 13 | 229 | 1 | 0 | 10x10 |
| stereovision3 | 15 | 41 | 0 | 0 | 7x7 |
| mkPktMerge | 21 | 467 | 15 | 0 | 28x28 |
| diffeq2 | 22 | 162 | 0 | 5 | 16x16 |
| diffeq1 | 37 | 258 | 0 | 5 | 16x16 |
| boundtop | 54 | 389 | 1 | 0 | 15x15 |
| mkDelayWorker32B | 74 | 1059 | 43 | 0 | 50x50 |
| mkSMAdapter4B | 125 | 398 | 5 | 0 | 20x20 |
| sha | 142 | 74 | 0 | 0 | 17x17 |
| raygentop | 143 | 541 | 1 | 6 | 19x19 |
| or1200 | 252 | 779 | 2 | 1 | 27x27 |
| blob_merge | 494 | 136 | 0 | 0 | 28x28 |
| stereovision0 | 707 | 366 | 0 | 0 | 33x33 |
| stereovision1 | 788 | 260 | 0 | 43 | 40x40 |
| stereovision2 | 1956 | 331 | 0 | 192 | 82x82 |

(The 15 main designs of rounds 1 to 7; the calibration constructions of round 5 are not used.) The sweep runs the designs in this order,
every arm of a design before the next design, and the largest last. A first gate per external placer: `ch_intrinsics`, `stereovision3`
and `mkPktMerge` must run end to end (rc 0, the reader accepts every atom, WL and CPD parsed) before any further design is attempted.

**Seeds.** VPR `--seed` 1 to 6 for every arm and design. **Seeds 1-3 are the choice seeds:** any arm, converter option or placer parameter
that is selected or tuned is selected on seeds 1-3 only (round-7 lesson, merged as nornsIII 8c52c7f8). **Seeds 4-6 are held out:** they are run
only after the choice is committed (a dated entry at the end of this file naming the chosen arm and parameters and its SHA) and every
reported comparison is on seeds 4-6. Seeds 1-3 results are reported as the selection data, labelled as such, never as the result.

**Measures** per run (parsed from the VPR log by `nornlib.Metrics` and `scripts/placers_rt.py`): routed total wirelength `WL`; minimum
channel width `W` (`Best routing used a channel width factor of`); `CPD` (`Final critical path delay (least slack)`); logic CLB count;
placement runtime (`Analytical Placement took` or `SA Placement took` for VPR, plus the external placer's wall time and the converter wall
time, reported separately because they are different machines of work); packing time; routing time; `max_rss`. The summary quantity is the
objective of round 7, `WL x CPD` (lower is better), with `W` reported beside it. Each design reports the median over seeds 4-6 of each
arm; the cross-design summary is the geometric mean of the per-design ratio (arm median / `vpr_ap_reread` median) and (arm median /
`vpr_ap` median), with a bootstrap over designs (10000 resamples, seed 20261026, percentile 95% interval). No hypothesis tests with
statuses. Runs, per VPR arm and external arm: 15 designs x 6 seeds = 90; VPR time from round-7 speeds is about 245 s per seed and arm for
the 15 designs, so about 25 min per arm; the external placer time is measured at the first gate and stated before the sweep.

**Locks and hygiene.** Every VPR run takes `flock -x /tmp/claude-1000/norns-vpr.lock`, one VPR at a time (Peter 2026-10-26). Builds of
third-party tools and long external-placer runs take the heavy lock `/tmp/claude-1000/odin3-heavy.lock`. Third-party builds go to
`/tmp/claude-1000/<tag>-build` or a `work/` directory, never into this repository, never into `external/` or `$VTR_ROOT`. Raw VPR working
directories go to a fresh `mktemp -d /tmp/claude-1000/npl-XXXX`; the repository receives only metrics JSON and scripts. No deletes of any
kind in any script. No absolute home-directory paths in committed files.

## 5. Stop rules

Stop and report (do not force) if any holds:
1. A step needs a change to VTR source or to `$VTR_ROOT`, or to a third-party clone.
2. A placer needs more than 10 agent-days in total, or its environment (Python/PyTorch versions) cannot be created without root and without
   changing the system Python; the estimate and the reason are then reported.
3. The first gate fails: an external arm does not reach rc 0 with a full atom list on `ch_intrinsics`, `stereovision3` and `mkPktMerge`.
4. A design has fewer than 5 of 6 successful seeds on an arm: it is dropped from that arm's summary and listed with the error; a run that
   fails (rc != 0 or a 7200 s timeout) is retried at most once.
5. An external placer's measured wall time on `stereovision2` (the largest design) would take the arm past 8 h, or peak memory passes 60% of
   the 23 GB VM: the largest designs are cut first and the cut is committed and stated.
6. Disk: stop before a new design if `/tmp/claude-1000` has less than 30 GB free; scratch is never deleted.
7. The lock cannot be taken for more than 6 h.
8. Any file would have to be deleted to continue: stop and ask.

## 6. What needs Peter's approval before any external placer is built or run

(Dispatch 1 builds and runs none.) Per tool: (a) nextpnr: installing `libeigen3-dev` and the Boost program_options, iostreams and thread dev
packages with `sudo apt` (or approving a header-only Eigen and a local Boost under `/tmp/claude-1000`), a `git submodule` fetch if the build needs
it, and a build into `/tmp/claude-1000/nextpnr-build` under the heavy lock; plus approval to write our own viaduct uarch (C++) in a Norns
`placers/` directory (our code, ISC-compatible, not vendored third-party code). (b) OpenPARF or DREAMPlaceFPGA: creating a Python 3.7 and PyTorch 1.7.1/1.8
environment (needs conda/mamba or a pyenv-style tool, none present), `git clone --recursive` submodule fetches, and a build into
`/tmp/claude-1000/<tag>-build`; plus a decision on whether the fabric mismatch (Xilinx slice) is acceptable for the claim.

## 7. Citations (verified 2026-10-27; entries in `docs/paper/joined.bib`, each with a `% Checked:` line)

VTR is cited as `rose2012vtr` (FPGA 2012, DOI present) AND `elgammal2025vtr9` (VTR 9, TRETS 2025), with commit 3c9a4d23b2. New keys:
`shah2019nextpnr`, `gort2012heap`, `nextpnr` (software, ISC), `rajarathnam2022dreamplacefpga`, `rajarathnam2023dreamplacefpga_pl`,
`li2019elfplace`, `dreamplacefpga` (software, BSD-3), `mai2023openparf`, `mai2022multielectrostatic`, `openparf` (software, BSD-3).
`rajarathnam2024better` (the VPR analytical-plus-annealing paper, relevant to the AP arm) already exists in `joined.bib`.
Nothing is credited from memory: authors, titles, venues, pages and DOIs were taken from the Crossref record, the arXiv record and the project
files named in each `% Checked:` line.

## 8. nextpnr build recipe (Dispatch 2, 2026-10-27; Peter approved nextpnr plus local Eigen and Boost; own uarch, OpenPARF and DREAMPlaceFPGA still not approved)

Scratch lives under `/tmp/claude-1000` (nothing deleted). `$WS` is the odin3-ws checkout; `$D=/tmp/claude-1000/nextpnr-deps`. Every build ran
under `flock -x /tmp/claude-1000/odin3-heavy.lock`, `-j4`. The VM had Python 3.12.3, CMake 3.28.3, Ninja, g++ 13.3, zlib and bzip2 dev headers.

**Licences.** nextpnr: ISC (`COPYING`). Boost: Boost Software License 1.0 (`LICENSE_1_0.txt`). Eigen: MPL-2.0 (`COPYING.MPL2`; header-only, used
unmodified). None is vendored into a Norns repository; the binaries live only under `/tmp`.

**Dependencies (official release tarballs, sha256 computed here after download).**

| Package | Version | URL | sha256 |
|---|---|---|---|
| Boost | 1.86.0 | `https://archives.boost.io/release/1.86.0/source/boost_1_86_0.tar.bz2` | `1bed88e40401b2cb7a1f76d4bab499e352fa4d0c5f31c0dbae64e24d34d7513b` |
| Eigen | 3.4.0 | `https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.bz2` | `b4c198460eba6f28d34894e3a5710998818515104d6e74e5cc331ce31e46e626` |

**Recipe (exact commands).**

```
D=/tmp/claude-1000/nextpnr-deps
mkdir -p $D/dl $D/src-boost $D/src-eigen $D/prefix
cd $D/dl && curl -fsSLO https://archives.boost.io/release/1.86.0/source/boost_1_86_0.tar.bz2
cd $D/dl && curl -fsSLO https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.bz2
sha256sum $D/dl/*            # compare with the table
tar -xjf $D/dl/boost_1_86_0.tar.bz2 -C $D/src-boost
tar -xjf $D/dl/eigen-3.4.0.tar.bz2  -C $D/src-eigen
# Boost: its own documented bootstrap and b2 only
cd $D/src-boost/boost_1_86_0
./bootstrap.sh --prefix=$D/prefix --with-libraries=program_options,iostreams,thread,filesystem,system
./b2 -j4 install
# Eigen: header-only, CMake install
cmake -S $D/src-eigen/eigen-3.4.0 -B $D/build-eigen -DCMAKE_INSTALL_PREFIX=$D/prefix -DCMAKE_BUILD_TYPE=Release
cmake --install $D/build-eigen
# nextpnr (external/nextpnr at 9691ce8c, read only, out-of-tree build)
cmake -S $WS/external/nextpnr -B /tmp/claude-1000/nextpnr-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DARCH=generic \
  -DBUILD_GUI=OFF -DBUILD_PYTHON=OFF -DBUILD_RUST=OFF -DBUILD_TESTS=OFF \
  -DBOOST_ROOT=$D/prefix -DBoost_NO_SYSTEM_PATHS=ON -DEigen3_DIR=$D/prefix/share/eigen3/cmake
cmake --build /tmp/claude-1000/nextpnr-build -j4
export LD_LIBRARY_PATH=$D/prefix/lib      # Boost shared libraries
```

No git submodule was fetched: with GUI, Python, Rust and tests off, CMake used only the tracked `3rdparty/json11` and `3rdparty/oourafft`.
Nothing else was downloaded. The `generic` arch includes the viaduct uarchs `example` and `fabulous`.

**Cost.** Dependency step wall time 22 min 18 s, but this includes waiting for the heavy lock behind another lane, so it is an upper bound (peak
RSS of one process 0.28 GB). nextpnr: configure plus 56 build steps took 50 s of lock-held wall time (peak RSS of one process 0.73 GB, `time -v`;
well under 60% of the 23 GB VM). Disk: nextpnr build 256 MB, dependency prefix 193 MB, whole `nextpnr-deps` 1.2 GB (sources and tarballs
included); `/mnt/c` had 64 GB free before the build.

**Smoke test.** `nextpnr-generic --version` prints "Next Generation Place and Route (Version 9691ce8)". The bundled example was run as its
`viaduct_example.sh` does: the repo's built Yosys with `synth_viaduct_example.tcl` on `generic/examples/blinky.v`, then
`nextpnr-generic --uarch example --json blinky.json`. Result: rc 0, 14 LUT4, 8 DFF, 10 IOB placed on a 7200-LUT device, HeAP placer time 0.01 s,
SA refinement 0.00 s, routing complete (72 arcs). Total wall time 3.09 s (mostly device creation), peak RSS 1.03 GB (the example device).

**Odin III JSON.** `odin3 --top top -p "read_verilog blinky.v; proc; flatten; opt; write_json out.json"` (installed release build, 1.1.1 ABI 7),
with and without `--odin3`, is read by nextpnr's JSON frontend: it parses and the failure comes later at packing ("Top-level port 'rst'
driving illegal port $c10.SRST", rc 125), because the netlist still holds coarse `$sdff`-type cells instead of LUT4/DFF/IOB. So the
schema is accepted; a mapped netlist (LUT cells with `INIT`, `DFF`, `INBUF`/`OUTBUF` per the uarch) is still to be tested and needs the uarch.

**What decision 3 (own viaduct uarch for k6_frac_N10) would need.**
1. A new uarch directory next to `generic/viaduct/example` (about 330 lines for the example). It must be registered in `generic/CMakeLists.txt`
   and the viaduct list, so the uarch cannot live outside the nextpnr tree: it needs either a patched copy of nextpnr (the clone stays read only) or
   an out-of-tree fork. Decision for Peter: patched copy under `/tmp` or a Norns `placers/` directory holding only our files plus a build-time patch.
2. Per-design grid: width, height, IO perimeter (capacity 8), CLB columns, mult and memory columns, read from the VPR `.place` header or the
   architecture file; `init()` creates bels (10 LUT+FF pairs per CLB, 8 IOB per IO tile, mult and memory bels), minimal dummy wires and pips.
3. Cell types: LUT6 with INIT, DFF, IOB, and either carry/adder, mult and memory cells or a rule that they are fixed or excluded. Fracturable LUT
   pairs and input sharing are legality code (`isBelLocationValid`) or ignored, as the earlier fairness notes say.
4. A converter from the BLIF/atom netlist to Yosys JSON (Odin's `write_json` after a LUT mapping may do part of this), fixed IO positions so HeAP is
   used (otherwise nextpnr falls back to SA, `generic/arch.cc:610-625`), and a reader for the `--write` JSON's `NEXTPNR_BEL` attribute.
5. Routing is not needed; a placement-only run uses `--no-route` (option present in `common/kernel/command.cc`).

## 9. Dispatch 3 pre-registration (2026-10-27, written and pushed BEFORE any gate run; keeps every rule above)

Peter 2026-10-27: decision 3 (own viaduct uarch in C++, held in Norns), decision 4 parks OpenPARF and DREAMPlaceFPGA. Work so far, before this entry:
the uarch and its build were written and smoke-tested on one construction (`n5_rand_ctl_64`, seed 1, three or four nextpnr runs of both placers). Those
are development runs, not arm results, and no VPR comparison data exist yet except the one `vpr_ap` seed-1 reference run (below).

### 9.1 Families (Peter 2026-10-27: use different analytic and annealing placers; report per family)
| family | arm | what it is |
|---|---|---|
| analytic | `vpr_ap` | VPR default flow (AP: SimPL-style global placer, doi 10.1145/2461256.2461279, then VPR legalisation, anneal refinement) |
| analytic | `ext_nextpnr_heap` | nextpnr `--placer heap` (HeAP, Gort and Anderson FPL 2012; nextpnr's HeAP is followed by its own temperature-zero SA refinement pass, which is part of the arm) |
| analytic | `vpr_ap_reread` (control) | `vpr_ap` seed s, then its own `final.flat_place` read back by the default flow |
| annealing | `vpr_sa` | `--pack --place --route --analysis` |
| annealing | `ext_nextpnr_sa` | nextpnr `--placer sa` (placer1.cc, "based on arachne-pnr") |
| annealing | `vpr_sa_reread` (control, NEW) | `vpr_sa` seed s, then its own `final.flat_place` read back by the default flow |
`norns_ap` (own placer) is not briefed and not in this experiment. nextpnr offers only `sa` and `heap` on the generic arch (`generic/arch.cc:754`).

**Per-family reporting rule.** Every table, ratio, geometric mean and sentence is per family. An external arm is compared with its own family's VPR arm and
its own family's reread control (heap with `vpr_ap` and `vpr_ap_reread`; sa with `vpr_sa` and `vpr_sa_reread`). No headline compares across families
(heap against `vpr_sa`, or sa against `vpr_ap`); a cross-family number may appear only in a labelled appendix row. Both external arms enter VPR the same way
(mode A, the default flow with `--read_flat_place`), so the reread control that matches the entry path is the same refinement count for both families; the SA
family's second control exists to show how much of the SA arm's result is VPR's own re-legalisation.

### 9.2 The uarch (what the external placers see; fixed before the gate, choices were made on the development construction only)
Source `placers/nextpnr_k6/` (ISC header, derived in structure from nextpnr `generic/viaduct/example`, credit in the file), overlay plus a two-line CMake patch,
built by `placers/nextpnr_k6/build.sh` (Section 9.6). Grid from the VPR reference run (`FPGA sized to W x H`): IO ring, corners empty, 8 IOB bels per IO tile
(z = VPR sub tile); CLB tiles at every interior x with x mod 8 not 2 and not 6 (the memory columns start at x = 2 and mult_36 columns at x = 6, repeat 8, arch XML
lines 227-239), 10 BLE slots per tile, each a LUT6 bel and a DFF bel; tile legality = at most 40 distinct external input nets (the 40 `I` pins; own outputs feed
back). Not modelled: LUT fracturing (n2_lut5 mode), carry, mult_36, memory, clocks (clock nets are not connected, as VPR's placer ignores them), routing (dummy wires,
`--no-route`), cell timing (the generic arch has none, so neither external arm is timing-driven; both VPR arms are: a fairness caveat that is stated in every table).
Two development findings that fix uarch choices before the gate:
1. `pair=0`: LUT6 and DFF are independent cells. With the LUT-to-DFF relative constraint (`pair=1`) nextpnr's SA fails on `n5_rand_ctl_64` for every
   seed tried (1 to 4): "failed to place chain starting at cell", because the constraint legaliser refuses any tile that already holds a locked chain
   (`common/place/place_common.cc`, `valid_loc_for`, "Don't place at tiles where any strongly bound Bels exist"), so SA needs at least as many tiles as chains. HeAP works either
   way. Both arms therefore run with `pair=0`; VPR re-forms the BLEs when it legalises.
2. IO is fixed: every pad is given the `BEL` of its position in the `vpr_ap` seed-1 `final.flat_place` of the same design. HeAP then has anchors (log line "Placed 17 cells
   based on constraints"); with a viaduct uarch nextpnr uses HeAP regardless (`generic/arch.cc:610-625`: the fall-back to SA applies only without a uarch). The same pad
   positions are used for every seed and both arms. Caveat stated with every result: the externals get the pad positions that VPR's analytic placer chose (seed 1); `vpr_ap`
   and `vpr_sa` choose their own for each seed.

### 9.3 Converter coverage and the hard-block census (measured 2026-10-27 from `runs/<d>/netlist/<d>.blif`)
Cells of the BLIF to nextpnr JSON (`scripts/nextpnr_blif2json.py`): `.names` to LUT6 (64-bit INIT from the cover), `.latch` to DFF, pads to IOB; atom names are the VPR atom
names. Readback (`scripts/nextpnr_readback.py`): the `NEXTPNR_BEL` of each cell to a flat-place line `atom x y 0 sub_tile`; sub tile 0 for logic (the flat-place format has no
in-CLB slot: `base/load_flat_place.cpp:140-213` reads sub_tile as an integer, the IO sub tile slot), the pad's own slot for pads.
Census of the 15 main designs (`.subckt` counts): ch_intrinsics 8 single_port_ram; stereovision3 31 adder; mkPktMerge 51 adder + 459 dual_port_ram; diffeq2 136 adder + 5 multiply;
diffeq1 136 adder + 5 multiply; boundtop 166 adder + 32 single_port_ram; mkDelayWorker32B 833 adder + 1336 dual_port_ram; mkSMAdapter4B 370 adder + 153 dual_port_ram; sha 320 adder;
raygentop 453 adder + 15 multiply + 21 single_port_ram; or1200 563 adder + 64 dual_port_ram + 1 multiply; blob_merge 3815 adder; stereovision0 2741 adder; stereovision1 2482 adder +
152 multiply; stereovision2 12175 adder + 468 multiply. **None of the 15 main designs is LUT/FF-only**, so no main design qualifies for the first gate and the gate named in Section 4
(ch_intrinsics, stereovision3, mkPktMerge) cannot run: ch_intrinsics has memory, stereovision3 carry, mkPktMerge both.

### 9.4 First gate, as run in this dispatch (substitute set; the controller may rule otherwise)
Because no main design qualifies, the gate runs on three LUT/FF-only designs of the round-5 netlist-level calibration constructions (`runs/n5_*`, LUT feeding one flip-flop by construction),
smallest first: `n5_rand_ctl_16`, `n5_mesh_ctl_64`, `n5_chain_ctl_256`. They are pipeline-validation data for the converter, the uarch and the readback, labelled "Dispatch 3 gate substitute";
they are not part of the 15-design corpus, and no conclusion about main designs is drawn from them. Arms: `vpr_ap`, `vpr_ap_reread`, `vpr_sa`, `vpr_sa_reread`, `ext_nextpnr_heap`,
`ext_nextpnr_sa`; VPR `--seed` 1 to 3 for every arm (the external placer seed equals the VPR seed); the reference for pads and the atom list is `vpr_ap` seed 1. Seeds 4 to 6 are not run.
Flags as Section 4 (`--timing_report_npaths 200 --route_file /dev/null`, minimum channel width search on, `--analysis` for the stage-flag arms). nextpnr: `--uarch k6 --vopt width=W --vopt height=H
--no-route --placer {heap,sa} --seed s`, no lock (small), wall time and nextpnr's own placer times recorded.
**Pass criteria (all must hold):** every run rc 0 and routes legally (VPR prints "Circuit successfully routed"); the reader accepts every atom (0 warnings of the form "Flat placement file, line"); the converter
and readback report 0 atoms without a cell and 0 moved pads. **Stop rule (Dispatch 3):** if any external arm's routed WL is more than 2x the same family's reread control on the same design and seed, stop
and report the likely cause before changing anything. No arm, option or parameter is chosen on seeds 4 to 6.
Measures: WL, W, CPD, VPR AP time or SA time, nextpnr placer time (HeAP time plus its SA refinement time; SA time plus initial placement), converter wall time; the summary quantity is WL x CPD as in Section 4.

### 9.5 Hard-block rule (a proposal only; nothing of it is built or run in this dispatch)
Needed because every main design has carry (adder) atoms or memory/multiplier atoms. Proposal, in cost order:
* **H0 (cheapest, bias-aware): fixed anchors.** `adder`, `multiply`, `single_port_ram` and `dual_port_ram` atoms are written to the flat-place file at their `vpr_ap` seed-1 positions (as pads are) and
  excluded from the placer; the externals place only LUTs, FFs and pads' neighbours. Bias: the externals inherit VPR's analytic placement of the hard blocks; mark every result "H0" and compare only with
  `vpr_ap_reread`. Cost: a converter change of about a day; no uarch change except that nets to fixed cells need anchor cells (fixed cells of an `ANCHOR` type on dummy bels).
* **H1: carry as plain cells.** An `ADD` cell type (one adder bit, ports a b cin sumout cout) on an `ADD` bel type with two bels per BLE slot (the arch has the adder in the `arithmetic` mode of the `fle`, arch XML
  lines 448-484, to be read exactly before coding), carry nets as ordinary nets, no chain constraint (VPR rebuilds chains when it legalises and the SA legaliser cannot hold more chains than tiles). Mult and
  memory as H0. Cost: about 2 to 3 agent-days; the open question is whether unconstrained carry bits give VPR a placement it can still chain.
* **H2: full.** `MULT36` and `MEM` bel types in the x mod 8 = 6 and 2 columns (heights 4 and 6 rows), cell widths mapped to the fracturing modes (`multiply` 9x9 to 36x36, memory aspect modes of arch XML
  lines 874-1250), chain constraints for carry under HeAP only. Cost: 5 or more agent-days; recommended only if H1 shows the carry model matters.
Recommendation: H0 first (it exercises all 15 designs and isolates the effect of the LUT/FF placer), then H1 on the designs where H0 and `vpr_ap_reread` differ most.

### 9.6 Overlay layout and build recipe (reproducible)
`placers/nextpnr_k6/{k6.cc, constids.inc, cmake-register.patch, build.sh}`. `build.sh` (1) exports `external/nextpnr` HEAD (9691ce8c) with `git archive` to
`/tmp/claude-1000/nextpnr-k6-src` (the clone is not touched), (2) copies `k6.cc` and `constids.inc` to `generic/viaduct/k6/`, (3) applies `cmake-register.patch` (two lines in `generic/CMakeLists.txt`), (4) runs
cmake and ninja into `/tmp/claude-1000/nextpnr-k6-build` under `flock -x /tmp/claude-1000/odin3-heavy.lock`, with the Section 8 dependency prefix. Run with `LD_LIBRARY_PATH=/tmp/claude-1000/nextpnr-deps/prefix/lib`.
No GitHub fork; the licence of the added files is ISC (nextpnr's), credit to gatecat in the header. Licences of the dependencies are in Section 8.

### 9.7 Dated entry 2026-10-27 (still before any counted gate run): BLE merge replaces independent LUT and DFF cells (supersedes Section 9.2 item 1; the old text stays)
First gate attempt (unmerged uarch, `pair=0`, design `n5_rand_ctl_16`, seeds 1 to 3, metrics kept in `data/placers/gate_attempt1_n5_rand_ctl_16.json`): the VPR arms ran (rc 0), the nextpnr runs
and readbacks were clean (337 of 337 atoms, 0 moved pads), but VPR refused the external flat-place files in 4 of 6 runs (`ext_nextpnr_heap` seeds 1, 2, 3 and `ext_nextpnr_sa` seed 3):
`analytical_placement_flow.cpp:110`, "AP block b5_l0 contains atom b5_q0 with a location (1, 4, ...) that conflicts the location of other atoms in this block of (1, 5, ...)". VPR's AP flow treats a
LUT and the flip-flop it alone feeds as one pre-packed molecule that must sit at one location, and independent LUT and DFF cells put them in different tiles. This attempt is not a result. Rule change:
the uarch has one `BLE` bel per slot (10 per CLB tile, matching "10 BLE slots" of the arch); `pack()` merges a `LUT6` whose only sink is a `DFF` D pin with that `DFF` into one `BLE` cell (named after the LUT,
the DFF's name in the attribute `FF_ATOM`), and retypes a lone LUT6 or DFF to `BLE`. Readback gives both atoms of a BLE cell the BLE's location. No relative constraint is used, so SA still starts (the chain
legaliser problem of Section 9.2 item 1 does not arise). Tile legality is unchanged (at most 40 distinct external input nets). The merge rule mirrors VPR's molecule rule (LUT output net with exactly one sink,
that sink a flip-flop D pin); where VPR forms a molecule differently, VPR's error above would show it, and such a run counts as a failed gate run. The gate of Section 9.4 (substitute set, arms, seeds, pass criteria,
2x stop rule) is unchanged and is run now with this uarch. A development run of `n5_rand_ctl_64` seed 1 on the new uarch (SA 958 HPWL, HeAP 961 HPWL, both legal readbacks) is the only look at the new rule.

### 9.8 Gate result (2026-10-27, uarch of Section 9.7, substitute set of Section 9.4; metrics `data/placers/gate_<design>.json`, table by `scripts/placers_gate_table.py`)
Pass criteria met on all 54 external-arm and VPR-arm runs of the three designs: rc 0, "Circuit successfully routed", 0 reader warnings, 0 atoms without a cell, 0 moved pads. nextpnr peak RSS 10 MB
(rand_ctl_16), 20 MB (mesh_ctl_64) and 57 MB (chain_ctl_256) (JSON `max_rss_kb`). **Stop rule fired:** `ext_nextpnr_sa` seed 1 on `n5_chain_ctl_256` has WL 11492 = 4.03x `vpr_sa_reread` (4.16x `vpr_ap_reread`, 2.762 k).
Nothing was tuned. Likely cause (from the logs, not yet tested by any change): nextpnr's SA collapses to a greedy descent (its temperature falls from 1 to 6e-4 within 15 iterations, no timing term) and ends at an HPWL of
3514, 3064 and 3465 for seeds 1 to 3 against 1183, 1193 and 1439 for HeAP on the same design. VPR's full legaliser then starts from that placement: seed 1 gave 257 CLBs instead of the 256 the construction
needs and an initial bb_cost of 140.1 (seed 2: 39.8; HeAP seed 1: 21.6; `vpr_sa_reread` seed 1: 21.2) that VPR's low-temperature anneal only brought to 73.8. The result is a poor start for
VPR, not a converter fault (the same flow with the HeAP file or VPR's own file is fine). Seeds 4 to 6 are not run. All rows below are seeds 1 to 3 (selection seeds), per family.
```

n5_rand_ctl_16  grid [7, 7]  converter: 160 LUT, 160 FF, 17 pads, 0.11 s
 family analytic
  arm                 seed rc routed   WL     W   CPD_ns  vpr_place_s  nextpnr_s(heap+sa|init+sa)
  vpr_ap                 1  0 True      412   22   1.114        0.14  
  vpr_ap                 2  0 True      424   20   1.183        0.13  
  vpr_ap                 3  0 True      412   22   1.217        0.13  
  vpr_ap_reread          1  0 True      471   18   1.322        0.10  
  vpr_ap_reread          2  0 True      444   22   1.135        0.11  
  vpr_ap_reread          3  0 True      427   18   1.256        0.10  
  ext_nextpnr_heap       1  0 True      520   22   1.192        0.11  0.23
  ext_nextpnr_heap       2  0 True      503   18   1.353        0.11  0.14
  ext_nextpnr_heap       3  0 True      420   22   1.143        0.10  0.15
 family annealing
  arm                 seed rc routed   WL     W   CPD_ns  vpr_place_s  nextpnr_s(heap+sa|init+sa)
  vpr_sa                 1  0 True      409   26   1.038        0.02  
  vpr_sa                 2  0 True      514   20   1.238        0.02  
  vpr_sa                 3  0 True      433   20   1.098        0.02  
  vpr_sa_reread          1  0 True      470   22   1.407        0.10  
  vpr_sa_reread          2  0 True      483   20   1.362        0.10  
  vpr_sa_reread          3  0 True      443   20   1.223        0.10  
  ext_nextpnr_sa         1  0 True      415   20   1.170        0.10  1.14
  ext_nextpnr_sa         2  0 True      616   22   1.397        0.11  1.08
  ext_nextpnr_sa         3  0 True      597   22   1.419        0.12  1.06
 stop-rule ext_nextpnr_heap s1: WL / vpr_ap_reread = 1.10
 stop-rule ext_nextpnr_heap s2: WL / vpr_ap_reread = 1.13
 stop-rule ext_nextpnr_heap s3: WL / vpr_ap_reread = 0.98
 stop-rule ext_nextpnr_sa s1: WL / vpr_sa_reread = 0.88
 stop-rule ext_nextpnr_sa s2: WL / vpr_sa_reread = 1.28
 stop-rule ext_nextpnr_sa s3: WL / vpr_sa_reread = 1.35

n5_mesh_ctl_64  grid [13, 13]  converter: 640 LUT, 640 FF, 17 pads, 0.39 s
 family analytic
  arm                 seed rc routed   WL     W   CPD_ns  vpr_place_s  nextpnr_s(heap+sa|init+sa)
  vpr_ap                 1  0 True     4176   26   1.465        0.59  
  vpr_ap                 2  0 True     4342   26   1.811        0.60  
  vpr_ap                 3  0 True     4653   24   1.936        0.58  
  vpr_ap_reread          1  0 True     4459   26   2.026        0.38  
  vpr_ap_reread          2  0 True     4697   24   1.726        0.48  
  vpr_ap_reread          3  0 True     3988   28   1.812        0.35  
  ext_nextpnr_heap       1  0 True     3241   24   1.833        0.35  0.99
  ext_nextpnr_heap       2  0 True     2933   24   1.440        0.36  1.13
  ext_nextpnr_heap       3  0 True     2692   24   1.310        0.35  0.88
 family annealing
  arm                 seed rc routed   WL     W   CPD_ns  vpr_place_s  nextpnr_s(heap+sa|init+sa)
  vpr_sa                 1  0 True     3450   22   1.851        0.09  
  vpr_sa                 2  0 True     3594   22   2.545        0.08  
  vpr_sa                 3  0 True     3130   24   1.507        0.10  
  vpr_sa_reread          1  0 True     3334   22   1.989        0.32  
  vpr_sa_reread          2  0 True     2930   24   1.327        0.30  
  vpr_sa_reread          3  0 True     3048   24   1.393        0.32  
  ext_nextpnr_sa         1  0 True     3645   26   2.603        0.34  5.92
  ext_nextpnr_sa         2  0 True     3682   26   1.709        0.34  5.74
  ext_nextpnr_sa         3  0 True     3840   26   1.706        0.38  6.17
 stop-rule ext_nextpnr_heap s1: WL / vpr_ap_reread = 0.73
 stop-rule ext_nextpnr_heap s2: WL / vpr_ap_reread = 0.62
 stop-rule ext_nextpnr_heap s3: WL / vpr_ap_reread = 0.68
 stop-rule ext_nextpnr_sa s1: WL / vpr_sa_reread = 1.09
 stop-rule ext_nextpnr_sa s2: WL / vpr_sa_reread = 1.26
 stop-rule ext_nextpnr_sa s3: WL / vpr_sa_reread = 1.26

n5_chain_ctl_256  grid [21, 21]  converter: 2560 LUT, 2560 FF, 17 pads, 1.43 s
 family analytic
  arm                 seed rc routed   WL     W   CPD_ns  vpr_place_s  nextpnr_s(heap+sa|init+sa)
  vpr_ap                 1  0 True     2818   38   1.092        1.77  
  vpr_ap                 2  0 True     2843   34   1.092        1.77  
  vpr_ap                 3  0 True     2791   38   1.093        1.76  
  vpr_ap_reread          1  0 True     2762   38   1.093        1.04  
  vpr_ap_reread          2  0 True     2866   34   1.096        1.08  
  vpr_ap_reread          3  0 True     2790   38   1.093        1.05  
  ext_nextpnr_heap       1  0 True     2894   26   1.087        1.04  8.78
  ext_nextpnr_heap       2  0 True     2814   26   1.090        1.05  9.05
  ext_nextpnr_heap       3  0 True     3729   34   1.091        1.09  5.73
 family annealing
  arm                 seed rc routed   WL     W   CPD_ns  vpr_place_s  nextpnr_s(heap+sa|init+sa)
  vpr_sa                 1  0 True     2943   28   1.092        0.27  
  vpr_sa                 2  0 True     2867   26   1.099        0.27  
  vpr_sa                 3  0 True     2909   34   1.089        0.28  
  vpr_sa_reread          1  0 True     2855   34   1.093        1.12  
  vpr_sa_reread          2  0 True     2875   26   1.090        1.08  
  vpr_sa_reread          3  0 True     2900   34   1.089        1.02  
  ext_nextpnr_sa         1  0 True    11492   26   1.660        1.25  35.96
  ext_nextpnr_sa         2  0 True     3333   38   1.205        1.07  34.17
  ext_nextpnr_sa         3  0 True     4959   34   1.235        1.10  32.88
 stop-rule ext_nextpnr_heap s1: WL / vpr_ap_reread = 1.05
 stop-rule ext_nextpnr_heap s2: WL / vpr_ap_reread = 0.98
 stop-rule ext_nextpnr_heap s3: WL / vpr_ap_reread = 1.34
 stop-rule ext_nextpnr_sa s1: WL / vpr_sa_reread = 4.03  > 2x STOP
 stop-rule ext_nextpnr_sa s2: WL / vpr_sa_reread = 1.16
 stop-rule ext_nextpnr_sa s3: WL / vpr_sa_reread = 1.71
```

## 10. Dispatch 4 pre-registration (2026-10-27, written and pushed BEFORE any run it governs; keeps every rule above)

Peter 2026-10-27 ("I like your decisions") approved: (1) the three LUT/FF-only constructions (`n5_rand_ctl_16`, `n5_mesh_ctl_64`, `n5_chain_ctl_256`) are a PIPELINE gate only, not research
results; (2) the Section 9.8 stop-rule fire is recorded as a finding, followed by one pre-registered change (`--starttemp`); (3) the hard-block rule is H0 now (H1 comes in a later dispatch).
No run of this dispatch exists before this commit. Arms are listed by family everywhere (Section 9.1); every table and caption of this dispatch repeats the H0 bias statement of Section 10.3.

### 10.1 The SA finding (recorded, not a result; from Section 9.8)
`ext_nextpnr_sa` seed 1 on `n5_chain_ctl_256` routed with WL 11492 = 4.03x `vpr_sa_reread` (4.16x `vpr_ap_reread`). nextpnr's SA temperature, which starts at 1 (`placer1.cc:1238`, default of `placer1/startTemp`)
and is multiplied by 0.5 when the acceptance ratio exceeds 0.96 (`placer1.cc:340`), fell to 6e-4 within 15 iterations in that run: with HPWL deltas of order 1 or more per move the search is a greedy descent. Final nextpnr HPWL on that design:
3514, 3064, 3465 (SA, seeds 1-3) against 1183, 1193, 1439 (HeAP). This is the likely cause; it is tested only by the one change below. Seeds 4-6 were not run in Dispatch 3.

### 10.2 SA start temperature (the one pre-registered change to `ext_nextpnr_sa`)
* **Parameter:** nextpnr's existing `--starttemp T` (a float in HPWL cost units; no nextpnr code change). **Grid (5 values, fixed now): T in {1, 3, 10, 30, 100}**; T = 1 is nextpnr's default and is the Dispatch 3 arm.
* **Set:** the Dispatch 3 substitute set (`n5_rand_ctl_16`, `n5_mesh_ctl_64`, `n5_chain_ctl_256`; no hard blocks, so H0 plays no part). It is a pipeline-calibration set, chosen because no main design is LUT/FF-only; the transfer of the choice to the main designs
  is a stated assumption, not a finding.
* **Selection on seeds 1-3 only.** For every T, run `ext_nextpnr_sa` (seeds 1-3, uarch and flags of Section 9, nextpnr seed = VPR seed, mode A) on the three designs, with the matching `vpr_sa_reread` and `vpr_sa` controls (same seeds). Quantity:
  Q(T) = geometric mean over the 9 (design, seed) pairs of (WL x CPD of `ext_nextpnr_sa` at T) / (WL x CPD of `vpr_sa_reread`). **Choose the T with the smallest Q(T)**; a difference under 1% is a tie, broken to the smaller T. Also reported: the largest
  WL ratio to `vpr_sa_reread` over the 9 pairs for each T (the 2x rule of Section 9.4).
* **If no T brings every one of the 9 WL ratios to 2.0 or less,** that is recorded in a dated entry, the arm is kept with the smallest-Q(T) value and carries the label "SA start temperature not sufficient (2x rule not met)" in every table.
* **Report on seeds 4-6 (held out).** After the choice is committed (dated entry naming T and its SHA), run on the substitute set seeds 4-6: `ext_nextpnr_sa` at the chosen T and at the default T = 1, `vpr_sa`, `vpr_sa_reread`. Report per design the median and the min-max of the three seeds
  of WL, W, CPD and WL x CPD. Nothing is chosen from seeds 4-6.

### 10.3 Hard-block rule H0 (Section 9.5 H0, now adopted) and its bias statement
* **Rule.** The converter reads the `vpr_ap` seed-1 `final.flat_place` of the design (as for pads in Section 9.2 item 2). Every atom of the models `adder`, `multiply`, `single_port_ram`, `dual_port_ram` becomes a cell of the type `ANCHOR`, fixed by
  `BEL` at the exact (x, y) of its reference line, on a dummy `ANCHOR` bel of the uarch (new bel type; the bels at a location are created from a converter-written list `x y count`, passed with `--vopt anchors=FILE`; they carry no pins, do not count against
  the 10 BLE slots of a tile, and are not part of tile legality). Their nets enter the JSON, so nextpnr's HeAP and SA see the hard blocks as fixed anchors on their nets. A net with no movable cell (only pads and anchors) is not emitted, and an anchor with no emitted net is not emitted.
  Pins on clock nets and on constant or unconnected nets (`vcc`, `gnd`, `unconn`) are not connected. Readback writes every hard-block atom VERBATIM from the reference line (x, y, layer, sub tile); a hard-block cell reported at another location is counted (must be 0).
  Movable in nextpnr: only the BLE cells (LUT6, DFF and merged LUT6+DFF). Pads stay fixed as in Section 9.2.
* **Legality check.** The H0 flat-place file of every one of the 15 main designs must be accepted by VPR: rc 0, no reader warning, "Circuit successfully routed". It is checked by the seed-1 runs of the main comparison (below); a design whose external file VPR refuses is listed as ineligible with the VPR
  error line for that arm, never silently dropped, and nothing is retuned for it. Fixing a converter bug is allowed and is a dated entry.
* **Bias statement (printed in every caption of this dispatch, verbatim in meaning):** *"H0: adders, multipliers and RAMs are fixed at the positions of the VPR analytic placer (`vpr_ap`, seed 1), as are the pads, in both external arms and for every seed. nextpnr therefore places only the LUT/flip-flop logic, around
  hard blocks and pads that VPR's analytic placer chose. The external arms inherit that part of VPR's solution; the annealing-family external arm inherits it from the analytic family. nextpnr has no timing model; both VPR families are timing-driven."*
  Consequence for reading: the external arms are not independent placements of whole designs. Compare each external arm only with its own family's reread control; the hard-block part of the comparison is deliberately neutral (zero degrees of freedom for externals, seed-1 positions) and the variance across seeds of the external arms is understated for that part.

### 10.4 Main comparison (after the starttemp choice and the H0 build; includes the H0 legality check)
* **Designs:** the 15 main designs of Section 4, smallest first by logic CLBs (ch_intrinsics, stereovision3, mkPktMerge, diffeq2, diffeq1, boundtop, mkDelayWorker32B, mkSMAdapter4B, sha, raygentop, or1200, blob_merge, stereovision0, stereovision1, stereovision2), every arm and seed of one design
  before the next design of the same driver. Two drivers run in parallel on alternate positions of that order; they share only the VPR lock; each still goes smallest first.
* **Arms by family** (all through mode A, `--read_flat_place` into the default flow, flags of Section 9.4): analytic: `vpr_ap`, `vpr_ap_reread`, `ext_nextpnr_heap`; annealing: `vpr_sa`, `vpr_sa_reread`, `ext_nextpnr_sa` (T = the choice of Section 10.2).
* **Seeds:** 1 to 6 for every arm. Seeds 1-3 are selection data; the reported comparison is seeds 4-6 (held out). The reference of all external arms is `vpr_ap` seed 1 for every seed (Section 9.2); the `vpr_ap` seed-1 run is shared.
* **Measures:** routed WL, W, CPD, VPR placement time (AP or SA), nextpnr placer time, converter time, nextpnr peak RSS; the summary quantity is WL x CPD (Section 4).
* **Summaries (written after all seeds finish; no paper section yet):** per design and arm, the median over seeds 4-6 and the min-max; per family, the geometric mean over designs of the ratio (arm median / own-family reread median) and (arm median / own-family VPR median), with the bootstrap of Section 4 (10000 resamples, seed 20261026, percentile 95%).
  A dated results entry follows in this file. Seeds 1-3 are shown separately and labelled selection data.
* **Stop rules** are those of Section 5 and Section 9.4 with these precisions: (a) pipeline faults (rc not 0, no legal route, reader warning, an atom without a cell, a moved pad or hard block) stop the affected design for that arm, are listed, and are retried once (Section 5 rule 4); (b) the 2x rule of Section 9.4 is
  EVALUATED per design on the held-out medians and per run, and a fire is reported and the arm labelled, not a halt, because its cause is already recorded (Section 10.1) and this dispatch keeps the arm labelled; (c) memory: stop if one nextpnr process passes 13 GB (about 56% of the 23 GB VM);
  (d) Section 5 rule 5 (an arm past 8 h on `stereovision2`: cut the largest designs first, commit the cut); (e) stop if `/mnt/c` has under 30 GB free; (f) no arm, option or parameter is chosen on seeds 4-6.

### 10.5 Dated entry 2026-10-27: SA start temperature chosen on seeds 1-3 (before any substitute-set seed 4-6 run)
Grid of Section 10.2 run on the substitute set, seeds 1-3, driver `scripts/placers_main.py` (tag `temp_sel`, metrics `data/placers/temp_sel_<design>.json`, table by `scripts/placers_temp_table.py sel`).
The T = 1 rows reproduce the Dispatch 3 gate numbers exactly (same WL for `vpr_sa`, `vpr_sa_reread` and `ext_nextpnr_sa` on every seed), so VPR and nextpnr runs are deterministic. All 45 external runs and 9 control runs: rc 0, legal route.
Quantity Q(T) and the largest WL ratio to `vpr_sa_reread` over the 9 (design, seed) pairs:
```
     T     Q(T)  max WL ratio  missing/illegal  per-pair WL ratio (design seed)
     1    1.631          4.03                0  rand_1:0.88 rand_2:1.28 rand_3:1.35 mesh_1:1.09 mesh_2:1.26 mesh_3:1.26 chain1:4.03 chain2:1.16 chain3:1.71
     3    1.693          4.81                0  rand_1:0.93 rand_2:0.79 rand_3:0.97 mesh_1:1.13 mesh_2:1.36 mesh_3:1.23 chain1:1.08 chain2:4.49 chain3:4.81
    10    1.487          3.42                0  rand_1:1.07 rand_2:0.87 rand_3:1.06 mesh_1:1.14 mesh_2:1.05 mesh_3:1.30 chain1:1.66 chain2:2.03 chain3:3.42
    30    1.602          4.27                0  rand_1:1.21 rand_2:1.02 rand_3:0.97 mesh_1:1.05 mesh_2:1.06 mesh_3:1.15 chain1:2.57 chain2:4.27 chain3:1.81
   100    1.172          1.33                0  rand_1:1.31 rand_2:1.00 rand_3:0.86 mesh_1:0.98 mesh_2:1.33 mesh_3:1.19 chain1:1.19 chain2:1.09 chain3:1.02

choice (smallest Q, ties under 1% to the smaller T): T = 100; max WL ratio there 1.33; 2x rule met
```
**Choice: T = 100** (smallest Q(T) = 1.172; the 2x rule of Section 9.4 is met, max WL ratio 1.33). Q(T) is not monotone in T for T = 1 to 30 (1.63, 1.69, 1.49, 1.60): the chain design with three seeds is noisy there, so only T = 100 is distinctly better and "the temperature falls too fast" is a partial explanation at best, tested by this one change. From here on `ext_nextpnr_sa` means `--placer sa --starttemp 100`
in the main comparison; the T = 1 arm is kept as a labelled secondary row on the substitute set only. The held-out substitute-set run (seeds 4-6: `ext_nextpnr_sa` at T = 100 and T = 1, `vpr_sa`, `vpr_sa_reread`) follows this commit.
**Scheduling deviation (stated, not a selection leak):** to use idle time, the main-comparison drivers were started before this choice with the arms that have no tunable parameter (`vpr_ap`, `vpr_ap_reread`, `vpr_sa`, `vpr_sa_reread`, `ext_nextpnr_heap`), seeds 1 to 6 per design in one pass, so their seeds 4-6 were
run before this entry. Nothing is chosen from them: the only parameter of the dispatch (T) was fixed above from the substitute set seeds 1-3. `ext_nextpnr_sa` on the main designs runs after this commit.
