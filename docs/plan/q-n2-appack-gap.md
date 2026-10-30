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
