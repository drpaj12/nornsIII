"""Write the round-6 paper text: docs/paper/r6-*.tex, included by norns.tex.

Every deciding number comes from data/analysis/r6-results.json (scripts/r6stats.py), data/r6/keep.json and
data/r6/runs.jsonl; no number is typed here. Usage: python scripts/write_round6.py
"""

from __future__ import annotations

import math
import sys

import nornlib as nl

PAPER = nl.WS / "docs" / "paper"
PLAN = nl.WS / "docs" / "plan" / "round6.md"
PROTOCOL_SHA = "0ffcfc1"
RES = nl.DATA / "analysis" / "r6-results.json"
LEVELS = (0, 25, 50, 75, 100)
PEACE = ("mesh_tree", "mesh", "tree", "chain")


def tex(s) -> str:
    return str(s).replace("_", r"\_").replace("%", r"\%")


def nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def f3(x) -> str:
    return "n/a" if nan(x) else f"{x:.3f}"


def f2(x) -> str:
    return "n/a" if nan(x) else f"{x:.2f}"


def pct(x) -> str:
    return "n/a" if nan(x) else f"{100 * x:.1f}\\%"


def peq(p) -> str:
    return "p=n/a" if nan(p) else ("p<0.001" if p < 0.001 else f"p={p:.3f}")


def write(name: str, text: str) -> None:
    (PAPER / name).write_text(text, encoding="utf-8")


def ci(v: dict) -> str:
    return f"[{f3(v['ci90'][0])}, {f3(v['ci90'][1])}]"


def lvl(level: int) -> str:
    return f"{level / 100:g}"


def one_sentence(res: dict) -> str:
    """The paper's one-sentence answer, built from H33 to H37 statuses."""
    ben, hurt, leak = res["benefit"]["WL"], res["hurt"]["WL"], res["leak_a1"]["WL"]
    sup = res["break_even"]["supported_levels"]
    hurts = [lv for lv in LEVELS if hurt[str(lv)]["status"] == "supported"]
    if sup:
        a = (f"At alignment a={lvl(min(sup))} and above up to 0.75, HDL-aware packing beats stock VPR on routed wirelength without the leak "
             f"(supported at a in {{{', '.join(lvl(x) for x in sup)}}}; lowest measured word-file purity of a supported level "
             f"{f3(res['break_even']['lowest_measured_alignment'])})")
    else:
        a = ("At no non-leaky alignment tested (a in {0, 0.25, 0.5, 0.75}) does the literal H34 rule support a wirelength gain of "
             "HDL-aware packing over stock VPR (statuses: " + ", ".join(f"a={lvl(x)} {tex(ben[str(x)]['status'])}" for x in (0, 25, 50, 75)) + ")")
    b = (f"; with the leak (a=1) the wirelength ratio is {f3(leak['gmean'])} ({tex(leak['status'])})")
    c = ("; it hurts (WL at least 2\\% worse, Holm) at a in {" + ", ".join(lvl(x) for x in hurts) + "}" if hurts else
         "; it does not hurt by the literal H35 rule at any alignment tested (" + ", ".join(f"a={lvl(x)} {tex(hurt[str(x)]['status'])}" for x in LEVELS) + ")")
    return a + b + c + "."


