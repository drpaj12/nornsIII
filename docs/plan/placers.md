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
