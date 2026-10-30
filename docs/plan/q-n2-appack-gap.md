# Q-N2: what is APPack bad at? Where and why the stock clusters depart from the known clustering C (plan written 2026-10-30, before the analysis)

This file is committed and pushed before any number of this analysis is computed. It is not edited after the analysis; results are appended
below under their own dated heading. It is a MEASUREMENT (no hypothesis, no verdict word beyond "measurement"). No VPR run is made: the
analysis reads the census, the known clustering and the packed `.net` of the existing round 9 runs (read only).

## Plain-English summary

Peter (2026-10-30): "I think we stay with our AAPack questions (as we are going now) that is what is AAPack bad (TpekoCluster as gap and how
to make it better) at and is there a way to make it better." This entry answers the first half only: WHERE and WHY the clusters of VPR's
default packer (APPack, the analytical-flow form of AAPack) depart from the known clustering C. "How to make it better" is the next
question and "what is a good way forward from the clustering" is a separate later one; neither is touched here.

On the 33 round 9 designs stock VPR needs about 10 percent more CLBs than the known clustering (stock / N_C 1.103 corrected). The
packer logged every decision it made (which molecule it added to which cluster, what else was waiting in its candidate queue with what gain,
what it refused, when it closed a cluster). We replay that log against C. For every cluster VPR built we ask: did its seed start a fresh
cluster of C or a leftover piece of one (a); did it add a molecule from another cluster of C while a member of the seed's own cluster of C
was waiting in the queue (b) or was not even a candidate (c); did it close with room left and members of the seed's cluster still unpacked
(d); did it close full with members still unpacked (e). Then we hand out the CLB gap to these five kinds by one stated rule, and report
the share of each, per design and pooled. Where the data allow, we also say how much of the extra wire cut and of the extra near-critical
crossings comes from each kind. The answer is a list of the two or three kinds of mistake that carry most of the gap, each with numbers
and an example cluster. Possible fixes are listed as untested ideas only.

Purpose (hub docs/purpose.md): Norns, packing quality; path purpose "good centroids from the design via good packing". Research question
N Q1.6 (room in the packer), after Q-N1b. Measure: share of the stock-versus-C gap (CLBs; where possible wire cut and near-critical
crossings) attributed to each kind of packing decision. Metrics are reported in Peter's order: speed (near-critical crossings), wirelength
(nets cut), area (CLBs).

## Data (read only, nothing is re-run)

* `work/r9-out-v2/<design>/<own|foreign>/sh<k>/census.tsv`: stock pack census (Norns binary, no affinity, `--norns_pack_census`; records M, A,
  P, Q, F, K, see packer/README.md) for the 33 designs, own and foreign C, shuffles 0 to 3 = 264 packs.
* `.../sh<k>/affinity.tsv`: the known clustering C (atom, cluster id), dummy atoms included. `.../sh<k>/design.blif`: the shuffled D'.
* `.../sh<k>/run-*/stock.s1/design.net`: the packed netlist of the stock pack (FLE slots per CLB). Corrected N_C (Kc) from `data/r9/full-summary.json`.
* Flat atom positions: `final.flat_place` exists per stock run but it is the position after the whole flow, not the global-placement positions
  APPack used while packing; the attenuation by distance is therefore NOT measurable from the logs. Reported as not measured. No rerun is made.
* The Q-N1b oracle logs (`work/n1b-out`) are used only for the cross-check of what the true seed oracle left unrebuilt, if time allows.

## Decision taxonomy, as computed