def status_rows(res: dict) -> str:
    rows = []
    k, kk, al, rp, rm = res["keep"], res["keep_k1_k4"], res["align"], res["repro"], res["room"]
    rows.append(f"H29 & synthesis keeps the construction (k1 to k5) & {tex(k['status'])} & {k['kept']} of {k['n']} kept ({pct(k['share'])}); k1 to k4 alone {kk['kept']} of {kk['n']} \\\\")
    rows.append(f"H30 & the alignment manipulation works & {tex(al['status'])} & Spearman {f3(al['rho'])}; median measured purity {f3(al['median_level0'])} at a=0, {f3(al['median_level100'])} at a=1, n={al['n']} \\\\")
    rows.append(f"H31 & the forced clustering reproduces the blocks & {tex(rp['status'])} & mean reproduction {f3(rp['mean'])}, {pct(rp['share_full'])} of designs exact on all three seeds, n={rp['n']} designs \\\\")
    for m in ("CLB", "WL", "CPD"):
        v = rm[m]
        rows.append(f"H32 & room (stock vs known, mesh and tree cells): {m} & {tex(v['status'])} & geomean {f3(v['gmean'])}, 90\\% CI {ci(v)}, Holm ${peq(v['p_holm'])}$, n={v['n']} cells \\\\")
    for m in ("CLB", "WL", "CPD"):
        v = res["leak_a1"][m]
        rows.append(f"H33 & norns vs stock at a=1 (leak), mesh and tree: {m} & {tex(v['status'])} & geomean {f3(v['gmean'])}, 90\\% CI {ci(v)}, Holm ${peq(v['p_holm'])}$, n={v['n']} \\\\")
    for lv in (0, 25, 50, 75):
        v = res["benefit"]["WL"][str(lv)]
        rows.append(f"H34 & norns vs stock at a={lvl(lv)}: WL & {tex(v['status'])} & geomean {f3(v['gmean'])}, 90\\% CI {ci(v)}, Holm(4) ${peq(v['p_holm'])}$, n={v['n']} \\\\")
    for lv in LEVELS:
        v = res["hurt"]["WL"][str(lv)]
        rows.append(f"H35 & does norns hurt at a={lvl(lv)}: WL & {tex(v['status'])} & geomean {f3(v['gmean'])}, 90\\% CI {ci(v)}, Holm(5) ${peq(v['p_holm'])}$, n={v['n']} \\\\")
    for m in ("WL", "CLB", "CPD"):
        v = res["dose"][m]
        rows.append(f"H36 & dose-response, slope of ln ratio on measured alignment: {m} & {tex(v['status'])} & median slope {f3(v['median_slope'])}, {v['negative_cells']}/{v['cells']} cells negative, Holm ${peq(v['p_holm'])}$, permutation ${peq(v['perm_p'])}$ \\\\")
    c = res["control_chain"]
    rows.append(f"H37 & control: chain, norns vs stock WL & {tex(c['status'])} & geomean {f3(c['gmean'])}, 90\\% CI {ci(c)}, n={c['n']} \\\\")
    return "\n".join(rows)


def level_table(res: dict) -> str:
    """Per level: norns/stock WL (mesh and tree, mesh, tree, chain), placebo, measured purity."""
    t = res["tables"]
    rows = []
    for lv in LEVELS:
        cells = []
        for name in PEACE:
            v = t[f"norns/stock_WL_{name}_a{lv}"]
            cells.append(f"{f3(v['gmean'])} {ci(v)}")
        pl = res["placebo"]["WL"].get(str(lv))
        cells.append(f"{f3(pl['gmean'])}" if pl else "--")
        cells.append(f3(res["align_by_level"][str(lv)]["median"]))
        rows.append(f"{lvl(lv)} & " + " & ".join(cells) + r" \\")
    return "\n".join(rows)


def known_table(res: dict) -> str:
    t = res["tables"]
    rows = []
    for lv in LEVELS:
        cells = []
        for a, r in (("stock", "known"), ("norns", "known")):
            for m in ("WL", "CLB", "CPD"):
                cells.append(f3(t[f"{a}/{r}_{m}_mesh_tree_a{lv}"]["gmean"]))
        rows.append(f"{lvl(lv)} & " + " & ".join(cells) + r" \\")
    return "\n".join(rows)


