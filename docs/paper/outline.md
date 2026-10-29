# Proposed new main-paper outline: The Norns III

Order requested in the brief. Every current section is mapped (keep / move / shrink to a log row / drop) so nothing is lost silently. Paper text is not edited in this step.

## New structure (as built in step 2; norns.tex inputs n-*.tex)

Changes to the step-1 outline from Peter's decisions: seeding is a negative baseline (decision 4); the paper is re-centred on the packer, the known-optimum yardstick and the leak finding; H22 is withdrawn and replaced by H22' (decision 2); H37 is reported per alignment level (decision 5); E10 is added; fragile rows are POSSIBLY GOOD (decision 1); no pre-registration wording in the paper (decision 7); a glossary built from terms.md sits in Background (decision 8); untested hypotheses are a Future work section (decision 10).

0. Abstract (norns.tex).
1. Introduction (n-intro.tex): problem in plain English, what good means (area, speed = critical and near-critical, power not measured), the Mimir data, the five innovations in plain English, contributions with their hypotheses.
2. Background (n-background.tex): glossary in dependency order (terms.md), concepts, related work, the suite tree (Fig. 1).
3. The Innovations (n-innovations.tex): packer; yardstick; the leak; pair-class census and near-critical statistic; seeding baseline (Fig. 2); outside placers and run records. Plain English then technical.
4. Methodology (n-method.tex): setup, benchmarks table, metrics (area, speed, power), verdicts, statistics, Mimir as the instrument.
5. Experiments (n-experiments.tex): scatter (H8, H10a, H9a); room (H24, H27, H29-H31, H25/H19, H32, H20); with the leak (H33, H36, H35, H34, H22, H23); realistic words (H22', H37 per level); near-critical (H17a, H17c); E10; seeding (R1, H4); hierarchy (H11); hindsight and other placers (R7a, R8a, R8b).
6. Discussion and limits, Future work (U1 to U5), Conclusion (n-discussion.tex).
Appendix A: research log, every hypothesis, one row each (n-log.tex, 62 rows).

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

## Step 2 note on the mapping

The legacy files r2-*.tex to r8-*.tex (and their appendices with the dated rule changes) are no longer inputs of norns.tex. They are kept in the repository as the pre-restructure text; the register (hypotheses.md) and docs/plan/ hold every rule, date and number. The old Table qor is kept (Table 4 of the paper); the old crossover table and the old method detail on seed construction are reduced to the paragraphs of Sections 3.5 and 5.7. The old Results text for rounds one to seven is replaced by the experiment subsections of Section 5.
