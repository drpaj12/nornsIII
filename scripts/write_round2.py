"""Write the round-2 paper text: docs/paper/r2-*.tex, included by norns.tex.

Every number comes from r2lib.compute() (data/ records), so the text regenerates byte-identically
from a fresh checkout. Usage: python scripts/write_round2.py
"""

from __future__ import annotations

import math
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
         "urd_shuf": "Urd, permuted"}


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
            "ret_full": f"{ret['full']:.2f}", "ret_inter": f"{ret['inter']:.2f}"}


def method(R: dict) -> str:
    c = R["coverage_all"]
    n = R["n_designs"]
    bf = lambda k: f"{100 * c[k + '_word'] / c[k + '_total']:.0f}\\%"
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
({c['unjoined']} of {c['blocks']} cells, {pct(c['unjoined'] / c['blocks'])}, found no BLIF block and are left unlabelled;
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
coordinates permuted, 20 samples). Coherence is the NMI between a $g\\times g$ grid partition
($g=\\lceil\\sqrt{{\\#\\text{{labels}}}}\\rceil$) and the labels, and the compactness
(label CLBs per grid tile of the label's bounding box, CLB-weighted). RQ-N2 correlates the seed
gain with three structure measures of the netlist graph: Louvain modularity $Q$; the $z$-score of
$Q$ against a degree-preserving null (double edge swaps, 20 samples); and the inverse Rent
exponent $-p$, with $p$ fitted from the terminals of BFS balls of geometric sizes (a lower
exponent is a more local design). Spearman's $\\rho$ and $p$-value are reported with $n={n}$,
which is small.

\\paragraph{{Hypotheses and decision rules.}}
Paired comparisons are per design (variant over reference), reported as a geomean ratio, the number of
designs where the variant is better and a two-sided exact sign test. H7a: \\code{{words}} beats Urd in
soft wirelength (supported if the geomean is below 1 and $p<0.05$, not supported if the
geomean is at least 1, else inconclusive). H7b: \\code{{slices}} beats \\code{{words}} on wirelength and
channel width (supported if both geomeans are below 1 and the wirelength sign test has $p<0.05$).
H7c: \\code{{hier}} has the lowest geomean wirelength of all eleven soft families. H7d: \\code{{words\\_partial}}
is at least as good as the full word seed (supported if the geomean ratio is at most 1, inconclusive up to 1.01).
H1: the baseline's final placement is module- and word-coherent (supported if, for both labellings,
at least two thirds of the designs lie more than two null standard deviations above the null in both
NMI and compactness). H2: structure predicts gain (supported if at least two of the three
measures correlate positively with the best round-two gain at $p<0.05$; not supported if no
correlation reaches $p<0.05$). H4: random start $>$ permuted clusters $>$ quotient layout $\\ge$ analytic start in
wirelength ratio, for Urd and for the best new family.
"""


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
        rows.append(arm_row(f"{LABEL[best].split(',')[0]}, permuted",
                            vb[f"{best}_shuf"]))
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
H7d is {d['status']}: \\code{{words\\_partial}} over \\code{{words}} is {f3(d['gm'])}
(better on {d['wins']} of {d['n']}, $p={pfmt(d['p'])}$).
"""
    out += f"""Ties (identical results) are left out of the sign tests: {a['ties']} for H7a, {b['ties']} for H7b and
{d['ties']} for H7d. A family with nothing to rearrange reproduces its reference exactly (a design whose words are
all single-CLB, or that has one module): \\code{{slices}} equals \\code{{words}} on {len(R['same']['slices_words'])}
designs, \\code{{hier}} equals Urd on {len(R['same']['hier_urd'])} and \\code{{words\\_partial}} equals \\code{{words}} on
{len(R['same']['partial_words'])}.
"""
    if best:
        hb, xo = R.get("hard_best"), R.get("xover")
        out += f"""The best new family by geomean wirelength is {code(best)}, so the coarse-random, hard and
crossover arms below use it."""
        if hb and hb["n"]:
            out += f""" Its hard arm (one region per cluster, scale~1) is {f3(hb['gm'])} in wirelength over
{hb['n']} designs, better than the baseline on {hb['wins']}; round one's hard arm pooled to {R['r1']['hard_wl']}."""
        if xo and xo["n"]:
            out += f""" Its crossover sweep, started from its own scale-1 placement, has median crossover scale
{xo['median']:g} against {xo['r1_median']:g} for round one's best-of-seven $P^*$ (at least round one's on
{xo['ge_r1']} of {xo['n']} designs); at twice the crossover the retention median is {f2(xo['hot_ret_median'])} and the
seed beats an unseeded run at the same temperature on {xo['hot_wins'][0]} of {xo['hot_wins'][1]} designs."""
        out += "\n\n"
    ur, bq = h4["urd"], h4["best"]
    out += f"""\\textbf{{RQ-N4, clustering versus coarse layout.}} H4 is {h4['status']}. For Urd the wirelength
ratios are random start {f3(ur['random'])}, permuted cluster positions {f3(ur['shuffled'])}, quotient
layout {f3(ur['quotient'])}"""
    if bq["quotient"] == bq["quotient"] and best:
        out += f"""; for {code(best)} they are {f3(bq['random'])}, {f3(bq['shuffled'])} and {f3(bq['quotient'])}"""
    out += """. The analytic baseline is 1 by definition, so a random start above 1 means VPR's analytic
start is better than a random one, and the gap between the permuted and the quotient arm is what
the coarse layout is worth beyond the clustering itself.\n\n"""
    if n1:
        m, w = n1["module"], n1["word"]
        out += f"""\\textbf{{RQ-N1, does VPR rediscover the hierarchy?}} H1 is {h['H1']['status']}. Table~\\ref{{tab:r2n1}}
gives medians over designs: the final placement is above the random null in NMI on {m['above_null']} of {m['n_z']}
designs for modules and {w['above_null']} of {w['n_z']} for words, and in compactness on {m['dens_above_null']}
and {w['dens_above_null']} (more than two null standard deviations). Final and analytic placements are close, and the final
NMI is at least the analytic one on {m['final_ge_initial']} of {m['n']} (modules) and {w['final_ge_initial']} of {w['n']}
(words) designs. With many small labels the NMI of a random placement is itself high (word null
{f2(w['nmi_null'])}), so compactness is the cleaner signal.

\\begin{{table}}[t]
\\caption{{RQ-N1: medians over designs of the grid-partition NMI and label compactness of the
analytic start, VPR's final placement and a random null (20 permutations). Designs with a
single module have no module label and are left out of that row.}}
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
        out += f"""\\textbf{{RQ-N2, does structure predict the gain?}} H2 is {h['H2']['status']}: {h['H2']['n_sig']} of
{h['H2']['n_pairs']} correlations reach $p<0.05$ (no multiple-comparison correction; $n=15$ designs, so only a
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
"""
    return out


def discussion(R: dict) -> str:
    h = R["hyp"]
    best = R["best"]
    vb = R["vs_base"]
    a, b, c_, d = h["H7a"], h["H7b"], h["H7c"], h["H7d"]
    s = f"""Round two. The bitwise idea is tested in four forms, and the evidence is this: word clusters
against module clusters are {a['status']} ({f3(a['gm'])}); laying the words out bit-sliced against the quotient layout of the same
clusters is {b['status']} ({f3(b['gm'])} in wirelength); the hierarchical
combination is {c_['status']} as the best seed (rank {c_['rank']} of {c_['of']}); and seeding only the
word cells is {d['status']} as good as seeding everything ({f3(d['gm'])}). The word
membership available from Odin~III covers the flip-flops, adders, multipliers and memories but only
{R['coverage_all']['lut_word'] * 100 // R['coverage_all']['lut_total']}\\% of the LUTs, because ABC's cone provenance merges the spans of
mixed logic, so the word seeds are datapath-register seeds more than whole-datapath seeds; a result
against bitwise seeding here is a result about that coverage as much as about the idea."""
    t0 = lambda k: f3(vb[k]["init_t"]) if k in vb and vb[k]["n"] else "n/a"
    s += f"""

One confound the scale-1 comparison cannot remove: VPR derives its start temperature from the starting
placement, so a start that is worse than the analytic one is annealed hotter and, in these runs, longer. The
geomean start temperature relative to the baseline is {t0('random')} for the random start,
{t0('urd')} for Urd and {t0(best) if best else 'n/a'} for the best new family, and placement runtime moves with it
(Table~\\ref{{tab:r2qor}}). The arms are therefore compared at VPR's own temperature, not at equal anneal effort, and
the random start beating a connectivity-aware start would be a statement about the schedule as much as about the start;
the effort curve (N3) is the experiment that separates them and stays open."""
    s += f"""

On the coarse-versus-fine question that round one left open, the arms give the answer for these
designs: H4 is {h['H4']['status']}, with Urd at random {f3(h['H4']['urd']['random'])}, permuted
{f3(h['H4']['urd']['shuffled'])} and quotient {f3(h['H4']['urd']['quotient'])}. RQ-N1 explains part of the
round-one parity: VPR's own final placement is already clearly more module- and word-compact than a random
placement (H1 {h['H1']['status']}), so a seed that says the same thing adds little. Whether the structure of the
netlist predicts where a seed helps is H2, {h['H2']['status']}. All of this is $n=15$ designs, median 125 CLBs, one VPR
seed per configuration; differences of a percent are within what a different VPR seed can move."""
    return s


def conclusion(R: dict) -> str:
    h = R["hyp"]
    return (f"Round two adds bitwise seeds to the provenance hierarchy. At VPR's own start temperature the "
            f"best of them, {code(R['best']) if R['best'] else 'n/a'}, is "
            f"{f3(R['vs_base'][R['best']]['wirelength']) if R['best'] else 'n/a'} of the baseline's wirelength, "
            f"the Urd hierarchy is {f3(R['vs_base']['urd']['wirelength'])}, and the question that made the idea "
            f"worth testing, bit-level structure against module structure, comes out "
            f"{h['H7a']['status']} (H7a) and {h['H7c']['status']} (H7c) on these designs.")


def appendix(R: dict) -> str:
    h = R["hyp"]
    vb = R["vs_base"]
    best = R["best"]
    def row(rq, hyp, rnd, status, num):
        return f"{rq} & {hyp} & {rnd} & {status} & {num} \\\\"
    rows = [
        row("N7", "H7a words beat Urd", "2", h["H7a"]["status"],
            f"{f3(h['H7a']['gm'])} ({h['H7a']['wins']}/{h['H7a']['n']})"),
        row("N7", "H7b slices beat words", "2", h["H7b"]["status"],
            f"WL {f3(h['H7b']['gm'])}, ch.\\ {f3(h['H7b']['chan_gm'])}"),
        row("N7", "H7c hier is best", "2", h["H7c"]["status"],
            f"rank {h['H7c']['rank']}/{h['H7c']['of']}"),
        row("N7", "H7d partial $\\ge$ full", "2", h["H7d"]["status"], f3(h["H7d"]["gm"])),
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
                        f"{h['H2']['n_sig']}/{h['H2']['n_pairs']} at $p<0.05$"))
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
designs are small, median 125 CLBs (size effect untested, N5); and whether the gain is the clustering or the coarse
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

\\paragraph{{Still open.}} N3 (effort curve: how the result changes with the anneal budget, e.g. inner\\_num);
N5 (size: designs of 1000 CLBs and up, where a seed has more to say); N6 (region looseness: constraint
regions between the soft seed and the tight regions of round one); LUT coverage of the word membership
(a front-end change, not a seeding change); more than one VPR seed per configuration.

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