Unit = molecule (the packer's unit: a LUT with its flip-flop, an adder chain piece); its C cluster = the label of its atoms (root atom). Weight =
FLE slots it takes in the `.net`. For every stock logic cluster s: c0 = C cluster of its seed. A molecule of c0 is *free* at a time if no earlier
cluster, and no earlier step of s, holds it, and it fits the free FLE slots of s.

* (a) seed: s is seeded in a C cluster that is already open (one of its molecules sits in an earlier stock cluster), i.e. s is a leftover piece of a split C cluster.
* (b) wrong add: s adds a molecule of another C cluster while at least one free member of c0 is waiting in its candidate queue (a `Q` record not yet taken
  or refused). Recorded: the rank of the best waiting member by queue-time gain, whether its gain equals the pick's (a tie, to 1e-6 relative), the gain
  ratio, the candidate source of the pick.
* (c) missing candidate: as (b) but no free member of c0 is in the queue. Reason, from the netlist at that moment (nets with more than 32 sinks are not
  used by the packer's connection search): c1 no net to the cluster, c2 only through a net with more than 32 sinks, c3 directly connected
  (nets of at most 32 sinks) but not queued (cut by the queue cap or APPack's distance threshold; not separable without the positions), c4 refused earlier in s
  (an `F` record), c5 two hops only, c6 the pick was an unrelated-clustering pick (no connection candidate existed).
* (d) early close: s closes with free slots left and a free member of c0 that would fit. Closing reason from the census: refused pins (`F` status 1)
  or refused routing (status 2) after the last add, no candidate at all, queue not empty at close (a repeated pick ends the growth).
* (e) capacity cut: s closes full and members of c0 remain with no foreign molecule in s and a fresh seed; split into construction artefact (the
  FLE demand of c0 in the `.net` exceeds 10) and real (it does not).

Also counted but not a mistake: *filler* adds (a molecule of another C cluster when no free member of c0 exists).

## Attribution of the CLB gap (the rule, stated before the numbers)

Per run, S = stock logic CLBs, T = FLE slots used by them, u_s = 10 - FLE(s). Then S - T/10 = sum over clusters of u_s/10 exactly (the CLBs lost
as empty slots); the gap to the corrected N_C is S - Kc = sum u_s/10 + (T/10 - Kc), the last term a small accounting residual (reported as its own row).
Each non-full cluster hands its u_s/10 to ONE kind, by the first of these that holds on the timeline of that cluster: (b) or (c), by the
kind of its first wrong add that displaced a free member of c0; else (d) or (e) at its close (when members of c0 remain); else (a) when its seed was a leftover
piece (it is a pure piece of a split C cluster, no deviation of its own); else (x) *tail/other* (c0 fully packed or nothing left to pack). A full cluster hands
over nothing: the damage of a wrong add made in a full cluster appears as a leftover piece elsewhere and is charged there, under (a); to say what split
that piece, every (a) share is subdivided by the kind of the pick that took the other members of c0 away (b, c, d, e, seed, filler, unrelated), weighted by the molecules.
Pooling: per design the mean over its 4 shuffles, then median, 10th and 90th percentile over designs (CAD reporting, sorted per-design table), and
the pooled share (sum of the per-design CLB amounts). Splits: VTR Verilog designs against MCNC (the 15 keep-sweep VTR designs against the rest of the
33), own against foreign C.

## Speed and wirelength (where the data allow)

* Speed: pack-time criticality of an input pin (`P` records, VPR's own timing analysis before packing). A near-critical edge = pc >= 0.90, from the driver atom to
  the sink atom. An *extra crossing* = the edge crosses stock clusters but not C clusters. Counted per kind of the pick that put the sink or the driver away from
  its C cluster. Post-route criticality of atoms in wrong clusters is not joined (needs the timing report per run; stated limit).
* Wirelength: nets cut. A net is *extra cut* if it touches more stock clusters than C clusters (pads and hard blocks count as their own cluster in both). Attributed to the
  kinds of the displaced atoms on it.

## What this cannot show

The census is a log of one stock run; it does not say what the packer would have done after a different choice (a counterfactual needs a run, and none is made).
A leftover piece is charged to its own timeline; the causal chain is approximated by the subdivision of (a). Whether a free member of c0 would have been *legal* in the cluster
(pins, routing) is judged only by slot count and the `F` records. Distance attenuation is not measured. N_C(corrected) is the bound, so the clma gap
(100 CLBs against 56) is large and is shown with and without clma.

## Results, 2026-10-30 (measurement; no VPR run was made)

Plain English first. Where does the 10 percent extra CLB count of stock VPR come from? We replayed the packer's own decision log for 33 designs
(own and foreign known clustering C, 4 shuffles each, 264 packs; `scripts/q2gap.py`, `scripts/q2pool.py`, `data/q2/summary.json`) against C.
The gap is mostly a few CLBs per design lost as half-empty clusters (stock CLBs 1.07 times N_C at the median design, 10th to 90th percentile
1.03 to 1.17). Followed back to the decision that made each half-empty cluster, **about 60 percent of the gap (66 percent without clma) comes from one
thing: the packer picks an atom of another known cluster although a legal atom of the seed's own known cluster is waiting in its queue, with a
strictly lower queue gain.** In 99.8 percent of these picks the right atom's gain is strictly lower, not tied (ties 0.14 percent), on average 0.46 of the
pick's gain. The next carries 11 percent (24 percent on the VTR Verilog designs, 0.3 percent on the MCNC designs): the cluster closes with free slots
because the remaining candidates are refused for input pins. Smaller: leftover refilling (14 percent), a right atom never offered because it is only
two hops from the cluster (6 percent). A capacity cut (closed full while the known cluster is larger than what fits) never occurs. What this
cannot tell: whether a better rule would keep the right atoms together (that is the next question); distance attenuation of APPack is not
measured (no global-placement positions were logged; the post-flow `final.flat_place` is a different placement, and no rerun was made).

What was measured. Per stock logic cluster s, c0 = known cluster of its seed. Rule (stated in the plan before the numbers): each non-full cluster hands its lost
slots (10 minus FLEs used; summed over clusters, divided by 10, they are the stock CLBs minus FLE demand/10 exactly) to the first deviation on its own timeline: a
wrong add (b or c), else a close with free slots and free members of c0 (d or e), else (a) a leftover piece of an already split known cluster, else (x). The leftover pieces
(a) are then handed back to the kind of pick that took the other members of c0 away (the "root-cause" view, the headline). Accounting residual (T/10 minus N_C(corrected)):
-1.5 percent of the gap.

| share of the CLB gap | first deviation (own timeline) | root cause (headline) | root cause, clma left out | per design median [10th, 90th] (root) | VTR Verilog, pooled | MCNC, pooled | own C | foreign C |
|---|---|---|---|---|---|---|---|---|
| b wrong add, right atom queued | 0.149 | 0.603 | 0.656 | 0.78 [0.26, 0.88] | 0.488 | 0.702 | 0.611 | 0.593 |
| c wrong add, right atom not a candidate | 0.025 | 0.063 | 0.069 | 0.045 [0.00, 0.14] | 0.083 | 0.046 | 0.062 | 0.065 |
| d early close, free slots, free members | 0.100 | 0.114 | 0.125 | 0.00 [0.00, 0.44] | 0.242 | 0.003 | 0.114 | 0.114 |
| e capacity cut | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| filler (picks after c0 was already used elsewhere) | n/a | 0.136 | 0.149 | 0.127 [0.06, 0.29] | 0.191 | 0.089 | 0.133 | 0.139 |
| a leftover piece (first-deviation view only) | 0.642 | (handed back) | | | | | | |
| x other (clma 40 slots; tails) | 0.099 | 0.099 | 0.015 | 0 [0.00, 0.09] | 0.018 | 0.169 | 0.092 | 0.107 |

Pooled over 66 design/construction sets, gap 956 CLBs (mean of 4 shuffles each), 12832 stock clusters. Per design (own and foreign together) sorted by stock/N_C:
The table is in `data/q2/summary.json` (`per_design_sorted_by_stock_over_Kc`); the top rows: clma 1.78 (gap 87, 93 percent x), diffeq2 1.21 (d 0.53),
ch_intrinsics 1.19, mkDelayWorker32B 1.17, ex1010 1.15 (b 0.83), apex2 1.14 (b 0.89), diffeq1 1.13, or1200 1.13; the lowest: dsip 1.02, boundtop 1.02, alu4 1.02.
Design kinds differ: on the MCNC logic the gap is b (median design 0.84), on the VTR Verilog designs with carry chains and wide logic it is b (0.43) and d (0.28).

Failure kinds, with numbers (sums of per-design means over the 66 sets) and one example each.

1. **b, wrong add with the right atom queued** (26214 picks; 99.84 percent with a strictly lower queue gain for the right atom, tie 0.14 percent, higher 0.02 percent; the right
   atom is first among the remaining queue in 22.7 percent, not first in 77.3 percent; mean gain ratio right/pick 0.463). The right atom shares at least as many nets with the cluster
   as the pick in 63 percent of the picks, so net count alone does not explain the order. Not explained by: stale queue gains (the right atom gained a connection after it was
   queued in 0.03 percent), a bigger pick molecule (pick has more atoms in 17 percent, fewer in 14 percent), timing pull (pick timing gain >= 0.9 in 17 percent). All 26214 are
   connection-or-timing candidates (source 1). Example: apex2, own C, shuffle 1, cluster 1 (seed in known cluster 21): pick n487791548 (known cluster 95, queue gain 0.1907) over
   n136484765 (known cluster 21, 0.1823, second in the queue); later n707140040 (known cluster 95, 1.391) over n138998098 (known cluster 21, 0.190, fifth of 41).
2. **d, early close at the pin limit** (1013 closes; 98.5 percent after refusals for input pins (`F` status 1), 1.5 percent no candidate; the free member of c0 had been refused
   earlier in the same cluster in 65 percent, was still queued at close in 31 percent, was never a candidate in 4 percent). Example: diffeq2, own C, shuffle 1, cluster 15 (seed
   molecule of 40 atoms, a carry chain, plus three 2-atom molecules): 8 of 10 FLEs used, 63 refusals for pins (status 1), 5 free members of known cluster 4. Same cluster in sha (cluster 19): 9 FLEs,
   2 free members, refused earlier.
3. **filler, then c** (filler picks 19997, a consequence of a split known cluster; c events 1988: right atom only two hops away 77 percent, refused earlier 8 percent, direct net but not
   queued 5 percent (queue cap or distance, not separable), no net 5 percent, only through a net of more than 32 sinks 5 percent). Example c: mkPktMerge, own C, shuffle 1, cluster 19 (seed
   in known cluster 3): picks of known cluster 0, 7 free members of known cluster 3 with no net to the cluster (c1), closes at 5 FLEs by pins.
4. Seeds: the seed is in the cluster's majority known cluster for 72 percent of the 12832 clusters; 23 percent of the stock clusters are pure (one known cluster); leftover pieces (a) are
   0.56 per stock cluster. This agrees with Q-N1b (25.5 percent of clusters rebuilt exactly with the best seed).

Speed and wirelength (where the data allow; the kinds here are those of the displaced atoms on the net or edge, not the first-deviation rule).
* Speed. Near-critical edges (pack-time criticality >= 0.90, VPR's own pre-pack analysis): 28682; 55.1 percent cross stock clusters against 50.4 percent crossing known clusters (per design
  ratio median 1.084 [0.965, 1.326]). Edges crossing stock but not C: 3399 (11.9 percent of the near-critical edges): b 58.7 percent, a (leftover pieces) 28.3 percent, filler 8.4 percent,
  seed 3.0 percent, c 1.5 percent. So the wrong adds of kind b also cause most of the extra near-critical crossings. Post-route criticality of atoms in wrong clusters is not joined (not measured).
* Wirelength. Nets cut: stock 111958 against C 84544 (per design median ratio 1.334 [1.113, 1.756]; the round 9 stock/exact wirelength was 1.32). Gross extra cut (nets touching
  more stock than known clusters): b 33.0 percent, a 28.7, filler 26.9, seed 8.5, c 2.4, other 0.4. The cut ratio is a count, not wirelength; the equality of the two numbers is not a measurement of cause.
* Area: the table above.

Limits. The census gives the queue-time gain, so "gain strictly lower" is the queue order VPR used. Legality of the right atom in the cluster is judged by free slots and the refusals
logged, not by a trial. 109 clusters (of 12832 x 4 sets) have a molecule-weight sum different from the `.net` FLE count (chain molecules); the `.net` count is used for the waste. s38584.1 and
all other designs are in; clma is shown with and without. UNTESTED ideas (no run made, for the next question): (i) rank candidates by the sum of connection to the cluster rather than the VPR
molecule gain; (ii) keep atoms of the same HDL word or provenance group together as a gain term (the Norns affinity arm already does this and reaches 0.82 to 1.00 purity with C); (iii) when a cluster is
refused for pins with free slots, try the free atoms that add fewer new input nets; (iv) hold back a candidate from another group while a group member is queued. Verdict word: MEASUREMENT.

Code and data: `scripts/q2gap.py`, `scripts/q2pool.py`, `tests/test_q2.py`, `data/q2/summary.json`. Per-pack outputs are kept outside the repository (`work/q2-out/runs5`).

Per-design table (own and foreign C together, root-cause shares of the CLB gap, sorted by stock/N_C corrected):

| design | kind | stock/N_C | gap (CLBs) | b wrong add | c missing | d early close | filler | x other |
|---|---|---|---|---|---|---|---|---|
| clma | MCNC | 1.777 | 87.0 | 0.07 | 0.00 | 0.00 | 0.01 | 0.93 |
| diffeq2 | VTR | 1.214 | 13.2 | 0.23 | 0.00 | 0.53 | 0.25 | 0.00 |
| ch_intrinsics | VTR | 1.188 | 4.5 | 0.28 | 0.20 | 0.44 | 0.08 | 0.00 |
| mkDelayWorker32B | VTR | 1.165 | 29.5 | 0.47 | 0.20 | 0.17 | 0.09 | 0.12 |
| ex1010 | MCNC | 1.146 | 92.2 | 0.83 | 0.08 | 0.00 | 0.08 | 0.00 |
| apex2 | MCNC | 1.137 | 30.8 | 0.89 | 0.05 | 0.00 | 0.06 | 0.00 |
| diffeq1 | VTR | 1.130 | 10.8 | 0.31 | 0.05 | 0.36 | 0.28 | 0.00 |
| or1200 | VTR | 1.129 | 78.5 | 0.53 | 0.04 | 0.30 | 0.12 | 0.02 |
| seq | MCNC | 1.121 | 23.8 | 0.86 | 0.08 | 0.00 | 0.06 | 0.00 |
| apex4 | MCNC | 1.112 | 22.2 | 0.88 | 0.04 | 0.00 | 0.07 | 0.08 |
| pdc | MCNC | 1.111 | 49.5 | 0.86 | 0.08 | 0.00 | 0.06 | 0.00 |
| spla | MCNC | 1.103 | 33.5 | 0.83 | 0.07 | 0.01 | 0.08 | 0.00 |
| stereovision3 | VTR | 1.092 | 4.2 | 0.46 | 0.01 | 0.24 | 0.34 | 0.00 |
| mkPktMerge | VTR | 1.085 | 3.8 | 0.23 | 0.41 | 0.27 | 0.14 | 0.00 |
| frisc | MCNC | 1.077 | 29.2 | 0.80 | 0.02 | 0.02 | 0.16 | 0.00 |
| s298 | MCNC | 1.077 | 11.5 | 0.85 | 0.05 | 0.00 | 0.10 | 0.00 |
| mkSMAdapter4B | VTR | 1.076 | 22.0 | 0.40 | 0.04 | 0.34 | 0.15 | 0.08 |
| sha | VTR | 1.073 | 24.8 | 0.25 | 0.02 | 0.62 | 0.12 | 0.00 |
| des | MCNC | 1.067 | 13.5 | 0.85 | 0.05 | 0.00 | 0.11 | 0.00 |
| blob_merge | VTR | 1.066 | 118.5 | 0.59 | 0.07 | 0.12 | 0.23 | 0.00 |
| tseng | MCNC | 1.065 | 6.0 | 0.84 | 0.01 | 0.00 | 0.15 | 0.00 |
| misex3 | MCNC | 1.060 | 9.8 | 0.87 | 0.04 | 0.00 | 0.09 | 0.00 |
| s38584.1 | MCNC | 1.056 | 29.0 | 0.78 | 0.01 | 0.00 | 0.15 | 0.12 |
| ex5p | MCNC | 1.056 | 6.0 | 0.90 | 0.03 | 0.00 | 0.08 | 0.00 |
| raygentop | VTR | 1.054 | 19.8 | 0.63 | 0.04 | 0.11 | 0.30 | 0.02 |
| diffeq | MCNC | 1.053 | 7.0 | 0.74 | 0.00 | 0.00 | 0.26 | 0.00 |
| elliptic | MCNC | 1.052 | 17.2 | 0.75 | 0.06 | 0.00 | 0.19 | 0.00 |
| s38417 | MCNC | 1.052 | 30.0 | 0.80 | 0.01 | 0.01 | 0.18 | 0.00 |
| bigkey | MCNC | 1.045 | 6.0 | 0.67 | 0.09 | 0.00 | 0.24 | 0.00 |
| stereovision1 | VTR | 1.042 | 111.5 | 0.46 | 0.13 | 0.22 | 0.20 | 0.00 |
| alu4 | MCNC | 1.024 | 4.5 | 0.85 | 0.05 | 0.00 | 0.10 | 0.00 |
| boundtop | VTR | 1.023 | 3.0 | 0.87 | 0.00 | 0.00 | 0.79 | 0.00 |
| dsip | MCNC | 1.021 | 3.2 | 0.80 | 0.09 | 0.00 | 0.11 | 0.00 |
