"""Write the round-2 paper text: docs/paper/r2-*.tex, included by norns.tex.

Every number comes from r2lib.compute() (data/ records), so the text regenerates byte-identically
from a fresh checkout. Usage: python scripts/write_round2.py
"""

from __future__ import annotations

import statistics
import sys

import nornlib as nl
import r2lib
from r2lib import f2, f3, pfmt

PAPER = nl.WS / "docs" / "paper"
QUOTE = ("consider that bitwise is more relevant in the Norn path so we should consider that as "
         "an additional seeding aspect (not necessarily the entire HDL structure (though "
         "hierarchically yes)). Let's include this and run the next set of experiments noting "
         "this thought pattern in the appendix of each paper so we can see the progress ... "
         "write up into the papers findings.")
LABEL = {"urd": "Urd (round 1)", "louvain": "Louvain", "spectral": "Spectral",
         "affinity": "Affinity prop.", "kmeans_k": "k-means $k$",
         "kmeans_2k": "k-means $2k$", "kmeans_4k": "k-means $4k$",
         "words": "Words", "words_inter": "Words, inter only",
         "slices": "Slices", "hier": "Hier",
         "words_partial": "Words, partial", "random": "Random start",
         "urd_shuf": "Urd, permuted", "words_partial_shuf": "Words, partial, permuted"}


GAIN = {"urd": "the Urd gain", "best_r1": "the best round-one gain", "best_r2": "the best new-family gain"}
MEAS = {"q": "$Q$", "q_z": "$z(Q)$", "rent_p": "$-p$"}


def code(s: str) -> str:
    return "\\code{" + s.replace("_", "\\_") + "}"


def design_tex(name: str) -> str:
    return name.replace("_", "\\_")


def pct(x: float) -> str:
    return f"{100 * x:.1f}\\%"


def sentence_status(h: dict) -> str:
    return h["status"]


def round1() -> dict:
    """Round-one headline numbers from the round-one generators' summary and records."""
    import statistics
    import report
    s = nl.read_json(nl.WS / "docs" / "plan" / "paper-summary.json")
    data, designs = report.load_all()
    ret = {}
    for var in ("full", "inter"):
        vals = [float(r["retention"]) for d in designs for seed in report.FAMILIES
                for r in [report.pick(data[d], "soft", seed, var)]
                if r and r.get("retention") is not None]
        ret[var] = statistics.median(vals)
    return {"soft_wl": s["soft_wl"], "inter_wl": s["inter_wl"], "soft_chan": s["soft_chan"],
            "soft_runtime": s["soft_runtime"], "hard_wl": s["hard_wl"], "hard_runs": s["hard_runs"],
            "hard_better": s["hard_runs_better"],
            "hot_wins": sum(v[0] for v in s["hot_wins"].values()),
            "hot_n": sum(v[1] for v in s["hot_wins"].values()),
            "clb_median": s["benchmarks"]["clb_median"],
            "ret_full": f"{ret['full']:.2f}", "ret_inter": f"{ret['inter']:.2f}"}


