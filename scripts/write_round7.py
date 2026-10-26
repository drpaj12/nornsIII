"""Write the round-7 paper text: docs/paper/r7-*.tex, included by norns.tex.

Every number comes from data/r7/{gap,dup,mine,corpus}.json (scripts/r7stats.py, scripts/r7mine.py); no number is typed
here. Needs only the committed data (no runs/). Usage: python scripts/write_round7.py
"""

from __future__ import annotations

import math
import statistics
import sys

import nornlib as nl

PAPER = nl.WS / "docs" / "paper"
D7 = nl.DATA / "r7"
PROTOCOL_SHA = "93c983a"
LEVEL_TEX = {"same_word": "same word", "same_bit": "same bit index", "same_word_bit": "same word and bit", "same_stmt": "same statement",
             "same_inst_d1": "same instance, depth 1", "same_inst_d2": "same instance, depth 2", "same_inst_d3": "same instance, depth 3",
             "same_inst_full": "same instance (full path)"}
CLASSES = ("SC", "SN", "SI", "OR", "FL")


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
    for k in ("gap", "dup", "mine", "corpus"):
        p = D7 / f"{k}.json"
        out[k] = nl.read_json(p) if p.is_file() else None
    return out


def med(vals: list) -> float:
    v = [x for x in vals if not nan(x)]
    return statistics.median(v) if v else float("nan")


def main_gaps(gap: list[dict]) -> list[dict]:
    return [g for g in gap if "H" in g and not g["design"].startswith("n5_")]


def calib_gaps(gap: list[dict]) -> list[dict]:
    return [g for g in gap if "H" in g and g["design"].startswith("n5_")]


# ---------------------------------------------------------------------------------------
# TikZ figures (the paper has tikz but no pgfplots)

