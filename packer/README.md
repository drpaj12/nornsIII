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
| `vpr/src/pack/norns_affinity.h/.cpp` | new: reads the affinity file (`atom name`, TAB, `integer group id`), group lookup, member lists, dominant group; parse errors of the group id stop with `VPR_FATAL_ERROR` (affinity file and line); log-only proposal counters | +182 |
| `vpr/src/pack/greedy_candidate_selector.cpp` | loads the file in the constructor; counts the groups of a cluster's atoms and keeps its dominant group; adds `+ beta` per candidate atom in that group to the molecule gain (`get_molecule_gain`); proposes up to `feasible_block_array_size` unclustered group members after the connectivity step (new `add_cluster_molecule_candidates_by_norns_group`); log-only counter of the proposal step (attempted, queued, calls with none queued; one `Norns proposals:` log line when packing ends, active only with weight > 0) | +88 |
| `vpr/src/pack/greedy_candidate_selector.h` | the new method; two fields in `ClusterGainStats` (group counts, dominant group) | +17 |
| `vpr/src/base/read_options.cpp/.h` | options `--norns_affinity <file>` (default empty) and `--norns_affinity_weight <beta>` (default 0) | +19 |
| `vpr/src/base/setup_vpr.cpp` | hands the two options to the packer (`norns::set_options`) | +2 |

Nothing is removed from any VTR line (all diffs are additions). `vpr_types.h` is untouched
on purpose (it is included everywhere); the options travel through `norns::set_options`.

## Round 4 changes (docs/plan/round4.md, Stage 1)

* Proposal counting. `add_molecule_to_pb_stats_candidates` now returns whether the molecule entered the candidate
  queue. The cap of the group-member proposal (`feasible_block_array_size`, 30) counts queued molecules by default
  (`--norns_proposal_count queued`); `--norns_proposal_count attempted` is the round-3 behaviour (the cap counted
  molecules handed to the queue, whether or not it accepted them). The scan order (atom id) is unchanged. The round-3
  hit rate (queued / attempted) and the fixed one are in the paper (`tab:r4proposals`).
* Census, log-only (`--norns_pack_census <file>`; `norns_affinity.h` `Census`, hooks in `greedy_candidate_selector.cpp`
  and one line in `greedy_clusterer.cpp` that passes the legalizer status). Tab separated records: `M` a molecule added
  to a cluster (cluster number, index, seed or candidate, source, queue-time gain, affinity bonus, attraction gain, base
  gain, dominant affinity group, root atom), `A` its atoms with the sharing, connection, timing and combined gain VPR
  held for them, `P` the pack-time criticality of each input pin, `Q` a molecule entering the candidate queue (source),
  `F` a candidate the legalizer refused (status 1 = pin feasibility, 2 = intra-cluster routing), `K` a cluster closed.
  Sources: 0 seed, 1 connectivity and timing, 2 affinity group, 3 transitive, 4 high fanout, 5 attraction group,
  6 RAM, 7 unrelated clustering. The code reads the gain maps with `find` only and never touches the random state, so
  the `.net` is unchanged (Stage-1 gate (b)).
* Gates: `scripts/round4.py gate` (results `data/analysis/r4-gate.json`).
  Gate (c) compares against the round-3 binary (`$NORNS_VPR_R3`, default `/tmp/claude-1000/nr4-w/vpr-r3`): the overlay
  as committed at `7e26f3b` (before the round-4 packer commit `00518c8`), on the same VTR commit and with the same cmake flags.
  `sh packer/build.sh --r3` builds exactly that in a separate tree (`$NORNS_VTR_R3`, default `work/norns-vtr-r3`); it
  exports `packer/vpr` of `7e26f3b` with `git archive`, so no round-4 file is left over. Point `NORNS_VPR_R3` at
  `$NORNS_VTR_R3/build/vpr/vpr`. (The script path is the documented route; the binary used for the committed gate was copied
  from the round-3 build before the round-4 overlay, and was not rebuilt in the fix round.)
* Fix round (docs/plan/round4.md, last entry): (i) `last_status` (`norns_affinity.h`) is a global set in
  `GreedyClusterer::try_add_candidate_mol_to_cluster` (`greedy_clusterer.cpp`) right after `add_mol_to_cluster` returns, and
  the only caller of `update_cluster_gain_stats_candidate_failed` (which writes the `F` record) is the `else` branch of
  that same call in `GreedyClusterer::try_grow_cluster`, with no code between them: every `F` record follows an attempt and reads
  that attempt's status. No code change. (ii) Cost of `queued` counting: a molecule already in the queue returns false and
  does not consume the cap, so with `queued` counting the scan of `add_cluster_molecule_candidates_by_norns_group` can walk the
  whole group on every call (the cost grows with the size of the group). It is a
  run-time cost, not a correctness issue (the gates pass); it is not bounded in this round (log-only note, no behaviour change). The
  census `Norns proposals:` line (calls, attempted, queued) gives its size.

## Known limits of the proposal step (round 3; fixed above)

In `add_cluster_molecule_candidates_by_norns_group` the counter `added` (cap `feasible_block_array_size`, 30) was incremented
for every molecule handed to the candidate queue, not for every molecule the queue accepts: the queue ignores a molecule that
is already in it or (APPack) too far from the cluster in the global placement, and a rejected molecule still spent the cap.
The group is scanned in atom-id (netlist) order, so the members tried first are the lowest ids, a netlist-order bias that
remains. The log-only counter reports attempted and queued molecules and proposal calls that queued nothing (`Norns
proposals:` line of `vpr.out`). The fraction of affinity-file entries that matched an atom is printed in the existing
`Norns affinity:` line. The round-3 affinity files listed atoms VPR does not have (absorbed buffer LUTs, dead logic) and
named adders wrongly; see `scripts/affinity.py` and `data/analysis/r4-join.json`.

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