def method(R: dict) -> str:
    c = R["coverage_all"]
    n = R["n_designs"]
    def bf(k: str) -> str:
        return f"{100 * c[k + '_word'] / c[k + '_total']:.0f}\\%"

    return f"""\\subsection{{Round two: bitwise seeds and structure analyses}}
\\label{{sec:r2-method}}

Round one seeded VPR with module-level clusters. Datapath logic is bit-level: a
32-bit register or adder is a regular stack of identical bit cells, and the carry chain
already shows that VPR places such stacks as ordered vertical runs. Round two therefore
adds a bit-level seeding aspect that keeps the module hierarchy at the coarse level
(Section~\\ref{{sec:r2-appendix}} records where the idea came from).

\\paragraph{{Word membership from Odin~III data, not names.}}
The obvious source, the provenance BLIF's block name \\code{{module/\\$nN@file:line}}, is too
coarse: the line is the HDL \\emph{{statement}}, so one \\code{{always}} block is one group (the
largest (module, file:line) group in any design holds up to {c['max_line_group'][0]} blocks,
and sha's holds 1739 of its 2506 blocks; {c['lines_multi']} of the {c['lines']} statement lines that
hold word blocks hold more than one word, up to {c['max_words_line']}). The finer records exist in the Odin~III session that
writes the BLIF, so the seed builder reruns the identical script, checks that the BLIF it
writes equals the kept one byte for byte ({'all' if c['identical'] else 'not all'} {n} designs
match), and reads the records Loki~III's labeller reads: the HDL name \\code{{bus[i]}} of a
cell's output net and the source spans of each cell, matched to the word-level cells that
exist before technology mapping. A final cell joins its BLIF block through the net id the BLIF
name carries (\\code{{\\$n<id>}}), so the join is by identifier, not by string
({c['unjoined']} of the {c['odin_cells']} Odin~III final cells, {pct(c['unjoined'] / c['odin_cells'])}, found no BLIF block and are left unlabelled,
from none to {pct(c['unjoined_worst']['share'])} per design, the worst being {code(c['unjoined_worst']['design'])} with {c['unjoined_worst']['n']} of {c['unjoined_worst']['of']};
the writer legalises dotted names, handled explicitly). A block's word is the first rule
that applies: (bus) an output net named \\code{{bus[i]}} puts it in word \\code{{bus}} at bit $i$,
which holds for every flip-flop that keeps a register name; (cell) exactly one word-level cell's
spans lie inside the block's spans, which is true for adders, multipliers, memories and
single-statement LUTs; otherwise (none) the block has no word. Bit order inside an adder word is
the carry-chain position. ABC's cone provenance merges the spans of a LUT that mixes words,
and its edge budget makes some runs share one record, so {bf('lut')} of the LUTs get a word
against {bf('ff')} of the flip-flops and {bf('hard')} of the hard cells. Over all designs,
{pct(c['in_word'] / c['blocks'])} of the blocks are in a word (per-design median
{pct(c['median_share'])}); {c['words']} words in all.

\\paragraph{{Seed families.}}
A CLB joins a word cluster when at least one third of its atoms carry a word and that word is
the plurality; otherwise it keeps its Urd module cluster. Four families follow, each entering
VPR as a soft initial placement at VPR's own start temperature (scale~1).
\\code{{words}}: the word CLB groups are the clusters, arranged by the round-one quotient-graph
layout. \\code{{slices}}: the same clusters, but each word is laid out as a vertical run in bit
order (bit~0 on top, the carry-chain direction), runs of equal length aligned to the same rows,
so that bit $i$ of connected words shares a row; true carry chains are untouched.
\\code{{hier}}: Urd module clusters at the coarse level and, inside each module, the words as
bit-sliced runs. \\code{{words\\_partial}}: only the word CLBs are seeded, every other CLB keeps
VPR's analytic position (and every carry chain with an unseeded CLB stays whole). The
\\code{{words}} family also has the inter-cluster-only variant. Pads and multipliers stay
anchored as in round one.

\\paragraph{{Random and coarse-random arms (RQ-N4).}}
\\code{{random}} is a random legal start: every logic CLB takes a random slot and carry chains a
random window, fed as a soft seed at scale~1. The coarse-random arm keeps the clusters and
their within-cluster order but permutes the cluster positions on the die (\\code{{urd\\_shuf}} for
Urd, and the \\code{{*\\_shuf}} twin of the best new family).

\\paragraph{{Structure analyses (no VPR runs).}}
RQ-N1 measures, on each design's unseeded baseline, how module- and word-coherent three
placements are: VPR's analytic start, its final placement, and a random null (logic-CLB
coordinates permuted, 20 samples). A logic CLB carries the plurality label of its atoms (module: the Urd module; word:
the word with most atoms in the CLB; a CLB without one is unlabelled). Coherence is the NMI between a $g\\times g$ grid partition
of the labelled CLBs ($g=\\max(2,\\lceil\\sqrt{{\\#\\text{{labels}}}}\\rceil)$, the grid spanning the labelled CLBs' bounding box) and the labels. The compactness is a
separate metric that does not use the grid: the CLB-weighted mean over labels with at least two CLBs of the label's CLBs divided
by the area, in tiles, of the label's bounding box. A labelling is scored only with at least four labelled CLBs and two labels, and a design
is counted against the null only when the null's standard deviation is positive (counted separately for the two metrics). A design with
fewer than two real Urd modules (\\code{{diffeq1}} and \\code{{diffeq2}}, which have one module plus the artificial flat group, and \\code{{sha}} and \\code{{stereovision3}}, which have none)
has no module row. Label sets with fewer than {r2lib.TINY_LABELLED} labelled CLBs are flagged in the results. RQ-N2 correlates the seed
gain with three structure measures of the netlist graph: Louvain modularity $Q$; the $z$-score of
$Q$ against a degree-preserving null (double edge swaps, 10 per edge, 20 samples); and the inverse Rent
exponent $-p$, with $p$ fitted from the terminals of BFS balls of geometric sizes (a lower
exponent is a more local design). Spearman's $\\rho$ and $p$-value are reported with $n={n}$,
which is small, and again as partial correlations with the edge count regressed out, because graph size drives both $z(Q)$ and the gain.

\\paragraph{{Hypotheses and decision rules.}}
Paired comparisons are per design (variant over reference), reported as a geomean ratio, the number of
designs where the variant is better and a two-sided exact sign test. H7a: \\code{{words}} beats Urd in
soft wirelength (supported if the geomean is below 1 and $p<0.05$, not supported if the
geomean is at least 1, else inconclusive). H7b: \\code{{slices}} beats \\code{{words}} on wirelength and
channel width (supported if both geomeans are below 1 and the wirelength sign test has $p<0.05$).
H7c: \\code{{hier}} has the lowest geomean wirelength of all eleven soft families. H7d: \\code{{words\\_partial}}
is better than the full word seed (supported if the geomean ratio is below 1 and the wirelength sign test has $p<0.05$, not supported
if it is above 1 with $p<0.05$, else inconclusive; no equivalence margin was fixed, so ``at least as good'' is not testable here).
H1: the baseline's final placement is module- and word-coherent (supported if, for both labellings,
at least two thirds of the designs lie more than two null standard deviations above the null in NMI and at least two thirds in
compactness, the two counted separately; not supported if fewer than a third do for both labellings and both metrics). H2: structure predicts gain (supported if at least two of the three
measures correlate positively with the best round-two gain at $p<0.05$; not supported if no
correlation of either sign reaches $p<0.05$). H4: random start $>$ permuted clusters $>$ quotient layout $\\ge$ analytic start in
wirelength ratio, for Urd and for the best new family.

\\paragraph{{Which rules predate the data.}}
These rules were not registered anywhere outside the repository, so their order is stated from the commit times of
that repository. The decision-rule code for H7a to H7d and H4 was committed at 15:21 on 2026-10-24 and H1's rule (with the compactness
criterion) at 15:24, before the first round-two VPR data (15:38). Some of those rules were later found weak and
changed; the appendix lists the changes. After the first data: tie handling in the sign tests (ties left out) came with the first data
commit; the methodology text that states the rules was written at 17:31, after nine designs; the best family was frozen at
{R['best_n']} designs after their results were seen (so the hard, crossover and permuted arms of the best family use a choice made
on data); the H2 rule was briefly changed and reverted, and the H7d rule was replaced after review. The next round fixes every decision rule, and the equivalence margin of
H7d, in a commit before any run.
"""


