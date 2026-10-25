# The Norns packer (a copy/modification of VPR's AAPack/APPack clusterer)

VPR's packer is AAPack, the greedy clusterer in `vpr/src/pack/` (not T-VPack). In the default
flow of VTR 3c9a4d23b2 (`VTR_COMMIT`) the same clusterer runs inside the analytical-placement
flow as APPack (candidate gains attenuated by distance in the global placement). This directory
holds the files changed from that commit (MIT licence, `LICENSE-VTR.md`; every VTR header is kept)
and a script that builds them into a private tree. Peter's request (2026-10-24): "Let's build our
own Norns based packer ... as a copy/modification to Apack to allow us to our controlled
experiments." The change is a provenance-affinity term; legality is AAPack's legalizer, untouched.

## What changed (against VTR 3c9a4d23b2)

| file | change | lines |
|---|---|---|
| `vpr/src/pack/norns_affinity.h/.cpp` | new: reads the affinity file (`atom name`, TAB, `integer group id`), group lookup, member lists, dominant group | +157 |
| `vpr/src/pack/greedy_candidate_selector.cpp` | loads the file in the constructor; counts the groups of a cluster's atoms and keeps its dominant group; adds `+ beta` per candidate atom in that group to the molecule gain (`get_molecule_gain`); proposes up to `feasible_block_array_size` unclustered group members after the connectivity step (new `add_cluster_molecule_candidates_by_norns_group`) | +67 |
| `vpr/src/pack/greedy_candidate_selector.h` | the new method; two fields in `ClusterGainStats` (group counts, dominant group) | +17 |
| `vpr/src/base/read_options.cpp/.h` | options `--norns_affinity <file>` (default empty) and `--norns_affinity_weight <beta>` (default 0) | +19 |
| `vpr/src/base/setup_vpr.cpp` | hands the two options to the packer (`norns::set_options`) | +2 |

Nothing is removed from any VTR line (all diffs are additions). `vpr_types.h` is untouched
on purpose (it is included everywhere); the options travel through `norns::set_options`.

## The gain term and its scale

The stock per-atom gain is `(sharing + connection gain) / pins` (and a timing term); it lies in
[0, 1]. A molecule's gain is the sum over its atoms. With `--norns_affinity_weight beta` > 0 a
molecule gets `+ beta` for every atom whose group equals the open cluster's dominant group (the
plurality group of the grouped atoms packed so far, ties to the lower id), so beta is in units of
a single connected atom's gain. Why also propose group members: the bits of a word are usually
parallel, with no net between them, so the connectivity search never lists them; the proposal
puts up to `feasible_block_array_size` (30) unclustered members of the dominant group into the
queue where the gain ranks them with the connected candidates. Not changed: the seed selector (a
new cluster is still seeded by the stock rule; its group is then the first grouped atom's), the
legalizer, the pin-feasibility filter, APPack's distance threshold (a group member far from the
cluster in the global placement is still rejected in the analytical flow).

AAPack already has `AttractionInfo` groups (from floorplan constraints) that do something similar;
they are left alone because they also penalise other-group candidates and change the failed-
molecule handling, which the controlled experiment does not want.

With the options absent, or with `beta = 0`, the packer takes the stock path: the file (if given) is
read and the group counts are kept, but no gain or candidate changes. The control gate
(`scripts/round3.py gate`, results `data/analysis/r3-gate.json`) checks the `.net` is byte-identical to the
stock `vpr`'s on all 15 designs.

## Build

`sh packer/build.sh` clones `$VTR_ROOT` (read only; a local clone, not a worktree) to
`$NORNS_VTR` (default `work/norns-vtr`), checks out `VTR_COMMIT`, takes the submodules from the
same checkout, overlays `packer/vpr/`, configures with the stock flags (release, `-O3`, LTO,
`VTR_ASSERT_LEVEL=2`) without Odin, Parmys, ABC and tests, and builds the `vpr` target with
`-j4` under the heavy lock (`/tmp/claude-1000/odin3-heavy.lock`). The binary is
`$NORNS_VPR` (`scripts/env.sh`: `$NORNS_VTR/build/vpr/vpr`). Build output stays out of git.