def main() -> int:
    res = nl.read_json(RES)
    keep = nl.read_json(nl.DATA / "r6" / "keep.json")
    failing = sorted(d for d, v in keep.items() if not v["kept"])
    sentence = one_sentence(res)
    k = res["keep"]
    write("r6-abstract.tex", fr"""
A sixth round removes the leak of the fifth: the Norns HDL-aware packer gained over stock VPR only where the HDL word file was the block partition. It keeps the round-five datapath blocks, topologies (mesh, tree, and a chain control) and known optimal clustering, and changes only how the HDL declares its registers, so that a controlled fraction of each block's flip-flops sit in other blocks' words (alignment a from 1, the leak, to 0, every word spanning about ten blocks): {k['n']} generated designs, {k['kept']} of which keep the construction through Odin III. {sentence} Scope: one packer configuration ($\beta=4$) and words of exactly ten bit-slice flip-flops, which equals one CLB ($N_{{\mathrm{{LE}}}}=10$); other word sizes are untested. Alignment is a construction on synthetic designs, not a measurement of real HDL. Protocol \code{{{PROTOCOL_SHA}}}.
""")
    write("r6-method.tex", fr"""
\subsection{{Round six: method}}
\label{{sec:r6-method}}
\paragraph{{Question N Q3.1 on the yardstick of N Q1.6.}} As the alignment $a$ between the HDL words and the optimal blocks falls from 1 to 0, how does the gain of the Norns HDL-aware packer over the stock VPR packer in wirelength, CLB count and critical-path delay change, and does it ever do worse? Round five could not say: in its \code{{dp}} designs the word file equals the block partition.
\paragraph{{Designs.}} The logic of a round-six design is exactly the round-five \code{{dp}} design of the same topology and size (same blocks, functions, wiring and fixed I/O; each block fills one CLB). Only the HDL declaration of the registers changes: inside a block the registers and ports are scalars, and the top module declares $B$ vectors \code{{w<j>[9:0]}} that are the HDL words. At alignment $a$, a fraction $1-a$ of each block's flip-flops is displaced and dealt, ordered by local bit then block, into the displaced slots, so a word holds the same local bit of consecutive blocks (a bit-slice). At $a=1$ the words are the blocks (the leak, the reference); at $a=0$ every word holds ten flip-flops of ten blocks and a block's flip-flops sit in ten words. Levels $a\in\{{0,0.25,0.5,0.75,1\}}$, topologies mesh, tree and chain, $B\in\{{16,\dots,1024\}}$ (seven sizes): {k['n']} designs. The alignment is measured after synthesis as the purity of the word file against the blocks. Arms: \code{{stock}}, \code{{norns}} (round-four headline configuration, fed the word file as written) and \code{{known}} (block membership as affinity, $\beta=100$), three VPR seeds each. Primary metric of every hypothesis is wirelength; CLB count and delay are secondary. The placebo is the ratio of stock at level $a$ to stock at $a=1$ of the same cell: the same logic with different register names.
Rules, thresholds and statuses are in the protocol (\code{{docs/plan/round6.md}}, SHA \code{{{PROTOCOL_SHA}}}) and its dated entries; the paper repeats none of them. Excluded by the rule fixed in advance: {', '.join(tex(d) for d in failing) if failing else 'none'}.
""")
    write("r6-results.tex", fr"""
\subsection{{Round six: results}}
\label{{sec:r6-results}}
Table~\ref{{tab:r6status}} gives every hypothesis with its status and deciding number. Table~\ref{{tab:r6level}} gives, per alignment level, the Norns / stock wirelength ratio (geometric mean over designs, 90\% bootstrap interval), the placebo and the measured alignment; Table~\ref{{tab:r6known}} the gap to the known clustering. {sentence}
\begin{{table*}}[t]
\caption{{Round-six hypotheses (protocol \code{{{PROTOCOL_SHA}}}). Ratios are arm / reference, geometric mean over designs of the geometric mean over seeds; ``mesh and tree'' is the headroom set.}}
\label{{tab:r6status}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}lp{{5.2cm}}p{{2.4cm}}p{{8.4cm}}@{{}}}}
\toprule
H & test & status & deciding number \\
\midrule
{status_rows(res)}
\bottomrule
\end{{tabular}}
\end{{table*}}
\begin{{table*}}[t]
\caption{{Norns / stock routed wirelength per alignment level $a$: geometric mean with 90\% bootstrap interval for mesh and tree, mesh, tree and chain; placebo (stock at level $a$ / stock at $a=1$, mesh and tree); median measured word-file purity.}}
\label{{tab:r6level}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}rlllllr@{{}}}}
\toprule
$a$ & mesh+tree & mesh & tree & chain & placebo & purity \\
\midrule
{level_table(res)}
\bottomrule
\end{{tabular}}
\end{{table*}}
\begin{{table}}[t]
\caption{{Ratio to the known clustering on mesh and tree: stock (WL, CLB, CPD) then norns (WL, CLB, CPD), per level $a$.}}
\label{{tab:r6known}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}rrrrrrr@{{}}}}
\toprule
$a$ & WL & CLB & CPD & WL & CLB & CPD \\
\midrule
{known_table(res)}
\bottomrule
\end{{tabular}}
\end{{table}}
{room_note(res)}
{variants(res)}
""")
    write("r6-discussion.tex", fr"""
\subsection{{Round six: discussion}}
\label{{sec:r6-discussion}}
{discussion(res)}
""")
    write("r6-appendix.tex", appendix())
    return 0