def h7d_note(d: dict) -> str:
    return " (no evidence of a difference)" if d["status"] == "inconclusive" else ""


def h7d_phrase(d: dict) -> str:
    """H7d as a clause for the discussion."""
    return {"supported": "better than seeding everything",
            "not supported": "worse than seeding everything",
            "inconclusive": "not distinguishable from seeding everything"}[d["status"]]


def arm_row(label: str, v: dict) -> str:
    return (f"{label} & {f3(v['wirelength'])} & {f3(v['cpd_ns'])} & {f3(v['chan_width'])} & "
            f"{f3(v['place_s'])} & {f2(v['init_t'])} & {v['wins']}/{v['n']} \\\\")


def results(R: dict) -> str:
    h = R["hyp"]
    vb = R["vb"] = R["vs_base"]
    best = R["best"]
    rows = []
    for key in ("urd", "words", "words_inter", "slices", "hier", "words_partial", "random",
                "urd_shuf"):
        if key in vb and vb[key]["n"]:
            rows.append(arm_row(LABEL[key], vb[key]))
    if best and f"{best}_shuf" in vb and vb[f"{best}_shuf"]["n"]:
        rows.append(arm_row(LABEL.get(f"{best}_shuf", f"{best}_shuf"), vb[f"{best}_shuf"]))
    n = R["n_designs"]
    a, b, c_, d = h["H7a"], h["H7b"], h["H7c"], h["H7d"]
    h4 = h["H4"]
    n1 = R.get("n1")
    n2 = R.get("n2")
    sp = n2["spearman"] if n2 else {}
    out = f"""\\subsection{{Round two results}}
\\label{{sec:r2-results}}

\\begin{{table}}[t]
\\caption{{Round two: geomean ratios vs the unseeded baseline at scale~1 for the soft arms (Urd from
round one for reference). The last column is the number of designs where the routed wirelength is
below the baseline. WL is routed wirelength, Chan.\\ the minimum channel width, Time the
placement runtime, $T_0$ the anneal's start temperature that VPR derives from the
starting placement. Below 1.0 is better (except $T_0$, a diagnostic).}}
\\label{{tab:r2qor}}
\\centering
\\footnotesize\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lcccccc}}
\\toprule
Seed & WL & Delay & Chan.\\ & Time & $T_0$ & Better \\\\
\\midrule
{chr(10).join(rows)}
\\bottomrule
\\end{{tabular}}
\\end{{table}}

\\textbf{{RQ-N7, bitwise seeds ({n} designs, one VPR seed each).}}
H7a is {a['status']}: \\code{{words}} over Urd is {f3(a['gm'])} in wirelength, better on {a['wins']} of
{a['n']} designs (sign test $p={pfmt(a['p'])}$).
H7b is {b['status']}: \\code{{slices}} over \\code{{words}} is {f3(b['gm'])} in wirelength
(better on {b['wins']} of {b['n']}, $p={pfmt(b['p'])}$) and {f3(b['chan_gm'])} in channel width
(better on {b['chan_wins']} of {b['chan_n']}).
H7c is {c_['status']}: \\code{{hier}} ranks {c_['rank']} of {c_['of']} families at
{f3(c_['hier_gm'])}; the lowest is {code(c_['best_name'])} at {f3(c_['best_gm'])}.
H7d is {d['status']}{h7d_note(d)}: \\code{{words\\_partial}} over \\code{{words}} is {f3(d['gm'])}
(better on {d['wins']} of {d['n']}, $p={pfmt(d['p'])}$).
"""
    out += f"""Ties (identical results) are left out of the sign tests: {a['ties']} for H7a, {b['ties']} for H7b and
{d['ties']} for H7d. A family with nothing to rearrange reproduces its reference exactly (a design whose words are
all single-CLB, or that has one module): \\code{{slices}} equals \\code{{words}} on {len(R['same']['slices_words'])}
design(s), \\code{{hier}} equals Urd on {len(R['same']['hier_urd'])} and \\code{{words\\_partial}} equals \\code{{words}} on
{len(R['same']['partial_words'])}.
"""
    out += audit_text(R)
    pt = R.get("partial")
    if pt:
        share = [x["moved_words_partial"] / x["logic_memory_clbs"] for x in pt]
        lo = min(pt, key=lambda x: x["moved_words_partial"] / x["logic_memory_clbs"])
        hi90 = sum(1 for x in share if x >= 0.9)
        allm = sorted(x["moved_words_partial"] / x["placed_blocks"] for x in pt)
        out += f"""\\code{{words\\_partial}} places only the word CLBs, so how much of each design it moves matters for H7d
(Table~\\ref{{tab:r2partial}}). Of the logic and memory CLBs the seed moves a median of {100 * statistics.median(share):.0f}\\% per design
({hi90} of {len(pt)} designs at 90\\% or more, down to {100 * min(share):.0f}\\% on {design_tex(lo['design'])}); counting every placed block, pads and
multipliers included, which are anchored in every arm, the median is only {100 * statistics.median(allm):.0f}\\% (for example
{pt[0]['moved_words_partial']} of {pt[0]['placed_blocks']} on {design_tex(pt[0]['design'])}). Where the seed covers nearly all logic CLBs,
\\code{{words\\_partial}} differs little from \\code{{words}}, so H7d compares two similar placements; where it covers little (for example
{design_tex(lo['design'])}), most of the seed is VPR's own analytic start. H7d is
therefore a weak test of ``seeding fewer CLBs'' on the designs where the share is high.
"""
    if best:
        hb, xo = R.get("hard_best"), R.get("xover")
        out += f"""The best new family by geomean wirelength is {code(best)} (chosen on the {R['best_n']} designs whose
soft arms were complete when the hard and crossover arms were queued"""
        out += (f"""; over all {n} designs it is {code(R['best_now'])}""" if R['best_now'] != best else "")
        out += f"""), so the coarse-random, hard and crossover arms below use it. Its geomean of
{f3(vb[best]['wirelength'])} is a selected figure: the family was the best of four on those {R['best_n']} designs and is reported on
them (and on the {n - R['best_n']} added later), so it is biased low, and it lies inside the band of the other arms."""
        if hb and hb["n"]:
            out += f""" Its hard arm (one region per cluster, scale~1) is {f3(hb['gm'])} in wirelength over
{hb['n']} designs, better than the baseline on {hb['wins']}; round one's hard arm pooled to {R['r1']['hard_wl']} (all families, all designs)."""
            if hb["failed"] and hb["urd_n"]:
                out += f""" That figure is over the {hb['n']} survivors only, and the {len(hb['failed'])} designs that failed are among the largest, so
survivors flatter it. Round one's Urd hard arm over the same {hb['urd_n']} designs is {f3(hb['urd_gm'])} (better on {hb['urd_wins']}):
on equal designs the bitwise family's hard arm is {'worse' if hb['gm'] > hb['urd_gm'] else 'better'} than Urd's."""
            if hb["failed"]:
                out += (f""" The hard arm failed in VPR's initial placement on {len(hb['failed'])} designs
({', '.join(design_tex(x) for x in hb['failed'])}: no free sites for the constrained blocks, the same failure round one
had on blob\\_merge) and those are left out. The builder's region check counts a box as large enough when it holds as many logic sites
as the cluster's own CLBs; it does not count the unseeded CLBs that this family leaves at their analytic positions,
which can sit inside a box, so these failures may be builder-side rather than a property of hard regions.""")
        if xo and xo["n"]:
            miss = xo["nowin"]
            out += f""" Its crossover sweep, started from its own scale-1 placement, has median crossover scale
{xo['median']:g} against {xo['r1_median']:g} for round one's best-of-seven $P^*$ over the {xo['n']} of {xo['n_all']} designs where
it won at some scale (at least round one's on {xo['ge_r1']} of {xo['n']}); at twice the crossover the retention median is
{f2(xo['hot_ret_median'])} and the seed beats an unseeded run at the same temperature on {xo['hot_wins'][0]} of {xo['hot_wins'][1]} designs."""
            if miss:
                won = " and ".join(f"{miss[x]:g}$\\times$ on {design_tex(x)}" for x in miss)
                out += f""" {" and ".join(design_tex(x) for x in miss)} had no winning scale at all and are left out of
those medians and counts (round one won up to {won}). Counting them as failures, the family is at least round one's on
{xo['ge_r1']} of {xo['n_all']} designs, and the median over all {xo['n_all']} (a failure taken as below the lowest scale) is
{xo['median_all']:g} against {xo['r1_median_all']:g}."""
        out += "\n\n"
    ur, bq = h4["urd"], h4["best"]
    out += f"""\\textbf{{RQ-N4, clustering versus coarse layout.}} H4 is {h4['status']}. For Urd the wirelength
ratios are random start {f3(ur['random'])}, permuted cluster positions {f3(ur['shuffled'])}, quotient
layout {f3(ur['quotient'])}"""
    if bq["quotient"] == bq["quotient"] and best:
        out += f"""; for {code(best)} they are {f3(bq['random'])}, {f3(bq['shuffled'])} and {f3(bq['quotient'])}"""
    out += """. The analytic baseline is 1 by definition, so a random start """
    out += ("below 1 means the anneal from a random start ended with shorter wire than from VPR's analytic start"
            if ur["random"] < 1 else
            "above 1 means VPR's analytic start is better than a random one")
    out += """; the gap between the permuted and the quotient arm is what
the coarse layout is worth beyond the clustering itself."""
    if bq["quotient"] == bq["quotient"] and bq["shuffled"] == bq["shuffled"] and best:
        out += (f""" Permuting the cluster positions changes the wirelength by
{100 * (ur['shuffled'] / ur['quotient'] - 1):+.1f}\\% for Urd and {100 * (bq['shuffled'] / bq['quotient'] - 1):+.1f}\\% for
{code(best)} relative to the quotient layout (negative is shorter).""")
    out += "\n\n"
    if n1:
        m, w = n1["module"], n1["word"]
        out += f"""\\textbf{{RQ-N1, does VPR rediscover the hierarchy?}} H1 is {h['H1']['status']}. Table~\\ref{{tab:r2n1}}
gives medians over designs: the final placement is above the random null in NMI on {m['above_null']} of {m['n_z']}
designs for modules and {w['above_null']} of {w['n_z']} for words, and in compactness on {m['dens_above_null']} of {m['dens_n_z']}
and {w['dens_above_null']} of {w['dens_n_z']} (more than two null standard deviations). Modules are counted over {m['n']} designs, not 15 or 13:
\\code{{diffeq1}} and \\code{{diffeq2}} have a single module, whose second label is the artificial flat group, and \\code{{sha}} and
\\code{{stereovision3}} have none. {tiny_text(m, w)} Final and analytic placements are close, and the final
NMI is at least the analytic one on {m['final_ge_initial']} of {m['n']} (modules) and {w['final_ge_initial']} of {w['n']}
(words) designs. With many small labels the NMI of a random placement is itself high (word null
{f2(w['nmi_null'])}), so compactness is the cleaner signal.

\\begin{{table}}[t]
\\caption{{RQ-N1: medians over designs of the grid-partition NMI and label compactness of the
analytic start, VPR's final placement and a random null (20 permutations). Designs with fewer
than two real modules have no module label and are left out of that row.}}
\\label{{tab:r2n1}}
\\centering
\\footnotesize\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lccc}}
\\toprule
Labels & $n$ & NMI (start/final/null) & Comp.\\ (start/final/null) \\\\
\\midrule
Module & {m['n']} & {f2(m['nmi_initial'])}/{f2(m['nmi_final'])}/{f2(m['nmi_null'])} & {f2(m['dens_initial'])}/{f2(m['dens_final'])}/{f2(m['dens_null'])} \\\\
Word & {w['n']} & {f2(w['nmi_initial'])}/{f2(w['nmi_final'])}/{f2(w['nmi_null'])} & {f2(w['dens_initial'])}/{f2(w['dens_final'])}/{f2(w['dens_null'])} \\\\
\\bottomrule
\\end{{tabular}}
\\end{{table}}

"""
    if n2:
        def cell(g, p):
            v = sp.get(f"{g}~{p}")
            return "--" if v is None else f"{v['rho']:.2f} ({pfmt(v['p'])})"
        out += f"""\\textbf{{RQ-N2, does structure predict the gain?}} H2 is {h['H2']['status']}: {h['H2']['n_pos']} of
{h['H2']['n_pairs']} correlations are positive at $p<0.05$ and {h['H2']['n_neg']} negative (the hypothesis predicts positive; no multiple-comparison correction; $n=15$ designs, so only a
large $\\rho$ can be told from chance). Table~\\ref{{tab:r2n2}} lists Spearman's $\\rho$ (and $p$).

\\begin{{table}}[t]
\\caption{{RQ-N2: Spearman $\\rho$ ($p$) between per-design structure and seed gain
(1 - wirelength ratio): Urd round one, best of seven round-one families, best new family. The
inverse Rent exponent is $-p$.}}
\\label{{tab:r2n2}}
\\centering
\\footnotesize\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lccc}}
\\toprule
Gain & $Q$ & $z(Q)$ & $-p_{{\\text{{Rent}}}}$ \\\\
\\midrule
Urd, round one & {cell('urd', 'q')} & {cell('urd', 'q_z')} & {cell('urd', 'rent_p')} \\\\
Best round one & {cell('best_r1', 'q')} & {cell('best_r1', 'q_z')} & {cell('best_r1', 'rent_p')} \\\\
Best new family & {cell('best_r2', 'q')} & {cell('best_r2', 'q_z')} & {cell('best_r2', 'rent_p')} \\\\
\\bottomrule
\\end{{tabular}}
\\end{{table}}

{n2_size_text(R)}"""
    return out


