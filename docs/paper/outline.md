# Proposed new main-paper outline: The Norns III

Order requested in the brief. Every current section is mapped (keep / move / shrink to a log row / drop) so nothing is lost silently. Paper text is not edited in this step.

## New structure

0. Abstract: plain-English problem, the innovations with their USEFUL hypotheses only, one sentence on what was dismissed.
1. Introduction.
   - Problem in plain English (placement starts from a layout; does the designer's structure help; where is it lost).
   - The innovations in plain English (innovations.md 1 to 8, shortened).
   - Contributions: the USEFUL hypotheses H8, H9a-word/H9a-wordio, H10a, H17c, H20/H25/H19/H32, H33, H35, H36 and the honest INCONCLUSIVE answers R1a, R1e, R7a.
2. Background (terms in dependency order, terms.md): FPGA, netlist, HDL, LUT, K, BLE, CLB, provenance, placement, routing, wirelength, critical path, CPD, slack, near-critical, VPR, packing, simulated annealing, seed.
3. The innovation (plain English, then technical): the packer with HDL affinity; the known-optimum benchmarks; the pair-class census; seeding and the crossover as the baseline idea that did not pay.
4. Methodology: setup (15 VTR designs, architecture, VPR/VTR 9 commit), metrics: area (logic CLB count, grid, channel width), speed (routed WL, CPD, and near-critical statistics: only H17c exists today), power (not measured in any round); statistics (geomean ratio, sign test, Wilcoxon, Holm, bootstrap, permutation null); decision rules and what is pre-registered (round 3 to 6) versus reconstructed (rounds 1, 2 H2, 7, 8); data: the Mimir dataset and what provenance adds (section "Mimir as the instrument" below).
5. Experiments, one subsection per USEFUL or INCONCLUSIVE hypothesis kept in the main paper: hypothesis, experiment, result, verdict.
   - 5.1 Does packing dilute structure (H8, H10a, H9a-word/wordio).
   - 5.2 Room for a better packer (H25/H19, H20, H32).
   - 5.3 When does HDL-aware packing pay (H33, H35, H36; H34a-d and H37 as the limits).
   - 5.4 What gets clustered on critical paths (H17a measurement, H17c).
   - 5.5 Does seeding help at VPR's temperature (R1a, R1b, R1e, H4; INCONCLUSIVE/DISMISSED answers to the opening question).
   - 5.6 Is the hierarchy physical (H1, H11; INCONCLUSIVE).
   - 5.7 Headroom by hindsight (R7a) and other placers (R8a, R8b).
6. Discussion and limits: single VPR seed in rounds 1-2, 15 small designs, leak, chain control failure (H37), no power, H0 bias, erratum (carry chains absent in round-3 affinity files).
7. Conclusion.
Appendix A: research log, every hypothesis incl. DISMISSED, one row each (hypotheses.md rows with verdict DISMISSED or not in main paper; the dated thought-pattern log stays here).

## Mapping of the current paper

| current location | content | new place | action |
|---|---|---|---|
| norns.tex:41-72 abstract | rounds 1-2 prose + r4..r8 abstracts | Abstract | rewrite; shrink to innovations and verdicts |
| norns.tex:75-116 Introduction | question, contributions list (1)-(6) | Introduction | rewrite around innovations |
| norns.tex:118-130 Fig. yggdrasil paragraph | tree picture | Introduction (end) | keep |
| norns.tex:131-155 Background | SA/RLPlace; the seeds | Background | keep, add term list in dependency order |
| norns.tex:157-300 Methodology (seed construction, injection, crossover) | how seeds are built | 3 (seeding as baseline idea) and 4 | shrink; detail to an appendix |
| norns.tex:300-345 benchmarks table | 15 designs | 4 Methodology | keep |
| norns.tex:393-446 Results rounds 1 | QoR tables, crossover | 5.5 | shrink to R1a/R1b/R1e; R1c, R1d, R1f become log rows |
| r2-method.tex / r2-results.tex | word membership, families, N4, N1, N2 | 3 (word membership) and 5.5, 5.6 | keep word membership; H7a-d, H2 to log rows; H4, H1 kept |
| r2-discussion, r2-conclusion | | 6, 7 | merge |
| r2-appendix.tex | research log, dated rule changes | Appendix A | keep verbatim |
| r3-method / r3-results | N8-N11 | 3, 5.1, 5.6 | H8, H9a-word/wordio, H10a, H11 kept; H9b, H9c, H10b to log rows |
| r3-discussion, r3-appendix | | 6, Appendix A | merge |
| r4-method / r4-results | census, knowns, hierarchy, H14-H16 | 5.4 and Appendix A | H17a/c/d kept (H17a measurement); H13, H15, H16, H14, K1-K8 to log rows (H14 is the central negative for the packer: stated in 5.3) |
| r4-abstract / discussion / appendix | | Abstract, 6, A | merge |
| r5-method / r5-results | known-optimum benchmarks | 3, 4, 5.2 | keep H25/H19, H20, H24/H27; H18/H28 stated as limits of the yardstick; H21, H22, H23 to 5.3 as the leak finding |
| r6-method / r6-results | alignment | 5.3 | keep H29-H36; H37 as limit |
| r7-method / r7-results | corpus, hindsight, mining | 5.7 and Appendix A | shrink: R7a main; R7b and exploratory tables to the appendix |
| r8-results | other placers | 5.7 | shrink to Table tab:r8family and the run-record paragraph |
| norns.tex Discussion / Conclusion (lines 457-501) | | 6, 7 | rewrite |
| norns.tex:Appendices r2-r7 | | Appendix A | keep, add the register |

## Mimir as the instrument

Mímir III is how we find out why things are placed where they are: provenance links every placed object to its HDL origin, so data features plus provenance give exploration paths into the real multi-metric problem (area low, speed high, power low), with speed measured by the critical and near-critical timing.

Hypotheses that need Mímir data (provenance-linked placement and timing): H1, H11 (placement of HDL-labelled CLBs), H17c/H17d (near-critical edges in CLBs), H15 (statement-level critical delay), R7a/R7b (mining of HDL features against placement), H36/H33 (alignment of words with blocks), and any future hypothesis about where a given HDL construct lands.

What Mímir holds today (mimir/schema.py:130-140; mimir/importers/norns.py:15-50): `structure_mapping` rows per (design, structure_id, run_id, level) with `bbox_x0..y1`, `spread` (placed footprint of an HDL structure's CLBs) and `crit_share` (the structure's share of path 1's data delay, only with a timing-attribution run), `lost_at_pass`, `joined_with`; the Norns importer maps the run fields to `vpr.wirelength`, `vpr.chan_width`, `vpr.cpd`, `vpr.worst_slack`, `vpr.logic_clbs`, `vpr.place_time`, `vpr.bb_cost_*`, `norns.purity`, `norns.reproduction`, `norns.cut`, `norns.retention`, `norns.critical_matched_delay_share`, `norns.objective` and others.

What is missing: (1) near-critical statistics per HDL object (only path 1 gives `crit_share`; no share over the top-k or within-10% paths, so H17c cannot be recomputed from Mímir); (2) power: no power metric exists in the schema or the Norns importer (power was never measured); (3) worst slack per structure; (4) round 1-2 per-run records predate the run-record format (VTR commit unknown for them).
