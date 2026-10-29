"""Writes docs/plan/critical-heap.md from data/analysis/heap-*.json (tables are generated; prose cites the same numbers).
  python3 scripts/heap_doc.py"""
import collections
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
A = REPO / "data" / "analysis"
J = lambda n: json.loads((A / n).read_text())  # noqa: E731


def f(x, d=2):
    return "-" if x is None else f"{x:.{d}f}"


def iv(s, d=2):
    return f"{f(s['median'], d)} [{f(s['lo90'], d)}, {f(s['hi90'], d)}]"


def table(head, rows):
    return "\n" + "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


q1, q2, q3, q4, q5, q6, ln = J("heap-q1.json"), J("heap-q2.json"), J("heap-q3.json"), J("heap-q4.json"), J("heap-q5.json"), J("heap-q6.json"), J("heap-q1-lines.json")
VIEWNAME = {"op": "operator", "blk": "block", "det": "detector (netlist)"}


def q1_table(view):
    rows = []
    kinds = sorted(q1[f"{view}@0.9"], key=lambda k: -(q1[f"{view}@0.9"][k]["atoms"]["median"] or 0))
    for k in kinds:
        r = []
        for thr in (0.9, 0.95, 0.99):
            v = q1[f"{view}@{thr}"].get(k)
            r.append(f"{iv(v['atoms'])} (n={v['atoms']['n_designs']})" if v else "-")
        v = q1[f"{view}@0.9"][k]
        rows.append([k] + r + [iv(v["delay"]), v["never_in_heap_designs"]])
    return table(["kind", "atoms, crit >= 0.90", "crit >= 0.95", "crit >= 0.99", "delay-weighted, 0.90", "designs with 0 heap atoms (0.90)"], rows)


def AUC(tgt, name):
    m = ms[f"{tgt}:{name}"]
    return iv({"median": m["auc_median"], "lo90": m["auc_lo90"], "hi90": m["auc_hi90"]})


q3rows = [[r["design"], f(r["cpd_ns"]), r["paths"], r["paths_ge90"], r["paths_ge99"], f"{r['ne90']} / {r['ne95']} / {r['ne99']}", f(r["last_crit"]),
           f"{f(r['crit_p10'])} / {f(r['crit_p50'])} / {f(r['crit_p90'])}", r["atoms"], f"{r['heap_atoms_90']} / {r['heap_atoms_95']} / {r['heap_atoms_99']}"]
          for r in q3 if r["seed"] == 1]
q4rows = [[p["design"], p["atoms"], p["pack_heap"], p["route_heap"], f(p["stay"]), f(p["from_pack_heap"]), f(p["new_arrival_pc_lt_090"]), f(p["pack_heap_unseen"]),
           f(p["rho_crank_pc"]), f(p["pack_heap_in_first_quartile"]), f(p["floor_ratio"]), f(p["near_net_share"])] for p in q4["per_run"] if p["seed"] == 1]
mat = collections.Counter()
for p in q4["per_run"]:
    for k, c in p["matrix"].items():
        mat[k] += c
BINS = (">=0.99", "0.90-0.99", "0.50-0.90", "<0.50", "unseen")
matrows = []
for a in ("<0.50", "0.50-0.90", "0.90-0.99", ">=0.99"):
    tot = sum(c for k, c in mat.items() if k.startswith(a + "|"))
    matrows.append([a, tot] + [f(mat[a + "|" + b] / tot, 3) for b in BINS])
S4 = q4["summary"]
S6 = q6["cones"]["summary"]
ms = q6["model_sets"]
nf = sorted(d for d in {r["design"] for r in q3})
lines_rows = []
for d in ("sha", "diffeq1", "or1200", "raygentop", "stereovision3"):
    for t in ln[d]["top"][:4]:
        lines_rows.append([d, t["line"], t["heap_atoms"], t["atoms"], f(t["enrichment"])])