def audit_text(R: dict) -> str:
    """Seed-file audit: the committed builders reproduce the seeds VPR ran from; the slices fallback."""
    au = R.get("audit")
    if not au:
        return ""
    all_same = all(v["identical_to_runs"] for v in au.values())
    fb = [d for d, v in au.items() if v["fallback_changes_slices"]]
    sw = [d for d, v in au.items() if v["slices_equals_words"]]
    hu = [d for d, v in au.items() if v["hier_equals_urd"]]
    mk_note = (" On \\code{mkDelayWorker32B} only 9 CLBs carry a word label, in 7 words, and no word has two CLBs off the carry chains."
               if "mkDelayWorker32B" in sw else "")
    out = f"""Seed audit. Rebuilding the seven round-two seed families from the kept word membership with the committed builders gives
{'seed files byte-identical to the ones VPR ran from on all ' + str(len(au)) + ' designs' if all_same else 'seed files that differ from the ones VPR ran from on some designs'};
so every \\code{{slices}} run used the column-major bit-order fallback of the committed code, and that fallback changes the slices
seed on {len(fb)} designs ({', '.join(design_tex(x) for x in fb)}). The designs where \\code{{slices}} equals \\code{{words}} as a seed file
({', '.join(design_tex(x) for x in sw) or 'none'}) and where \\code{{hier}} equals Urd ({', '.join(design_tex(x) for x in hu) or 'none'}) are equal because there is nothing to rearrange, not because
a code path was skipped.{mk_note}
"""
    return out + "\n"


