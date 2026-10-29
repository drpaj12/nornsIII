# Innovations of The Norns III paper

Plain English first, then the technical paragraph, then the H-IDs (from hypotheses.md) whose USEFUL verdict proves the value, then what is still unproven. Only USEFUL verdicts count as proof; a mechanism or validity check is marked as such.

## 1. Placement that starts from the designer's structure (seeding)

Plain English. When an FPGA tool places a design it starts from a rough layout and then shakes it up with a "heated" search. We hand the tool a different rough layout: one that keeps together the pieces the designer wrote together (an HDL module, a register and its bits). We then ask how hot the search can be before it throws that layout away.
Technical. A seed is a partition of the placed blocks, either the Odin III provenance hierarchy (Urd) or a Loki III L2 clustering (Louvain, spectral, affinity propagation, k-means at k, 2k, 4k); a cut-weighted quotient-graph layout places clusters on the die, and the seed enters VPR as an initial-placement file (soft) or floorplan regions (hard); word and bit-slice variants add Odin III word membership (norns.tex:167-262, r2-method.tex:10-48).
Proves its value: none. R1a, R1b, H7a, H7b, H7d are INCONCLUSIVE, R1c, H7c and H4 are DISMISSED (a random start is as good).
Still unproven: any end-metric gain from a seed at VPR's own temperature; whether a seed beats a random start with equal effort.

## 2. The crossover sweep (how hot the anneal may start)

Plain English. A way to measure how much of a good starting layout survives when the search is made hotter: raise the temperature until the head start disappears.
Technical. Cold-start from P*, the best placement over all seeds; sweep the initial temperature as a multiple S of VPR's automatic estimate; the crossover is the largest tested S at which the cold start still routes shorter than an unseeded run at the same S; also run all seeds at 2x the crossover (norns.tex:282-296).
Proves its value: none (R1e INCONCLUSIVE: P* is the best of about 20 placements, no equal-effort control; R1f, checkpointing, DISMISSED).
Still unproven: that the crossover reflects the seed rather than selection.

## 3. The Norns packer (HDL-affinity clustering)

Plain English. Before placement, a tool packs small pieces of logic into chip tiles. The normal packer does not know which pieces belong to the same register. Ours is a copy of the normal packer that adds a bonus for putting pieces of the same HDL word or module in the same tile.
Technical. A patch to VPR's AAPack adds a gain term beta per atom of the candidate molecule's affinity group (module, word, or word+io) read from a file; legality stays with AAPack (r3-method.tex:10-35, patches/).
Proves its value: H8 (the stock packer does scatter words: purity 0.63, split 4.00), H9a-word and H9a-wordio (affinity raises purity with no CLB growth; mechanism check), H10a (io-words add 24.1% LUT coverage), H33 (with the leak the packer cuts WL to 0.669 of stock), H36 (the gain follows measured alignment), H35 (it hurts WL when words do not match blocks; a finding about limits).
Still unproven: any end-metric gain without the leak (H34a-d DISMISSED, H14 DISMISSED, H9c DISMISSED, H37 control failed with chain WL 4.150 of stock); effect on near-critical paths; the round-3 affinity files omitted carry chains (erratum).

## 4. Known-optimum-by-construction benchmarks (the yardstick)

Plain English. To know whether a packer or placer is good we need designs where we know the best grouping. We build designs out of blocks that each exactly fill one tile, wired as chains, meshes, trees and random graphs, so the intended grouping is known. (It is an optimum for tile count only; it is not a proven best placement.)
Technical. A generator writes 72 designs (netlist level and Verilog through Odin III, 4 to 1024 blocks) and 105 with controlled alignment between HDL words and blocks; a forced-clustering packing `.net` reproduces the blocks; ratios are against the placement VPR produces from that clustering (r5-method.tex:5-7, r6-method.tex:4-5).
Proves its value: H24/H27 and H29-H31 (validity checks: reproduction 1.000, 105/105 kept), H25/H19 (stock packer is 1.22 times the known clustering in WL), H32 (1.489 on mesh and tree), H20 (WL room remains for the Norns packer).
Still unproven: H18 and H28 are DISMISSED under their literal pre-data rules (32/72 and 37/72); the amended and slack rules were chosen after the data; the optimum is a clustering optimum, not a placement optimum; H21 (gap grows with size) is INCONCLUSIVE.

## 5. Pair-class census of the packer (what gets clustered)

Plain English. A direct count of which kinds of pairs of logic pieces the normal packer puts together: pairs on a critical path, pairs sharing an input, and pairs that merely fill space.
Technical. Log-only counters in the packer plus Odin III post-route critical-path attribution classify CLB pairs into series-critical, series-noncritical, shared-input, orthogonal and filler (r4-method.tex:24).
Proves its value: H17c (near-critical edges cross CLBs less often than edges in general: median ratio 0.652, p=0.027, n=9, literal rule), H17d (sanity: above the shuffle null); H17a is a measurement, not a hypothesis (4.0 / 32.0 / 64.4 percent).
Still unproven: H17c has 9 designs and fails an unregistered n<12 reading; H17b DISMISSED.

## 6. Hierarchy is physical (evidence for the premise)

Plain English. Do pieces of the same HDL module sit near each other on the chip, even if the placer never saw the hierarchy?
Technical. Compactness and NMI of module/word labels against a random null (H1) and distance of same-word/same-module CLB pairs beyond net connectivity (H11).
Proves its value: none yet (H1 and H11 INCONCLUSIVE; compactness is above the null on 10/11 and 14/15 designs; same-module d=-0.188, p<0.001 with 10 of 11 designs sign-consistent where 12 were required).
Still unproven: the literal registered counts.

## 7. Hindsight clustering and the placement corpus (round 7)

Plain English. After the fact, find out which pieces a good placement put close together and ask whether a packer that had known that would have done better. This tells how much room there is.
Technical. 1660 VPR placements, a hindsight `.net` built from the best stock placement of seeds 1 to 5 and measured on seeds 6 to 10; held-out gaps with bootstrap; mining with a shuffled-label null (r7-method.tex:1-30).
Proves its value: none (R7a, R7b INCONCLUSIVE).
Still unproven: any held-out gain (median WL gap 0.987 on 8 designs).

## 8. Other placers through VPR's flat-placement file, with run records (round 8)

Plain English. Run a placer from outside VTR (nextpnr), feed its result back into VPR, and let VPR route and time it, so every placer is judged by the same router and timer. Every run writes a record of exactly what was run and how each parameter was known.
Technical. Converter to `--read_flat_place`; per-family ratios against a reread control; rule H0 fixes hard blocks and pads at VPR's analytic positions; `mimir-run.json` run records importable by Mimir III (r8-results.tex:1-83).
Proves its value: none as a hypothesis (R8a, R8b INCONCLUSIVE); the run-record format is a tool result, not a hypothesis.
Still unproven: the nextpnr SA wirelength advantage (0.947) apart from the inherited hard blocks.