q2rows = [[k, v["words"], v["bits_seen"], f(v["mean_spearman_bit_vs_crit"], 3), *[f(v["heap_rate_by_position_quartile"][str(i)], 3) for i in range(4)]] for k, v in sorted(q2.items())]
q5unseen = [[k, f(v[0]), v[1]] for k, v in sorted(q5["unseen_share_op"].items())]
q5rows = [[view, k, v["designs"], v["never_in_heap_designs"], f(v["median_enrichment"])] for view in ("op", "blk", "det") for k, v in sorted(q5[view].items())]
aucrows = []
for name in ("kind", "kind+ops", "kind+ops+netlist", "netlist only"):
    aucrows.append([name, iv({"median": ms[f"route:{name}"]["auc_median"], "lo90": ms[f"route:{name}"]["auc_lo90"], "hi90": ms[f"route:{name}"]["auc_hi90"]}),
                    iv({"median": ms[f"pack:{name}"]["auc_median"], "lo90": ms[f"pack:{name}"]["auc_lo90"], "hi90": ms[f"pack:{name}"]["auc_hi90"]})])
uni = [[k.split(":")[1], iv({"median": q6["univariate"]["route:" + k.split(":")[1]]["auc_median"], "lo90": q6["univariate"]["route:" + k.split(":")[1]]["auc_lo90"], "hi90": q6["univariate"]["route:" + k.split(":")[1]]["auc_hi90"]}),
        iv({"median": v["auc_median"], "lo90": v["auc_lo90"], "hi90": v["auc_hi90"]})] for k, v in q6["univariate"].items() if k.startswith("pack:")]
mux = [[d, iv(q6["mux_depth"]["route:" + d]), iv(q6["mux_depth"]["pack:" + d], 3), q6["mux_depth"]["route:" + d]["n_designs"]] for d in ("0", "1", "2", "3", "4+")]
bitp = [[k, iv(v, 3), v["n_designs"]] for k, v in q6["bit_position"].items()]

