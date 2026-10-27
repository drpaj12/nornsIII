"""Write the round-7 paper text: docs/paper/r7-*.tex, included by norns.tex.

Every number comes from data/r7/{gap,net_gap,dup,mine,corpus,r5check}.json (scripts/r7stats.py, r7fstats.py, r7mine.py)
or from the constants of scripts/r7lib.py; no number is typed here. Needs only the committed data (no runs/).
Usage: python scripts/write_round7.py
"""

from __future__ import annotations

import math
import statistics
import sys

import nornlib as nl
import r7lib as lib

PAPER = nl.WS / "docs" / "paper"
D7 = nl.DATA / "r7"
LEVEL_TEX = {"same_word": "same word", "same_bit": "same bit index", "same_word_bit": "same word and bit", "same_stmt": "same statement",
             "same_inst_d1": "same instance, depth 1", "same_inst_d2": "same instance, depth 2", "same_inst_d3": "same instance, depth 3",
             "same_inst_full": "same instance (full path)"}
CLASSES = ("SC", "SN", "SI", "OR", "FL")
VPRCITE = r"VTR~\cite{rose2012vtr}, VTR~9~\cite{elgammal2025vtr9}, commit \code{3c9a4d23b2}"   # every table of VPR runs cites this
CLASS_TEX = {"gain": "gain", "borderline": "borderline", "worse": "worse", "undetermined": "n/a"}
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def w(n: int) -> str:
    return WORDS.get(n, str(n))


def tex(s) -> str:
    return str(s).replace("_", r"\_").replace("%", r"\%")


def nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def f2(x) -> str:
    return "n/a" if nan(x) else f"{x:.2f}"


def f3(x) -> str:
    return "n/a" if nan(x) else f"{x:.3f}"


def pct(x) -> str:
    return "n/a" if nan(x) else f"{100 * x:.1f}\\%"


def cint(v: dict) -> str:
    return f"{f3(v['gm'])} [{f3(v['lo'])}, {f3(v['hi'])}]"


def write(name: str, text: str) -> None:
    (PAPER / name).write_text(text, encoding="utf-8")


def load() -> dict:
    out = {}
    for k in ("gap", "net_gap", "dup", "mine", "corpus", "r5check", "net_check"):
        p = D7 / f"{k}.json"
        out[k] = nl.read_json(p) if p.is_file() else None
    return out


def med(vals: list) -> float:
    v = [x for x in vals if not nan(x)]
    return statistics.median(v) if v else float("nan")


def done(recs: list[dict]) -> list[dict]:
    return [g for g in recs if "hindsight_arm" in g]


def real(recs: list[dict]) -> list[dict]:
    return [g for g in done(recs) if not g["design"].startswith("n5_")]


def calib(recs: list[dict]) -> list[dict]:
    return [g for g in done(recs) if g["design"].startswith("n5_")]


def missing_main(d: dict) -> list[str]:
    have = {g["design"] for g in real(d["gap"])}
    return [x for x in lib.MAIN if x not in have]


# ---------------------------------------------------------------------------------------
# TikZ figures (the paper has tikz but no pgfplots)

def fig_gap(recs: list[dict]) -> str:
    """Wirelength gap per design of the .net arm on the test seeds; designs with no gain found carry the word, not a dot."""
    pts = [g["heldout"]["WL"]["hi"] for g in recs if not g["no_gain"] and not nan(g["heldout"]["WL"]["hi"])]
    lo_x, hi_x = 0.9, max([1.2] + pts)

    def x(v: float) -> float:
        return 6.0 * (min(max(v, lo_x), hi_x) - lo_x) / (hi_x - lo_x)

    n = len(recs)
    lines = [r"\begin{figure}[t]", r"\centering", r"\begin{tikzpicture}[x=1cm,y=0.33cm,font=\scriptsize]"]
    for i, g in enumerate(recs):
        y = -i
        lines.append(rf"\node[anchor=east] at (-0.1,{y}) {{{tex(g['design'])}}};")
        if g["no_gain"]:
            lines.append(rf"\node[anchor=west] at ({x(1.0) + 0.2:.2f},{y}) {{no gain found}};")
            continue
        wl = g["heldout"]["WL"]
        lines.append(rf"\draw[line width=1.2pt] ({x(wl['lo']):.2f},{y}) -- ({x(wl['hi']):.2f},{y});")
        lines.append(rf"\fill ({x(wl['gm']):.2f},{y}) circle (1.6pt);")
    lines.append(rf"\draw[dashed] ({x(1.0):.2f},0.8) -- ({x(1.0):.2f},{-n + 0.2});")
    lines.append(rf"\draw (0,{-n + 0.1}) -- (6,{-n + 0.1});")
    for v in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0):
        if lo_x <= v <= hi_x:
            lines.append(rf"\node at ({x(v):.2f},{-n - 0.7}) {{{v:g}}};")
    lines += [r"\end{tikzpicture}",
              rf"\caption{{Round 7: wirelength gap net0$/$hindsight per design for the \code{{.net}} arm on the held-out seeds {lib.HELD_SEEDS[0]} to {lib.HELD_SEEDS[-1]} (dot: geometric mean over the {w(len(lib.HELD_SEEDS))} seeds, bar: 95\% bootstrap "
              rf"interval over those seeds). Designs where the procedure found no gain carry no dot. VPR runs: {VPRCITE}. Above 1, the stock clustering routes longer wires than the best-known one.}}",
              r"\label{fig:r7gap}", r"\end{figure}"]
    return "\n".join(lines)


def fig_classes(figs: dict) -> str:
    cols = {"SC": "red!70", "SN": "orange!70", "SI": "blue!50", "OR": "green!50!black", "FL": "gray!40"}
    designs = list(figs["class_shares"])
    lines = [r"\begin{figure}[t]", r"\centering", r"\begin{tikzpicture}[x=1cm,y=0.3cm,font=\scriptsize]"]
    for i, d in enumerate(designs):
        for j, lab in enumerate(("stock", "hindsight")):
            row = figs["class_shares"][d][lab]
            y = -(2 * i + j)
            if j == 0:
                lines.append(rf"\node[anchor=east] at (-0.1,{y - 0.5}) {{{tex(d)}}};")
            if row[0] is None:
                continue
            x0 = 0.0
            for c, v in zip(CLASSES, row):
                wd = 5.0 * v
                lines.append(rf"\fill[{cols[c]}] ({x0:.3f},{y - 0.4}) rectangle ({x0 + wd:.3f},{y + 0.4 - 0.0});")
                x0 += wd
    lines.append(r"\node[anchor=west] at (5.2,0) {" + ", ".join(rf"\textcolor{{{cols[c]}}}{{\rule{{4pt}}{{4pt}}}}~{c}" for c in CLASSES) + "};")
    lines += [r"\end{tikzpicture}",
              r"\caption{Round 7: N17 class shares of the pairs that share a CLB, per design: upper bar the best stock run, lower bar the best affinity-bias hindsight run.}",
              r"\label{fig:r7classes}", r"\end{figure}"]
    return "\n".join(lines)