def room_note(res: dict) -> str:
    """Why H32 (stock / known WL) differs from round 5's H25 (cause: topology mix; size set and aggregation checked)."""
    r5 = nl.read_json(nl.DATA / "analysis" / "r5-results.json")
    pooled = r5["room_NL_stock"]["WL"]
    topo = r5["room_by_topology_NL_stock"]
    big = r5["room_NL_stock_B32"]["WL"]
    h = res["room"]["WL"]
    return (f"Why the stock / known wirelength ratio of H32 ({f3(h['gmean'])}) differs from round five's ({f3(pooled['gmean'])}, n={pooled['n']} designs): round five pooled all four topologies, and its chain and random designs have no headroom "
            f"(chain {f3(topo['chain']['WL']['gmean'])}, random {f3(topo['rand']['WL']['gmean'])}), diluting the pool; round five's mesh ({f3(topo['mesh']['WL']['gmean'])}) and tree ({f3(topo['tree']['WL']['gmean'])}) alone are close to the {f3(h['gmean'])} here, which is taken over mesh and tree cells only. "
            f"The size set does not explain it (round five restricted to $B\\ge32$ gives {f3(big['gmean'])}, n={big['n']}), and neither does the aggregation (cells here, designs there).")


def variants(res: dict) -> str:
    d, dl = res["dose"]["WL"], res["dose_leakfree_variant"]["WL"]
    lk = res["leak"]
    gc = res["gap_closed"]
    out = [f"Dose-response (H36, WL): median slope {f3(d['median_slope'])} of ln ratio on measured alignment, 90\\% interval of the mean slope [{f3(d['ci90_mean_slope'][0])}, {f3(d['ci90_mean_slope'][1])}]; labelled variant on the leak-free levels only ($a\\le0.75$): median slope {f3(dl['median_slope'])}, {dl['negative_cells']}/{dl['cells']} cells negative ({tex(dl['status'])} by the same rule). "]
    out.append("Norns \\code{.net} equal to the stock \\code{.net} on all three seeds, per level: " +
               ", ".join(f"a={lvl(int(a))}: {v['net_equal_stock']} of {v['designs']} (mean word purity {f3(v['mean_word_purity'])})" for a, v in lk.items()) + ". ")
    out.append("Fraction of the stock-to-known WL gap closed by norns on designs with stock ratio $\\ge1.03$ (mesh and tree): " +
               ", ".join(f"a={lvl(lv)}: {f3(gc[f'WL_a{lv}']['mean'])} (n={gc[f'WL_a{lv}']['n']})" for lv in LEVELS) + ". ")
    pu = res["purity"]
    out.append("Mean purity of the packings against the blocks (null in brackets), stock / norns / known: " +
               "; ".join(f"a={lvl(lv)}: {f3(pu[f'stock_a{lv}']['purity'])} ({f3(pu[f'stock_a{lv}']['null'])}) / {f3(pu[f'norns_a{lv}']['purity'])} / {f3(pu[f'known_a{lv}']['purity'])}" for lv in LEVELS) + ". ")
    if res["failed_runs"]:
        out.append("Failed runs (listed, not replaced): " + ", ".join(tex(x) for x in res["failed_runs"]) + ". ")
    if res["excluded_low_reproduction"]:
        out.append("Excluded from H32 to H36 for reproduction below 0.9: " + ", ".join(tex(x) for x in res["excluded_low_reproduction"]) + ". ")
    return "".join(out)