DOC = f"""# The critical heap: which constructs end up near-critical, and how the heap moves (data only)

Purpose: speed = critical + near-critical paths (hub purpose; Norns and Mimir speed RQs; measure: speed). Peter 2026-10-29: criticality is the main
focus of the packer, an HDL structure is a suggestion of what to pack together (probably at bit-path level); is there data on which HDL constructs
lead into "the critical heap" (the paths suspected critical that the greedy packer takes first), and does the heap persist, pushed down, to the end?
Data-first rule (Peter 10-26): this document measures and shows; it gives no verdict. Candidate hypotheses are listed at the end, untested.

## Plain-English summary

* The heap is small and concentrated. On the 15 Verilog designs of the keep sweep (45 runs: 3 seeds each; post-route), the 1000-path report reaches
  below crit 0.90 in every run, so the crit >= 0.90 heap is complete (no run is truncated at 0.90, 0.95 or 0.99). The heap holds a median
  {f(sorted(r['heap_atoms_90']/r['atoms'] for r in q3)[len(q3)//2]*100, 1)}% of the atoms of a design and lives in a median of {f(S6['groups_holding_heap']['median'], 0)} register-bit cones
  (cone = fan-in of one register bit or output; {f(S6['comb_share_in_heap_groups']['median']*100, 0)}% of the combinational atoms).
* Which constructs: with the operator-level labels, carry-chain adders are enriched only at the top of the heap (crit >= 0.99: median enrichment
  {iv(q1['op@0.99']['adder']['atoms'])}, n={q1['op@0.99']['adder']['atoms']['n_designs']} designs) and sit at about the baseline at crit >= 0.90 ({iv(q1['op@0.9']['adder']['atoms'])}).
  Multipliers are strongly enriched but exist in only {q1['op@0.9']['multiplier']['atoms']['n_designs']} designs. Equality comparators are absent from the heap in
  most designs (median {f(q1['op@0.9']['equality']['atoms']['median'])}), muxes and relational operators are below baseline.
* Bit level: neither word bits nor carry-chain positions show an MSB effect. Heap rate by position quartile is flat (adder chains: {', '.join(f(q2['adder carry chain']['heap_rate_by_position_quartile'][str(i)], 3) for i in range(4))}).
* Dynamics: the packer does take the pack-time heap earlier (Spearman between cluster number and pack-time crit: {iv(S4['rho_crank_pc'])}), but the heap does not stay put:
  only {iv(S4['stay'])} of the pack-time heap (crit >= 0.90) is in the post-route heap, while {iv(S4['from_pack_heap'])} of the post-route heap was in the
  pack-time heap ({iv(S4['new_arrival_pc_lt_090'])} are new arrivals with pack-time crit < 0.90).
* Floor: with wire delay removed (cell delays only) the slowest reported path would run at {iv(S4['floor_ratio'])} of the real CPD; wire delay is
  {iv(S4['near_net_share'])} of the delay of the near-critical paths. A heap always exists (crit is relative to the worst path) and the wire share is what the placement decides.
* HDL hints (Q6): construct kind and expression depth carry little signal for the post-route heap (leave-one-design-out AUC {AUC('route', 'kind+ops')}),
  adding netlist depth and register/adder type gives {AUC('route', 'kind+ops+netlist')};
  for the pack-time heap the netlist depth alone reaches {AUC('pack', 'netlist only')}.

## Method and data

* Post-route side: `norns-keep.db` (Mimir schema 7, read only), the 45 runs with kept timing: `timing_path` (crit of each of up to 1000 paths), `timing_path_node`
  (atoms, `cell_delay_ns`, `net_delay_in_ns`, word and bit), `timing_run`. Config E10 `base` (vpr_sa, K6, norns architecture), seeds 1, 2, 3. See `docs/plan/keep-sweep-2026-10-29.md`.
* Atom criticality rc(atom) = the largest crit of a reported path containing the atom (a lower bound; an atom in no reported path has rc <= last_crit, "unseen").
  The heap at threshold t = atoms with rc >= t. Atoms in `timing_path_node` are named like the packer's atoms (all 15 designs, 100% of the matched path atoms occur in the census).
* Constructs: `lane3-structures.db` (read only), structures of the 15 designs (`norns/<d>`), their `structure_member` atoms. Three views: operator
  (`granularity = operator`, HDL operators), block (`granularity = block`, always blocks and assigns) and detector (netlist detectors). Atom names are the same hash names in the keep
  netlists and the structure runs (not every keep atom is a member: `none` collects atoms in no structure of the view). An atom takes the kind of the smallest
  structure containing it. The structure runs and the keep runs are separate Odin III runs of the same base netlist; the overlap was not 100% (for example stereovision0 has no detector structures), so the `none` row mixes "no construct" and "not covered".
* Baseline: all logic atoms of the design (the census atoms, pads excluded: LUTs, flip-flops, adder bits, hard blocks), not the 1000 reported paths. Enrichment of kind k =
  (share of heap atoms in k) / (share of all atoms in k). The delay-weighted variant weights each heap atom by `cell_delay_ns + net_delay_in_ns` of its node on the most critical path through it, against the same atom-count baseline.
* Summary across designs: per design the mean over its 3 seeds, then the median over designs with a 90% percentile bootstrap (2000 resamples of designs). A design counts for a kind with >= 5 atoms of
  the kind and >= 10 heap atoms. Seed spread (mean standard deviation of the ratio over the 3 seeds, median over kinds) is {f(sorted(v['mean_seed_sd'] for v in q1['op@0.9'].values() if v['mean_seed_sd'] is not None)[len(q1['op@0.9'])//2], 2)} at the operator view, 0.90.
* Pack side: new beta-0 census runs (`scripts/heap_census.py`): the Norns VPR binary, E10 `base` flags except `--pack` only (packing does not depend on later stages), `--norns_pack_census`, seeds 1 to 3, all 15 designs, under the Norns VPR lock, RLIMIT_AS 14 GB.
  Gate: the `.net` of every census run is byte-identical to the `.net` of the sweep run (45 of 45, rc 0). The census runs live in `work/heap-out` (outside the worktree). Pack-time criticality pc(atom) = the largest `P` value over
  the atom's input pins at the moment its molecule was added (VPR's pre-cluster timing, which VPR updates as clusters close, so pc is "the heap as the packer saw it then"). Pack order = cluster number of the final (closed) cluster; the pack-time heap = pc >= 0.90.
  Existing round-4 censuses (`work/norns-exp/data/<d>/r4census.json`, `scripts/r4census.py`) were not reused: they come from other flags (round-4 analytic arms) and the new runs cover all 15 designs on exactly the sweep flags.
* New store: none needed (`work/mimir-data/heap.db` was not created); derived tables are `data/analysis/heap-q*.json`, rebuilt by `scripts/heap_analyze.py` from the stores read-only, the census files and the BLIFs.
* Scripts: `heap_census.py`, `heap_data.py` (loader), `heap_lib.py` (join, ratio, bootstrap, Spearman, census parser, netlist levels and cones), `heap_analyze.py`, `heap_figs.py`, `heap_doc.py` (this file). Tests: `python3 tests/test_heap.py` (16 tests: innermost-kind join, ratio, bootstrap, Spearman, census parser, levels, cones, carry chains).

## Q1. Construct enrichment

Median (90% bootstrap) over designs of the per-design enrichment; n = designs that count for the kind. A ratio of 1 = the kind is in the heap in proportion to its atoms.

### Operator view
{q1_table('op')}

### Block view
{q1_table('blk')}

### Detector view (netlist detectors; stereovision0 to 2 have none)
{q1_table('det')}

Figure: `docs/figures/critical-heap/q1-enrichment.png`.

Controller first cut (pooled delay, baseline = reported paths) said adder 2.16, multiplier 1.66, mux 0.29, relational 0.40, equality 0.15. Reproduced properly the picture changes in two ways: with the
whole-design baseline and designs as replicates the adder ratio at 0.90 is about 1 (it reaches 2 only at 0.99), and the multiplier value rests on {q1['op@0.9']['multiplier']['atoms']['n_designs']} designs.
The low mux, relational and equality values do reproduce.

### By HDL line (for Wyrd)
Top lines by heap atoms (crit >= 0.90, seed 1; enrichment = line's heap share / line's atom share). All designs are in `data/analysis/heap-q1-lines.json` (top 8 each).
{table(['design', 'line', 'heap atoms', 'atoms on the line', 'enrichment'], lines_rows)}

## Q2. Bit level

Words of >= 8 bits. Word kind = the most common operator-view kind (else block view) of the word's atoms. The Odin III attribution gives word and bit only for atoms in a reported path and only for flip-flops, hard blocks and some
LUTs; adder bits have none, so adders use the position along the carry chain (netlist) instead. Heap rate = share of the bits (or chain positions) with rc >= 0.90, by quartile of the relative position (0 = LSB / chain head).
{table(['word kind', 'words', 'bits seen', 'mean Spearman(bit, crit)', 'Q0 (LSB)', 'Q1', 'Q2', 'Q3 (MSB)'], q2rows)}

Figure: `docs/figures/critical-heap/q2-bit-position.png`. No multiplier word appears (multiplier atoms carry no word attribution). There is no MSB-heavy pattern in these data; the adder chains (12,858 atoms in chains of >= 8 across the 45 runs) show a flat 3 to 4% heap rate over the four quartiles.

## Q3. Heap size and shape (seed 1; seeds 2 and 3 in `data/analysis/heap-q3.json`)

`paths` = paths in the 1000-path report; `paths >= t` counts reported paths; `endpoints` = `n_endpoints_090/095/099` of `timing_run`. `last crit` = crit of the last reported path (stereovision3 reports all 201 of its paths; its stored
last_crit of 1.00 is the store's value). Truncation flags (`trunc_090/095/099`) are 0 in all 45 runs: the report always reached below 0.90 before the 1000-path cap.
{table(['design', 'CPD ns', 'paths', 'paths >= .90', 'paths >= .99', 'endpoints .90/.95/.99', 'last crit', 'crit p10/p50/p90', 'atoms', 'heap atoms .90/.95/.99'], q3rows)}

Figure: `docs/figures/critical-heap/q3-wall.png`. The wall: the number of paths within 0.01 of the worst ranges from 1 (mkDelayWorker32B, blob_merge) to 25 (stereovision2); the heap at 0.90 holds 1 to 419 reported paths.

## Q4. Heap dynamics through the flow

Per design (seed 1; medians over designs with intervals in the summary below). `pack heap` = atoms with pc >= 0.90; `route heap` = atoms with rc >= 0.90; `stay` = share of the pack heap in the route heap; `from pack` = share of the route heap that was in the pack heap;
`new` = share of the route heap with pc < 0.90; `unseen` = share of the pack heap in no reported path; `rho` = Spearman(cluster number, pc); `Q1 share` = share of the pack heap packed in the first quarter of clusters (0.25 if no order effect);
`floor` = (largest cell-delay sum of a reported path) / CPD; `wire` = net share of the near-critical path delay.
{table(['design', 'atoms', 'pack heap', 'route heap', 'stay', 'from pack', 'new', 'unseen', 'rho', 'Q1 share', 'floor', 'wire'], q4rows)}

Summary over the 15 designs (median [90% bootstrap]; per design the mean of 3 seeds):
{table(['measure', 'value'], [[k, iv(v, 3)] for k, v in S4.items()])}

Transition of atoms from pack-time criticality (rows) to post-route criticality (columns), row-normalised, all 45 runs pooled (pack-time rows below 0.50 pooled):
{table(['pack-time crit', 'atoms'] + list(BINS), matrows)}

* Pack order against criticality: the correlation is negative in {sum(1 for p in q4['per_run'] if p['seed']==1 and (p['rho_crank_pc'] or 0) < 0)} of 15 designs (seed 1): the greedy seed selection and the timing gain take higher-pc atoms in earlier clusters, moderately ({iv(S4['rho_crank_pc'])}). Exceptions are the designs
  dominated by hard blocks (mkDelayWorker32B, rho +0.78).
* The first-quarter share of the pack heap is {iv(S4['pack_heap_in_first_quartile'])} (0.25 = no order effect).
* The floor measurement: the heap exists after routing in every run (crit is relative), and its member paths are {iv(S4['near_net_share'])} wire by delay. The cell-only logic-depth ordering of the reported paths (paths with cell sum >= 0.9 of the
  largest) shares {iv(S4['logic_vs_route_jaccard'])} Jaccard with the routed heap and covers {iv(S4['logic_heap_recall_of_route'])} of the routed heap's paths. Only the 1000 reported paths enter, so a deeper but unreported path could raise the largest cell sum.

Figure: `docs/figures/critical-heap/q4-dynamics.png`.

## Q5. What is not in the heap

Per view and kind (crit >= 0.90): designs where the kind counts, designs where it has zero heap atoms, median enrichment.
{table(['view', 'kind', 'designs', 'designs with 0 heap atoms', 'median enrichment'], q5rows)}

Share of atoms (all 45 runs pooled, operator view) that are in no reported path at all, with the atom count:
{table(['kind', 'share unseen', 'atoms'], q5unseen)}

Equality comparators and FSM blocks are the constructs most often absent (equality: 6 of 10 designs, fsm: 4 of 7 in the block view). No kind is absent from the heap in all designs; the kinds with structure rows but too few atoms to count (shifter, memory, unknown) cannot be judged.

## Q6. Do HDL hints known before packing predict the heap?

Atoms: all logic atoms of the 45 runs. Targets: (route) rc >= 0.90 from the keep store; (pack) pc >= 0.90 from the census. Features are computed from HDL / Odin III data and the BLIF only, never from VPR timing:
(a) construct kind (operator view, else block view, else none); (b) operator depth = number of BINARY/UNARY/TERNARY/CONCAT nodes in the structure's `construct_chain` (`structure.construct_chain` of lane3-structures, from the Odin III AST provenance),
and width proxy = log2 of the member count of the innermost structure (word width itself exists only for atoms in a reported path, see Q2); (c) mux depth = number of IF, CASE and TERNARY nodes in the same chain (case/if nesting of the source line; source: `construct_chain`, the AST provenance);
(d) combinational depth = LUT levels from the nearest register / primary input / hard block, on the BLIF (a carry chain counts once; single-input buffers are absorbed as VPR does); (e) bit index within a word: see the bit-position table
(Odin III word attribution; only for atoms in a reported path, so those rates condition on being in the report; adder bits use carry-chain position).
Model: L2-regularised logistic regression (numpy Newton), standardised features, each design weighted equally, **leave-one-design-out** (train on 14 designs, test on the held-out one, all 3 seeds); AUC per held-out design,
then median [90% bootstrap] over the 15 designs. 0.5 = no signal.

### AUC by feature set
{table(['features', 'route heap AUC', 'pack heap AUC'], aucrows)}

Univariate AUC of a numeric feature (no model; per design, median [90%]); route heap first, pack heap second:
{table(['feature', 'route heap', 'pack heap'], uni)}

### Heap-membership rate by mux depth (per-design rate, median over designs with >= 5 atoms at that depth)
{table(['mux depth', 'route heap rate', 'pack heap rate', 'designs'], mux)}

### Heap-membership rate by bit position
{table(['position', 'route heap rate', 'designs'], bitp)}

### One combinational bit-path group per register bit
Group = fan-in cone of one register bit (latch) or primary output, back to registers, PIs and hard blocks. Each combinational atom is assigned to the cone of its highest-hint endpoint; hint = combinational depth of the endpoint's driver
(ties by name). Per run, summarised as median [90%] over designs:
{table(['measure', 'value'], [[k, iv(v, 3)] for k, v in S6.items()])}

Group-size distribution (median over designs): half the groups hold 1 atom, 90% hold at most {f(S6['size_p90']['median'], 0)}, the largest holds {f(S6['size_max']['median'], 0)}. `paths_inside_one_group` = share of the near-critical paths (crit >= 0.90) all of whose combinational
atoms are assigned to the group of the path's own endpoint; `heap_atoms_staying` = share of heap combinational atoms for which every near-critical path through them ends in their own group. The first is low because shared logic is assigned to one
deepest endpoint, not to each cone that contains it: a bit-path group by exclusive assignment covers a near-critical path completely only for a minority of paths, the heap atoms mostly remain within one group. Figure: `docs/figures/critical-heap/q6-auc.png`.

## Not measured, and why

* The pack-time heap at the start of packing (before the first cluster): the census logs pin criticality when each molecule is added, not the initial table; `pre_pack.report_timing.setup.rpt` exists in the run directories and could be parsed (not done).
* Word width and bit index for atoms outside the reported paths: the Odin III attribution covers only atoms in the reported paths (Q2, Q6 e).
* Multiplier bits: no word attribution; two designs hold multipliers.
* Delay-weighted baseline: the baseline is atom counts (there is no per-atom delay for atoms in no path).
* Crit-versus-lines for MCNC designs: the 20 MCNC designs have no attribution (blif input, `norns-keep.db`: 0 imported), so the study covers the 15 Verilog designs only.
* Hard-block (memory, multiplier) connectivity is cut at the block boundary in the cone and level computation.

## Candidate hypotheses (not tested; for Peter to choose)

* H1 Bit-path affinity from HDL hints. Group the atoms of each register bit's fan-in cone (exclusive assignment to the deepest endpoint, as measured in Q6) and give the packer that grouping as the affinity file.
  Arms (written, not run): A0 stock (beta 0); A1 cone groups, `--norns_affinity <cones> --norns_affinity_weight beta` for beta in {{1, 4, 16, 100}}; A2 cones restricted to the groups the hint model ranks highest (top 5% by depth);
  A3 null: the same group-size distribution assigned at random among atoms of the same module; A4 cones plus the block-membership file of round 5 for comparison. Measures per arm: CPD, number of atoms with rc >= 0.90 and >= 0.99, wirelength; 15 designs x 3 seeds; the verdict
  rule (effect size, interval, designs improved of 15) fixed before the run.
* H2 Heap floor = logic depth. The routed heap cannot fall below the cell-delay sum of the slowest path; measured here the cell-only share of the CPD is about 0.4, so the floor would only matter for placements far better than VPR's.
* H3 Carry-chain adders enter the heap only at the very top (crit >= 0.99): packing a carry chain with its LUT consumers could matter at 0.99 but not for the broad 0.90 heap.
* H4 The pack-time heap is wide and short-lived: most of the pack heap does not remain post-route, and about a quarter of the post-route heap was not in the pack heap; packing by pre-cluster criticality is a weak proxy for the final heap.
* H5 Netlist depth beats HDL constructs as an early predictor of the pack-time heap (AUC {f(ms['pack:netlist only']['auc_median'], 2)} against {f(ms['pack:kind']['auc_median'], 2)} for construct kind).
"""
(REPO / "docs" / "plan" / "critical-heap.md").write_text(DOC)
print(len(DOC))