def tiny_text(m: dict, w: dict) -> str:
    parts = []
    for lab, a in (("module", m), ("word", w)):
        if a["tiny"]:
            parts.append(f"{lab} labels on " + ", ".join(design_tex(x) for x in a["tiny"]))
    if not parts:
        return ""
    return ("Label sets with fewer than " + str(r2lib.TINY_LABELLED) + " labelled CLBs carry little information (" +
            "; ".join(parts) + ").")


def n2_size_text(R: dict) -> str:
    """Graph size as a confounder of the N2 correlations (partial Spearman controlling for edges)."""
    n2 = R["n2"]
    pe, ve = n2.get("partial_edges"), n2.get("vs_edges")
    if not pe or not ve:
        return ""

    def cell(g, p):
        v = pe.get(f"{g}~{p}")
        return "--" if v is None else f"{v['rho']:.2f} ({pfmt(v['p'])})"

    def rp(k):
        return f"$\\rho={ve[k]['rho']:.2f}$ (${peq(ve[k]['p'])}$)"

    nul = f"{n2['swaps_per_edge']}"
    return f"""Graph size is a confounder. The measure $z(Q)$ rises with the number of edges ({rp('q_z')}), and the gains fall with it: the best
new-family gain against edges is {rp('gain_best_r2')}, the best round-one gain {rp('gain_best_r1')}, Urd's {rp('gain_urd')}. Table~\\ref{{tab:r2n2p}}
repeats the correlations of Table~\\ref{{tab:r2n2}} as partial Spearman correlations with the rank of the edge count regressed out of both
variables. The null graphs behind $z(Q)$ use {nul} double edge swaps per edge on every design (an earlier run capped the swaps at 200000, which left
3.8 to 9.8 per edge on the five graphs above 20000 edges; the cap was removed and the null recomputed). The best-of-$k$ gains are maxima over $k$
families per design ($k=7$ round one, $k=4$ round two), a positively biased gain, and the noise of a single VPR seed per configuration is unquantified.

\\begin{{table}}[t]
\\caption{{RQ-N2 with graph size controlled: partial Spearman $\\rho$ ($p$) between structure and seed gain, the rank of the edge count
regressed out of both.}}
\\label{{tab:r2n2p}}
\\centering
\\footnotesize\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lccc}}
\\toprule
Gain & $Q$ & $z(Q)$ & $-p_{{\\text{{Rent}}}}$ \\\\
\\midrule
Urd, round one & {cell('urd', 'q')} & {cell('urd', 'q_z')} & {cell('urd', 'rent_p')} \\\\
Best round one & {cell('best_r1', 'q')} & {cell('best_r1', 'q_z')} & {cell('best_r1', 'rent_p')} \\\\
Best new family & {cell('best_r2', 'q')} & {cell('best_r2', 'q_z')} & {cell('best_r2', 'rent_p')} \\\\
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""


def peq(p: float) -> str:
    return "p<0.001" if p < 0.001 else f"p={p:.3f}"


def size_clause(R: dict, keys: list[str]) -> str:
    pe = R["n2"].get("partial_edges", {})
    parts = [f"{pe[k]['rho']:.2f}, ${peq(pe[k]['p'])}$" for k in keys if k in pe]
    return ("; it tracks graph size, and with the edge count regressed out the partial $\\rho$ is "
            + " and ".join(parts)) if parts else ""


def discussion(R: dict) -> str:
    h = R["hyp"]
    n1 = R["n1"]
    best = R["best"]
    vb = R["vs_base"]
    a, b, c_, d = h["H7a"], h["H7b"], h["H7c"], h["H7d"]
    s = f"""Round two. The bitwise idea is tested in four forms, and the evidence is this: word clusters
