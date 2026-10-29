# Picking from the critical heap: how the greedy packer goes wrong, and the exception HDL patterns (data only)

Purpose: speed = critical + near-critical paths (hub purpose; Norns packing RQs; measure: speed and wirelength). Terminology (Peter 2026-10-29): the **critical heap** = the paths suspected critical; the packer greedily takes from it first; as it is worked a new heap forms; at the end a heap remains whose criticality has been pushed down to a floor it cannot get below. Study 1 (`docs/plan/critical-heap.md`, nornsIII #24) measured the heap. This study asks how the greedy pick goes wrong (questions P1 to P8) and, as Peter asked, keeps a catalogue of the exception HDL patterns: each pattern has a detector that works before packing and the hint it would give the packer. Data-first rule (Peter 10-26): this document measures and shows; every hint is UNTESTED and the hypotheses at the end are untested.

## Plain-English summary

* The packer does not see a moving heap. Its criticality is computed once, before packing, with one fixed delay for every net, and never updated in the default flow (VTR commit 3c9a4d23b2: `update_timing_info` is called only from the analytical global placer). So the heap the packer works on is the pre-pack heap. Of the molecules it takes with a pack-time crit >= 0.90 (4.3% [3.0%, 11.1%] (n=15) of all picks), 81% [63%, 91%] (n=15) contain no atom of the post-route heap (seed picks 74% [24%, 88%] (n=15), candidate picks 82% [72%, 92%] (n=15)).
* Going the other way, 32% [15%, 62%] (n=15) of the post-route heap is packed in the second half of the cluster order, and 5% [1%, 7%] (n=15) had a pack-time crit below 0.50 (the packer did not know they were critical). Filler by source: none of the post-route heap atoms came in through unrelated clustering or with a zero gain (median).
* The cuts. A reported near-critical path (crit >= 0.90) touches a median 3.7 [3.0, 4.3] (n=13) clusters; the floor from capacity is 1.9 [1.0, 2.7] (n=13) (10 BLEs per cluster) or 1.0 [1.0, 1.6] (n=13) (20, if every FLE held two LUTs). 98% [82%, 100%] (n=13) of the paths are above the 10-BLE floor. 98% [85%, 100%] (n=12) of the distinct crossing edges fall where the earlier cluster closed with all 10 FLEs used: the packer fills clusters to the brim, so almost every cut is a capacity cut. What fills the cluster is mostly not the heap: in clusters that hold a post-route heap atom, 70% [64%, 74%] (n=14) of the FLEs hold atoms outside the heap (heap atoms occupy 2.5 [2.2, 3.1] (n=14) of 10 FLEs).
* Reconvergence. At a fork atom (two or more successors on near-critical paths) the clusters split the successors in 67% [33%, 90%] (n=11) of the cases (some with the fork, some not), all with the fork in 7% [0%, 26%] (n=11), none in 31% [3%, 54%] (n=11). 66% [26%, 83%] (n=12) of the crossing edges sit at a fork or join atom.
* Ties. The queue gain of the molecule picked equals that of another queued molecule in 35% [29%, 45%] (n=15) of the picks (exact), 60% [54%, 70%] (n=15) within 5%. The tie is broken by queue order (98% [96%, 100%] (n=15) of exact ties go to the molecule queued first, that is the scan order). Ties that involve a pack-time heap atom are few (9% [4%, 26%] (n=15) of the 5% ties); on those the pick had a lower post-route crit than a tied heap competitor 23% [9%, 44%] (n=15) of the time and a higher one 14% [7%, 19%] (n=15) (the intervals overlap).
* Max-over-pins. Only 6% [1%, 18%] (n=15) of the pack-heap atoms with two or more input nets have a single critical pin; they stay in the post-route heap as often as the others (23% [0%, 43%] (n=12) against 29% [13%, 45%] (n=14)). A related effect is real: 10% [0%, 25%] (n=15) of the picks made on a timing gain >= 0.90 are atoms whose own input pins are all below 0.50 (the gain was inherited from a sibling sink of the net); they stay in the heap 4% [0%, 17%] (n=9) of the time, against 14% [6%, 17%] (n=15) for the picks with a critical pin of their own.
* High-fanout nets (more than 32 sinks, ignored by the packer's gain) are almost absent from the post-route near-critical nets: 0.0% [0.0%, 0.2%] (n=13) of them; one net in all 15 designs (boundtop `tm3_sram_we`, fan-out 64, a write enable steering a 64-bit data word). Nets of 9 to 32 sinks, which the packer treats as ordinary nets, are present: 24 near-critical nets in 7 designs (seed 1), driven by comparison results, subtract borrow bits, state bits and enables.
* HDL words. Of 165 word groups of >= 8 bits (36 from the Odin III attribution, 129 from top-level buses), 91% have under 1% of their bit pairs tied by dataflow (a net, or one atom in between). The stock packer already puts only 7% of the pairs of a word in one cluster (median) and spreads a word over 3.8 times the minimum number of clusters. Word-major grouping would therefore ask the packer to bind bits that have no dataflow between them; the words with the most tied pairs (5 to 25%) are adder words (a 32-cell adder word: 12%) and a few LUT words.
* The catalogue (below) has 11 rows. The patterns with a measured effect on the pick or the cut: the parallel bus word (no dataflow), the fork atom, the capacity cut that is filled by non-heap atoms (a general mechanism, not an HDL exception), the decision-bit fan-out net, the timing gain inherited from a sibling sink, and logic fed by a hard block (pre-pack heap that does not stay).

## Method and data

* Runs: the 45 beta-0 census runs of the heap lane (15 VTR Verilog designs x seeds 1 to 3; `work/heap-out`; the `.net` of every run is byte-identical to the stock sweep run; no new VPR run was made). Post-route side: `norns-keep.db` (1000-path timing report per run, atoms named like the packer's). Netlist: the keep-sweep BLIF of each design. All stores read only.
* Pack-time crit pc(atom) and post-route crit rc(atom), the post-route heap (rc >= 0.90) and the pack-time heap (pc >= 0.90) are those of the heap lane (`scripts/heap_lib.py`, `heap_data.py`, reused as they are). pc is the pre-pack criticality of VPR's own static timing analysis (one delay of 1.338 ns for every net between logic blocks (carry hops excepted) in the pre-pack report of diffeq1, `pre_pack.report_timing.setup.rpt` in the run directory); it is read here from the census `P` records. The heap-lane document says VPR updates it as clusters close; that is wrong for the default flow (the only call that refreshes it is in the analytical global placer), and the numbers of that document do not change.
* Cluster of an atom: the `.net` (`clb[i]`, FLE slot `fle[j]`, 10 FLEs per clb in the Norns architecture); each `.net` cluster holds the atoms of exactly one census cluster (checked in every run: no mixed cluster). A cluster is *full* when all 10 FLEs hold an atom. Molecule root, the queue gains and the refusal records (`F`) come from the census (`packer/README.md`, Round 4 changes).
* Summary over designs as in the heap lane: per design the mean over its 3 seeds, then the median over designs with a 90% percentile bootstrap (2000 resamples of designs); n = designs with a value.
* Code: `scripts/heappick_lib.py` (census, `.net`, crossing causes, queue ties, fan-out, pair ties), `heappick_run.py` (P1 to P7, P9 per run), `heappick_groups.py` (P8), `heappick_data.py`, `heappick_analyze.py` (writes `data/analysis/heappick.json`), `heappick_figs.py`, `heappick_doc.py` (this file). Tests: `python3 tests/test_heappick.py` (19 tests).

### How each question is measured

* P1: a *pick* is a molecule added to a cluster (census `M`). Heap pick: any atom of the molecule has pc >= 0.90; it *leaves* if none of its atoms has rc >= 0.90 (an atom in no reported path has rc below the last reported crit, always below 0.90).
* P2: the distinct near-critical paths (crit >= 0.90) of the report. A path is cut at pads and hard blocks into runs of logic atoms (LUT, adder, FF in clb clusters); a launching register at the head is dropped (it is packed with the previous stage). BLEs = LUT and adder atoms; floor = sum over runs of ceil(BLEs / 10), or / 20; clusters touched = number of same-cluster segments. A crossing is two consecutive atoms of a run in different clusters (distinct edges over all paths). Its cause is read from the cluster that was packed first (it closed without taking the other atom): `full`, else `refused_pins` / `refused_route` (a census `F` record of the other atom's molecule, status 1 / 2), else queued but never taken, else never proposed.
* P3: fork atoms = atoms with >= 2 distinct successors on the near-critical paths (join = predecessors); `split` = some of them in the atom's cluster and some not.
* P4: the census is replayed in file order; the pending queue of a cluster = molecules with a `Q` record not yet added (`M`) or refused (`F`). The gains are queue-time gains: VPR never refreshes the gain of a molecule already in the queue (`add_molecule_to_pb_stats_candidates`: "if already in queue, do nothing"). A tie = another pending molecule with gain >= picked gain x (1 - epsilon). `hot` = a pack-time heap atom among the tied molecules.
* P5: clusters holding >= 1 post-route heap atom: FLEs with a heap atom against the other FLEs; `min clusters` = ceil(heap FLEs / 10).
* P6: per atom, the distinct input nets and their pack-time crit (`P` records); single-pin = best pin >= 0.90 and second best < 0.50. Timing gain inheritance: `update_timing_gain_values` gives an atom that drives a net into the cluster the *largest* pin crit over all sinks of that net; the census `A` timing gain >= 0.90 with all own input pins < 0.50 marks such a pick.
* P7: the nets between consecutive atoms of the near-critical paths, with the fan-out of the BLIF net (single-input buffers absorbed); the packer ignores nets above 32 sinks (`vpr.out`: `clb:32`).
* P8: see the section; P9: detector counts for the catalogue.

## P1. Stale criticality

| measure | median over designs [90% bootstrap] |
|---|---|
| share of all picks with pc >= 0.90 | 4% [3%, 11%] (n=15) |
| heap picks that leave the heap | 81% [63%, 91%] (n=15) |
|   seed picks | 74% [24%, 88%] (n=15) |
|   candidate picks | 82% [72%, 92%] (n=15) |
| post-route heap packed in the second half of the cluster order | 32% [15%, 62%] (n=15) |
| post-route heap with pc < 0.50 | 5% [1%, 7%] (n=15) |
| post-route heap picked as unrelated filler (source 7) | 0% [0%, 0%] (n=15) |
| post-route heap picked with zero queue gain | 0% [0%, 0%] (n=15) |
| Spearman(pc, rc) over atoms seen in a report | 0.66 [0.60, 0.73] (n=15) |

| design | pack-heap picks leaving (seed / candidate) | post-route heap late | pc < 0.50 |
|---|---|---|---|
| blob_merge | 73% (7% / 82%) | 80% | 2% |
| boundtop | 74% (87% / 72%) | 79% | 6% |
| ch_intrinsics | 100% (100% / 100%) | 0% | 100% |
| diffeq1 | 42% (2% / 52%) | 15% | 0% |
| diffeq2 | 46% (17% / 51%) | 32% | 0% |
| mkDelayWorker32B | 99% (98% / 99%) | 83% | 17% |
| mkPktMerge | 100% (100% / 100%) | 33% | 33% |
| mkSMAdapter4B | 81% (81% / 81%) | 23% | 6% |
| or1200 | 91% (88% / 92%) | 62% | 0% |
| raygentop | 82% (69% / 89%) | 43% | 5% |
| sha | 55% (19% / 78%) | 0% | 1% |
| stereovision0 | 81% (74% / 83%) | 2% | 20% |
| stereovision1 | 100% (100% / 100%) | 81% | 7% |
| stereovision2 | 29% (24% / 35%) | 20% | 1% |
| stereovision3 | 63% (44% / 66%) | 13% | 2% |

Figure: `docs/figures/heap-picking/p1-picks-leaving.png`.

Which pack-heap atoms stay (share of the atoms with pc >= 0.90 that are in the post-route heap, per design then median; designs with >= 10 such atoms):

| category | stay | atoms (all runs) |
|---|---|---|
| after_hard_block | 0.07 [0.00, 0.50] (n=5) | 6420 |
| blk=adder | 0.00 [0.00, 0.37] (n=5) | 951 |
| blk=counter | 0.42 [0.00, 0.84] (n=2) | 129 |
| blk=equality | 0.00 [0.00, 0.00] (n=1) | 288 |
| blk=fsm | 0.52 [0.00, 0.81] (n=3) | 579 |
| blk=logic | 0.09 [0.02, 0.60] (n=4) | 1716 |
| blk=mux | 0.08 [0.00, 0.31] (n=8) | 1659 |
| blk=none | 0.30 [0.30, 0.30] (n=1) | 66 |
| blk=register_word | 0.21 [0.10, 0.61] (n=8) | 14262 |
| carry_chain | 0.49 [0.00, 0.75] (n=6) | 951 |
| lvl=1-3 | 0.23 [0.11, 0.43] (n=15) | 17934 |
| lvl=11+ | 0.29 [0.29, 0.29] (n=1) | 330 |
| lvl=4-6 | 0.24 [0.00, 0.51] (n=9) | 1230 |
| lvl=7-10 | 0.41 [0.41, 0.41] (n=1) | 156 |
| op=adder | 0.36 [0.13, 0.52] (n=10) | 10539 |
| op=equality | 0.03 [0.00, 0.83] (n=5) | 276 |
| op=multiplier | 0.76 [0.76, 0.76] (n=1) | 84 |
| op=mux | 0.41 [0.06, 0.42] (n=3) | 1155 |
| op=none | 0.25 [0.17, 0.37] (n=15) | 6102 |
| op=relational | 0.97 [0.18, 1.00] (n=3) | 1494 |
| typ=adder | 0.40 [0.15, 0.56] (n=10) | 10215 |
| typ=ff | 0.33 [0.01, 0.82] (n=11) | 2718 |
| typ=lut | 0.18 [0.06, 0.35] (n=15) | 6567 |
| typ=other | 0.53 [0.30, 0.76] (n=2) | 150 |

Reading: the pick is made on a number that never moves, and 8 of 10 heap picks do not survive. The picks leave least in diffeq1, diffeq2 (42%, 46%) and stereovision2 (29%); in ch_intrinsics, mkPktMerge, stereovision1 and mkDelayWorker32B (shallow or hard-block designs) all or nearly all of them leave (100%, 100%, 100%, 99%). Stay by category is thin (n = designs with >= 10 such atoms): `after_hard_block` atoms (logic fed by a multiplier or a memory) stay 7% (n=5 designs); operator-view comparators (`relational`) stay 97% (n=3) and equality atoms 3% (n=5).

## P2. Capacity cuts

| measure | median [90% bootstrap] |
|---|---|
| near-critical paths (distinct) | 20 [6, 31] (n=15) |
| BLEs per path (mean) | 15.0 [4.6, 22.1] (n=13) |
| clusters touched (mean) | 3.7 [3.0, 4.3] (n=13) |
| floor, 10 BLEs per cluster (mean) | 1.9 [1.0, 2.7] (n=13) |
| floor, 20 BLEs per cluster (mean) | 1.0 [1.0, 1.6] (n=13) |
| paths above the 10-BLE floor | 98% [82%, 100%] (n=13) |
| paths above the 20-BLE floor | 100% [100%, 100%] (n=13) |
| paths of <= 10 BLEs (no hard block) that still touch >= 2 clusters | 100% [100%, 100%] (n=11) |
| extra clusters over the floor, paths of > 10 BLEs | 1.0 [0.8, 5.6] (n=7) |
| extra clusters over the floor, paths with a carry chain | 3.3 [1.1, 7.1] (n=4) |
| extra clusters over the floor, paths without | 1.1 [1.0, 2.7] (n=9) |
| distinct crossing edges | 20 [8, 33] (n=15) |

Cause of the crossing edges (earlier cluster read; share of distinct crossing edges):

| cause | median [90% bootstrap] |
|---|---|
| earlier cluster closed full | 98% [85%, 100%] (n=12) |
| not full, other atom refused (pins, status 1) | 2% [0%, 15%] (n=12) |
| not full, refused (routing, status 2) | 0% [0%, 0%] (n=12) |
| not full, queued but never taken | 0% [0%, 0%] (n=12) |
| not full, never proposed | 0% [0%, 0%] (n=12) |

42% [33%, 79%] (n=11) of the full-cluster cuts were also refused by the legalizer earlier in that cluster. What happened to the atom left behind (all of them heap atoms), as a share of all capacity cuts:

| what happened to the left-behind atom in the full cluster | share of capacity cuts |
|---|---|
| never entered the queue of that cluster | 25% [3%, 64%] (n=11) |
| queued; the picks after it all had gain >= its gain (outranked in queue order) | 21% [0%, 29%] (n=11) |
| queued; a later pick had a lower gain (it had left the queue: cleared after 30 pops, or refused) | 25% [10%, 31%] (n=11) |
| queued; no pick followed | 0% [0%, 10%] (n=11) |

(The categories do not add to 100% in the medians; per-design values are in `data/analysis/heappick.json`.)

| design | paths | clusters touched | floor10 | floor20 | over floor10 | crossing edges | full |
|---|---|---|---|---|---|---|---|
| blob_merge | 3 | 12.9 | 4.3 | 2.3 | 100% | 25 | 68% |
| boundtop | 20 | 2.0 | 1.0 | 1.0 | 100% | 20 | 100% |
| ch_intrinsics | 0 | - | - | - | - | 0 | - |
| diffeq1 | 32 | 3.3 | 2.2 | 1.4 | 89% | 37 | 97% |
| diffeq2 | 31 | 3.3 | 2.2 | 1.3 | 86% | 33 | 99% |
| mkDelayWorker32B | 1 | 3.7 | 1.0 | 1.0 | 100% | 3 | 0% |
| mkPktMerge | 20 | 1.0 | 1.0 | 1.0 | 0% | 0 | - |
| mkSMAdapter4B | 11 | 3.8 | 1.0 | 1.0 | 100% | 20 | 100% |
| or1200 | 56 | 4.3 | 4.1 | 2.8 | 20% | 26 | 74% |
| raygentop | 6 | 3.0 | 1.9 | 1.0 | 75% | 8 | 100% |
| sha | 24 | 8.6 | 3.0 | 1.7 | 100% | 47 | 86% |
| stereovision0 | 69 | 3.7 | 1.0 | 1.0 | 82% | 69 | 100% |
| stereovision1 | 0 | - | - | - | - | 0 | - |
| stereovision2 | 405 | 7.2 | 2.7 | 1.6 | 100% | 732 | 95% |
| stereovision3 | 16 | 2.1 | 1.0 | 1.0 | 98% | 11 | 100% |

Figure: `docs/figures/heap-picking/p2-visits-vs-floor.png`. Reading: the paths are not cut for want of space on the path (the floor would allow 1 to 2 clusters); they are cut where a cluster closed full, and the cluster was full of other atoms (P5). Every path of <= 10 BLEs touches two or more clusters in the median design.

## P3. Reconvergence

| measure | median [90% bootstrap] |
|---|---|
| fork atoms (>= 2 successors on near-critical paths) per design | 4 [1, 13] (n=15) |
| fork atoms: successors split between the fork's cluster and others | 67% [33%, 90%] (n=11) |
| fork atoms: all successors in the fork's cluster | 7% [0%, 26%] (n=11) |
| fork atoms: none in the fork's cluster | 31% [3%, 54%] (n=11) |
| join atoms: split | 99% [94%, 100%] (n=6) |
| crossing edges incident to a fork or join atom | 66% [26%, 83%] (n=12) |
| atoms (in clusters) on >= 2 near-critical paths | 27% [20%, 42%] (n=14) |

Reading: a shared atom can sit with only one of its paths, and mostly does. How many of the extra crossings are avoidable is not measurable from the census (the cluster that closed full could not take the other branch). The pre-pack version of the same count (atoms with >= 2 consumers on pins with pc >= 0.90) is in the catalogue.

## P4. Ties at the top of the heap

Choices = candidate picks with another molecule pending (median 1149 [474, 2153] (n=15) per design). The picked molecule is the best pending one in 99% of the choices (for the rest the census does not say why; a queue clear is one possibility). The queue-time gain differs by > 10% from the molecule gain at pick time in 3% [1%, 12%] (n=15) of the candidate picks.

| epsilon | tie rate | with a pack-heap atom among the tied (`hot`) | hot: picked less post-route-critical than a heap competitor | hot: picked more critical | picked = earliest queued | hot ties per design |
|---|---|---|---|---|---|---|
| exact | 35% [29%, 45%] (n=15) | 1% [0%, 21%] (n=15) | 20% [2%, 57%] (n=12) | 15% [3%, 25%] (n=12) | 98% [96%, 100%] (n=15) | 4 [1, 24] (n=15) |
| 1% | 54% [49%, 58%] (n=15) | 5% [2%, 21%] (n=15) | 13% [7%, 32%] (n=15) | 19% [6%, 25%] (n=15) | 89% [84%, 90%] (n=15) | 55 [8, 120] (n=15) |
| 5% | 60% [54%, 70%] (n=15) | 9% [4%, 26%] (n=15) | 23% [9%, 44%] (n=15) | 14% [7%, 19%] (n=15) | 82% [71%, 87%] (n=15) | 58 [23, 120] (n=15) |

Source of the picked molecule in exact ties (pooled over designs): conn/timing 15522, high fanout 1308, ram 5769, transitive 25158. Ties at gain zero: median share 0%.

Figure: `docs/figures/heap-picking/p4-ties.png`. Reading: ties are common (a third of the picks are exact ties, source mostly transitive or connectivity); they are resolved by the order in which the molecules entered the queue (within the sinks of one net, the atom-id scan order of `packer/README.md`). Ties that involve the pack-time heap are rare; on those the picked molecule is the less post-route-critical one somewhat more often than the more critical one, with overlapping intervals. The per-design counts of `hot` ties are small (the median design has 4 exact and 55 within 1%), so the intervals are wide.

## P5. Filler

| measure | median [90% bootstrap] |
|---|---|
| clusters holding a post-route heap atom, share of all clusters | 17% [12%, 24%] (n=15) |
| FLEs of those clusters that hold no heap atom | 70% [64%, 74%] (n=14) |
| heap FLEs per such cluster (of 10) | 2.5 [2.2, 3.1] (n=14) |
| heap clusters / minimum clusters for the heap FLEs | 3.6 [3.0, 4.0] (n=14) |
| capacity cuts whose full cluster still holds a non-heap FLE | 100% [67%, 100%] (n=11) |

Where the non-heap atoms of the heap clusters came from (pooled over runs): conn/timing 18086, high fanout 224, seed 10796, transitive 4042 atoms. So the filler is not unrelated clustering (not one atom): it is ordinary connectivity and timing candidates, the seed of the cluster, and transitive atoms; the packer fills a cluster with the best-gain neighbours, and for most heap atoms those neighbours are not heap atoms. "Went to non-heap atoms" is true of 70% of the slots; "a heap atom refused later for lack of space" is measured by the capacity cuts of P2 (every cut at a full cluster that still holds a non-heap FLE, which is the typical case here).

## P6. Max over pins

| measure | median [90% bootstrap] |
|---|---|
| pack-heap atoms (>= 2 input nets) with a single critical pin | 6% [1%, 18%] (n=15) |
|   of those, in the post-route heap | 23% [0%, 43%] (n=12) |
| pack-heap atoms with >= 2 critical pins, in the post-route heap | 29% [13%, 45%] (n=14) |
| AUC of the best pin crit for post-route heap membership | 0.93 [0.86, 0.95] (n=15) |
| AUC of the mean pin crit | 0.84 [0.82, 0.93] (n=15) |
| timing-gain >= 0.90 picks with all own pins < 0.50 (inherited) | 10% [0%, 25%] (n=15) |
|   of those, in the post-route heap | 4% [0%, 17%] (n=9) |
| timing-gain >= 0.90 picks with an own pin >= 0.90, in the post-route heap | 14% [6%, 17%] (n=15) |
| inherited picks per design | 3 [0, 12] (n=15) |

Reading: the best pin predicts the post-route heap well (AUC 0.93), better than the mean over pins, so the max rule is not the weak point; the weak point is that criticality is pre-pack, not that it is a maximum. The inheritance case is small in count and the intervals reach 0.

## P7. High-fanout critical nets

| measure | median [90% bootstrap] |
|---|---|
| near-critical nets per design | 39 [27, 83] (n=15) |
| near-critical nets above the pack threshold (32 sinks) | 0.0% [0.0%, 0.2%] (n=13) |
| near-critical edges on such nets | 0.0% [0.0%, 0.2%] (n=13) |
| near-critical nets with > 16 sinks | 0.8% [0.0%, 1.6%] (n=13) |
| near-critical nets with > 8 sinks | 1.6% [0.0%, 6.7%] (n=13) |
| baseline: driver atoms with a net above 32 sinks | 0.6% [0.3%, 1.3%] (n=15) |

Near-critical nets with more than 8 sinks (seed 1; source text from the VTR benchmark):

| design | sinks | atom | HDL line | HDL text | atom kind (block view / operator view) |
|---|---|---|---|---|---|
| blob_merge | 18 | ff | blob_merge.v:254 | `always@(posedge clk) begin` | fsm / none |
| blob_merge | 12 | adder | blob_merge.v:1520 | `diff5 = dividend_copy4 - divider_copy4;` | mux / adder |
| blob_merge | 12 | adder | blob_merge.v:1535 | `diff6 = dividend_copy5 - divider_copy5;` | mux / adder |
| blob_merge | 11 | adder | blob_merge.v:1551 | `diff7 = dividend_copy6 - divider_copy6;` | mux / adder |
| blob_merge | 10 | adder | blob_merge.v:1489 | `diff3 = dividend_copy2 - divider_copy2;` | mux / adder |
| blob_merge | 9 | adder | blob_merge.v:1505 | `diff4 = dividend_copy3 - divider_copy3;` | mux / adder |
| boundtop | 64 | lut | - | `` | mux / none |
| mkSMAdapter4B | 31 | lut | mkSMAdapter4B.v:1372 | `wci_respF_c_r != 2'b10 && wci_reqF__EMPTY_N &&` | mux / mux |
| or1200 | 25 | ff | - | `` | register_word / none |
| or1200 | 19 | ff | or1200.v:3227 | `always @(posedge clk ) begin` | register_word / none |
| raygentop | 9 | ff | raygentop.v:2711 | `always @(posedge clk)` | register_word / none |
| sha | 32 | lut | sha.v:127 | `assign SHA1_f1_BCD = (B & C) ^ (~B & D);` | logic / mux |
| sha | 15 | ff | sha.v:148 | `always @(posedge clk_i)` | fsm / none |
| stereovision0 | 29 | ff | stereovision0.v:1191 | `always @(posedge clk)` | register_word / none |
| stereovision0 | 17 | lut | stereovision0.v:887 | `if ((horiz <= x_reg_r) & (horiz >= x_reg_l) & (vert <= y_reg_dn) & (vert >= y_reg_up))` | fsm / relational |
| stereovision0 | 13 | lut | stereovision0.v:3301 | `if (res_2_5 > res_2_6)` | register_word / relational |
| stereovision0 | 12 | lut | stereovision0.v:3229 | `if (res_1_1 > res_1_2)` | register_word / relational |
| stereovision0 | 11 | lut | stereovision0.v:3187 | `if (d_in12 > d_in13)` | register_word / relational |
| stereovision3 | 12 | ff | stereovision3.v:1029 | `always @(posedge tm3_clk_v2)` | counter / none |
| stereovision3 | 11 | ff | stereovision3.v:1029 | `always @(posedge tm3_clk_v2)` | counter / none |

Reading: nets above 32 sinks are ignored by the packer's gain and are essentially never on a near-critical path (median 0%; the one exception is the 64-sink write enable of boundtop). The constructs on the nets of 9 to 32 sinks are decision bits: a comparison (`if (a > b)`), the borrow of a subtract that selects the quotient bit (blob_merge `diffN = dividend - divider`), state registers of an `always @(posedge clk)` block and enables. They are below the high-fanout threshold, so the packer treats them as ordinary nets.

## P8. Harmful HDL grouping candidates

Words: `odin` = word of an atom in a reported path (Odin III attribution; only a sample of the design's words, 36 of >= 8 atoms), `port` = a top-level bus of >= 8 bits and the logic atoms next to its pad bits (the same bus can appear in both). The Odin III word attribution is not available for the whole design in the kept data, and every design is one module after flattening, so the module level and the full word level are not measurable here. Tie share: over all pairs of the word's atoms (or 4000 sampled pairs): *flow* = a net joins the pair or one atom sits between them; *any* = flow or a common source or sink. Nets above 32 sinks do not count (as in the packer).

| source | words | flow share < 1% | any share < 5% | median pairs in one cluster | median clusters / minimum | words with flow share >= 10% |
|---|---|---|---|---|---|---|
| odin | 36 | 100% | 92% | 12% | 3.0 | 0 |
| port | 129 | 88% | 81% | 6% | 4.0 | 4 |
| all | 165 | 91% | 83% | 7% | 3.8 | 4 |

Relation to P2 to P5: 25 of the 165 words hold a post-route heap atom; their flow share is 0.00 (median), the same as the others; Spearman(flow share, heap rate) = -0.06, Spearman(flow share, pairs in one cluster) = 0.27. Words that are tied by dataflow:

| design | word | bits | flow share | pairs in one cluster | atoms |
|---|---|---|---|---|---|
| stereovision1 | in:offchip_sram_data_in | 14 | 0.25 | 0.35 | {'lut': 14} |
| diffeq1 | in:DXport | 32 | 0.12 | 0.50 | {'adder': 32} |
| diffeq2 | in:dxport | 32 | 0.12 | 0.50 | {'adder': 32} |
| or1200 | out:dcpu_adr_o | 32 | 0.12 | 0.50 | {'adder': 32} |
| or1200 | in:dcpu_dat_i | 42 | 0.07 | 0.14 | {'lut': 42} |
| raygentop | out:rgStat | 32 | 0.06 | 0.30 | {'ff': 31, 'lut': 1} |
| stereovision0 | in:x_in | 29 | 0.06 | 0.25 | {'adder': 13, 'ff': 16} |
| stereovision0 | in:y_in | 29 | 0.06 | 0.29 | {'adder': 13, 'ff': 16} |

Figure: `docs/figures/heap-picking/p8-word-ties.png`. Reading: the bits of a word are, in dataflow terms, parallel lanes: 9 of 10 words have under 1% of their bit pairs tied, and the stock packer already scatters them (median 7% of pairs in one cluster). The tied words are the adder words (carry chain: a 32-bit adder word has 12% of its pairs tied by the chain, and the stock packer puts 50% of its pairs in one cluster, the highest in the data). Grouping a word as a unit (word-major) is therefore a bet against what the dataflow says for the common word; it is the carry-chain words where grouping agrees with the dataflow.

## The exception HDL pattern catalogue

Detectors use only data that exist before packing: the BLIF netlist (nets, fan-out, LUT levels, carry chains), Odin III provenance (HDL construct kinds, top-level buses, source lines) and the pre-pack criticality (VPR's own static timing analysis, `pre_pack.report_timing.setup.rpt`; here read from the census `P` records). Frequency = designs of the 15 with at least one instance and the size where it matters. Every hint is UNTESTED.

| # | pattern and HDL shape | detector (exact rule) | frequency in the 15 designs | what greedy does with it (evidence) | implied packer hint (UNTESTED) |
|---|---|---|---|---|---|
| 1 | **Parallel bus word**, word-major trap. `reg [31:0] q; always @(posedge clk) q <= d;` bit i depends on bit i of another word only | a bus (top-level port `name[i]` or Odin word) of >= 8 bits whose logic atoms have < 1% of their pairs tied by flow (sampled pairs, nets > 32 sinks ignored) | 91% of 165 words, in 13 designs | stock packing already splits them (median 7% of pairs together, 3.8x the minimum clusters); no relation of tie share to heap membership (P8) | do not group the word; group by bit slice (bit i of the word with its next-stage bit i) |
| 2 | **Carry-chain adder word** (the aligned case). `assign s = a + b;` 32 bits | >= 8 adder cells chained cin to cout in the BLIF | 11 of 15 designs; median 2 [1, 4] (n=15) chains, 1.5% [0.1%, 3.9%] (n=15) of the logic atoms | adder words are among the most tied words (32-cell word: 12% of pairs, 50% already in one cluster; P8); pack-heap chain atoms stay 49% [0%, 75%] (n=6); paths with a chain are cut 3.3 [1.1, 7.1] (n=4) clusters over the floor, others 1.1 [1.0, 2.7] (n=9) | group the word as a unit, start the chain at a cluster boundary, expect one cut per 20 adders |
| 3 | **Fork atom with divergent critical branches**. `x = f(a); y = g(x); z = h(x);` two critical consumers of one atom | atom with >= 2 distinct consumers on pins with pc >= 0.90 (pre-pack) | 13 of 15 designs; median 40 [12, 132] (n=15) atoms | post-route: successors split in 67% [33%, 90%] (n=11) of the forks, 66% [26%, 83%] (n=12) of the crossing edges are at a fork or join atom; pre-pack detector outcome: split 57% [43%, 89%] (n=13), all together 20% [5%, 32%] (n=13), none 5% [3%, 26%] (n=13) | keep the fork atom with the consumer of larger downstream depth (more LUT levels to the endpoint); accept the cut on the other branch |
| 4 | **Capacity cut at a cluster filled by non-heap atoms**. any path longer than the room left in its cluster | generic, not an HDL exception: a pre-pack-critical (pc >= 0.90) path of >= 2 BLEs (every design has some) | post-route: paths above the floor 98% [82%, 100%] (n=13); 98% [85%, 100%] (n=12) of cuts at a full cluster; 70% [64%, 74%] (n=14) of FLEs in heap clusters are non-heap | fills the cluster with best-gain neighbours (connectivity, transitive); heap atoms of the next path element are not reserved room | reserve slots: stop adding non-critical candidates while a pc >= 0.90 successor of an atom in the cluster is pending |
| 5 | **Decision-bit fan-out**. `if (a > b) w <= x; else w <= y;`, `diff = d - q; if (diff[31]) ...`, a state or enable bit steering a word | net of 9 to 32 sinks (below the packer's 32) whose driver is a relational operator, an adder carry-out, or a register, and with a pre-pack-critical sink pin | 8 of 15 designs have a pre-pack-critical net of 9 to 32 sinks (1 [0, 8] (n=15) per design, median); 24 near-critical post-route nets in 7 designs; drivers (pre-pack-critical nets, seed 1): adder 13, equality 3, mux 16, other 2, reg 102, relational 20 | treated as an ordinary net (below the 32-sink threshold); what the packer does with their sinks is not measured here, only that they are on near-critical paths | pull the sinks of a decision bit into the driver's cluster in criticality order |
| 6 | **Very-high-fan-out control** (> 32 sinks): enable, reset, select of a wide word | net with > 32 sinks | 17 [7, 22] (n=15) nets per design (clocks, resets, enables); pre-pack critical in 5 designs; post-route near-critical: 1 net (boundtop `tm3_sram_we`, 64 sinks) | ignored by the gain (`> high_fanout_threshold`); used only as a tie-break when the queue is empty | group its sinks by bit slice; low priority (rare) |
| 7 | **Deep non-adder cone** (longer than a cluster). a chain of > 10 LUT levels | combinational LUT level >= 11 on a non-adder atom (adders count once per chain) | 1 of 15 designs (blob_merge: 1137 atoms, max level 22; all others <= 7) | in blob_merge 56 pack-heap atoms are deep, 9 post-route heap; paths of > 10 BLEs are cut 1.0 [0.8, 5.6] (n=7) clusters over the floor | expect >= ceil(depth/10) - 1 cuts; place the cuts on the lowest-fan-out nets |
| 8 | **Hard-block-fed logic**. `p = a * b; r <= p + c;` logic after a multiplier or memory output | logic atom with an input net driven by a hard block (multiplier, memory) | 10 of 15 designs; 7.4% [0.0%, 12.8%] (n=15) of the logic atoms (median) | pack-heap atoms of this kind stay in the post-route heap 7% [0%, 50%] (n=5); the pre-pack delay model charges every net hop the same, hard blocks included | discount pc for paths through a hard block; do not spend heap picks on them |
| 9 | **Timing gain inherited from a sibling sink**. an atom that drives a net with one critical and several non-critical sinks | atom picked with timing gain >= 0.90 and all own input pins < 0.50 (census), predictable pre-pack: driver of a net whose largest sink crit >= 0.90 and whose connecting sink crit < 0.50 | 10% [0%, 25%] (n=15) of picks made on a high timing gain (median; 3 [0, 12] (n=15) picks per design; the detector here is the census outcome, its pre-pack form is not counted); stay 4% [0%, 17%] (n=9) against 14% [6%, 17%] (n=15) | `update_timing_gain_values` takes the largest crit over all sinks of the net (INPUT case) | use the crit of the pin that connects to the cluster instead of the maximum over the net |
| 10 | **Equal-criticality sibling set / tie-prone fan-out**. bit-parallel logic fed by one net | net with >= 3 sinks of identical pc >= 0.90 (within 0.001) | 6 of 15 designs have one; exact ties on 35% [29%, 45%] (n=15) of the picks in general | tie broken by queue order (98% [96%, 100%] (n=15)); on hot exact ties the pick was lower post-route than a heap competitor 20% [2%, 57%] (n=12), higher 15% [3%, 25%] (n=12) of the time (intervals overlap) | tie-break by downstream depth; weak evidence, low priority |
| 11 | **Collector or status register**. `always @(posedge clk) status <= {a, b, c};` read only at a pad | flip-flop whose output feeds no logic atom (only pads) | 6 of 15 designs; median 0 [0, 40] (n=15) per design (0.0% [0.0%, 0.5%] (n=15) of flip-flops) | measured non-problem: collector flip-flops are in the post-route heap 0% [0%, 33%] (n=6) of the time (n designs with one: 6) | none needed; use as cluster filler (UNTESTED) |

Rows 1, 3, 4, 5, 8 and 9 are the patterns with a measured effect on the pick or the cut; rows 6, 10 and 11 are measured non-problems or rare; rows 2 and 7 describe a case the data show only in a few designs. "Frequency" counts the designs of the keep sweep, which are the VTR Verilog benchmarks; it says nothing about other design families.

## Candidate hypotheses (untested)

Each names the purpose (speed, wirelength; Norns packing RQs, no RQ ID is given in the brief) and the measure. None has been run.

1. **Refresh criticality while packing.** The packer's pc never moves (P1); a timing update after every N clusters (or using the post-route heap of a first pass) raises the share of heap picks that stay above the 23% [11%, 45%] of the heap lane. Measure: stay rate, CPD. Needs VPR runs (the analytical-placer flow already calls the update).
2. **Reserve room on the path.** 98% of the cuts are capacity cuts in clusters that are 70% non-heap (P2, P5): hold FLEs open for a pending pc >= 0.90 successor. Measure: clusters touched per near-critical path against the floor, CPD.
3. **Keep the fork atom with the deeper branch** (row 3): a rule on the 57% to 67% of forks that split. Measure: crossings at fork atoms, CPD.
4. **Do not group parallel words** (row 1): 9 of 10 words have no dataflow between bits; compare word-major affinity against bit-slice affinity on the buses with flow share < 1%, and word-major on carry-chain words only. Measure: WL and CPD per word class.
5. **Use the connecting pin's crit** instead of the maximum over the net's sinks (row 9). Measure: stay rate of timing-gain picks.
6. **Pull decision-bit sinks to the driver** (row 5). Measure: crossings on 9 to 32-sink near-critical nets.
7. **Discount paths through hard blocks** in the pre-pack criticality (row 8): the 7% stay of logic after a multiplier or memory suggests the pre-pack model overcharges them. Measure: stay rate, CPD on diffeq and stereovision.
8. **Tie-break by downstream depth** (row 10); expected effect small (ties with the heap are few).

## What could not be measured

* Whether a cut was avoidable: the census records the candidates the packer proposed, not the ones it could have; a counterfactual needs a packer run.
* Words beyond the sample: the Odin III word attribution exists only for atoms in a reported path (36 words of >= 8 atoms), and the word membership files of the earlier rounds are not kept; the port buses stand in for the rest. Modules: one per design.
* Ties: the heap order is reconstructed from queue-time gains in the census; the census does not mark a queue clear (after 30 pops), so 1% of the picks ("not top") cannot be replayed.
* Source line text of near-critical nets is available only for atoms with a provenance line; one net (boundtop `tm3_sram_we`) has none.
* Paths: only the 1000 reported paths enter (so a deeper but unreported path can exist); designs with few near-critical paths (ch_intrinsics, mkPktMerge, stereovision1: 0 to 20) give thin P2 and P3 numbers.
* No VPR run was made; hypotheses 1 to 8 all need packer runs.