def discussion(res: dict) -> str:
    out = []
    sentence = one_sentence(res)
    out.append(f"The one-sentence answer, built from the literal statuses of H33 to H37: {sentence} ")
    al = res["align"]
    out.append(f"The manipulation did what it was built to do (H30 {tex(al['status'])}: Spearman {f3(al['rho'])}, median measured purity {f3(al['median_level0'])} at $a=0$ and {f3(al['median_level100'])} at $a=1$), so a level is a measured fraction of the word file that equals the block partition. ")
    d = res["dose"]["WL"]
    out.append(f"The dose-response slope of the wirelength ratio on measured alignment is {f3(d['median_slope'])} (status {tex(d['status'])}); a gain concentrated at $a=1$ would also give a negative slope, so the leak-free variant and the per-level tests H34 carry the non-leaky claim. ")
    c = res["control_chain"]
    ch = [(lv, res["tables"][f"norns/stock_WL_chain_a{lv}"]) for lv in LEVELS]
    bad = [lv for lv, v in ch if not (0.98 <= v["ci90"][0] and v["ci90"][1] <= 1.02)]
    out.append(f"On the chain control, where round five found no headroom, norns / stock is {f3(c['gmean'])} pooled over the five levels (H37 {tex(c['status'])}, pooled as pre-registered); per level, a=" +
               ", ".join(lvl(lv) for lv, _ in ch) + " give " + ", ".join(f2(v["gmean"]) for _, v in ch) +
               ". The chain control (90\\% interval inside [0.98, 1.02]) " +
               ("fails at every level $a<1$ and holds at $a=1$." if bad == [lv for lv in LEVELS if lv < 100] else
                "fails at $a\\in\\{" + ", ".join(lvl(x) for x in bad) + "\\}$.") + " The pooled figure hides this level structure; H37 keeps its pre-registered pooled status. ")
    pl = res["placebo"]["WL"]
    out.append("The placebo (stock at level $a$ against stock at $a=1$) has geometric mean " +
               ", ".join(f"{f3(pl[str(lv)]['gmean'])} at $a={lvl(lv)}$" for lv in (0, 25, 50, 75)) +
               ". The synthesised BLIFs of one cell are structurally identical across levels and only the register names and the \\code{.net} hashes differ; stock VPR is invariant to register names here (zero noise), so the placebo is an invariance check of the stock packer, not a noise null, and it gives no interval against which to call a Norns effect found. ")
    out.append("Limits: one packer configuration (the round-four headline setting, $\\beta=4$) on words of exactly ten bit-slice flip-flops, equal to the CLB capacity ($N_{\\mathrm{LE}}=10$); the word size was not varied, so word sizes other than one CLB are untested; synthetic designs from a generator; the alignment is a construction (a bit-slice deal of flip-flop names), not real HDL, where a word's members need not be bit-slices and LUT words exist; the word file carries flip-flop words only; the Norns packer was not tuned for partial alignment; three topologies and one logic family; the known optimum is a clustering optimum, not a proven wirelength or delay optimum. A result at a given $a$ says what this packer does when that fraction of the HDL words falls in the block, not what real HDL gives.")
    return "".join(out)


def appendix() -> str:
    return fr"""
\subsection{{Round six: research log}}
\label{{sec:r6-appendix}}
\paragraph{{2026-10-26, round six.}} Peter (2026-10-26): ``Yes to both'' (to: merge Task 3, and run Norns round 6 as the non-leaky HDL-word test). Question N Q3.1 (area, speed, wirelength) on the yardstick of N Q1.6; protocol \code{{{PROTOCOL_SHA}}}. Disclosures: a four-design mechanism probe (synthesis and word recovery, no VPR) preceded the protocol commit and is recorded in the protocol and in \code{{data/r6/probe}}; the Python binding of the Odin III checkout (ABI 7) did not match its built library (ABI 6), so the binding of Odin III v1.1.1 (commit a1cf6ffd, ABI 6) was used; a pilot of the pipeline (nine VPR runs, three arms by three seeds, on each of \code{{r6\_mesh\_a0\_16}} and \code{{r6\_mesh\_a100\_16}}; protocol entry (b)) was made before the arm batch and is included in \code{{data/r6/runs.jsonl}} and in the statistics; the probe run directories under \code{{runs/}} were deleted by mistake of the lane (they held no round-five data).

The research-question table of the research log gains the row

\begin{{table}}[t]
\caption{{Research question updated in round six.}}
\label{{tab:r6rq}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}lp{{6.4cm}}@{{}}}}
\toprule
RQ & question (measures) \\
\midrule
N Q3.1 & Does packing by higher-level ideas keep the HDL structure, and does it improve placement area and speed when the HDL words do not match the optimal blocks? (area, speed, wirelength) \\
\bottomrule
\end{{tabular}}
\end{{table}}
Regeneration: \code{{python scripts/write\_round6.py}} from \code{{data/analysis/r6-results.json}} (\code{{scripts/r6stats.py}}); the steps that need \code{{runs/}} are \code{{r6.py synth, words, arms}}, and their outputs are committed in \code{{data/r6/}} (\code{{keep.json}}, \code{{runs.jsonl}}, \code{{designs.json}}).
"""


if __name__ == "__main__":
    sys.exit(main())