against module clusters are {a['status']} ({f3(a['gm'])}); laying the words out bit-sliced against the quotient layout of the same
clusters is {b['status']} ({f3(b['gm'])} in wirelength); the hierarchical
combination is {c_['status']} as the best seed (rank {c_['rank']} of {c_['of']}); and seeding only the
word cells is {h7d_phrase(d)} (H7d {d['status']}, {f3(d['gm'])}, better on {d['wins']} of {d['n']}). The word
membership available from Odin~III covers the flip-flops, adders, multipliers and memories but only
{R['coverage_all']['lut_word'] * 100 // R['coverage_all']['lut_total']}\\% of the LUTs, because ABC's cone provenance merges the spans of
mixed logic, so the word seeds are datapath-register seeds more than whole-datapath seeds; a result
against bitwise seeding here is a result about that coverage as much as about the idea."""
    def t0(k: str) -> str:
        return f2(vb[k]["init_t"]) if k in vb and vb[k]["n"] else "n/a"

    t0s = [v["init_t"] for k, v in vb.items() if v["n"] and (k in ("urd", "words", "words_inter", "slices", "hier", "words_partial",
                                                                    "random", "urd_shuf") or k.endswith("_shuf"))]
    t0lo, t0hi = f"{min(t0s):.1f}", f"{max(t0s):.1f}"
    bands = [vb[k]["wirelength"] for k in ("urd", "words", "words_inter", "slices", "hier", "words_partial",
                                           "random", "urd_shuf", f"{best}_shuf" if best else "") if k in vb and vb[k]["n"]]
    if bands:
        s += f"""

Every soft arm of Table~\\ref{{tab:r2qor}}, bitwise or not, random start included, lands between {f3(min(bands))} and
{f3(max(bands))} of the baseline's wirelength: a band of {100 * (max(bands) / min(bands) - 1):.1f}\\% in a geomean over
{R['n_designs']} designs. The conclusions below are conclusions about differences inside that band."""
    s += f"""

One confound the scale-1 comparison cannot remove: VPR derives its start temperature $T_0$ from the starting
placement, so a start that is worse than the analytic one is annealed hotter and, in these runs, longer. The
geomean start temperature relative to the baseline is {f2(vb['random']['init_t'])} for the random start,
{f2(vb['urd']['init_t'])} for Urd and {f2(vb[best]['init_t']) if best else 'n/a'} for the best new family, and placement runtime moves with it
(Table~\\ref{{tab:r2qor}}). The arms are therefore compared at VPR's own temperature, not at equal anneal effort. The confound
bears directly on four comparisons: H4 (random start, permuted and quotient layouts have $T_0$ of {t0('random')}, {t0('urd_shuf')} and {t0('urd')} times the baseline's, for Urd),
H7a (\\code{{words}} {t0('words')} against Urd {t0('urd')}), H7b (\\code{{slices}} {t0('slices')} against \\code{{words}} {t0('words')}) and H7d
(\\code{{words\\_partial}} {t0('words_partial')} against \\code{{words}} {t0('words')}; against the permuted Urd arm {t0('urd_shuf')}). The start temperatures
of the arms differ by {t0lo} to {t0hi} times the baseline's, and the direction of the bias is unknown: a hotter
start can erase more of the seed, or give the anneal more moves to repair a worse one. A random start beating a connectivity-aware start
would be a statement about the schedule as much as about the start. The effort curve (N3) is the experiment that separates the two, and it stays open."""
    s += f"""

On the coarse-versus-fine question that round one left open, the arms give these numbers: H4 is {h['H4']['status']}, with Urd at random {f3(h['H4']['urd']['random'])}, permuted
{f3(h['H4']['urd']['shuffled'])} and quotient {f3(h['H4']['urd']['quotient'])}. RQ-N1 measures part of the
round-one parity: VPR's final placement has {f2(n1['module']['dens_final'] / n1['module']['dens_null'])}$\\times$ the null's
module compactness and {f2(n1['word']['dens_final'] / n1['word']['dens_null'])}$\\times$ its word compactness (medians), which
is {h['H1']['status']} as a rediscovery of the hierarchy by the NMI-and-compactness rule, which suggests the placer already groups much of
what a module or word seed would group. Whether the structure of the
netlist predicts where a seed helps is H2, {h['H2']['status']}"""
    if h["H2"].get("n_neg"):
        s += f""" (the one correlation that reaches $p<0.05$ is negative: {', '.join(GAIN[k.split('~')[0]] + ' vs ' + MEAS[k.split('~')[1]] for k in h['H2']['neg'])}{size_clause(R, h['H2']['neg'])})"""
    s += f""". All of this is $n=15$ designs, median {R['r1']['clb_median']:g} CLBs, one VPR
seed per configuration; the seed-to-seed spread of VPR is not measured here, so differences of about a percent should not be read as effects."""
    return s


def conclusion(R: dict) -> str:
    h = R["hyp"]
    vb = R["vs_base"]
    bands = [vb[k]["wirelength"] for k in ("urd", "words", "words_inter", "slices", "hier", "words_partial",
                                           "random", "urd_shuf", f"{R['best']}_shuf" if R["best"] else "")
             if k in vb and vb[k]["n"]]
    return (f"Round two adds bitwise seeds to the provenance hierarchy. At VPR's own start temperature the "
            f"best of the four new families, {code(R['best']) if R['best'] else 'n/a'}, is "
            f"{f3(vb[R['best']]['wirelength']) if R['best'] else 'n/a'} of the baseline's wirelength; that is a figure "
            f"selected as the best of four on the data it is reported on, it sits inside the "
            f"{f3(min(bands))} to {f3(max(bands))} band that every soft arm falls in, and it is not an effect. "
            f"The question that made the idea worth testing, bit-level structure against module structure, comes out "
            f"{h['H7a']['status']} (H7a) and {h['H7c']['status']} (H7c) on these designs.")


def partial_table(R: dict) -> str:
    pt = R.get("partial")
    if not pt:
        return ""
    rows = "\n".join(f"{design_tex(x['design'])} & {x['placed_blocks']} & {x['logic_memory_clbs']} & {x['seeded']} & "
                      f"{x['moved_words_partial']} & {x['moved_words']} \\\\" for x in pt)
    return f"""\\begin{{table}}[t]
\\caption{{How much of each design the \\code{{words\\_partial}} seed places. Logic and memory CLBs only (pads and multipliers are
anchored in every arm); Seeded = CLBs in a word cluster that VPR's initial placement is given a slot for; Moved = CLBs whose seeded
position differs from VPR's analytic start, for \\code{{words\\_partial}} and for the full \\code{{words}} seed.}}
\\label{{tab:r2partial}}
\\centering
\\scriptsize\\setlength{{\\tabcolsep}}{{2pt}}
\\begin{{tabular}}{{lccccc}}
\\toprule
Design & Placed & Logic+mem. & Seeded & Moved (part.) & Moved (words) \\\\
\\midrule
{rows}
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""


def appendix(R: dict) -> str:
    h = R["hyp"]

    def row(rq, hyp, rnd, status, num):
        return f"{rq} & {hyp} & {rnd} & {status} & {num} \\\\"
    rows = [
        row("N7", "H7a words beat Urd", "2", h["H7a"]["status"],
            f"{f3(h['H7a']['gm'])} ({h['H7a']['wins']}/{h['H7a']['n']})"),
        row("N7", "H7b slices beat words", "2", h["H7b"]["status"],
            f"WL {f3(h['H7b']['gm'])}, ch.\\ {f3(h['H7b']['chan_gm'])}"),
        row("N7", "H7c hier is best", "2", h["H7c"]["status"],
            f"rank {h['H7c']['rank']}/{h['H7c']['of']}"),
        row("N7", "H7d partial better than full", "2", h["H7d"]["status"], f3(h["H7d"]["gm"])),
        row("N4", "H4 random $<$ permuted $<$ quotient", "2", h["H4"]["status"],
            f"{f3(h['H4']['urd']['random'])}/{f3(h['H4']['urd']['shuffled'])}/{f3(h['H4']['urd']['quotient'])}"),
    ]
    if "n1" in R:
        n1 = R["n1"]
        rows.append(row("N1", "H1 baseline already coherent", "2", h["H1"]["status"],
                        f"{n1['module']['above_null']}/{n1['module']['n_z']} mod., "
                        f"{n1['word']['above_null']}/{n1['word']['n_z']} word"))
    if "n2" in R:
        rows.append(row("N2", "H2 structure predicts gain", "2", h["H2"]["status"],
                        f"{h['H2']['n_pos']}+/{h['H2']['n_neg']}- of {h['H2']['n_pairs']} at $p<0.05$"))
    r1 = R["r1"]
    return f"""\\appendix
\\section{{Research log}}
\\label{{sec:r2-appendix}}

This log records the thought pattern of the study so a reader can follow how each result
produced the next question. Entries are dated; numbers are those of the generated tables.

\\paragraph{{2026-10-23, round one: the question and its hypotheses.}} Does seeding VPR's anneal from
netlist clusters or the provenance hierarchy improve placement, and how hot can the anneal start before it
destroys the seed? Hypotheses: a seed helps at VPR's own start temperature; the helpful temperature range
is bounded by a design-level crossover; the provenance hierarchy and recovered clusters differ; hard regions help or hurt.

\\paragraph{{2026-10-24, what round one said.}} Soft seeds sat at parity with the analytic baseline
(wirelength {r1['soft_wl']} full, {r1['inter_wl']} inter-cluster only; channel width {r1['soft_chan']}; runtime {r1['soft_runtime']}); hard regions were worse
({r1['hard_wl']}, {r1['hard_better']} of {r1['hard_runs']} better); seed retention was {r1['ret_full']}/{r1['ret_inter']} at scale~1 but a seeded run won only {r1['hot_wins']} of {r1['hot_n']} head-to-heads at twice the
crossover; Urd was the worst soft and the best hard seed.

\\paragraph{{2026-10-24, what it suggested.}} The baseline is VPR's connectivity-aware analytic
start, so \\emph{{better than random}} was never tested; the anneal budget may erase what a seed adds (an
effort curve is untested, N3); VPR's flat placement may already rediscover the structure the seed carries (N1); the
designs are small, median {r1['clb_median']:g} CLBs (size effect untested, N5); and whether the gain is the clustering or the coarse
layout was not separable (N4).

\\paragraph{{2026-10-24, Peter's bitwise idea.}} ``{QUOTE}''
Reading: Norns is the datapath path, bits are the unit of structure there, so word and bit-slice
structure is a seeding aspect of its own, with the module hierarchy kept at the coarse level.

\\paragraph{{2026-10-24, round two: questions and hypotheses.}} N7 (bitwise seeds): H7a to H7d.
N1: H1 (VPR rediscovers the hierarchy). N2: H2 (structure predicts the gain). N4: H4 (random start,
permuted clusters, quotient layout, analytic start). The word membership had to come from data: the
provenance BLIF line is a statement, so the membership is read from Odin~III's bus names and source spans and
joined by net id (Section~\\ref{{sec:r2-method}}); only about {R['coverage_all']['lut_word'] * 100 // R['coverage_all']['lut_total']}\\%
of the LUTs get a word.

\\paragraph{{2026-10-24, round two: outcomes.}} {h['H7a']['status'].capitalize()} for H7a, {h['H7b']['status']} for H7b,
{h['H7c']['status']} for H7c, {h['H7d']['status']} for H7d, {h['H4']['status']} for H4"""+(f""", {h['H1']['status']} for H1 and {h['H2']['status']} for H2""" if 'n1' in R and 'n2' in R else "")+f""";
the numbers are in Table~\\ref{{tab:r2log}} and Section~\\ref{{sec:r2-results}}.

\\paragraph{{2026-10-24, rules changed after the data.}} Two decision rules were touched after the
results were visible, and one count was corrected. (1) H2: the rule fixed in the methodology text was ``not supported if no correlation reaches
$p<0.05$''. When the full data showed one significant correlation, a negative one (best new-family gain against $z(Q)$,
$\\rho=-0.59$, $p=0.021$ with the null of the first run), the rule was briefly changed to count only positive correlations, which turned the status into
not supported. That change is reverted: under the rule as first written the status is {h['H2']['status']}. The null was then recomputed without
the cap on edge swaps (RQ-N2) and the correlation is $\\rho={R['n2']['spearman']['best_r2~q_z']['rho']:.2f}$, $p={pfmt(R['n2']['spearman']['best_r2~q_z']['p'])}$.
(2) H7d: the first rule called ``at least as good'' supported at a geomean ratio of 1 or below, with no test and no margin,
and so called H7d supported at {f3(h['H7d']['gm'])} (better on {h['H7d']['wins']} of {h['H7d']['n']}, $p={pfmt(h['H7d']['p'])}$). A geomean near
1 with a non-significant sign test is no evidence either way, so the status is {h['H7d']['status']} (``no evidence of a difference'').
(3) H1: the count of designs above the null in compactness was first divided by the number of designs scored on NMI; it now has its own
denominator, and the module row no longer counts the designs with fewer than two real modules (13 designs became {R['n1']['module']['n']}). The status of H1 did
not change.

\\paragraph{{Still open.}} N3 (effort curve: how the result changes with the anneal budget, e.g. inner\\_num);
N5 (size: designs of 1000 CLBs and up, where a seed has more to say); N6 (region looseness: constraint
regions between the soft seed and the tight regions of round one); LUT coverage of the word membership
(a front-end change, not a seeding change); more than one VPR seed per configuration.
Next round: H7d is to be tested as non-inferiority, which needs a stated margin on the geomean wirelength ratio; the
margin is to be fixed, together with every other decision rule, in a commit before any run, and chosen from the
run-to-run spread that several VPR seeds per configuration will measure. No margin is proposed from the present
single-seed data.

{partial_table(R)}
\\begin{{table}}[t]
\\caption{{Research questions and hypotheses of the study with status and the deciding number.}}
\\label{{tab:r2log}}
\\centering
\\footnotesize\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{@{{}}lp{{2.5cm}}lp{{1.5cm}}p{{2.2cm}}@{{}}}}
\\toprule
RQ & Hypothesis & Round & Status & Deciding number \\\\
\\midrule
R1 & soft seed stays at parity & 1 & supported & wirelength {r1['soft_wl']} \\\\
R1 & hard regions help & 1 & not supported & {r1['hard_wl']} ({r1['hard_better']}/{r1['hard_runs']}) \\\\
R1 & seeds win at $2\\times$ crossover & 1 & not supported & {r1['hot_wins']}/{r1['hot_n']} \\\\
{chr(10).join(rows)}
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""


def main(argv: list[str]) -> int:
    R = r2lib.compute()
    R["r1"] = round1()
    files = {"r2-method.tex": method(R), "r2-results.tex": results(R),
             "r2-discussion.tex": discussion(R), "r2-conclusion.tex": conclusion(R),
             "r2-appendix.tex": appendix(R)}
    for name, text in files.items():
        (PAPER / name).write_text(text, encoding="utf-8")
        print(f"wrote {PAPER / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