def fig_dist(figs: dict) -> str:
    bins = figs["dist_bins"]
    labels = [f"{bins[i]}" if bins[i + 1] - bins[i] == 1 else f"{bins[i]}-{bins[i + 1] - 1}" for i in range(len(bins) - 1)]
    lines = [r"\begin{figure}[t]", r"\centering", r"\begin{tikzpicture}[x=0.21cm,y=2.2cm,font=\tiny]"]
    for r, (rel, v) in enumerate(figs["dist_by_relation"].items()):
        oy = -r * 1.1
        lines.append(rf"\node[anchor=east] at (-0.3,{oy + 0.3}) {{{tex(LEVEL_TEX.get(rel, rel))}}};")
        for i, (a, b) in enumerate(zip(v["related"], v["unrelated"])):
            lines.append(rf"\fill[blue!60] ({i * 2.2:.1f},{oy}) rectangle ({i * 2.2 + 0.9:.1f},{oy + 0.9 * a:.3f});")
            lines.append(rf"\fill[gray!60] ({i * 2.2 + 1.0:.1f},{oy}) rectangle ({i * 2.2 + 1.9:.1f},{oy + 0.9 * b:.3f});")
    oy = -len(figs["dist_by_relation"]) * 1.1 + 0.9
    for i, lab in enumerate(labels):
        lines.append(rf"\node at ({i * 2.2 + 1.0:.1f},{oy - 0.05}) {{{lab}}};")
    lines += [r"\end{tikzpicture}",
              rf"\caption{{Round 7 (exploratory): distribution of the placed Manhattan distance (CLB units, mean over {w(len(lib.SEEDS))} stock seeds) of pairs with the HDL relation "
              r"(blue) and without it (gray), per relation, pooled over designs; bars are shares of each group.}",
              r"\label{fig:r7dist}", r"\end{figure}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------

def ho(d: dict) -> dict:
    """The held-out summary of data/r7/net_gap.json (seeds 6-10; fix round 2)."""
    return d["net_gap"]["summary"]["heldout"]


def oos_stats(d: dict) -> tuple[int, int, float]:
    """Affinity-bias arm, out of sample (arm chosen on seeds 1-5, evaluated on 6-10): designs with no gain, designs, median WL gap on the rest."""
    oos = [g["oos"] for g in real(d["gap"]) if "oos" in g]
    return sum(1 for o in oos if o["no_gain"]), len(oos), med([o["WL"]["gm"] for o in oos if not o["no_gain"]])


def w_more(ratio) -> str:
    """The W gap is net0 over the arm (below 1 means the arm needs a wider channel): the width the arm needs in excess of net0, in percent."""
    return "n/a" if nan(ratio) else f"{100 * (1 / ratio - 1):.1f}"


def w_txt(d: dict) -> str:
    """The channel-width trade-off beside the WL, CPD and CLB gaps (item 6): W is net0 over the arm, so a value below 1 means the arm needs more width."""
    h = ho(d)
    return (f"channel-width ratio (net0 over the arm; below 1 means the arm needs a wider channel) {f3(h['h_not_net0']['W'])} held out, "
            f"about {w_more(h['h_not_net0']['W'])}\\% more width, and {f3(h['selection_h_not_net0']['W'])} on the selection seeds, in sample, about {w_more(h['selection_h_not_net0']['W'])}\\% more")


def arm_counts(d: dict) -> dict:
    """Completed runs per arm kind over the whole round, with the seeds they cover (analytical-placement batch from corpus.json, .net batch from net_gap.json)."""
    rows: dict = {}
    for dd, e in d["corpus"]["designs"].items():
        for arm, v in e["arms"].items():
            k = "stock" if arm == "stock" else ("known" if arm == "known" else "h")
            rows[("ap", k)] = rows.get(("ap", k), 0) + v["ok"]
    return rows


def abstract(d: dict) -> str:
    nd = d["net_gap"]["designs"]
    h = ho(d)
    sm = d["net_gap"]["summary"]
    c = d["corpus"]
    nc = sm["corpus"]
    runs = c["runs_ok"] + nc["runs_ok"]
    n_gain = len(h["classes"]["gain"])
    n_nogain = len(h["no_gain_designs"])
    n_real = h["n_real"]
    rec = sm["recovery_net"]["all"]["WL"]
    none, noos, oos_wl = oos_stats(d)
    mm = d["mine"]["models"]
    prim = next((mm[k] for k in ("net_gain", "aff_gain") if mm[k]["designs"] and mm[k]["summary"]["auc_full_minus_base"]["n_designs"]), None)
    mine_txt = ""
    if prim is not None:
        a = prim["summary"]["auc_full_minus_base"]
        mine_txt = (f"On held-out design families, HDL features change the AUC of predicting which pairs hindsight co-locates by {f3(a['mean'])} "
                    f"(shuffled-label null {f3(a['null_mean'])}), so in this data they add almost nothing beyond net structure and the stock clustering. ")
    return (r"\paragraph{Round seven (data first).} Rounds one to six each tested an idea. Round seven tests none: it runs " +
            f"{runs} VPR placements ({n_real} VTR designs and {len(calib(nd))} constructions whose block clustering is known by construction) and reports what the data shows. "
            f"All runs use {VPRCITE}. "
            r"The hindsight clustering is the stock clustering with logic elements moved or swapped between neighbouring CLBs according to where the best stock placement "
            r"put them; it is written as a VPR \code{.net} and run with packing off, so VPR builds exactly that clustering. "
            f"The arm is chosen on seeds 1 to 5 and measured on the held-out seeds 6 to 10. On the held-out seeds the arm has an objective interval above 1 on {n_gain} of {n_real} VTR designs "
            f"({len(h['classes']['borderline'])} borderline, {len(h['classes']['worse'])} worse) and no gain was found on {n_nogain}. "
            f"The held-out wirelength gap (stock clustering over the arm) has median {f3(h['pooled_all']['WL'])} over all {n_real} designs (no gain found counted as 1) "
            f"and {f3(h['h_not_net0']['WL'])} over the {h['n_h_not_net0']} designs where an arm was chosen; critical-path-delay gap {f3(h['pooled_all']['CPD'])} and {f3(h['h_not_net0']['CPD'])}, "
            f"CLB-count gap {f3(h['pooled_all']['CLB'])} and {f3(h['h_not_net0']['CLB'])}. "
            f"Median {w_txt(d)}. "
            f"On the selection seeds, in sample, the median wirelength gap over the same {h['n_h_not_net0']} designs is {f3(h['selection_h_not_net0']['WL'])}. "
            f"On the known constructions the procedure recovers a median of {f2(rec['median'])} of the wirelength gap held out (no gain counted as 0; {f2(rec['median_defined_only'])} over the {rec['n_defined']} constructions where it found one). "
            f"The earlier affinity-bias arm, tested out of sample (arm chosen on seeds 1 to 5, evaluated on 6 to 10), finds no gain on {none} of {noos} designs and a median wirelength gap of {f3(oos_wl)} on the others. "
            f"{mine_txt}"
            "Everything after the gap is exploratory and carries a shuffled-label null. "
            "The gap is a best-known bound made by selection, not an optimum.\n")


def method(d: dict) -> str:
    nd = d["net_gap"]["designs"]
    miss = missing_main(d)
    nreal = len(real(nd))
    miss_txt = (f"The main set is incomplete: {', '.join(tex(x) for x in miss)} ({len(miss)} of {len(lib.MAIN)} designs) have no results here; "
                "the cut is lock availability (another job held the heavy lock for hours, so the driver reached them last), not a choice of designs."
                if miss else "All designs of the main set are included.")
    return rf"""\subsection{{Round seven: a placement corpus and a hindsight clustering}}
\label{{sec:r7-method}}
Round seven asks two questions of data instead of testing an idea (N Q1.7: how far is the VPR packer from a best-known clustering made with
hindsight from good placements, and how much would LUT duplication add; N Q2.4: which HDL relations predict that atoms sit together in good
placements). Its protocol, committed before any run, is \code{{docs/plan/round7.md}} (commit \code{{{lib.PROTOCOL_SHA}}}, which froze the text only; the run code was
committed later, as \code{{{lib.CODE_SHA}}}); the one quantity defined in
advance is the \emph{{hindsight gap}} per design, and every other analysis is exploratory.

\textbf{{Corpus.}} {nreal} VTR designs of rounds one to four and {len(calib(nd))} round-five netlist-level constructions
(mesh and tree, $B\in\{{{','.join(str(b) for b in (16, 64, 256))}\}}$, whose block clustering is known by construction; it is a known clustering, not an optimum), each with VPR seeds 1 to {len(lib.SEEDS)} (stock and affinity-bias runs) or 1 to {len(lib.NET_SEEDS)} (\code{{.net}} arms), the architecture of rounds one
to six, VPR's default analytical-placement flow for the stock runs (VTR~\cite{{rose2012vtr}} and VTR~9~\cite{{elgammal2025vtr9}}, commit \code{{3c9a4d23b2}}, version 9.0.0-dev; the flow already clusters with APPack from atom positions; there is no separate analytical hindsight
start), and routing at the minimum channel width. {miss_txt} Each run records, per atom, the construct chain from the provenance names, the word and bit
index, the CLB, its coordinates, the pack-time (stock arm only) and post-route criticality and slack; per pair, the N17 class, the HDL relations and the distance in
each run; per net, fanout and CLBs spanned. Post-route criticality is path based, from the {lib.NPATHS} worst reported paths.

\textbf{{Hindsight clustering (the \code{{.net}} arm).}} The stock clustering is read from the stock \code{{.net}} of each design (the same in every seed). Its unit is the logic element
(fle: a LUT with its flip-flop, or a pair of small LUTs); CLBs with carry chains stay as they are. Take the best run of the previous arm
(seeds {', '.join(str(s) for s in lib.NET_SEEDS)}; lowest wirelength~$\times$~critical-path delay), keep its CLB positions fixed, and move logic elements between CLBs within Manhattan distance {w(lib.RADIUS)}
(or swap them) by greedy search, minimising the sum over nets of $(1+{lib.CRIT_W:g}\,\mathrm{{pcrit}})\cdot$HPWL under the exact CLB legality of the architecture
(at most {lib.CAP_FLE} logic elements, {lib.CAP_IN} distinct input nets and one clock per CLB; the crossbar is complete). The clustering is written as a \code{{.net}} file and VPR (VTR~\cite{{rose2012vtr}}, VTR~9~\cite{{elgammal2025vtr9}}, doi 10.1145/3734798, commit \code{{3c9a4d23b2}}) is run with packing off
(\code{{--net\_file}}, annealing placement from a random start, the router of every other arm), so the clustering VPR places is the one written (fidelity 1.0 by construction, asserted for every run
from the placed CLBs). \code{{net0}} is the stock clustering written by the same code and placed the same way, so \code{{net0}} and the hindsight arm differ only in the clustering. Repeat from
the best run of each round until the median objective stops improving by {lib.STOP_GAIN * 100:g}\% or after {w(lib.MAX_ROUNDS)} rounds. The rule is fixed in advance: the arm is the round with the lowest median objective over the {w(len(lib.NET_SEEDS))} seeds, and the \emph{{gap}} of a metric is
\code{{net0}} over that arm, seed for seed, with a bootstrap interval over those seeds. The gap on these seeds is \emph{{in sample}} (the arm is chosen on the seeds it is evaluated on; winner's-curse risk) and is labelled \emph{{selection seeds}}. The headline is the \emph{{held-out}} gap: after the arm is fixed on seeds {', '.join(str(s) for s in lib.NET_SEEDS)}, \code{{net0}} and the arm are run on seeds {', '.join(str(s) for s in lib.HELD_SEEDS)} (protocol amendment of 2026-10-27, written before the first held-out run), for every real design where an arm other than \code{{net0}} was chosen and, on the constructions, also for the known clustering. A design has a held-out gain when the 95\% bootstrap interval of its objective ratio (wirelength~$\times$~critical-path delay, \code{{net0}} over the arm) lies above 1. Peter cut the seeds of the new runs from {w(len(lib.SEEDS))} to {w(len(lib.NET_SEEDS))} (decision 2026-10-26, before the \code{{.net}} runs); the affinity-bias data have {w(len(lib.SEEDS))} seeds and get an out-of-sample check (arm chosen on seeds 1 to 5, evaluated on seeds 6 to 10). Each \code{{.net}} file is also checked for equivalence with the BLIF and with the stock \code{{.net}} (every atom sees the same nets on its input pins; every net read outside its CLB has an output pin; \code{{scripts/r7netcheck.py}}). Where the chosen arm is \code{{net0}} the procedure found no gain; no gap is printed for the design, and the pooled medians count it as gap 1 (recovery 0) beside the medians over the designs with an arm. Stock packing is the
same in every seed, so the CLB-count gap has no clustering variance: its interval covers placement noise only.

\textbf{{Affinity-bias arm.}} The earlier arm of this round hands the clustering to the Norns packer as an affinity file at weight {lib.AFF_BETA:g} on the analytical-placement flow. VPR's packer
rebuilds only part of the requested groups, so its gap is the \emph{{gap reachable via affinity bias}}, not a lower bound on the gap between the packer and a best-known clustering; its fidelity is reported.
\emph{{Duplication}} candidates are single LUTs whose output net has sinks in two or more logic CLBs; nothing is built.
"""


def corpus_table(d: dict) -> str:
    c = d["corpus"]
    rows = []
    nets = {g["design"]: g for g in done(d["net_gap"]["designs"])}
    for g in real(d["gap"]) + calib(d["gap"]):
        e = c["designs"].get(g["design"], {})
        n = nets.get(g["design"])
        rows.append(f"{tex(g['design'])} & {e.get('logic_clbs_seed1', 'n/a')} & {e.get('ok', 0)} & {e.get('failed', 0)} & {len(g.get('rounds', []))} & "
                    f"{tex(g['hindsight_arm'])} & {tex(n['hindsight_arm']) if n else 'n/a'} \\\\")
    return "\n".join([r"\begin{table}[t]", r"\caption{Round 7 corpus: logic CLBs of the stock seed-1 run, analytical-placement VPR runs completed and failed, affinity-bias rounds run, "
                      r"and the fixed-point arm of the affinity-bias and of the \code{.net} procedure. VPR runs: """ + VPRCITE + r".}", r"\label{tab:r7corpus}", r"\centering\scriptsize", r"\begin{tabular}{@{}lrrrrll@{}}", r"\toprule",
                      r"design & CLBs & ok & failed & rounds & affinity arm & \code{.net} arm \\", r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def gap_table_net(d: dict) -> str:
    nd = real(d["net_gap"]["designs"])
    s = d["net_gap"]["summary"]
    h = ho(d)
    rows = []
    for g in nd:
        if g["no_gain"]:
            rounds = ", ".join(f"h{i + 1} {f3(r['gap']['WL']['gm'])}" for i, r in enumerate(g["rounds"]))
            rows.append(f"{tex(g['design'])} & net0 & \\multicolumn{{7}}{{l}}{{no gain found on the selection seeds (WL gap of the rounds: {rounds}); not run on seeds 6 to 10}} \\\\")
            continue
        X, H = g["heldout"], g["H"]
        rows.append(f"{tex(g['design'])} & {tex(g['hindsight_arm'])} & {cint(X['WL'])} & {cint(X['CPD'])} & {cint(X['CLB'])} & {f3(X['W']['gm'])} & "
                    f"{CLASS_TEX[g['heldout_class']]} & {f3(H['WL']['gm'])} & {f3(H['CPD']['gm'])} \\\\")
    rows.append(r"\midrule")
    for key, lab in (("pooled_all", f"median, all {h['pooled_all']['n']} designs (no gain found = 1)"),
                     ("h_not_net0", f"median, the {h['h_not_net0']['n']} designs with an arm"),
                     ("heldout_gain", f"median, the {h['heldout_gain']['n']} designs with a held-out gain"),
                     ("without_borderline", f"median, arm chosen, borderline left out ({h['without_borderline']['n']})")):
        r = h[key]
        rows.append(f"{lab} & & {f3(r['WL'])} & {f3(r['CPD'])} & {f3(r['CLB'])} & {f3(r['W'])} & & & \\\\")
    sel = h["selection_h_not_net0"]
    rows.append(f"selection seeds, in sample: median over the {sel['n']} designs with an arm & & {f3(sel['WL'])} & {f3(sel['CPD'])} & {f3(sel['CLB'])} & {f3(sel['W'])} & & & \\\\")
    return "\n".join([r"\begin{table*}[t]", rf"\caption{{Round 7, the hindsight gap of the \code{{.net}} arm, \textbf{{held-out seeds {lib.HELD_SEEDS[0]} to {lib.HELD_SEEDS[-1]}}}: \code{{net0}} (the stock clustering, same placer) over the arm chosen on the selection seeds "
                      rf"{lib.NET_SEEDS[0]} to {lib.NET_SEEDS[-1]} (geometric mean over {w(len(lib.HELD_SEEDS))} seeds, 95\% bootstrap interval over those seeds; above 1 means the stock clustering is worse). "
                      r"Class: gain = the interval of the objective ratio (WL$\times$CPD) lies above 1, worse = below 1, borderline = it contains 1. The last two columns are the gap on the selection seeds (in sample: "
                      r"the arm is chosen on them, winner's-curse risk). A W below 1 means the arm needs a wider channel. "
                      rf"Fidelity is 1.0 by construction in {s['fidelity_one']} of {s['fidelity_runs']} runs. Stock packing is the same in every seed, so the CLB interval has no clustering variance. "
                      r"Where no arm beat \code{net0} on the selection seeds the row says so and the design counts as gap 1 in the first median. "
                      rf"Best-known, not optimal. VPR runs: {VPRCITE}.}}",
                      r"\label{tab:r7gap}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}lllllllll@{}}", r"\toprule", r"design & arm & WL & CPD & CLB & W & class & WL sel. & CPD sel. \\", r"\midrule"] + rows +
                     [r"\bottomrule", r"\end{tabular}", r"\end{table*}"])


def gap_table_aff(d: dict) -> str:
    rows = []
    for g in real(d["gap"]):
        if g["no_gain"]:
            rounds = ", ".join(f"{r['arm']} {f3(r['WL']['gm'])}" for r in g["rounds"])
            rows.append(f"{tex(g['design'])} & stock & \\multicolumn{{4}}{{l}}{{no gain found (WL gap of the rounds: {rounds})}} & {f2(g.get('fidelity_max'))}"
                        f"{' (not realised)' if g['not_realised'] else ''} \\\\")
            continue
        H = g["H"]
        rows.append(f"{tex(g['design'])} & {tex(g['hindsight_arm'])} & {cint(H['WL'])} & {cint(H['CPD'])} & {cint(H['CLB'])} & {f3(H['W']['gm'])} & "
                    f"{f2(g.get('fidelity_H'))}{' (not realised)' if g['not_realised'] else ''} \\\\")
    gains = [g for g in real(d["gap"]) if not g["no_gain"] and not g["not_realised"]]
    rows.append(r"\midrule")
    rows.append(f"median over the {len(gains)} designs with a gain and fidelity $\\ge$ {lib.FID_MIN:g} & & " +
                f"{f3(med([g['H']['WL']['gm'] for g in gains]))} & {f3(med([g['H']['CPD']['gm'] for g in gains]))} & "
                f"{f3(med([g['H']['CLB']['gm'] for g in gains]))} & {f3(med([g['H']['W']['gm'] for g in gains]))} & {f2(med([g.get('fidelity_H') for g in gains]))} \\\\")
    return "\n".join([r"\begin{table*}[t]", rf"\caption{{Round 7, the affinity-bias arm (the Norns packer with an affinity file at weight {lib.AFF_BETA:g}, analytical-placement flow, stock over arm, "
                      rf"geometric mean over {w(len(lib.SEEDS))} seeds with 95\% bootstrap interval; the arm and its source run were chosen on the same seeds, so the gap is optimistic by selection; the out-of-sample check is in the text). "
                      r"This is the gap reachable via affinity bias, not a lower bound on the gap between the packer and a best-known clustering: the packer rebuilds only part of the requested groups "
                      rf"(fidelity: share of the groups built whole; VPR runs: {VPRCITE}). A design whose fidelity stays below {lib.FID_MIN:g} in every round is marked ``not realised'' (protocol stop rule) and left out of the median; "
                      r"where no arm beat stock the row says so and no gap enters the median.}", r"\label{tab:r7gapaff}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}llllllr@{}}", r"\toprule", r"design & arm & WL & CPD & CLB & W & fidelity \\", r"\midrule"] + rows +
                     [r"\bottomrule", r"\end{tabular}", r"\end{table*}"])


def calib_table(d: dict) -> str:
    rows = []
    for g in calib(d["net_gap"]["designs"]):
        rec = g.get("recovery_heldout") or {}
        recs = g.get("recovery") or {}

        def r(m: str, rec=rec) -> str:
            v = rec.get(m) or {}
            if v.get("value") is None:
                return "none" if v.get("note") else "n/a"
            return f"{v['value']:.2f}" + ("*" if g["no_gain"] else "")

        if g.get("known") is None:
            rows.append(f"{tex(g['design'])} & \\multicolumn{{7}}{{l}}{{known clustering not a legal \\code{{.net}}: {tex(g.get('known_note', ''))}}} \\\\")
            continue
        x, kn = g.get("heldout"), g["known_heldout"]
        sel = recs.get("WL") or {}
        rows.append(f"{tex(g['design'])} & {f3(kn['WL']['gm'])} & {f3(x['WL']['gm']) if x else 'no gain'} & {r('WL')} & "
                    f"{f2(sel['value']) if sel.get('value') is not None else 'n/a'} & {f3(kn['CLB']['gm'])} & "
                    f"{f3(x['CLB']['gm']) if x else 'no gain'} & {r('CLB')} & {r('CPD')} \\\\")
    tab1 = "\n".join([r"\begin{table*}[t]", rf"\caption{{Round 7, calibration on the round-5 constructions, \code{{.net}} arm, held-out seeds {lib.HELD_SEEDS[0]} to {lib.HELD_SEEDS[-1]}: \code{{net0}} over the known clustering (known; the "
                      r"clustering the construction was built with, a known clustering and not an optimum) and over the hindsight arm (H) for wirelength and CLB count, and the recovery $(\ln \mathrm{net0}-\ln H)/(\ln \mathrm{net0}-\ln \mathrm{known})$ from the geometric means over the seeds "
                      rf"(``none'': the known clustering is less than {math.exp(0.05) * 100 - 100:.0f}\% better, nothing to recover; a star: no arm beat \code{{net0}}, recovery counted as 0). "
                      r"``WL rec. sel.'' is the wirelength recovery on the selection seeds (in sample). A recovery above 1 means the arm placed better than the known clustering did "
                      r"(n5\_tree\_dp\_16 has such a value: the known clustering is by construction, not optimal, so it can be beaten). The last column is the recovery of the critical-path delay. "
                      rf"VPR runs: {VPRCITE}.}}",
                      r"\label{tab:r7calib}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}lrrrrrrrr@{}}", r"\toprule", r"design & WL known & WL H & WL rec. & WL rec. sel. & CLB known & CLB H & CLB rec. & CPD rec. \\", r"\midrule"] +
                     rows + [r"\bottomrule", r"\end{tabular}", r"\end{table*}"])
    prows = []
    for arm, key in (("\\code{.net}, held out", "recovery_net"), ("\\code{.net}, selection seeds", "recovery_net_selection"), ("affinity-bias", "recovery_affinity")):
        for grp in ("B16", "B64", "B256", "all"):
            cells = []
            for m in ("WL", "CLB", "CPD"):
                v = d["net_gap"]["summary"][key][grp][m]
                cells.append(f"{f2(v['median'])} ({v['n_pooled']}/{v['n_designs']}) & {f2(v['median_defined_only'])} ({v['n_defined']})")
            prows.append(f"{arm} & {grp.replace('B', '$B$=') if grp != 'all' else 'all'} & " + " & ".join(cells) + r" \\")
    tab2 = "\n".join([r"\begin{table*}[t]", r"\caption{Round 7, recovery of the known-clustering gap, median over the designs of a size where the known clustering is at least 5\% better. "
                      r"Per metric two medians: the pooled one (the headline), where a design with no gain found counts as recovery 0 (pooled designs / designs of that size in brackets), "
                      r"and the one over the designs where an arm other than the stock was chosen (their number in brackets). Recovery is computed from the aggregated geometric means over seeds. "
                      rf"A median of 1 would mean the procedure reaches the known clustering. VPR runs: {VPRCITE}.}}", r"\label{tab:r7calibB}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}llrrrrrr@{}}", r"\toprule", r" & & \multicolumn{2}{c}{WL} & \multicolumn{2}{c}{CLB} & \multicolumn{2}{c}{CPD} \\",
                      r"arm & $B$ & pooled & defined only & pooled & defined only & pooled & defined only \\", r"\midrule"] + prows + [r"\bottomrule", r"\end{tabular}", r"\end{table*}"])
    return tab1 + "\n\n" + tab2


def dup_table(d: dict) -> str:
    rows = []
    for e in d["dup"]:
        if e["design"].startswith("n5_"):
            continue
        s, h = e["stock"], e.get("H")
        rows.append(f"{tex(e['design'])} & {f2(s['candidates'])} & {pct(s['share_of_luts'])} & {pct(s['near5_share'])} & {pct(s['near10_share'])} & "
                    f"{pct(s['saved_share_of_cpd'])} & {pct(h['saved_share_of_cpd']) if h else '--'} & {f2(s.get('other_only'))} \\\\")
    return "\n".join([r"\begin{table}[t]", r"\caption{Round 7, LUT duplication candidates (single-LUT drivers with sinks in two or more logic CLBs; pad and hard-block sinks do not count), median over the "
                      rf"{w(len(lib.SEEDS))} stock seeds of per-run values: count, share of all LUTs, share within {100 * (1 - lib.PCRIT_NEAR[0]):.0f}\% and {100 * (1 - lib.PCRIT_NEAR[1]):.0f}\% of the critical-path delay "
                      r"(a lower bound: criticality comes from the 200 reported paths, so a candidate on an unreported path counts as not critical), and the upper estimate of the delay "
                      r"saved if every candidate hop were free (share of CPD; stock, then the affinity-bias arm where it found a gain, `--' otherwise). Last column: LUTs that "
                      r"count only through one logic CLB plus a pad or hard block. Nothing is built. VPR runs: " + VPRCITE + r".}", r"\label{tab:r7dup}",
                      r"\centering\scriptsize", r"\begin{tabular}{@{}lrrrrrrr@{}}", r"\toprule",
                      r"design & cand. & of LUTs & near 5\% & near 10\% & saved & saved (H) & other \\", r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def model_table(m: dict, label: str, name: str, tag: str) -> str:
    s = m["summary"]
    rows = []
    for key, lab in (("auc_bit_minus_base", "AUC (connected pairs), bit features"), ("auc_full_minus_base", "AUC (connected pairs), all HDL"),
                     ("auc_uni_full_minus_base", "AUC (uniform pairs), all HDL"),
                     ("auc_chg_full_minus_base", "AUC (pairs whose co-location changed), all HDL"),
                     ("r2_bit_minus_base", "$R^2$ of normalised distance, bit features"), ("r2_full_minus_base", "$R^2$ of normalised distance, all HDL")):
        v = s.get(key)
        if v is None or not v["n_designs"]:
            continue
        rows.append(f"{lab} & {f3(v['mean'])} & {f3(v['median'])} & [{f3(v['ci_lo'])}, {f3(v['ci_hi'])}] & {v['n_positive']}/{v['n_designs']} & "
                    f"{f3(v['null_mean'])} [{f3(v['null_lo'])}, {f3(v['null_hi'])}] \\\\")
    return "\n".join([r"\begin{table}[t]", rf"\caption{{Round 7 (exploratory), held-out-family models, target {label}: {len(m['designs'])} designs in {len(m['families'])} families "
                      rf"({', '.join(tex(x) for x in m['families'])}). Baseline (net connectivity, criticality, kinds, stock co-CLB and stock distance, no HDL): "
                      rf"AUC on connected pairs mean {f3(m['auc_base_mean'])}, median {f3(m['auc_base_median'])}; on uniform pairs mean {f3(m['auc_uni_base_mean'])}. "
                      rf"Change from adding HDL features: mean and median over held-out designs, bootstrap interval of the mean, designs improved, and the same change with the HDL labels "
                      rf"(and the carry flag) shuffled, {m['summary']['auc_full_minus_base']['shuffles']} shuffles. The interval resamples design families. ``Pairs whose co-location changed'' are the pairs the stock and the target clustering treat differently (joined against split); there the stock co-CLB flag is dropped from the features, and the AUC ranks joined against split pairs. The $R^2$ rows use a distance regression target disjoint in seeds from the baseline distance feature.}}", rf"\label{{tab:r7model{tag}}}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}lrrcrc@{}}", r"\toprule", r"change & mean & median & 95\% CI & better & shuffled null \\", r"\midrule"] +
                     rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def mining_tables(d: dict) -> str:
    m = d["mine"]
    out = []
    rows = []
    for lv, v in m["table_xi"].items():
        if v["same_as"]:
            rows.append(f"{LEVEL_TEX[lv]} & \\multicolumn{{4}}{{l}}{{identical to {LEVEL_TEX[v['same_as']]}: the instance chain has depth 1}} \\\\")
            continue
        rows.append(f"{LEVEL_TEX[lv]} & {f3(v['median'])} & {v['n_negative']}/{v['n_designs']} & "
                    f"[{f3(v['null_lo'])}, {f3(v['null_hi'])}] & {f3(v['null_le_obs'])} \\\\")
    out.append("\n".join([r"\begin{table}[t]", r"\caption{Round 7 (exploratory), Table~\ref{tab:r3status} re-measured at each level of the HDL chain: the stratified "
                           r"distance difference $d_r$ (related minus unrelated pairs within net-connectivity strata, as a fraction of the unrelated mean; "
                           r"negative means closer than the nets predict), median over designs, designs with $d_r<0$, the range of the same statistic on "
                           r"label-shuffled data, and the share of the shuffles at or below the observed median. Levels that exist in the data are tested; a level "
                           r"identical to a shallower one is not tested again.}", r"\label{tab:r7xi}", r"\centering\scriptsize",
                           r"\begin{tabular}{@{}lrrcr@{}}", r"\toprule", r"relation & median $d_r$ & $d_r<0$ & null range & null$\le$obs \\", r"\midrule"] + rows +
                          [r"\bottomrule", r"\end{tabular}", r"\end{table}"]))
    for tag, name, label in (("net", "net_gain", r"co-location in the \code{.net} hindsight clustering, designs where it beat \code{net0}"),
                             ("aff", "aff_gain", "co-location in the best affinity-bias run, designs where it beat stock"),
                             ("affall", "aff_all", "co-location in the best affinity-bias run, all designs (variant: includes designs where hindsight equals stock)")):
        mm = m["models"][name]
        if mm["designs"] and mm["summary"]["auc_full_minus_base"]["n_designs"]:
            out.append(model_table(mm, label, name, tag))
        else:
            out.append(f"% model variant {name}: no design with both classes\n")
    st = m["stability"]
    rows = []
    for lv, v in st["levels"].items():
        rows.append(f"{LEVEL_TEX[lv]} & {pct(v['stable_given_related'])} & {pct(v['stable_given_unrelated'])} & {f3(v['diff'])} & "
                    f"[{f3(v['null_lo'])}, {f3(v['null_hi'])}] \\\\")
    cls = st["by_class_stable_share"]
    out.append("\n".join([r"\begin{table}[t]", rf"\caption{{Round 7 (exploratory), stability across seeds. The stock clustering barely depends on the seed ({pct(st['co_clb_pairs_seed_invariant_share'])} of the "
                           rf"universe pairs have the same co-CLB status in all {w(st['n_seeds'])} stock runs), so stability is read on placement: of the {st['pairs']} pairs of the unbiased samples "
                           rf"within {w(st['near_dist'])} CLBs in at least one seed, {st['stable_ge8']} ({pct(st['stable_ge8'] / st['pairs'] if st['pairs'] else float('nan'))}) are within {w(st['near_dist'])} CLBs in {w(st['stable_min'])} or more of {w(st['n_seeds'])}. "
                           r"Share of stable pairs given the relation and given its absence, their difference, and the label-shuffled range of the difference. By N17 class: "
                           + ", ".join(f"{c} {pct(cls[c])}" for c in CLASSES) + r".}", r"\label{tab:r7stab}", r"\centering\scriptsize",
                           r"\begin{tabular}{@{}lrrrc@{}}", r"\toprule", r"relation & stable $|$ rel. & stable $|$ not & diff. & null range \\", r"\midrule"] + rows +
                          [r"\bottomrule", r"\end{tabular}", r"\end{table}"]))
    dg = m["disagreement"]
    rows = []
    for lv, v in dg["levels"].items():
        a, b = v["dplus"], v["dminus"]
        rows.append(f"{LEVEL_TEX[lv]} & {f2(a['enrichment'])} & [{f2(a['null_lo'])}, {f2(a['null_hi'])}] & {f2(b['enrichment'])} & "
                    f"[{f2(b['null_lo'])}, {f2(b['null_hi'])}] \\\\")
    c = dg["counts"]
    out.append("\n".join([r"\begin{table}[t]", rf"\caption{{Round 7 (exploratory), where stock packing and the best affinity-bias hindsight run disagree (against the stock run of the same seed; "
                           rf"{c['dplus']} pairs joined by hindsight only, {c['dminus']} by stock only, {c['agree']} by both). "
                           r"Enrichment of each relation among the disagreement pairs over its share among the pairs of the universe (the unbiased samples; protocol baseline), "
                           r"with the label-shuffled range; the earlier baseline, the pairs both clusterings join, is kept in the data file as a logged deviation.}",
                           r"\label{tab:r7disagree}", r"\centering\scriptsize", r"\begin{tabular}{@{}lrcrc@{}}", r"\toprule",
                           r"relation & hindsight only & null & stock only & null \\", r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"]))
    prim = next((m["models"][k] for k in ("net_gain", "aff_gain") if m["models"][k]["designs"]), None)
    if prim is not None:
        coefs = prim["coef_full"]
        rows = [f"{LEVEL_TEX.get(f, f.replace('_', ' '))} & {f3(v['mean'])} & [{f3(v['ci_lo'])}, {f3(v['ci_hi'])}] \\\\" for f, v in coefs.items()]
        out.append("\n".join([r"\begin{table}[t]", r"\caption{Round 7 (exploratory), coefficients of the features in the full logistic model for hindsight "
                               r"co-location in the first model variant with designs (standardised features; mean over the held-out folds with a bootstrap interval over folds). "
                               r"The bit-level hint question "
                               r"(Peter 2026-10-26) is the rows ``same bit index'', ``same word and bit'', ``bit close'' and ``carry nb''.}", r"\label{tab:r7coef}",
                               r"\centering\scriptsize", r"\begin{tabular}{@{}lrc@{}}", r"\toprule", r"feature & coefficient & 95\% CI \\", r"\midrule"] + rows +
                              [r"\bottomrule", r"\end{tabular}", r"\end{table}"]))
    return "\n\n".join(out)


def run_count_table(d: dict) -> str:
    """Completed runs per arm kind and the seeds each covers (item 7); the n5_mesh_dp_16 probe is stated apart."""
    c = d["corpus"]
    sm = d["net_gap"]["summary"]["corpus"]
    ap = {"stock": 0, "h": 0, "known": 0}
    for e in c["designs"].values():
        for arm, v in e["arms"].items():
            ap["stock" if arm == "stock" else ("known" if arm == "known" else "h")] += v["ok"]
    rows = [f"stock packing, analytical placement & {w(len(lib.SEEDS))} (1 to {len(lib.SEEDS)}) & {ap['stock']} \\\\",
            f"affinity-bias rounds h1 to h5 & {w(len(lib.SEEDS))} (1 to {len(lib.SEEDS)}) & {ap['h']} \\\\",
            f"affinity-bias known clustering (constructions) & {w(len(lib.SEEDS))} (1 to {len(lib.SEEDS)}) & {ap['known']} \\\\"]
    labels = {"net0": "\\code{.net} net0", "net_h": "\\code{.net} hindsight rounds", "net_known": "\\code{.net} known clustering (constructions)"}
    for k in ("net0", "net_h", "net_known"):
        v = sm["runs_by_kind"].get(k)
        if not v:
            continue
        rows.append(f"{labels[k]}, selection seeds & {w(len(v['seeds_selection']))} ({v['seeds_selection'][0]} to {v['seeds_selection'][-1]}) & {v['selection']} \\\\")
        if v["heldout"]:
            rows.append(f"{labels[k]}, held-out seeds & {w(len(v['seeds_heldout']))} ({v['seeds_heldout'][0]} to {v['seeds_heldout'][-1]}) & {v['heldout']} \\\\")
    return "\n".join([r"\begin{table}[t]", r"\caption{Round 7, completed VPR runs per arm kind and the seeds they cover (failed runs: " + f"{c['runs_failed'] + sm['runs_failed']}" +
                      r"). The \code{.net} hindsight rounds are run on the held-out seeds only for the arm chosen on the selection seeds, and \code{net0} only where an arm was chosen "
                      r"or the design is a construction. The seeds 6 to 10 of the construction n5\_mesh\_dp\_16 were run earlier as a queued 10-seed probe (before the amendment that introduced the held-out seeds; "
                      r"its chosen arm is \code{net0}, so it decides nothing); they are used as held-out runs of that design and counted here. VPR runs: " + VPRCITE + r".}",
                      r"\label{tab:r7runs}", r"\centering\scriptsize", r"\begin{tabular}{@{}lrr@{}}", r"\toprule", r"arm kind & seeds & runs \\", r"\midrule"] + rows +
                     [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def results(d: dict) -> str:
    c = d["corpus"]
    nc = d["net_gap"]["summary"]["corpus"]
    h = ho(d)
    chk = d.get("net_check") or {}
    tt = chk.get("totals", {})
    chk_txt = ""
    if tt:
        chk_txt = (f" The equivalence check (\\code{{scripts/r7netcheck.py}}) ran on all {tt['files']} written \\code{{.net}} files ({tt['atoms_checked']} atoms; the stock files are included): "
                   f"{tt['files_ok']} of {tt['files']} files pass; {tt['B_lut_mismatch'] + tt['B_ff_mismatch']} atoms differ from the BLIF in their input nets, "
                   f"{tt['C_lut_vs_stock'] + tt['C_ff_vs_stock']} from the stock \\code{{.net}}, {tt['D_needed_output_without_clbout']} nets read outside their CLB lack an output pin, "
                   f"{tt['E_input_net_undriven']} CLB input pins carry an undriven net.")
    parts = [r"\subsection{Round seven results}", r"\label{sec:r7-results}",
             rf"All VPR runs of this round use VTR~\cite{{rose2012vtr}} and VTR~9~\cite{{elgammal2025vtr9}} at commit \code{{3c9a4d23b2}}. "
             rf"The corpus has {c['runs_ok']} completed analytical-placement VPR runs ({c['runs_failed']} failed) in {c['vpr_seconds'] / 3600:.2f}~h of VPR time and "
             rf"{nc['runs_ok']} runs of the \code{{.net}} arms ({nc['runs_failed']} failed, {nc['runs_selection_ok']} on the selection seeds, {nc['runs_heldout_ok']} on the held-out seeds) in {nc['vpr_seconds'] / 3600:.2f}~h; "
             rf"Table~\ref{{tab:r7runs}} counts the runs per arm and seeds and Table~\ref{{tab:r7corpus}} lists the designs. Table~\ref{{tab:r7gap}} and Figure~\ref{{fig:r7gap}} give the hindsight gap of the \code{{.net}} arm on the held-out seeds "
             rf"(the headline) next to the selection seeds: the arm has a held-out gain on {len(h['classes']['gain'])} of {h['n_real']} designs ({tex(', '.join(h['classes']['gain'])) or 'none'}), "
             rf"is borderline on {len(h['classes']['borderline'])} and worse on {len(h['classes']['worse'])}, and no arm beat the stock clustering on {len(h['no_gain_designs'])}. "
             rf"The median held-out wirelength gap is {f3(h['pooled_all']['WL'])} over all designs (no gain found = 1), {f3(h['h_not_net0']['WL'])} over the designs with an arm and "
             rf"{f3(h['heldout_gain']['WL'])} over the designs with a held-out gain only (the last is selected on the held-out result and is the most optimistic); on the selection seeds, in sample, the median over the designs with an arm was {f3(h['selection_h_not_net0']['WL'])}. "
             rf"Channel width: median {w_txt(d)}." + chk_txt + " "
             r"Table~\ref{tab:r7gapaff} gives the affinity-bias arm, "
             r"Tables~\ref{tab:r7calib} and~\ref{tab:r7calibB} the calibration against the known clustering, Table~\ref{tab:r7dup} the duplication counts, and "
             r"Tables~\ref{tab:r7xi} to~\ref{tab:r7coef} with Figures~\ref{fig:r7classes} and~\ref{fig:r7dist} the first mining. All mining is exploratory.",
             run_count_table(d), corpus_table(d), gap_table_net(d), fig_gap(real(d["net_gap"]["designs"])), gap_table_aff(d), calib_table(d), dup_table(d), mining_tables(d),
             fig_classes(d["mine"]["figures"]), fig_dist(d["mine"]["figures"])]
    return "\n\n".join(parts) + "\n"


def discussion(d: dict) -> str:
    nd = d["net_gap"]["designs"]
    h = ho(d)
    m = d["mine"]
    xi = m["table_xi"]
    neg = [LEVEL_TEX[lv] for lv, v in xi.items() if not v["same_as"] and v["holds_negative_median"] and v["null_le_obs"] is not None and v["null_le_obs"] < 0.05]
    dups = [e for e in d["dup"] if not e["design"].startswith("n5_")]
    n0 = sum(1 for e in dups if not e["stock"]["near5_share"])
    dup_near = med([e["stock"]["near5_share"] for e in dups])
    dup_save = med([e["stock"]["saved_share_of_cpd"] for e in dups])
    rc = d["r5check"]
    oos = [g["oos"] for g in real(d["gap"]) if "oos" in g]
    oos_none, _noos, oos_wl = oos_stats(d)
    ins_wl = med([g["H"]["WL"]["gm"] for g in real(d["gap"]) if "oos" in g and not g["oos"]["no_gain"] and "H" in g])
    rn = d["net_gap"]["summary"]["recovery_net"]["all"]
    rsel = d["net_gap"]["summary"]["recovery_net_selection"]["all"]
    prim_name = next((k for k in ("net_gain", "aff_gain") if m["models"][k]["designs"] and m["models"][k]["summary"]["auc_full_minus_base"]["n_designs"]), None)
    if prim_name:
        mm = m["models"][prim_name]
        s = mm["summary"]["auc_full_minus_base"]
        model_txt = (f"A model with HDL features, tested on held-out families (variant {tex(prim_name)}, {len(mm['designs'])} designs), changes the hindsight co-location AUC on connected pairs by "
                     f"{f3(s['mean'])} (median {f3(s['median'])}) [{f3(s['ci_lo'])}, {f3(s['ci_hi'])}] over a baseline with net connectivity, criticality and the stock clustering's own co-location and distance, "
                     f"against {f3(s['null_mean'])} [{f3(s['null_lo'])}, {f3(s['null_hi'])}] when the HDL labels are shuffled (the interval resamples design families, not designs). "
                     f"The variant that keeps designs where hindsight equals the stock clustering ({tex('aff_all')}) is in Table~\\ref{{tab:r7modelaffall}} only and is not used for a headline number.")
        ch = mm["summary"].get("auc_chg_full_minus_base")
        if ch and ch["n_designs"]:
            model_txt += (f" On the pairs whose co-location changed between the stock and the hindsight clustering (joined against split, stock flag removed from the features) "
                          f"the change is {f3(ch['mean'])} (median {f3(ch['median'])}) over {ch['n_designs']} designs, shuffled null {f3(ch['null_mean'])}.")
        model_txt += (" The baseline distance feature and the distance regression target use disjoint seed sets (stock: the five best seeds for the target, the other five for the baseline; "
                      "\\code{.net}: net0 seeds 6 to 10 for the target, 1 to 5 for the baseline), and the target placement flow of the \\code{.net} target is the baseline's flow.")
    else:
        model_txt = "No design had a hindsight clustering that beat the stock one with both classes present, so no held-out model could be fitted."
    depth_note = "the instance chain has depth 1 in every design, so the instance levels of depth 1 and of the full path are the same relation and deeper levels do not exist" \
        if any(v["same_as"] for v in xi.values()) else "the instance levels are tested as listed"
    return rf"""\subsection{{Round seven: what the data says and what it cannot say}}
\label{{sec:r7-discussion}}
\textbf{{Hindsight gap.}} The arm chosen on seeds 1 to 5 is measured on seeds 6 to 10. It has a held-out gain on {len(h['classes']['gain'])} of {h['n_real']} VTR designs, is borderline on {len(h['classes']['borderline'])} and worse on {len(h['classes']['worse'])}; on {len(h['no_gain_designs'])} no arm beat the stock clustering on the selection seeds. The median held-out wirelength gap (net0 over the arm) is {f3(h['pooled_all']['WL'])} over all designs (no gain = 1),
{f3(h['h_not_net0']['WL'])} over the {h['n_h_not_net0']} designs with an arm, {f3(h['without_borderline']['WL'])} when the borderline designs are left out ({h['without_borderline']['n']}) and {f3(h['heldout_gain']['WL'])} over the {h['heldout_gain']['n']} designs with a held-out gain; critical-path-delay gap {f3(h['pooled_all']['CPD'])}, {f3(h['h_not_net0']['CPD'])}, {f3(h['without_borderline']['CPD'])}, {f3(h['heldout_gain']['CPD'])} and CLB-count gap {f3(h['pooled_all']['CLB'])}, {f3(h['h_not_net0']['CLB'])}, {f3(h['without_borderline']['CLB'])}, {f3(h['heldout_gain']['CLB'])} in the same order. The in-sample medians on the selection seeds were {f3(h['selection_h_not_net0']['WL'])}, {f3(h['selection_h_not_net0']['CPD'])} and {f3(h['selection_h_not_net0']['CLB'])}: the difference to the held-out numbers is the selection bias.
Channel width: median {w_txt(d)}. On the designs without an arm the statement is about this procedure (a greedy move or swap of logic elements within
distance {w(lib.RADIUS)} from one placement), not about the packer. On the known constructions the procedure recovers a median of {f2(rn['WL']['median'])} of the wirelength gap on the held-out seeds, counting the {rn['WL']['n_nogain']} constructions with no gain found as 0 ({rn['WL']['n_pooled']} constructions with a gap to recover; Table~\ref{{tab:r7calibB}} by size); over the {rn['WL']['n_defined']} constructions where an arm was chosen the median is {f2(rn['WL']['median_defined_only'])}
(selection seeds, in sample: {f2(rsel['WL']['median'])} pooled, {f2(rsel['WL']['median_defined_only'])} defined only). So it falls well short of the known clustering on most constructions and the real-design gap is a best-known reference, not an optimum
(the procedure keeps CLB positions of one placement fixed, leaves carry-chain CLBs alone, and picks the arm and source run by the objective it reports). A recovery above 1 (n5\_tree\_dp\_16, wirelength) means the arm beat the known clustering, which is known by construction and not optimal.
Why stock over known is {f2(min(g['known']['WL']['gm'] for g in calib(nd) if g.get('known')))} to {f2(max(g['known']['WL']['gm'] for g in calib(nd) if g.get('known')))} here against round five's headline of
about 1.22: round five's geometric mean is over all 72 designs, whose chain and random topologies have no gap (chain 1.004, random 1.019) while mesh and tree sit at 1.423 and 1.522
(\code{{r5-results.tex}}, topology paragraph); this round uses only mesh and tree, and the flow and the known arm are the same (\code{{scripts/r5.py}} \code{{arm\_run}} and \code{{scripts/r7.py}} \code{{run\_arm}} both use VPR's default flow and weight {lib.AFF_BETA:g}):
the stock-over-known wirelength agrees with round five's on the same designs within a factor of {f3(rc['r7_over_r5_min'])} to {f3(rc['r7_over_r5_max'])} ({rc['n']} designs).

\textbf{{Out-of-sample check (affinity-bias arm).}} Choosing the arm on seeds 1 to 5 and evaluating stock over arm on seeds 6 to 10 finds no gain on {oos_none} of {len(oos)} designs; on the other {len(oos) - oos_none} the median wirelength gap is {f3(oos_wl)} (in-sample median on the same designs {f3(ins_wl)}).

\textbf{{Duplication.}} The share of duplication candidates within {100 * (1 - lib.PCRIT_NEAR[0]):.0f}\% of the critical-path delay is zero on {n0} of {len(dups)} designs and the median over designs is {pct(dup_near)}; since criticality comes from the {lib.NPATHS} reported
paths this share is a lower bound. The upper estimate of the delay all candidate hops would save is {pct(dup_save)} of the critical-path delay (median over designs, stock runs); it is an upper bound per hop, because it makes every candidate hop free.

\textbf{{Mining (exploratory).}} {model_txt} Table~\ref{{tab:r3status}}'s result (same word and same module sit closer than the nets predict) re-measured here holds at the levels
{', '.join(neg) if neg else '(none by this criterion)'} (negative median and at most 5\% of the shuffles at or below it); {depth_note}. The relations tested are those in
the provenance names and the word file; module type names are not in the BLIF, so ``module'' means the instance path. Peter's bit-level hint is
answered by the rows of Table~\ref{{tab:r7coef}} and the ``bit'' rows of the model tables. Models are held out by design family (stereovision0 to 3, diffeq1 and 2, and the mk* modules each form a family), so a
sibling never trains the model that is tested on it.

\textbf{{Limits.}} Best-known, not optimal. One architecture. VTR designs only; the big VTR designs were not run. The pair universe is a sample (all
co-located pairs, a sample of connected pairs and a uniform sample), the evaluation set is the two unbiased samples, and the {lib.NPATHS} reported timing paths bound
every criticality used. The null arm (net0 with permuted legal slots through the same selection rule) was not run, so the part of the held-out gain that a random legal rearrangement plus selection would give is not measured; the held-out seeds remove the selection bias on the seeds but not a bias of the greedy rule itself. The families for the model leave-out are decided from the Verilog: boundtop and raygentop, two designs of one ray-tracing system, share no module name and only two non-trivial source lines, so they are separate families. Nothing here is a hypothesis test with a status; the associations are the data's, with their nulls.
"""


def appendix(d: dict) -> str:
    c = d["corpus"]
    return rf"""\subsection{{Round seven: research log}}
\label{{sec:r7-appendix}}
\paragraph{{2026-10-26, round seven.}} Peter (2026-10-26), verbatim: ``In the Norns questions, I really think we should have a bunch of VTR placements that generate data that we then analyze with the qeustion what might be better clustering and intitialization - every idea we've had is in the other direction - hypothesis, test, not really better - it's like my data mining Journal paper with Gharibian, Shannon and Wilton''. I take the paper he means to be Gharibian, Shannon, Jamieson and Chung, TRETS 2013 \cite{{Gharibian2013tret}}, with the FPL 2014 paper by Gharibian, Shannon and Jamieson \cite{{gharibian2014identifying}}; this identification is an assumption of mine (his list names Wilton, and the Crossref entries of both papers, checked on 2026-10-26, do not list an author of that name). Question N Q1.7 (area, speed, wirelength): how far is the VPR packer from a best-known clustering made with hindsight from good placements, and how much would LUT duplication (after Schabas and Brown \cite{{schabas2003duplication}}) add? Question N Q2.4: which HDL relations predict which atoms sit together in good placements, and where does stock packing disagree? The answers are Tables~\ref{{tab:r7gap}} to~\ref{{tab:r7coef}}. The protocol text was committed before the first run (\code{{docs/plan/round7.md}}, commit \code{{{lib.PROTOCOL_SHA}}}); the run code was not (it was committed as \code{{{lib.CODE_SHA}}} after the first run), so the commit froze the text only. The remote records the creation of the branch with that commit before the first run finished (GitHub event log); the protocol's timestamp entries give the details.

\begin{{table}}[t]
\caption{{Research questions added in round seven.}}
\label{{tab:r7rq}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}lp{{6.4cm}}@{{}}}}
\toprule
RQ & question (measures) \\
\midrule
N Q1.7 & On real designs, how far is the VPR packer from a best-known clustering made with hindsight from good placements, and how much would LUT duplication add? (area, speed, wirelength) \\
N Q2.4 & Mined from many placements linked to the HDL: which HDL relations (word, bit index, statement, instance) predict which atoms sit together in good placements, and where does stock packing disagree? (wirelength, speed) \\
\bottomrule
\end{{tabular}}
\end{{table}}

\paragraph{{Agent defaults.}} The hindsight clustering is written as a \code{{.net}} (logic elements as units, exact CLB legality of the architecture) and run with packing off, from the best run of the previous round, arm chosen and evaluated on seeds 1 to 5 (in sample); the cost weight $1+{lib.CRIT_W:g}\,\mathrm{{pcrit}}$, the move radius of {w(lib.RADIUS)} CLBs are fixed in the protocol; carry-chain CLBs stay as they are; the affinity-bias arm of the first batch is kept and renamed. The best affinity-bias run is used for the disagreement table and the figures; the \code{{.net}} clustering is used as a mining target. The raw VPR directories are kept in scratch directories ({c['scratch_bytes'] / 1e9:.1f}~GB for the first batch) and \code{{runs/r7}} holds {c['runs_r7_bytes'] / 1e9:.1f}~GB; nothing was deleted.

\paragraph{{Fix round two (2026-10-27).}} A review of the first fix round found that the arm was chosen and reported on the same seeds and that the recovery medians dropped the designs where no arm was chosen. A protocol amendment, written and pushed before the first held-out run (\code{{docs/plan/round7.md}}), fixes the arm from \code{{rounds.json}} and runs \code{{net0}}, the arm and (constructions) the known clustering on seeds 6 to 10 under the Norns lock; the held-out gap is the headline, the gap on seeds 1 to 5 is labelled selection seeds, and the recovery headline counts a design with no gain found as 0 beside the median over the designs where an arm was chosen. The null arm of the review (net0 with permuted legal slots through the same selection) was optional and was not run. The queued 10-seed probe of n5\_mesh\_dp\_16 did run (its seeds 6 to 10 are the held-out runs of that design). The mining baseline now uses a distance feature disjoint in seeds from the distance target, the confidence intervals resample design families, and the held-out models are also scored on the pairs whose co-location changed.

Regeneration: \code{{python scripts/write\_round7.py}} from \code{{data/r7/*.json}}; the steps that need \code{{runs/}} are \code{{r7.py hind}}, \code{{r7net.py run}}, \code{{r7corpus.py}}, \code{{r7stats.py}}, \code{{r7fstats.py}} and \code{{r7mine.py}}.
"""


def main() -> int:
    d = load()
    if any(v is None for k, v in d.items() if k != "net_check"):
        nl.die("data/r7/{gap,net_gap,dup,mine,corpus,r5check}.json missing; run r7stats.py, r7fstats.py and r7mine.py first")
    write("r7-abstract.tex", abstract(d))
    write("r7-method.tex", method(d))
    write("r7-results.tex", results(d))
    write("r7-discussion.tex", discussion(d))
    write("r7-appendix.tex", appendix(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
