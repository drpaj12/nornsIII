"""Writes docs/plan/heap-picking.md from data/analysis/heappick.json (python3 scripts/heappick_doc.py [repo root])."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import heap_lib as hl


def f(s, nd=2, pct=False):
    """'median [lo90, hi90] (n=N)' of a summary dict."""
    if s is None or s["median"] is None:
        return "-"
    k = 100 if pct else 1

    def g(v):
        return f"{v * k:.{nd}f}" + ("%" if pct else "")

    return f"{g(s['median'])} [{g(s['lo90'])}, {g(s['hi90'])}] (n={s['n']})"


def pd_(s, key, nd=2, pct=False):
    v = s["per_design"].get(key)
    if v is None:
        return "-"
    return f"{v * (100 if pct else 1):.{nd}f}" + ("%" if pct else "")


def n_with(s, thr=0.0):
    """Designs whose per-design mean exceeds thr."""
    return sum(1 for v in s["per_design"].values() if v is not None and v > thr)


def build(S):
    P1, P2, P3, P4, P5, P6, P7, P9 = (S[k] for k in ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p9"))
    D = S["designs"]
    rows = S["p8_rows"]
    mid_nets = {(n["design"], n["atom"]) for n in S["p7_nets"] if 8 < n["fanout"] <= 32}
    mid_designs = len({d for d, _a in mid_nets})
    L = []
    w = L.append
    w("# Picking from the critical heap: how the greedy packer goes wrong, and the exception HDL patterns (data only)")
    w("")
    w("Purpose: speed = critical + near-critical paths (hub purpose; Norns packing RQs; measure: speed and wirelength). Terminology (Peter 2026-10-29): the **critical heap** = the paths suspected "
      "critical; the packer greedily takes from it first; as it is worked a new heap forms; at the end a heap remains whose criticality has been pushed down to a floor it cannot get below. "
      "Study 1 (`docs/plan/critical-heap.md`, nornsIII #24) measured the heap. This study asks how the greedy pick goes wrong (questions P1 to P8) and, as Peter asked, keeps a catalogue "
      "of the exception HDL patterns: each pattern has a detector that works before packing and the hint it would give the packer. Data-first rule (Peter 10-26): this document measures and "
      "shows; every hint is UNTESTED and the hypotheses at the end are untested.")
    w("")
    w("## Plain-English summary")
    w("")
    w(f"* The packer does not see a moving heap. Its criticality is computed once, before packing, with one fixed delay for every net, and never updated in the default flow (VTR commit 3c9a4d23b2: "
      f"`update_timing_info` is called only from the analytical global placer). So the heap the packer works on is the pre-pack heap. Of the molecules it takes with a pack-time crit >= 0.90 "
      f"({f(P1['heap_picks_share'], 1, True)} of all picks), {f(P1['heap_picks_leave'], 0, True)} contain no atom of the post-route heap (seed picks {f(P1['seed_picks_leave'], 0, True)}, "
      f"candidate picks {f(P1['cand_picks_leave'], 0, True)}).")
    w(f"* Going the other way, {f(P1['route_heap_late'], 0, True)} of the post-route heap is packed in the second half of the cluster order, and {f(P1['route_heap_pc_lt_050'], 0, True)} had a pack-time crit below 0.50 "
      f"(the packer did not know they were critical). Filler by source: none of the post-route heap atoms came in through unrelated clustering or with a zero gain (median).")
    w(f"* The cuts. A reported near-critical path (crit >= 0.90) touches a median {f(P2['mean_visits'], 1)} clusters; the floor from capacity is {f(P2['mean_floor10'], 1)} (10 BLEs per cluster) "
      f"or {f(P2['mean_floor20'], 1)} (20, if every FLE held two LUTs). {f(P2['share_over_floor10'], 0, True)} of the paths are above the 10-BLE floor. "
      f"{f(P2['cause_full'], 0, True)} of the distinct crossing edges fall where the earlier cluster closed with all 10 FLEs used: the packer fills clusters to the brim, so almost every cut is a capacity cut. "
      f"What fills the cluster is mostly not the heap: in clusters that hold a post-route heap atom, {f(P5['nonheap_fle_share'], 0, True)} of the FLEs hold atoms outside the heap "
      f"(heap atoms occupy {f(P5['heap_fle_per_heap_cluster'], 1)} of 10 FLEs).")
    w(f"* Reconvergence. At a fork atom (two or more successors on near-critical paths) the clusters split the successors in {f(P3['fork_split'], 0, True)} of the cases (some with the fork, some not), "
      f"all with the fork in {f(P3['fork_all'], 0, True)}, none in {f(P3['fork_none'], 0, True)}. {f(P3['branch_cross_share'], 0, True)} of the crossing edges sit at a fork or join atom.")
    w(f"* Ties. The queue gain of the molecule picked equals that of another queued molecule in {f(P4['e0.0']['tie_rate'], 0, True)} of the picks (exact), {f(P4['e0.05']['tie_rate'], 0, True)} within 5%. "
      f"The tie is broken by queue order ({f(P4['e0.0']['earliest_queued'], 0, True)} of exact ties go to the molecule queued first, that is the scan order). Ties that involve a pack-time heap atom are few "
      f"({f(P4['e0.05']['hot_share'], 0, True)} of the 5% ties); on those the pick had a lower post-route crit than a tied heap competitor {f(P4['e0.05']['hot_lost'], 0, True)} of the time and a higher one {f(P4['e0.05']['hot_won'], 0, True)} (the intervals overlap).")
    w(f"* Max-over-pins. Only {f(P6['single_share'], 0, True)} of the pack-heap atoms with two or more input nets have a single critical pin; they stay in the post-route heap as often as the others "
      f"({f(P6['single_stay'], 0, True)} against {f(P6['multi_stay'], 0, True)}). A related effect is real: {f(P6['inherited_share'], 0, True)} of the picks made on a timing gain >= 0.90 are atoms whose own input pins are all below 0.50 "
      f"(the gain was inherited from a sibling sink of the net); they stay in the heap {f(P6['inherited_stay'], 0, True)} of the time, against {f(P6['own_stay'], 0, True)} for the picks with a critical pin of their own.")
    w(f"* High-fanout nets (more than 32 sinks, ignored by the packer's gain) are almost absent from the post-route near-critical nets: {f(P7['hf_net_share'], 1, True)} of them; "
      f"one net in all 15 designs (boundtop `tm3_sram_we`, fan-out 64, a write enable steering a 64-bit data word). Nets of 9 to 32 sinks, which the packer treats as ordinary nets, are present: "
      f"{len(mid_nets)} near-critical nets in {mid_designs} designs (seed 1), driven by comparison results, subtract borrow bits, state bits and enables.")
    n_low = sum(1 for r in rows if r["flow"] < 0.01)
    w(f"* HDL words. Of {len(rows)} word groups of >= 8 bits ({sum(1 for r in rows if r['src'] == 'odin')} from the Odin III attribution, {sum(1 for r in rows if r['src'] == 'port')} from top-level buses), "
      f"{100 * n_low / len(rows):.0f}% have under 1% of their bit pairs tied by dataflow (a net, or one atom in between). The stock packer already puts only {100 * statistics.median(r['co_cluster'] for r in rows):.0f}% of the "
      f"pairs of a word in one cluster (median) and spreads a word over {statistics.median(r['spread'] for r in rows):.1f} times the minimum number of clusters. Word-major grouping would therefore ask the packer to "
      f"bind bits that have no dataflow between them; the words with the most tied pairs (5 to 25%) are adder words (a 32-cell adder word: 12%) and a few LUT words.")
    w("* The catalogue (below) has 11 rows. The patterns with a measured effect on the pick or the cut: the parallel bus word (no dataflow), the fork atom, the capacity cut that is filled by non-heap atoms (a general mechanism, not an HDL exception), "
      "the decision-bit fan-out net, the timing gain inherited from a sibling sink, and logic fed by a hard block (pre-pack heap that does not stay).")
    w("")
    w("## Method and data")
    w("")
    w("* Runs: the 45 beta-0 census runs of the heap lane (15 VTR Verilog designs x seeds 1 to 3; `work/heap-out`; the `.net` of every run is byte-identical to the stock sweep run; no new VPR run was made). "
      "Post-route side: `norns-keep.db` (1000-path timing report per run, atoms named like the packer's). Netlist: the keep-sweep BLIF of each design. All stores read only.")
    w("* Pack-time crit pc(atom) and post-route crit rc(atom), the post-route heap (rc >= 0.90) and the pack-time heap (pc >= 0.90) are those of the heap lane (`scripts/heap_lib.py`, `heap_data.py`, reused as they are). "
      "pc is the pre-pack criticality of VPR's own static timing analysis (one delay of 1.338 ns for every net between logic blocks (carry hops excepted) in the pre-pack report of diffeq1, `pre_pack.report_timing.setup.rpt` in the run directory); "
      "it is read here from the census `P` records. The heap-lane document says VPR updates it as clusters close; that is wrong for the default flow (the only call that refreshes it is in the analytical global placer), "
      "and the numbers of that document do not change.")
    w("* Cluster of an atom: the `.net` (`clb[i]`, FLE slot `fle[j]`, 10 FLEs per clb in the Norns architecture); each `.net` cluster holds the atoms of exactly one census cluster (checked in every run: no mixed cluster). "
      "A cluster is *full* when all 10 FLEs hold an atom. Molecule root, the queue gains and the refusal records (`F`) come from the census (`packer/README.md`, Round 4 changes).")
    w("* Summary over designs as in the heap lane: per design the mean over its 3 seeds, then the median over designs with a 90% percentile bootstrap (2000 resamples of designs); n = designs with a value.")
    w("* Code: `scripts/heappick_lib.py` (census, `.net`, crossing causes, queue ties, fan-out, pair ties), `heappick_run.py` (P1 to P7, P9 per run), `heappick_groups.py` (P8), `heappick_data.py`, "
      "`heappick_analyze.py` (writes `data/analysis/heappick.json`), `heappick_figs.py`, `heappick_doc.py` (this file). Tests: `python3 tests/test_heappick.py` (19 tests).")
    w("")
    w("### How each question is measured")
    w("")
    w("* P1: a *pick* is a molecule added to a cluster (census `M`). Heap pick: any atom of the molecule has pc >= 0.90; it *leaves* if none of its atoms has rc >= 0.90 (an atom in no reported path has rc below the last reported crit, always below 0.90).")
    w("* P2: the distinct near-critical paths (crit >= 0.90) of the report. A path is cut at pads and hard blocks into runs of logic atoms (LUT, adder, FF in clb clusters); a launching register at the head is dropped (it is packed with the previous stage). "
      "BLEs = LUT and adder atoms; floor = sum over runs of ceil(BLEs / 10), or / 20; clusters touched = number of same-cluster segments. A crossing is two consecutive atoms of a run in different clusters (distinct edges over all paths). "
      "Its cause is read from the cluster that was packed first (it closed without taking the other atom): `full`, else `refused_pins` / `refused_route` (a census `F` record of the other atom's molecule, status 1 / 2), else queued but never taken, else never proposed.")
    w("* P3: fork atoms = atoms with >= 2 distinct successors on the near-critical paths (join = predecessors); `split` = some of them in the atom's cluster and some not.")
    w("* P4: the census is replayed in file order; the pending queue of a cluster = molecules with a `Q` record not yet added (`M`) or refused (`F`). The gains are queue-time gains: VPR never refreshes the gain of a molecule already in the queue (`add_molecule_to_pb_stats_candidates`: \"if already in queue, do nothing\"). "
      "A tie = another pending molecule with gain >= picked gain x (1 - epsilon). `hot` = a pack-time heap atom among the tied molecules.")
    w("* P5: clusters holding >= 1 post-route heap atom: FLEs with a heap atom against the other FLEs; `min clusters` = ceil(heap FLEs / 10).")
    w("* P6: per atom, the distinct input nets and their pack-time crit (`P` records); single-pin = best pin >= 0.90 and second best < 0.50. Timing gain inheritance: `update_timing_gain_values` gives an atom that drives a net into the cluster the *largest* pin crit over all sinks of that net; "
      "the census `A` timing gain >= 0.90 with all own input pins < 0.50 marks such a pick.")
    w("* P7: the nets between consecutive atoms of the near-critical paths, with the fan-out of the BLIF net (single-input buffers absorbed); the packer ignores nets above 32 sinks (`vpr.out`: `clb:32`).")
    w("* P8: see the section; P9: detector counts for the catalogue.")
    w("")

    # ---- P1
    w("## P1. Stale criticality")
    w("")
    w("| measure | median over designs [90% bootstrap] |")
    w("|---|---|")
    for lab, k, pct in (("share of all picks with pc >= 0.90", "heap_picks_share", True), ("heap picks that leave the heap", "heap_picks_leave", True), ("  seed picks", "seed_picks_leave", True),
                        ("  candidate picks", "cand_picks_leave", True), ("post-route heap packed in the second half of the cluster order", "route_heap_late", True),
                        ("post-route heap with pc < 0.50", "route_heap_pc_lt_050", True), ("post-route heap picked as unrelated filler (source 7)", "route_heap_unrelated", True),
                        ("post-route heap picked with zero queue gain", "route_heap_gainless", True), ("Spearman(pc, rc) over atoms seen in a report", "rho_pc_rc", False)):
        w(f"| {lab} | {f(P1[k], 2 if not pct else 0, pct)} |")
    w("")
    w("| design | pack-heap picks leaving (seed / candidate) | post-route heap late | pc < 0.50 |")
    w("|---|---|---|---|")
    for d in D:
        w(f"| {d} | {pd_(P1['heap_picks_leave'], d, 0, True)} ({pd_(P1['seed_picks_leave'], d, 0, True)} / {pd_(P1['cand_picks_leave'], d, 0, True)}) | {pd_(P1['route_heap_late'], d, 0, True)} | {pd_(P1['route_heap_pc_lt_050'], d, 0, True)} |")
    w("")
    w("Figure: `docs/figures/heap-picking/p1-picks-leaving.png`.")
    w("")
    w("Which pack-heap atoms stay (share of the atoms with pc >= 0.90 that are in the post-route heap, per design then median; designs with >= 10 such atoms):")
    w("")
    w("| category | stay | atoms (all runs) |")
    w("|---|---|---|")
    for k, v in sorted(P1["stay_by_category"].items()):
        w(f"| {k} | {f(v, 2)} | {v['atoms']} |")
    w("")
    w("Reading: the pick is made on a number that never moves, and 8 of 10 heap picks do not survive. The picks leave least in diffeq1, diffeq2 (42%, 46%) and stereovision2 (29%); "
      "in ch_intrinsics, mkPktMerge, stereovision1 and mkDelayWorker32B (shallow or hard-block designs) all or nearly all of them leave (100%, 100%, 100%, 99%). Stay by category is thin (n = designs with >= 10 such atoms): `after_hard_block` atoms (logic fed by a multiplier or a memory) stay 7% (n=5 designs); operator-view comparators (`relational`) stay 97% (n=3) and equality atoms 3% (n=5).")
    w("")

    # ---- P2
    w("## P2. Capacity cuts")
    w("")
    w("| measure | median [90% bootstrap] |")
    w("|---|---|")
    for lab, k, nd in (("near-critical paths (distinct)", "n_paths", 0), ("BLEs per path (mean)", "blen_mean", 1), ("clusters touched (mean)", "mean_visits", 1), ("floor, 10 BLEs per cluster (mean)", "mean_floor10", 1),
                       ("floor, 20 BLEs per cluster (mean)", "mean_floor20", 1), ("paths above the 10-BLE floor", "share_over_floor10", 0), ("paths above the 20-BLE floor", "share_over_floor20", 0),
                       ("paths of <= 10 BLEs (no hard block) that still touch >= 2 clusters", "short_split", 0), ("extra clusters over the floor, paths of > 10 BLEs", "long_extra", 1),
                       ("extra clusters over the floor, paths with a carry chain", "chain_excess", 1), ("extra clusters over the floor, paths without", "nochain_excess", 1),
                       ("distinct crossing edges", "n_cross_edges", 0)):
        pct = k in ("share_over_floor10", "share_over_floor20", "short_split")
        w(f"| {lab} | {f(P2[k], 0 if pct or nd == 0 else nd, pct)} |")
    w("")
    w("Cause of the crossing edges (earlier cluster read; share of distinct crossing edges):")
    w("")
    w("| cause | median [90% bootstrap] |")
    w("|---|---|")
    for lab, k in (("earlier cluster closed full", "cause_full"), ("not full, other atom refused (pins, status 1)", "cause_refused_pins"), ("not full, refused (routing, status 2)", "cause_refused_route"),
                   ("not full, queued but never taken", "cause_queued_not_taken"), ("not full, never proposed", "cause_not_proposed")):
        w(f"| {lab} | {f(P2[k], 0, True)} |")
    w("")
    w(f"{f(P2['full_also_refused'], 0, True)} of the full-cluster cuts were also refused by the legalizer earlier in that cluster. What happened to the atom left behind (all of them heap atoms), as a share of all capacity cuts:")
    w("")
    w("| what happened to the left-behind atom in the full cluster | share of capacity cuts |")
    w("|---|---|")
    for lab, k in (("never entered the queue of that cluster", "full_never_queued_heap"), ("queued; the picks after it all had gain >= its gain (outranked in queue order)", "full_queued_outranked_heap"),
                   ("queued; a later pick had a lower gain (it had left the queue: cleared after 30 pops, or refused)", "full_queued_then_dropped_heap"),
                   ("queued; no pick followed", "full_queued_cluster_closed_next_heap")):
        w(f"| {lab} | {f(P2[k], 0, True)} |")
    w("")
    w("(The categories do not add to 100% in the medians; per-design values are in `data/analysis/heappick.json`.)")
    w("")
    w("| design | paths | clusters touched | floor10 | floor20 | over floor10 | crossing edges | full |")
    w("|---|---|---|---|---|---|---|---|")
    for d in D:
        w(f"| {d} | {pd_(P2['n_paths'], d, 0)} | {pd_(P2['mean_visits'], d, 1)} | {pd_(P2['mean_floor10'], d, 1)} | {pd_(P2['mean_floor20'], d, 1)} | {pd_(P2['share_over_floor10'], d, 0, True)} | {pd_(P2['n_cross_edges'], d, 0)} | {pd_(P2['cause_full'], d, 0, True)} |")
    w("")
    w("Figure: `docs/figures/heap-picking/p2-visits-vs-floor.png`. Reading: the paths are not cut for want of space on the path (the floor would allow 1 to 2 clusters); they are cut where a cluster closed full, "
      "and the cluster was full of other atoms (P5). Every path of <= 10 BLEs touches two or more clusters in the median design.")
    w("")

    # ---- P3
    w("## P3. Reconvergence")
    w("")
    w("| measure | median [90% bootstrap] |")
    w("|---|---|")
    for lab, k, pct in (("fork atoms (>= 2 successors on near-critical paths) per design", "forks", False), ("fork atoms: successors split between the fork's cluster and others", "fork_split", True),
                        ("fork atoms: all successors in the fork's cluster", "fork_all", True), ("fork atoms: none in the fork's cluster", "fork_none", True), ("join atoms: split", "join_split", True),
                        ("crossing edges incident to a fork or join atom", "branch_cross_share", True), ("atoms (in clusters) on >= 2 near-critical paths", "atoms_on_ge2", True)):
        w(f"| {lab} | {f(P3[k], 0, pct) if pct else f(P3[k], 0)} |")
    w("")
    w("Reading: a shared atom can sit with only one of its paths, and mostly does. How many of the extra crossings are avoidable is not measurable from the census (the cluster that closed full could not take the other branch). "
      "The pre-pack version of the same count (atoms with >= 2 consumers on pins with pc >= 0.90) is in the catalogue.")
    w("")

    # ---- P4
    w("## P4. Ties at the top of the heap")
    w("")
    w(f"Choices = candidate picks with another molecule pending (median {f(P4['n_choice'], 0)} per design). The picked molecule is the best pending one in {100 - 100 * P4['not_top']['median']:.0f}% of the choices "
      f"(for the rest the census does not say why; a queue clear is one possibility). The queue-time gain differs by > 10% from the molecule gain at pick time in {f(P4['stale_gain'], 0, True)} of the candidate picks.")
    w("")
    w("| epsilon | tie rate | with a pack-heap atom among the tied (`hot`) | hot: picked less post-route-critical than a heap competitor | hot: picked more critical | picked = earliest queued | hot ties per design |")
    w("|---|---|---|---|---|---|---|")
    for e, lab in (("e0.0", "exact"), ("e0.01", "1%"), ("e0.05", "5%")):
        x = P4[e]
        w(f"| {lab} | {f(x['tie_rate'], 0, True)} | {f(x['hot_share'], 0, True)} | {f(x['hot_lost'], 0, True)} | {f(x['hot_won'], 0, True)} | {f(x['earliest_queued'], 0, True)} | {f(x['hot_n'], 0)} |")
    w("")
    w(f"Source of the picked molecule in exact ties (pooled over designs): {', '.join(f'{k} {v}' for k, v in P4['e0.0']['src_pooled'].items())}. Ties at gain zero: median share 0%.")
    w("")
    w("Figure: `docs/figures/heap-picking/p4-ties.png`. Reading: ties are common (a third of the picks are exact ties, source mostly transitive or connectivity); they are resolved by the order in which the molecules entered the queue "
      "(within the sinks of one net, the atom-id scan order of `packer/README.md`). Ties that involve the pack-time heap are rare; on those the picked molecule is the less post-route-critical one somewhat more often than the more critical one, with overlapping intervals. "
      "The per-design counts of `hot` ties are small (the median design has 4 exact and 55 within 1%), so the intervals are wide.")
    w("")

    # ---- P5
    w("## P5. Filler")
    w("")
    w("| measure | median [90% bootstrap] |")
    w("|---|---|")
    for lab, k, pct, nd in (("clusters holding a post-route heap atom, share of all clusters", "heap_clusters_share", True, 0), ("FLEs of those clusters that hold no heap atom", "nonheap_fle_share", True, 0),
                            ("heap FLEs per such cluster (of 10)", "heap_fle_per_heap_cluster", False, 1), ("heap clusters / minimum clusters for the heap FLEs", "heap_clusters_over_min", False, 1),
                            ("capacity cuts whose full cluster still holds a non-heap FLE", "full_cross_with_filler", True, 0)):
        w(f"| {lab} | {f(P5[k], nd, pct)} |")
    w("")
    w(f"Where the non-heap atoms of the heap clusters came from (pooled over runs): {', '.join(f'{k} {v}' for k, v in P5['filler_source_pooled'].items())} atoms. "
      "So the filler is not unrelated clustering (not one atom): it is ordinary connectivity and timing candidates, the seed of the cluster, and transitive atoms; the packer fills a cluster with the best-gain neighbours, and for most heap atoms those neighbours are not heap atoms. "
      "\"Went to non-heap atoms\" is true of 70% of the slots; \"a heap atom refused later for lack of space\" is measured by the capacity cuts of P2 (every cut at a full cluster that still holds a non-heap FLE, which is the typical case here).")
    w("")

    # ---- P6
    w("## P6. Max over pins")
    w("")
    w("| measure | median [90% bootstrap] |")
    w("|---|---|")
    for lab, k, pct in (("pack-heap atoms (>= 2 input nets) with a single critical pin", "single_share", True), ("  of those, in the post-route heap", "single_stay", True), ("pack-heap atoms with >= 2 critical pins, in the post-route heap", "multi_stay", True),
                        ("AUC of the best pin crit for post-route heap membership", "auc_max_pin", False), ("AUC of the mean pin crit", "auc_mean_pin", False),
                        ("timing-gain >= 0.90 picks with all own pins < 0.50 (inherited)", "inherited_share", True), ("  of those, in the post-route heap", "inherited_stay", True),
                        ("timing-gain >= 0.90 picks with an own pin >= 0.90, in the post-route heap", "own_stay", True), ("inherited picks per design", "inherited_n", False)):
        w(f"| {lab} | {f(P6[k], 2 if not pct else 0, pct) if k not in ('inherited_n',) else f(P6[k], 0)} |")
    w("")
    w("Reading: the best pin predicts the post-route heap well (AUC 0.93), better than the mean over pins, so the max rule is not the weak point; the weak point is that criticality is pre-pack, not that it is a maximum. "
      "The inheritance case is small in count and the intervals reach 0.")
    w("")

    # ---- P7
    w("## P7. High-fanout critical nets")
    w("")
    w("| measure | median [90% bootstrap] |")
    w("|---|---|")
    for lab, k in (("near-critical nets per design", "near_nets"), ("near-critical nets above the pack threshold (32 sinks)", "hf_net_share"), ("near-critical edges on such nets", "hf_edge_share"),
                   ("near-critical nets with > 16 sinks", "gt16_net_share"), ("near-critical nets with > 8 sinks", "gt8_net_share"), ("baseline: driver atoms with a net above 32 sinks", "all_hf_driver_share")):
        pct = k != "near_nets"
        w(f"| {lab} | {f(P7[k], 1 if pct else 0, pct)} |")
    w("")
    w("Near-critical nets with more than 8 sinks (seed 1; source text from the VTR benchmark):")
    w("")
    w("| design | sinks | atom | HDL line | HDL text | atom kind (block view / operator view) |")
    w("|---|---|---|---|---|---|")
    seen = set()
    for n in S["p7_nets"]:
        key = (n["design"], n["line"], n["fanout"])
        if key in seen:
            continue
        seen.add(key)
        txt = n["text"].replace("|", "/")
        w(f"| {n['design']} | {n['fanout']} | {n['typ']} | {n['line'] or '-'} | `{txt}` | {n['blk']} / {n['op']} |")
    w("")
    w("Reading: nets above 32 sinks are ignored by the packer's gain and are essentially never on a near-critical path (median 0%; the one exception is the 64-sink write enable of boundtop). The constructs on the nets of 9 to 32 sinks "
      "are decision bits: a comparison (`if (a > b)`), the borrow of a subtract that selects the quotient bit (blob_merge `diffN = dividend - divider`), state registers of an `always @(posedge clk)` block and enables. "
      "They are below the high-fanout threshold, so the packer treats them as ordinary nets.")
    w("")

    # ---- P8
    w("## P8. Harmful HDL grouping candidates")
    w("")
    w("Words: `odin` = word of an atom in a reported path (Odin III attribution; only a sample of the design's words, 36 of >= 8 atoms), `port` = a top-level bus of >= 8 bits and the logic atoms next to its pad bits (the same bus can appear in both). "
      "The Odin III word attribution is not available for the whole design in the kept data, and every design is one module after flattening, so the module level and the full word level are not measurable here. "
      "Tie share: over all pairs of the word's atoms (or 4000 sampled pairs): *flow* = a net joins the pair or one atom sits between them; *any* = flow or a common source or sink. Nets above 32 sinks do not count (as in the packer).")
    w("")
    w("| source | words | flow share < 1% | any share < 5% | median pairs in one cluster | median clusters / minimum | words with flow share >= 10% |")
    w("|---|---|---|---|---|---|---|")
    for src in ("odin", "port", "all"):
        rr = [r for r in rows if src == "all" or r["src"] == src]
        w(f"| {src} | {len(rr)} | {100 * sum(r['flow'] < 0.01 for r in rr) / len(rr):.0f}% | {100 * sum(r['any'] < 0.05 for r in rr) / len(rr):.0f}% | "
          f"{100 * statistics.median(r['co_cluster'] for r in rr):.0f}% | {statistics.median(r['spread'] for r in rr):.1f} | {sum(r['flow'] >= 0.10 for r in rr)} |")
    w("")
    hot = [r for r in rows if r["heap_rate"] > 0]
    rho1 = hl.spearman([r["flow"] for r in rows], [r["heap_rate"] for r in rows])
    rho2 = hl.spearman([r["flow"] for r in rows], [r["co_cluster"] for r in rows])
    w(f"Relation to P2 to P5: {len(hot)} of the {len(rows)} words hold a post-route heap atom; their flow share is {statistics.median(r['flow'] for r in hot):.2f} (median), the same as the others; "
      f"Spearman(flow share, heap rate) = {rho1:.2f}, Spearman(flow share, pairs in one cluster) = {rho2:.2f}. Words that are tied by dataflow:")
    w("")
    w("| design | word | bits | flow share | pairs in one cluster | atoms |")
    w("|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: -r["flow"])[:8]:
        w(f"| {r['design']} | {r['key']} | {r['n']} | {r['flow']:.2f} | {r['co_cluster']:.2f} | {r['kinds']} |")
    w("")
    w("Figure: `docs/figures/heap-picking/p8-word-ties.png`. Reading: the bits of a word are, in dataflow terms, parallel lanes: 9 of 10 words have under 1% of their bit pairs tied, and the stock packer already scatters them (median 7% of pairs in one cluster). "
      "The tied words are the adder words (carry chain: a 32-bit adder word has 12% of its pairs tied by the chain, and the stock packer puts 50% of its pairs in one cluster, the highest in the data). "
      "Grouping a word as a unit (word-major) is therefore a bet against what the dataflow says for the common word; it is the carry-chain words where grouping agrees with the dataflow.")
    w("")

    # ---- catalogue
    nchain = n_with(P9["chain_count"])
    ncoll = n_with(P9["collector_count"])
    nfork = n_with(P9["fork_atoms"])
    ndeep = n_with(P9["deep_atoms"])
    nmid = n_with(P9["mid_critical"])
    nhfc = n_with(P9["hf_critical"])
    nhard = n_with(P9["after_hard"])
    nsib = n_with(P9["sibling_nets"])
    nport_words = len({r["design"] for r in rows if r["flow"] < 0.01})
    w("## The exception HDL pattern catalogue")
    w("")
    w("Detectors use only data that exist before packing: the BLIF netlist (nets, fan-out, LUT levels, carry chains), Odin III provenance (HDL construct kinds, top-level buses, source lines) and the pre-pack criticality (VPR's own static timing analysis, "
      "`pre_pack.report_timing.setup.rpt`; here read from the census `P` records). Frequency = designs of the 15 with at least one instance and the size where it matters. Every hint is UNTESTED.")
    w("")
    w("| # | pattern and HDL shape | detector (exact rule) | frequency in the 15 designs | what greedy does with it (evidence) | implied packer hint (UNTESTED) |")
    w("|---|---|---|---|---|---|")
    w(f"| 1 | **Parallel bus word**, word-major trap. `reg [31:0] q; always @(posedge clk) q <= d;` bit i depends on bit i of another word only | a bus (top-level port `name[i]` or Odin word) of >= 8 bits whose logic atoms have < 1% of their pairs tied by flow (sampled pairs, nets > 32 sinks ignored) | "
      f"{100 * n_low / len(rows):.0f}% of {len(rows)} words, in {nport_words} designs | stock packing already splits them (median {100 * statistics.median(r['co_cluster'] for r in rows):.0f}% of pairs together, "
      f"{statistics.median(r['spread'] for r in rows):.1f}x the minimum clusters); no relation of tie share to heap membership (P8) | do not group the word; group by bit slice (bit i of the word with its next-stage bit i) |")
    w(f"| 2 | **Carry-chain adder word** (the aligned case). `assign s = a + b;` 32 bits | >= 8 adder cells chained cin to cout in the BLIF | {nchain} of 15 designs; median {f(P9['chain_count'], 0)} chains, {f(P9['chain_atoms'], 1, True)} of the logic atoms | "
      f"adder words are among the most tied words (32-cell word: 12% of pairs, 50% already in one cluster; P8); pack-heap chain atoms stay {f(P1['stay_by_category']['carry_chain'], 0, True)}; paths with a chain are cut {f(P2['chain_excess'], 1)} clusters over the floor, others {f(P2['nochain_excess'], 1)} | "
      f"group the word as a unit, start the chain at a cluster boundary, expect one cut per 20 adders |")
    w(f"| 3 | **Fork atom with divergent critical branches**. `x = f(a); y = g(x); z = h(x);` two critical consumers of one atom | atom with >= 2 distinct consumers on pins with pc >= 0.90 (pre-pack) | {nfork} of 15 designs; median {f(P9['fork_atoms'], 0)} atoms | "
      f"post-route: successors split in {f(P3['fork_split'], 0, True)} of the forks, {f(P3['branch_cross_share'], 0, True)} of the crossing edges are at a fork or join atom; pre-pack detector outcome: split {f(P9['fork_split'], 0, True)}, all together {f(P9['fork_all'], 0, True)}, none {f(P9['fork_none'], 0, True)} | "
      f"keep the fork atom with the consumer of larger downstream depth (more LUT levels to the endpoint); accept the cut on the other branch |")
    w(f"| 4 | **Capacity cut at a cluster filled by non-heap atoms**. any path longer than the room left in its cluster | generic, not an HDL exception: a pre-pack-critical (pc >= 0.90) path of >= 2 BLEs (every design has some) | "
      f"post-route: paths above the floor {f(P2['share_over_floor10'], 0, True)}; {f(P2['cause_full'], 0, True)} of cuts at a full cluster; {f(P5['nonheap_fle_share'], 0, True)} of FLEs in heap clusters are non-heap | "
      f"fills the cluster with best-gain neighbours (connectivity, transitive); heap atoms of the next path element are not reserved room | reserve slots: stop adding non-critical candidates while a pc >= 0.90 successor of an atom in the cluster is pending |")
    w(f"| 5 | **Decision-bit fan-out**. `if (a > b) w <= x; else w <= y;`, `diff = d - q; if (diff[31]) ...`, a state or enable bit steering a word | net of 9 to 32 sinks (below the packer's 32) whose driver is a relational operator, an adder carry-out, or a register, and with a pre-pack-critical sink pin | "
      f"{nmid} of 15 designs have a pre-pack-critical net of 9 to 32 sinks ({f(P9['mid_critical'], 0)} per design, median); {len(mid_nets)} near-critical post-route nets in {mid_designs} designs; drivers (pre-pack-critical nets, seed 1): {', '.join(f'{k} {v}' for k, v in S['p9_mid_driver_kinds'].items())} | "
      f"treated as an ordinary net (below the 32-sink threshold); what the packer does with their sinks is not measured here, only that they are on near-critical paths | pull the sinks of a decision bit into the driver's cluster in criticality order |")
    w(f"| 6 | **Very-high-fan-out control** (> 32 sinks): enable, reset, select of a wide word | net with > 32 sinks | {f(P9['hf_nets'], 0)} nets per design (clocks, resets, enables); pre-pack critical in {nhfc} designs; post-route near-critical: 1 net (boundtop `tm3_sram_we`, 64 sinks) | "
      f"ignored by the gain (`> high_fanout_threshold`); used only as a tie-break when the queue is empty | group its sinks by bit slice; low priority (rare) |")
    w(f"| 7 | **Deep non-adder cone** (longer than a cluster). a chain of > 10 LUT levels | combinational LUT level >= 11 on a non-adder atom (adders count once per chain) | {ndeep} of 15 designs (blob_merge: {int(P9['deep_atoms']['per_design']['blob_merge'])} atoms, max level 22; all others <= 7) | "
      f"in blob_merge 56 pack-heap atoms are deep, 9 post-route heap; paths of > 10 BLEs are cut {f(P2['long_extra'], 1)} clusters over the floor | expect >= ceil(depth/10) - 1 cuts; place the cuts on the lowest-fan-out nets |")
    w(f"| 8 | **Hard-block-fed logic**. `p = a * b; r <= p + c;` logic after a multiplier or memory output | logic atom with an input net driven by a hard block (multiplier, memory) | {nhard} of 15 designs; {f(P9['after_hard'], 1, True)} of the logic atoms (median) | "
      f"pack-heap atoms of this kind stay in the post-route heap {f(P1['stay_by_category']['after_hard_block'], 0, True)}; the pre-pack delay model charges every net hop the same, hard blocks included | discount pc for paths through a hard block; do not spend heap picks on them |")
    w(f"| 9 | **Timing gain inherited from a sibling sink**. an atom that drives a net with one critical and several non-critical sinks | atom picked with timing gain >= 0.90 and all own input pins < 0.50 (census), predictable pre-pack: driver of a net whose largest sink crit >= 0.90 and whose connecting sink crit < 0.50 | "
      f"{f(P6['inherited_share'], 0, True)} of picks made on a high timing gain (median; {f(P6['inherited_n'], 0)} picks per design; the detector here is the census outcome, its pre-pack form is not counted); stay {f(P6['inherited_stay'], 0, True)} against {f(P6['own_stay'], 0, True)} | "
      f"`update_timing_gain_values` takes the largest crit over all sinks of the net (INPUT case) | use the crit of the pin that connects to the cluster instead of the maximum over the net |")
    w(f"| 10 | **Equal-criticality sibling set / tie-prone fan-out**. bit-parallel logic fed by one net | net with >= 3 sinks of identical pc >= 0.90 (within 0.001) | {nsib} of 15 designs have one; exact ties on {f(P4['e0.0']['tie_rate'], 0, True)} of the picks in general | "
      f"tie broken by queue order ({f(P4['e0.0']['earliest_queued'], 0, True)}); on hot exact ties the pick was lower post-route than a heap competitor {f(P4['e0.0']['hot_lost'], 0, True)}, higher {f(P4['e0.0']['hot_won'], 0, True)} of the time (intervals overlap) | tie-break by downstream depth; weak evidence, low priority |")
    w(f"| 11 | **Collector or status register**. `always @(posedge clk) status <= {{a, b, c}};` read only at a pad | flip-flop whose output feeds no logic atom (only pads) | {ncoll} of 15 designs; median {f(P9['collector_count'], 0)} per design ({f(P9['collector_ff'], 1, True)} of flip-flops) | "
      f"measured non-problem: collector flip-flops are in the post-route heap {f(P9['collector_in_heap'], 0, True)} of the time (n designs with one: {P9['collector_in_heap']['n']}) | none needed; use as cluster filler (UNTESTED) |")
    w("")
    w("Rows 1, 3, 4, 5, 8 and 9 are the patterns with a measured effect on the pick or the cut; rows 6, 10 and 11 are measured non-problems or rare; rows 2 and 7 describe a case the data show only in a few designs. "
      "\"Frequency\" counts the designs of the keep sweep, which are the VTR Verilog benchmarks; it says nothing about other design families.")
    w("")

    # ---- hypotheses
    w("## Candidate hypotheses (untested)")
    w("")
    w("Each names the purpose (speed, wirelength; Norns packing RQs, no RQ ID is given in the brief) and the measure. None has been run.")
    w("")
    w("1. **Refresh criticality while packing.** The packer's pc never moves (P1); a timing update after every N clusters (or using the post-route heap of a first pass) raises the share of heap picks that stay above the 23% [11%, 45%] of the heap lane. Measure: stay rate, CPD. Needs VPR runs (the analytical-placer flow already calls the update).")
    w("2. **Reserve room on the path.** 98% of the cuts are capacity cuts in clusters that are 70% non-heap (P2, P5): hold FLEs open for a pending pc >= 0.90 successor. Measure: clusters touched per near-critical path against the floor, CPD.")
    w("3. **Keep the fork atom with the deeper branch** (row 3): a rule on the 57% to 67% of forks that split. Measure: crossings at fork atoms, CPD.")
    w("4. **Do not group parallel words** (row 1): 9 of 10 words have no dataflow between bits; compare word-major affinity against bit-slice affinity on the buses with flow share < 1%, and word-major on carry-chain words only. Measure: WL and CPD per word class.")
    w("5. **Use the connecting pin's crit** instead of the maximum over the net's sinks (row 9). Measure: stay rate of timing-gain picks.")
    w("6. **Pull decision-bit sinks to the driver** (row 5). Measure: crossings on 9 to 32-sink near-critical nets.")
    w("7. **Discount paths through hard blocks** in the pre-pack criticality (row 8): the 7% stay of logic after a multiplier or memory suggests the pre-pack model overcharges them. Measure: stay rate, CPD on diffeq and stereovision.")
    w("8. **Tie-break by downstream depth** (row 10); expected effect small (ties with the heap are few).")
    w("")
    w("## What could not be measured")
    w("")
    w("* Whether a cut was avoidable: the census records the candidates the packer proposed, not the ones it could have; a counterfactual needs a packer run.")
    w("* Words beyond the sample: the Odin III word attribution exists only for atoms in a reported path (36 words of >= 8 atoms), and the word membership files of the earlier rounds are not kept; the port buses stand in for the rest. Modules: one per design.")
    w("* Ties: the heap order is reconstructed from queue-time gains in the census; the census does not mark a queue clear (after 30 pops), so 1% of the picks (\"not top\") cannot be replayed.")
    w("* Source line text of near-critical nets is available only for atoms with a provenance line; one net (boundtop `tm3_sram_we`) has none.")
    w("* Paths: only the 1000 reported paths enter (so a deeper but unreported path can exist); designs with few near-critical paths (ch_intrinsics, mkPktMerge, stereovision1: 0 to 20) give thin P2 and P3 numbers.")
    w("* No VPR run was made; hypotheses 1 to 8 all need packer runs.")
    w("")
    return "\n".join(L) + "\n"


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    S = json.loads((root / "data/analysis/heappick.json").read_text())
    (root / "docs/plan").mkdir(parents=True, exist_ok=True)
    (root / "docs/plan/heap-picking.md").write_text(build(S))
    print("wrote docs/plan/heap-picking.md")


if __name__ == "__main__":
    main()