def fig_gap(gaps: list[dict]) -> str:
    lo_x, hi_x = 0.9, max([1.2] + [g["H"]["WL"]["hi"] for g in gaps if not nan(g["H"]["WL"]["hi"])])

    def x(v: float) -> float:
        return 6.0 * (min(max(v, lo_x), hi_x) - lo_x) / (hi_x - lo_x)

    n = len(gaps)
    lines = [r"\begin{figure}[t]", r"\centering", r"\begin{tikzpicture}[x=1cm,y=0.33cm,font=\scriptsize]"]
    for i, g in enumerate(gaps):
        y = -i
        w = g["H"]["WL"]
        lines.append(rf"\node[anchor=east] at (-0.1,{y}) {{{tex(g['design'])}}};")
        lines.append(rf"\draw[line width=1.2pt] ({x(w['lo']):.2f},{y}) -- ({x(w['hi']):.2f},{y});")
        lines.append(rf"\fill ({x(w['gm']):.2f},{y}) circle (1.6pt);")
        h1 = g["h1"]["WL"]
        lines.append(rf"\draw[gray] ({x(h1['gm']):.2f},{y - 0.3}) -- ({x(h1['gm']):.2f},{y + 0.3});")
    lines.append(rf"\draw[dashed] ({x(1.0):.2f},0.8) -- ({x(1.0):.2f},{-n + 0.2});")
    lines.append(rf"\draw (0,{-n + 0.1}) -- (6,{-n + 0.1});")
    for v in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0):
        if lo_x <= v <= hi_x:
            lines.append(rf"\node at ({x(v):.2f},{-n - 0.7}) {{{v:g}}};")
    lines += [r"\end{tikzpicture}",
              r"\caption{Round 7: wirelength gap stock$/$hindsight per design (dot: geometric mean over 10 seeds of the fixed-point arm, bar: 95\% bootstrap "
              r"interval over seeds, gray tick: first hindsight round). Above 1, stock routes longer wires than the best-known clustering.}",
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
                w = 5.0 * v
                lines.append(rf"\fill[{cols[c]}] ({x0:.3f},{y - 0.4}) rectangle ({x0 + w:.3f},{y + 0.4 - 0.0});")
                x0 += w
    lines.append(r"\node[anchor=west] at (5.2,0) {" + ", ".join(rf"\textcolor{{{cols[c]}}}{{\rule{{4pt}}{{4pt}}}}~{c}" for c in CLASSES) + "};")
    lines += [r"\end{tikzpicture}",
              r"\caption{Round 7: N17 class shares of the pairs that share a CLB, per design: upper bar the best stock run, lower bar the best hindsight run.}",
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
              r"\caption{Round 7 (exploratory): distribution of the placed Manhattan distance (CLB units, mean over 10 stock seeds) of pairs with the HDL relation "
              r"(blue) and without it (gray), per relation, pooled over designs; bars are shares of each group.}",
              r"\label{fig:r7dist}", r"\end{figure}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------

def abstract(d: dict) -> str:
    gaps = main_gaps(d["gap"])
    wl = med([g["H"]["WL"]["gm"] for g in gaps])
    cpd = med([g["H"]["CPD"]["gm"] for g in gaps])
    clb = med([g["H"]["CLB"]["gm"] for g in gaps])
    c = d["corpus"]
    return (r"\paragraph{Round seven (data first).} Rounds one to six each tested an idea. Round seven tests none: it runs " +
            f"{c['runs_ok']} VPR placements ({len(gaps)} VTR designs and {len(calib_gaps(d['gap']))} known-optimum constructions, 10 seeds, stock and "
            r"hindsight clusterings) and reports what the data shows. The hindsight clustering re-packs the atoms where the best placement put them, "
            f"and the same placer and router, seed for seed, give a median wirelength gap of {f3(wl)}, critical-path-delay gap of {f3(cpd)} and "
            f"CLB-count gap of {f3(clb)} (stock over hindsight, median over designs). Everything after the gap is exploratory and carries a shuffled-label null. "
            "The gap is a best-known bound made by selection, not an optimum.\n")


def method(d: dict) -> str:
    return rf"""\subsection{{Round seven: a placement corpus and a hindsight clustering}}
\label{{sec:r7-method}}
Round seven asks two questions of data instead of testing an idea (N Q1.7: how far is the VPR packer from a best-known clustering made with
hindsight from good placements, and how much would LUT duplication add; N Q2.4: which HDL relations predict that atoms sit together in good
placements). Its protocol, committed before any run, is \code{{docs/plan/round7.md}} (commit \code{{{PROTOCOL_SHA}}}); the one quantity defined in
advance is the \emph{{hindsight gap}} per design, and every other analysis is exploratory.

\textbf{{Corpus.}} {len(main_gaps(d['gap']))} VTR designs of rounds one to four and {len(calib_gaps(d['gap']))} round-five netlist-level constructions
(mesh and tree, $B\in\{{16,64,256\}}$, whose block clustering is optimal by construction), each with VPR seeds 1 to 10, the architecture of rounds one
to six, VPR's default analytical-placement flow (VTR~\cite{{rose2012vtr}} and VTR~9~\cite{{elgammal2025vtr9}}, commit \code{{3c9a4d23b2}}, version 9.0.0-dev; the flow already clusters with APPack from atom positions; there is no separate analytical hindsight
start), and routing at the minimum channel width. Each run records, per atom, the construct chain from the provenance names, the word and bit
index, the CLB, its coordinates, the pack-time and post-route criticality and slack; per pair, the N17 class, the HDL relations and the distance in
each run; per net, fanout and CLBs spanned. Post-route criticality is path based, from the 200 worst reported paths.

\textbf{{Hindsight clustering.}} Take the best stock run (lowest wirelength~$\times$~critical-path delay). Keep its CLB positions fixed and move
LUT--FF molecules between CLBs within Manhattan distance two (or swap them) by greedy search, minimising the sum over nets of
$(1+4\,\mathrm{{pcrit}})\cdot$HPWL under an approximate CLB capacity (10 LUTs, 20 flip-flops, 40 inputs, 20 outputs); CLBs with carry chains stay
fixed. The result is handed to the packer as an affinity file at weight 100 (round five's known arm), so VPR's own legality check applies, and the
clustering VPR actually builds is measured. Repeat from the best run of each round until the median objective stops improving by 1\% or after five
rounds. The \emph{{gap}} of a metric is stock over hindsight, seed for seed, with a bootstrap interval over the ten seeds. \emph{{Duplication}}
candidates are single LUTs whose output net has sinks in two or more CLBs; nothing is built.
"""


def corpus_table(d: dict) -> str:
    c = d["corpus"]
    rows = []
    for g in main_gaps(d["gap"]) + calib_gaps(d["gap"]):
        e = c["designs"].get(g["design"], {})
        rounds = len(g.get("rounds", []))
        rows.append(f"{tex(g['design'])} & {e.get('logic_clbs_seed1', 'n/a')} & {e.get('ok', 0)} & {e.get('failed', 0)} & {rounds} & {tex(g['hindsight_arm'])} \\\\")
    return "\n".join([r"\begin{table}[t]", r"\caption{Round 7 corpus: logic CLBs of the stock seed-1 run, VPR runs completed and failed, hindsight rounds run, "
                      r"and the fixed-point arm.}", r"\label{tab:r7corpus}", r"\centering\scriptsize", r"\begin{tabular}{@{}lrrrrl@{}}", r"\toprule",
                      r"design & CLBs & ok & failed & rounds & arm \\", r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def gap_table(d: dict) -> str:
    rows = []
    for g in main_gaps(d["gap"]):
        H = g["H"]
        rows.append(f"{tex(g['design'])} & {tex(g['hindsight_arm'])} & {cint(H['WL'])} & {cint(H['CPD'])} & {cint(H['CLB'])} & {f3(H['W']['gm'])} & "
                    f"{f2(g.get('fidelity_H'))} \\\\")
    gaps = main_gaps(d["gap"])
    rows.append(r"\midrule")
    rows.append("median over designs & & " + f"{f3(med([g['H']['WL']['gm'] for g in gaps]))} & {f3(med([g['H']['CPD']['gm'] for g in gaps]))} & "
                f"{f3(med([g['H']['CLB']['gm'] for g in gaps]))} & {f3(med([g['H']['W']['gm'] for g in gaps]))} & {f2(med([g.get('fidelity_H') for g in gaps]))} \\\\")
    rows.append("first round only & & " + f"{f3(med([g['h1']['WL']['gm'] for g in gaps]))} & {f3(med([g['h1']['CPD']['gm'] for g in gaps]))} & "
                f"{f3(med([g['h1']['CLB']['gm'] for g in gaps]))} & {f3(med([g['h1']['W']['gm'] for g in gaps]))} & {f2(med([g.get('fidelity_h1') for g in gaps]))} \\\\")
    return "\n".join([r"\begin{table*}[t]", r"\caption{Round 7, the hindsight gap (stock over hindsight; geometric mean over 10 seeds, 95\% bootstrap interval "
                      r"over seeds; above 1 means stock is worse). Fidelity: share of the hindsight groups the packer built whole. The last two rows are medians over "
                      r"designs of the point values; ``first round only'' has no round selection. Best-known, not optimal; the arm and the source seed are chosen "
                      r"by the same objective on the same seeds, so the gap is optimistic by selection.}", r"\label{tab:r7gap}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}llllllr@{}}", r"\toprule", r"design & arm & WL & CPD & CLB & W & fidelity \\", r"\midrule"] + rows +
                     [r"\bottomrule", r"\end{tabular}", r"\end{table*}"])


def calib_table(d: dict) -> str:
    rows = []
    cg = calib_gaps(d["gap"])
    for g in cg:
        rec = g.get("recovery", {})

        def r(m: str) -> str:
            v = rec.get(m, {})
            if v.get("median") is None:
                return "none" if v.get("note") else "n/a"
            return f"{v['median']:.2f}"

        rows.append(f"{tex(g['design'])} & {f3(g['known']['WL']['gm'])} & {f3(g['H']['WL']['gm'])} & {r('WL')} & {f3(g['known']['CLB']['gm'])} & "
                    f"{f3(g['H']['CLB']['gm'])} & {r('CLB')} & {r('CPD')} \\\\")
    pooled = []
    for m in ("WL", "CLB", "CPD"):
        vals = [g["recovery"][m]["median"] for g in cg if g.get("recovery", {}).get(m, {}).get("median") is not None]
        pooled.append(f"{f2(med(vals))} ({len(vals)})")
    rows.append(r"\midrule")
    rows.append(f"median recovery (designs with a gap) & & & {pooled[0]} & & & {pooled[1]} & {pooled[2]} \\\\")
    return "\n".join([r"\begin{table*}[t]", r"\caption{Round 7, calibration on the round-5 constructions: stock over the known clustering (known) and stock over hindsight "
                      r"(H) for wirelength and CLB count, and the recovery $(\ln \mathrm{stock}-\ln H)/(\ln \mathrm{stock}-\ln \mathrm{known})$ per seed (median over "
                      r"seeds; ``none'': no gap to recover). The last column is the recovery of the critical-path delay.}", r"\label{tab:r7calib}", r"\centering\scriptsize",
                      r"\begin{tabular}{@{}lrrrrrrr@{}}", r"\toprule", r"design & WL known & WL H & WL rec. & CLB known & CLB H & CLB rec. & CPD rec. \\", r"\midrule"] +
                     rows + [r"\bottomrule", r"\end{tabular}", r"\end{table*}"])


def dup_table(d: dict) -> str:
    rows = []
    for e in d["dup"]:
        if e["design"].startswith("n5_"):
            continue
        s, h = e["stock"], e["H"]
        rows.append(f"{tex(e['design'])} & {f2(s['candidates'])} & {pct(s['share_of_luts'])} & {pct(s['near5_share'])} & {pct(s['near10_share'])} & "
                    f"{pct(s['saved_share_of_cpd'])} & {pct(h['saved_share_of_cpd'])} \\\\")
    return "\n".join([r"\begin{table}[t]", r"\caption{Round 7, LUT duplication candidates (single-LUT drivers with sinks in two or more CLBs), median over the "
                      r"10 stock seeds: count, share of all LUTs, share within 5\% and 10\% of the critical-path delay, and the upper estimate of the delay "
                      r"saved if every candidate hop were free (share of CPD; stock, then the hindsight arm). Nothing is built.}", r"\label{tab:r7dup}",
                      r"\centering\scriptsize", r"\begin{tabular}{@{}lrrrrrr@{}}", r"\toprule",
                      r"design & cand. & of LUTs & $\le5\%$ & $\le10\%$ & saved & saved (H) \\", r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def mining_tables(d: dict) -> str:
    m = d["mine"]
    out = []
    rows = []
    for lv, v in m["table_xi"].items():
        rows.append(f"{LEVEL_TEX[lv]} & {f3(v['median'])} & {v['n_negative']}/{v['n_designs']} & "
                    f"[{f3(v['null_lo'])}, {f3(v['null_hi'])}] & {f3(v['null_le_obs'])} \\\\")
    out.append("\n".join([r"\begin{table}[t]", r"\caption{Round 7 (exploratory), Table~\ref{tab:r3status} re-measured at each level of the HDL chain: the stratified "
                           r"distance difference $d_r$ (related minus unrelated pairs within net-connectivity strata, as a fraction of the unrelated mean; "
                           r"negative means closer than the nets predict), median over designs, designs with $d_r<0$, the range of the same statistic on "
                           r"label-shuffled data, and the share of the shuffles at or below the observed median.}", r"\label{tab:r7xi}", r"\centering\scriptsize",
                           r"\begin{tabular}{@{}lrrcr@{}}", r"\toprule", r"relation & median $d_r$ & $d_r<0$ & null range & null$\le$obs \\", r"\midrule"] + rows +
                          [r"\bottomrule", r"\end{tabular}", r"\end{table}"]))
    s = m["models"]["summary"]
    rows = []
    for key, lab in (("auc_bit_minus_base", "AUC, bit features added"), ("auc_full_minus_base", "AUC, all HDL features added"),
                     ("r2_bit_minus_base", "$R^2$ of distance, bit features"), ("r2_full_minus_base", "$R^2$ of distance, all HDL")):
        v = s[key]
        rows.append(f"{lab} & {f3(v['mean'])} & [{f3(v['ci_lo'])}, {f3(v['ci_hi'])}] & {v['n_positive']}/{v['n_designs']} & "
                    f"{f3(v['null_mean'])} [{f3(v['null_lo'])}, {f3(v['null_hi'])}] \\\\")
    out.append("\n".join([r"\begin{table}[t]", rf"\caption{{Round 7 (exploratory), held-out-design models. Baseline AUC (net connectivity, criticality, "
                           rf"kinds, no HDL) mean {f3(m['models']['auc_base_mean'])}. Change from adding HDL features, mean over held-out designs with a "
                           r"bootstrap interval, designs improved, and the same change when the HDL labels are shuffled within each design.}", r"\label{tab:r7model}",
                           r"\centering\scriptsize", r"\begin{tabular}{@{}lrcrc@{}}", r"\toprule", r"change & mean & 95\% CI & better & shuffled null \\", r"\midrule"] +
                          rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"]))
    st = m["stability"]
    rows = []
    for lv, v in st["levels"].items():
        rows.append(f"{LEVEL_TEX[lv]} & {pct(v['stable_given_related'])} & {pct(v['stable_given_unrelated'])} & {f3(v['diff'])} & "
                    f"[{f3(v['null_lo'])}, {f3(v['null_hi'])}] \\\\")
    cls = st["by_class_stable_share"]
    out.append("\n".join([r"\begin{table}[t]", rf"\caption{{Round 7 (exploratory), stability across seeds: of the {st['pairs']} pairs that share a CLB in at least one "
                           rf"stock run, {st['stable_ge8']} ({pct(st['stable_ge8'] / st['pairs'] if st['pairs'] else float('nan'))}) do so in eight or more of ten. "
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
    out.append("\n".join([r"\begin{table}[t]", rf"\caption{{Round 7 (exploratory), where stock packing and the hindsight clustering disagree (best hindsight run against "
                           rf"the stock run of the same seed; {c['dplus']} pairs joined by hindsight only, {c['dminus']} by stock only, {c['agree']} by both). "
                           r"Enrichment of each relation among the disagreement pairs over its share among the agreed pairs, with the label-shuffled range.}",
                           r"\label{tab:r7disagree}", r"\centering\scriptsize", r"\begin{tabular}{@{}lrcrc@{}}", r"\toprule",
                           r"relation & hindsight only & null & stock only & null \\", r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular}", r"\end{table}"]))
    coefs = m["models"]["coef_full"]
    rows = [f"{LEVEL_TEX.get(f, f.replace('_', ' '))} & {f3(v['mean'])} & [{f3(v['ci_lo'])}, {f3(v['ci_hi'])}] \\\\" for f, v in coefs.items()]
    out.append("\n".join([r"\begin{table}[t]", r"\caption{Round 7 (exploratory), coefficients of the HDL features in the full logistic model for hindsight "
                           r"co-location (standardised features; mean over the held-out folds with a bootstrap interval over folds). The bit-level hint question "
                           r"(Peter 2026-10-26) is the rows ``same bit index'', ``same word and bit'', ``bit close'' and ``carry nb''.}", r"\label{tab:r7coef}",
                           r"\centering\scriptsize", r"\begin{tabular}{@{}lrc@{}}", r"\toprule", r"feature & coefficient & 95\% CI \\", r"\midrule"] + rows +
                          [r"\bottomrule", r"\end{tabular}", r"\end{table}"]))
    return "\n\n".join(out)


def results(d: dict) -> str:
    c = d["corpus"]
    parts = [r"\subsection{Round seven results}", r"\label{sec:r7-results}",
             rf"The corpus has {c['runs_ok']} completed VPR runs ({c['runs_failed']} failed) in {c['vpr_seconds'] / 3600:.2f}~h of VPR time; "
             rf"Table~\ref{{tab:r7corpus}} lists them. Table~\ref{{tab:r7gap}} and Figure~\ref{{fig:r7gap}} give the hindsight gap, "
             r"Table~\ref{tab:r7calib} the calibration against the known optimum, Table~\ref{tab:r7dup} the duplication counts, and "
             r"Tables~\ref{tab:r7xi} to~\ref{tab:r7coef} with Figures~\ref{fig:r7classes} and~\ref{fig:r7dist} the first mining. All mining is exploratory.",
             corpus_table(d), gap_table(d), fig_gap(main_gaps(d["gap"])), calib_table(d), dup_table(d), mining_tables(d),
             fig_classes(d["mine"]["figures"]), fig_dist(d["mine"]["figures"])]
    return "\n\n".join(parts) + "\n"


def discussion(d: dict) -> str:
    gaps = main_gaps(d["gap"])
    m = d["mine"]
    s = m["models"]["summary"]["auc_full_minus_base"]
    xi = m["table_xi"]
    neg = [LEVEL_TEX[lv] for lv, v in xi.items() if v["holds_negative_median"] and v["null_le_obs"] is not None and v["null_le_obs"] < 0.05]
    wl = [g["H"]["WL"] for g in gaps]
    above = sum(1 for w in wl if w["lo"] > 1.0)
    dup_near = med([e["stock"]["near5_share"] for e in d["dup"] if not e["design"].startswith("n5_")])
    dup_save = med([e["stock"]["saved_share_of_cpd"] for e in d["dup"] if not e["design"].startswith("n5_")])
    calib = [g["recovery"]["WL"]["median"] for g in calib_gaps(d["gap"]) if g.get("recovery", {}).get("WL", {}).get("median") is not None]
    return rf"""\subsection{{Round seven: what the data says and what it cannot say}}
\label{{sec:r7-discussion}}
\textbf{{Hindsight gap.}} On {above} of {len(gaps)} designs the whole 95\% interval of the wirelength gap lies above one; the median gap is {f3(med([w['gm'] for w in wl]))}.
On the known-optimum constructions the procedure recovers a median of {f2(med(calib))} of the wirelength gap of the designs that have one
({len(calib)} designs), so it reaches a clustering about as good as the construction's; on real designs it is a best-known reference, not an optimum
(the procedure keeps CLB positions of one placement fixed, uses an approximate capacity, leaves carry-chain CLBs alone, and picks the arm and source run
by the objective it reports).

\textbf{{Duplication.}} The median share of duplication candidates within 5\% of the critical-path delay is {pct(dup_near)}, and the upper estimate of
the delay all candidate hops would save is {pct(dup_save)} of the critical-path delay (median over designs, stock runs); this is a deliberately optimistic
bound from the 200 reported paths.

\textbf{{Mining (exploratory).}} A model with HDL features, tested on held-out designs, changes the hindsight co-location AUC by {f3(s['mean'])}
[{f3(s['ci_lo'])}, {f3(s['ci_hi'])}] over a baseline with net connectivity and criticality, against {f3(s['null_mean'])} [{f3(s['null_lo'])}, {f3(s['null_hi'])}] when the HDL
labels are shuffled. Table~\ref{{tab:r3status}}'s result (same word and same module sit closer than the nets predict) re-measured here holds at the levels
{', '.join(neg) if neg else '(none by this criterion)'} (negative median and at most 5\% of the shuffles at or below it). The relations tested are those in
the provenance names and the word file; module type names are not in the BLIF, so ``module'' means the instance path. Peter's bit-level hint is
answered by the rows of Table~\ref{{tab:r7coef}} and the ``bit'' rows of Table~\ref{{tab:r7model}}.

\textbf{{Limits.}} Best-known, not optimal. One architecture. VTR designs only; the big VTR designs were not run. The pair universe is a sample (all
co-located pairs, a sample of connected pairs and a uniform sample), the evaluation set is the two unbiased samples, and the 200 reported timing paths bound
every criticality used. Nothing here is a hypothesis test with a status; the associations are the data's, with their nulls.
"""


def appendix(d: dict) -> str:
    c = d["corpus"]
    return rf"""\subsection{{Round seven: research log}}
\label{{sec:r7-appendix}}
\paragraph{{2026-10-26, round seven.}} Peter (2026-10-26), verbatim: ``In the Norns questions, I really think we should have a bunch of VTR placements that generate data that we then analyze with the qeustion what might be better clustering and intitialization - every idea we've had is in the other direction - hypothesis, test, not really better - it's like my data mining Journal paper with Gharibian, Shannon and Wilton''. The paper he means is Gharibian, Shannon, Jamieson and Chung, TRETS 2013 \cite{{Gharibian2013tret}}, with the FPL 2014 paper by Gharibian, Shannon and Jamieson \cite{{gharibian2014identifying}}; both entries were checked against Crossref on 2026-10-26 and neither lists an author named Wilton. Question N Q1.7 (area, speed, wirelength): how far is the VPR packer from a best-known clustering made with hindsight from good placements, and how much would LUT duplication (after Schabas and Brown \cite{{schabas2003duplication}}) add? Question N Q2.4: which HDL relations predict which atoms sit together in good placements, and where does stock packing disagree? The answers are Tables~\ref{{tab:r7gap}} to~\ref{{tab:r7coef}}. The protocol was committed before any run (\code{{docs/plan/round7.md}}, commit \code{{{PROTOCOL_SHA}}}); its timestamp correction entry is in the protocol.

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

\paragraph{{Agent defaults.}} The hindsight procedure uses the Norns affinity mechanism at weight 100 instead of writing a \code{{.net}} by hand (VPR's packer is the legality check); the cost weight $1+4\,\mathrm{{pcrit}}$, the move radius of two CLBs and the capacity limits are fixed in the protocol; carry-chain CLBs stay as they are; the best hindsight run for mining is the lowest-objective run of any hindsight arm. The raw VPR directories are kept in a scratch directory ({c['scratch_bytes'] / 1e9:.1f}~GB) and \code{{runs/r7}} holds {c['runs_r7_bytes'] / 1e9:.1f}~GB; nothing was deleted.

Regeneration: \code{{python scripts/write\_round7.py}} from \code{{data/r7/*.json}}; the steps that need \code{{runs/}} are \code{{r7.py hind}}, \code{{r7corpus.py}}, \code{{r7stats.py}} and \code{{r7mine.py}}.
"""


def main() -> int:
    d = load()
    if any(v is None for v in d.values()):
        nl.die("data/r7/{gap,dup,mine,corpus}.json missing; run r7stats.py and r7mine.py first")
    write("r7-abstract.tex", abstract(d))
    write("r7-method.tex", method(d))
    write("r7-results.tex", results(d))
    write("r7-discussion.tex", discussion(d))
    write("r7-appendix.tex", appendix(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
