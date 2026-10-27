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
    for k in ("gap", "net_gap", "dup", "mine", "corpus", "r5check"):
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
    pts = [g["H"]["WL"]["hi"] for g in recs if not g["no_gain"] and not nan(g["H"]["WL"]["hi"])]
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
        wl = g["H"]["WL"]
        lines.append(rf"\draw[line width=1.2pt] ({x(wl['lo']):.2f},{y}) -- ({x(wl['hi']):.2f},{y});")
        lines.append(rf"\fill ({x(wl['gm']):.2f},{y}) circle (1.6pt);")
    lines.append(rf"\draw[dashed] ({x(1.0):.2f},0.8) -- ({x(1.0):.2f},{-n + 0.2});")
    lines.append(rf"\draw (0,{-n + 0.1}) -- (6,{-n + 0.1});")
    for v in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0):
        if lo_x <= v <= hi_x:
            lines.append(rf"\node at ({x(v):.2f},{-n - 0.7}) {{{v:g}}};")
    lines += [r"\end{tikzpicture}",
              rf"\caption{{Round 7: wirelength gap net0$/$hindsight per design for the \code{{.net}} arm (dot: geometric mean over the {w(len(lib.NET_SEEDS))} seeds, in sample, bar: 95\% bootstrap "
              r"interval over those seeds). Designs where the procedure found no gain carry no dot. Above 1, the stock clustering routes longer wires than the best-known one.}",
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

def gain_medians(net: list[dict]) -> dict:
    gain = [g for g in real(net) if not g["no_gain"]]
    return {m: med([g["H"][m]["gm"] for g in gain]) for m in ("WL", "CPD", "CLB", "W")} | {"n": len(gain), "of": len(real(net))}


def abstract(d: dict) -> str:
    nd = d["net_gap"]["designs"]
    gm = gain_medians(nd)
    c = d["corpus"]
    runs = c["runs_ok"] + d["net_gap"]["summary"]["corpus"]["runs_ok"]
    return (r"\paragraph{Round seven (data first).} Rounds one to six each tested an idea. Round seven tests none: it runs " +
            f"{runs} VPR placements ({gm['of']} VTR designs and {len(calib(nd))} known-optimum constructions, {w(len(lib.SEEDS))} seeds) and reports what the data shows. "
            r"The hindsight clustering is the stock clustering with logic elements moved or swapped between neighbouring CLBs according to where the best stock placement "
            r"put them; it is written as a VPR \code{.net} and run with packing off, so VPR builds exactly that clustering. "
            f"The procedure finds a gain on {gm['n']} of {gm['of']} VTR designs; on those, the stock clustering over the hindsight clustering, seed for seed in sample (the arm is chosen on the same seeds), "
            f"has a median wirelength gap of {f3(gm['WL'])}, critical-path-delay gap of {f3(gm['CPD'])} and CLB-count gap of {f3(gm['CLB'])}. "
            f"On the other {gm['of'] - gm['n']} designs no gain was found. "
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
(mesh and tree, $B\in\{{{','.join(str(b) for b in (16, 64, 256))}\}}$, whose block clustering is optimal by construction), each with VPR seeds 1 to {len(lib.SEEDS)} (stock and affinity-bias runs) or 1 to {len(lib.NET_SEEDS)} (\code{{.net}} arms), the architecture of rounds one
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
\code{{net0}} over that arm, seed for seed, with a bootstrap interval over those seeds. The gap is \emph{{in sample}}: the arm is chosen on the seeds it is evaluated on (winner's-curse risk). Peter cut the seeds of the new runs from {w(len(lib.SEEDS))} to {w(len(lib.NET_SEEDS))} (decision 2026-10-26, before the \code{{.net}} runs); the affinity-bias data have {w(len(lib.SEEDS))} seeds and get an out-of-sample check (arm chosen on seeds 1 to 5, evaluated on seeds 6 to 10). Where the chosen arm is \code{{net0}} the procedure found no gain; no gap is printed or pooled. Stock packing is the
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
                      r"and the fixed-point arm of the affinity-bias and of the \code{.net} procedure.}", r"\label{tab:r7corpus}", r"\centering\scriptsize", r"\begin{tabular}{@{}lrrrrll@{}}", r"\toprule",
                      r"design & CLBs & ok & failed & rounds & affinity arm & \code{.net} arm \\", r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def gap_table_net(d: dict) -> str:
    nd = real(d["net_gap"]["designs"])
    s = d["net_gap"]["summary"]
    rows = []
    for g in nd:
        if g["no_gain"]:
            rounds = ", ".join(f"h{i + 1} {f3(r['gap']['WL']['gm'])}" for i, r in enumerate(g["rounds"]))
            rows.append(f"{tex(g['design'])} & net0 & \\multicolumn{{4}}{{l}}{{no gain found (WL gap of the rounds: {rounds})}} \\\\")
            continue
        H = g["H"]
        rows.append(f"{tex(g['design'])} & {tex(g['hindsight_arm'])} & {cint(H['WL'])} & {cint(H['CPD'])} & {cint(H['CLB'])} & {f3(H['W']['gm'])} \\\\")
    gm = gain_medians(d["net_gap"]["designs"])
    rows.append(r"\midrule")
    rows.append(f"median over the {gm['n']} designs with a gain & & {f3(gm['WL'])} & {f3(gm['CPD'])} & {f3(gm['CLB'])} & {f3(gm['W'])} \\\\")
    return "\n".join([r"\begin{table*}[t]", rf"\caption{{Round 7, the hindsight gap of the \code{{.net}} arm: \code{{net0}} (the stock clustering, same placer) over the arm with the best median objective, "
                      rf"in sample (geometric mean over {w(len(lib.NET_SEEDS))} seeds, 95\% bootstrap interval over those seeds; above 1 means the stock clustering is worse). "
                      rf"Fidelity is 1.0 by construction in {s['fidelity_one']} of {s['fidelity_runs']} runs. Stock packing is the same in every seed, so the CLB interval has no clustering variance. "
                      r"Where no arm beat \code{net0} the row says so and no gap enters the median; the median is over the designs with a gain only, "
                      r"which is selected on the seeds it is evaluated on (winner's-curse risk). Best-known, not optimal.}",
                      r"\label{tab:r7gap}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}llllll@{}}", r"\toprule", r"design & arm & WL & CPD & CLB & W \\", r"\midrule"] + rows +
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
                      rf"(fidelity: share of the groups built whole). A design whose fidelity stays below {lib.FID_MIN:g} in every round is marked ``not realised'' (protocol stop rule) and left out of the median; "
                      r"where no arm beat stock the row says so and no gap enters the median.}", r"\label{tab:r7gapaff}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}llllllr@{}}", r"\toprule", r"design & arm & WL & CPD & CLB & W & fidelity \\", r"\midrule"] + rows +
                     [r"\bottomrule", r"\end{tabular}", r"\end{table*}"])


def calib_table(d: dict) -> str:
    rows = []
    for g in calib(d["net_gap"]["designs"]):
        rec = g.get("recovery") or {}

        def r(m: str, rec=rec) -> str:
            v = rec.get(m) or {}
            if v.get("value") is None:
                return "none" if v.get("note") else "n/a"
            return f"{v['value']:.2f}"

        if g.get("known") is None:
            rows.append(f"{tex(g['design'])} & \\multicolumn{{7}}{{l}}{{known clustering not a legal \\code{{.net}}: {tex(g.get('known_note', ''))}}} \\\\")
            continue
        h = g.get("H")
        rows.append(f"{tex(g['design'])} & {f3(g['known']['WL']['gm'])} & {f3(h['WL']['gm']) if h else 'no gain'} & {r('WL')} & {f3(g['known']['CLB']['gm'])} & "
                    f"{f3(h['CLB']['gm']) if h else 'no gain'} & {r('CLB')} & {r('CPD')} \\\\")
    tab1 = "\n".join([r"\begin{table*}[t]", rf"\caption{{Round 7, calibration on the round-5 constructions, \code{{.net}} arm (in sample): \code{{net0}} over the known clustering (known) and over the hindsight arm "
                      r"(H) for wirelength and CLB count, and the recovery $(\ln \mathrm{net0}-\ln H)/(\ln \mathrm{net0}-\ln \mathrm{known})$ from the geometric means over the seeds "
                      rf"(``none'': the known clustering is less than {math.exp(0.05) * 100 - 100:.0f}\% better, nothing to recover). The last column is the recovery of the critical-path delay.}}",
                      r"\label{tab:r7calib}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}lrrrrrrr@{}}", r"\toprule", r"design & WL known & WL H & WL rec. & CLB known & CLB H & CLB rec. & CPD rec. \\", r"\midrule"] +
                     rows + [r"\bottomrule", r"\end{tabular}", r"\end{table*}"])
    prows = []
    for arm, key in (("\\code{.net}", "recovery_net"), ("affinity-bias", "recovery_affinity")):
        for grp in ("B16", "B64", "B256", "all"):
            cells = []
            for m in ("WL", "CLB", "CPD"):
                v = d["net_gap"]["summary"][key][grp][m]
                cells.append(f"{f2(v['median'])} ({v['n_defined']}/{v['n_designs']})")
            prows.append(f"{arm} & {grp.replace('B', '$B$=') if grp != 'all' else 'all'} & " + " & ".join(cells) + r" \\")
    tab2 = "\n".join([r"\begin{table}[t]", r"\caption{Round 7, recovery of the known-clustering gap, median over the designs of a size where the known clustering is at least 5\% better, "
                      r"by block count $B$ (designs with a recovery defined / designs of that size). Recovery is computed from the aggregated geometric means over seeds. "
                      r"A median of 1 would mean the procedure reaches the known clustering.}", r"\label{tab:r7calibB}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}llrrr@{}}", r"\toprule", r"arm & $B$ & WL & CLB & CPD \\", r"\midrule"] + prows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"])
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
                      r"count only through one logic CLB plus a pad or hard block. Nothing is built.}", r"\label{tab:r7dup}",
                      r"\centering\scriptsize", r"\begin{tabular}{@{}lrrrrrrr@{}}", r"\toprule",
                      r"design & cand. & of LUTs & near 5\% & near 10\% & saved & saved (H) & other \\", r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def model_table(m: dict, label: str, name: str, tag: str) -> str:
    s = m["summary"]
    rows = []
    for key, lab in (("auc_bit_minus_base", "AUC (connected pairs), bit features"), ("auc_full_minus_base", "AUC (connected pairs), all HDL"),
                     ("auc_uni_full_minus_base", "AUC (uniform pairs), all HDL"),
                     ("r2_bit_minus_base", "$R^2$ of normalised distance, bit features"), ("r2_full_minus_base", "$R^2$ of normalised distance, all HDL")):
        v = s[key]
        rows.append(f"{lab} & {f3(v['mean'])} & {f3(v['median'])} & [{f3(v['ci_lo'])}, {f3(v['ci_hi'])}] & {v['n_positive']}/{v['n_designs']} & "
                    f"{f3(v['null_mean'])} [{f3(v['null_lo'])}, {f3(v['null_hi'])}] \\\\")
    return "\n".join([r"\begin{table}[t]", rf"\caption{{Round 7 (exploratory), held-out-family models, target {label}: {len(m['designs'])} designs in {len(m['families'])} families "
                      rf"({', '.join(tex(x) for x in m['families'])}). Baseline (net connectivity, criticality, kinds, stock co-CLB and stock distance, no HDL): "
                      rf"AUC on connected pairs mean {f3(m['auc_base_mean'])}, median {f3(m['auc_base_median'])}; on uniform pairs mean {f3(m['auc_uni_base_mean'])}. "
                      rf"Change from adding HDL features: mean and median over held-out designs, bootstrap interval of the mean, designs improved, and the same change with the HDL labels "
                      rf"(and the carry flag) shuffled, {m['summary']['auc_full_minus_base']['shuffles']} shuffles.}}", rf"\label{{tab:r7model{tag}}}", r"\centering\scriptsize",
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
    prim = next((m["models"][k] for k in ("net_gain", "aff_gain", "aff_all") if m["models"][k]["designs"]), None)
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


def results(d: dict) -> str:
    c = d["corpus"]
    nc = d["net_gap"]["summary"]["corpus"]
    parts = [r"\subsection{Round seven results}", r"\label{sec:r7-results}",
             rf"The corpus has {c['runs_ok']} completed analytical-placement VPR runs ({c['runs_failed']} failed) in {c['vpr_seconds'] / 3600:.2f}~h of VPR time and "
             rf"{nc['runs_ok']} runs of the \code{{.net}} arms ({nc['runs_failed']} failed) in {nc['vpr_seconds'] / 3600:.2f}~h; "
             rf"Table~\ref{{tab:r7corpus}} lists the designs. Table~\ref{{tab:r7gap}} and Figure~\ref{{fig:r7gap}} give the hindsight gap of the \code{{.net}} arm, "
             r"Table~\ref{tab:r7gapaff} the affinity-bias arm, "
             r"Tables~\ref{tab:r7calib} and~\ref{tab:r7calibB} the calibration against the known optimum, Table~\ref{tab:r7dup} the duplication counts, and "
             r"Tables~\ref{tab:r7xi} to~\ref{tab:r7coef} with Figures~\ref{fig:r7classes} and~\ref{fig:r7dist} the first mining. All mining is exploratory.",
             corpus_table(d), gap_table_net(d), fig_gap(real(d["net_gap"]["designs"])), gap_table_aff(d), calib_table(d), dup_table(d), mining_tables(d),
             fig_classes(d["mine"]["figures"]), fig_dist(d["mine"]["figures"])]
    return "\n\n".join(parts) + "\n"


def discussion(d: dict) -> str:
    nd = d["net_gap"]["designs"]
    gm = gain_medians(nd)
    m = d["mine"]
    xi = m["table_xi"]
    neg = [LEVEL_TEX[lv] for lv, v in xi.items() if not v["same_as"] and v["holds_negative_median"] and v["null_le_obs"] is not None and v["null_le_obs"] < 0.05]
    dups = [e for e in d["dup"] if not e["design"].startswith("n5_")]
    n0 = sum(1 for e in dups if not e["stock"]["near5_share"])
    dup_near = med([e["stock"]["near5_share"] for e in dups])
    dup_save = med([e["stock"]["saved_share_of_cpd"] for e in dups])
    rc = d["r5check"]
    oos = [g["oos"] for g in real(d["gap"]) if "oos" in g]
    oos_none = sum(1 for o in oos if o["no_gain"])
    oos_wl = med([o["WL"]["gm"] for o in oos if not o["no_gain"]])
    ins_wl = med([g["H"]["WL"]["gm"] for g in real(d["gap"]) if "oos" in g and not g["oos"]["no_gain"] and "H" in g])
    rn = d["net_gap"]["summary"]["recovery_net"]["all"]
    prim_name = next((k for k in ("net_gain", "aff_gain", "aff_all") if m["models"][k]["designs"]), None)
    if prim_name:
        mm = m["models"][prim_name]
        s = mm["summary"]["auc_full_minus_base"]
        model_txt = (f"A model with HDL features, tested on held-out families (variant {tex(prim_name)}, {len(mm['designs'])} designs), changes the hindsight co-location AUC on connected pairs by "
                     f"{f3(s['mean'])} (median {f3(s['median'])}) [{f3(s['ci_lo'])}, {f3(s['ci_hi'])}] over a baseline with net connectivity, criticality and the stock clustering's own co-location and distance, "
                     f"against {f3(s['null_mean'])} [{f3(s['null_lo'])}, {f3(s['null_hi'])}] when the HDL labels are shuffled.")
    else:
        model_txt = "No design had a hindsight clustering that beat the stock one with both classes present, so no held-out model could be fitted."
    depth_note = "the instance chain has depth 1 in every design, so the instance levels of depth 1 and of the full path are the same relation and deeper levels do not exist" \
        if any(v["same_as"] for v in xi.values()) else "the instance levels are tested as listed"
    return rf"""\subsection{{Round seven: what the data says and what it cannot say}}
\label{{sec:r7-discussion}}
\textbf{{Hindsight gap.}} The \code{{.net}} procedure finds a gain on {gm['n']} of {gm['of']} VTR designs; on those the median wirelength gap (net0 over the arm, in sample) is {f3(gm['WL'])},
critical-path-delay gap {f3(gm['CPD'])}, CLB-count gap {f3(gm['CLB'])}. On the other designs it found no gain, which is a statement about this procedure (a greedy move or swap of logic elements within
distance {w(lib.RADIUS)} from one placement), not about the packer. On the known-optimum constructions the procedure recovers a median of {f2(rn['WL']['median'])} of the wirelength gap ({rn['WL']['n_defined']} designs with a gap to recover; Table~\ref{{tab:r7calibB}} by size),
so it falls well short of the construction's clustering and the real-design gap is a best-known reference, not an optimum
(the procedure keeps CLB positions of one placement fixed, leaves carry-chain CLBs alone, and picks the arm and source run by the objective it reports).
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
every criticality used. Nothing here is a hypothesis test with a status; the associations are the data's, with their nulls.
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

Regeneration: \code{{python scripts/write\_round7.py}} from \code{{data/r7/*.json}}; the steps that need \code{{runs/}} are \code{{r7.py hind}}, \code{{r7net.py run}}, \code{{r7corpus.py}}, \code{{r7stats.py}}, \code{{r7fstats.py}} and \code{{r7mine.py}}.
"""


def main() -> int:
    d = load()
    if any(v is None for v in d.values()):
        nl.die("data/r7/{gap,net_gap,dup,mine,corpus,r5check}.json missing; run r7stats.py, r7fstats.py and r7mine.py first")
    write("r7-abstract.tex", abstract(d))
    write("r7-method.tex", method(d))
    write("r7-results.tex", results(d))
    write("r7-discussion.tex", discussion(d))
    write("r7-appendix.tex", appendix(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
