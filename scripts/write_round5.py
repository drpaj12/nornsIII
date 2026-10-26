"""Write the round-5 paper text: docs/paper/r5-*.tex, included by norns.tex.

Every deciding number comes from data/analysis/r5-results.json (scripts/r5stats.py), data/r5/keep.json and
data/r5/runs.jsonl; no number is typed here. Usage: python scripts/write_round5.py
"""

from __future__ import annotations

import math
import sys

import nornlib as nl

PAPER = nl.WS / "docs" / "paper"
PLAN = nl.WS / "docs" / "plan" / "round5.md"
PROTOCOL_SHA = "7886f49"
RES = nl.DATA / "analysis" / "r5-results.json"


def tex(s: str) -> str:
    return str(s).replace("_", r"\_").replace("%", r"\%")


def f3(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def pf(p) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def peq(p) -> str:
    return "p=n/a" if p is None or (isinstance(p, float) and math.isnan(p)) else ("p<0.001" if p < 0.001 else f"p={p:.3f}")


def f4(x) -> str:
    return f"{x:.4f}"


def pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.1f}\\%"


def write(name: str, text: str) -> None:
    (PAPER / name).write_text(text, encoding="utf-8")


def room_rows(res: dict, key: str, label: str, hyp: str) -> str:
    rows = []
    for m in ("CLB", "WL", "CPD"):
        v = res[key][m]
        rows.append(f"{hyp} & {label}: {m} & {tex(v['status'])} & geomean {f3(v['gmean'])}, 90\\% CI [{f3(v['ci90'][0])}, {f3(v['ci90'][1])}], "
                    f"Holm ${peq(v['p_holm'])}$, n={v['n']} \\\\")
    return "\n".join(rows)


def growth_rows(res: dict, key: str, label: str, hyp: str) -> str:
    rows = []
    for m in ("CLB", "WL"):
        v = res[key][m]
        rows.append(f"{hyp} & {label}: {m} & {tex(v['status'])} & median slope {f3(v['median_slope'])} per doubling, "
                    f"{v['positive_cells']}/{v['cells']} cells positive, Holm ${peq(v['p_holm'])}$, permutation ${peq(v['perm_p'])}$ \\\\")
    return "\n".join(rows)


def main() -> int:
    res = nl.read_json(RES)
    keep = nl.read_json(nl.DATA / "r5" / "keep.json")
    hk, nk = res["keep_HDL"], res["keep_NL"]
    ho = res["keep_HDL_original_rule"]
    slack = sorted(v["slack"] for d, v in keep.items() if d.startswith("n5_") and "slack" in v)
    failing = sorted(d for d, v in keep.items() if not v["kept"])
    nlit, n5, ls, lk, cs = res["keep_NL_literal"], res["keep_NL_slack5"], res["local_search"], res["leak_HDL"], res["close_HDL_by_style"]
    write("r5-abstract.tex", fr"""
A fifth round builds the yardstick the earlier rounds lacked: 72 generated designs whose optimal clustering is known by construction (blocks that each fill one CLB, wired as chains, meshes, trees and random sparse graphs, 4 to 1024 blocks), in the manner of the PEKO/TPEKO placement benchmarks, at two levels: written directly as a netlist, and as Verilog through Odin III. The optimum is exact for the CLB count only; the cut is an upper bound on the minimum cut, and the wirelength and delay ratios are against the placement VPR produces from the forced block clustering, not against a proven placement optimum. Against that clustering the stock VPR packer's gap is {room_summary(res, 'room_NL_stock')} at the netlist level and {room_summary(res, 'room_HDL_stock')} at the HDL level; the HDL-aware packer's is {room_summary(res, 'room_HDL_norns')}. Status under the literal, pre-data rules: the netlist exactness check (H28) is {tex(nlit['status'])} ({nlit['kept']} of {nlit['n']} designs pass the zero-violation rule; the slack rule chosen after the data passes {nk['kept']} of {nk['n']}, labelled a variant) and the HDL yardstick check (H18) is {tex(ho['status'])} ({ho['kept']} of {ho['n']} under the original label rule; the amended rule keeps {hk['kept']}, {tex(hk['status'])}). The HDL-aware packer's gain over the stock packer (wirelength x{f3(res['close_HDL']['WL']['gmean'])}) is a leak, not evidence of HDL knowledge: it sits in \code{{dp}} (wirelength x{f3(cs['dp']['WL']['gmean'])}), where the word file is the block partition (purity {f4(lk['dp']['purity_norns'])} against the stock packer's {f4(lk['dp']['purity_stock'])}), and is zero in \code{{ctl}} (x{f3(cs['ctl']['WL']['gmean'])}; {lk['ctl']['net_equal_stock']} of {lk['ctl']['designs']} \code{{.net}} files equal the stock files), so this round is no evidence of an HDL-knowledge gain beyond the leak. Protocol \code{{{PROTOCOL_SHA}}}.
""")
    write("r5-method.tex", fr"""
\subsection{{Round five: method}}
\label{{sec:r5-method}}
\paragraph{{Question N Q1.6.}} On designs with a known optimal clustering, how far are the VPR packer and the Norns HDL-aware packer from it, and how does the gap grow with size? The idea follows Cong, Romesis and Xie~\cite{{Cong03tpeko}}, who built placement problems with known optima to measure how far placers are from them.
\paragraph{{What ``optimal'' means here.}} A \emph{{clustering}} optimum by construction, not a proven placement optimum. A block is 10 six-input functions, each feeding a flip-flop (10 logic elements of the \code{{k6\_frac\_N10}} architecture, so exactly one CLB), with dense internal connections and at most two external inputs per function. The CLB count $B$ is an exact lower bound and is reached by the block partition. The block partition's cut is exact for that partition but is an upper bound on the minimum cut: at the netlist level a local search of improving pair swaps found a slack of {pct(slack[0]) if slack else 'n/a'} to {pct(slack[-1]) if slack else 'n/a'} (median {pct(slack[len(slack)//2]) if slack else 'n/a'}) on the {len(slack)} netlist designs; the search was capped at 8 rounds and converged within the cap on {ls['converged_within_cap']} of {ls['n']} designs (at most {ls['max_rounds']} rounds), so the slack is a lower bound on the non-minimality of the block cut. The random-restart search (protocol: 20000 restarts; run: 500 at $B=4$ and 300 at $B=8$, {ls['restart_designs']} designs) found a smaller cut on {ls['search_smaller']} of them, but its best cuts at $B=8$ ({ls['search_best_range'][0]} to {ls['search_best_range'][1]}) are far above the block cuts ({ls['block_cut_b8_range'][0]} to {ls['block_cut_b8_range'][1]}), so it is weak evidence that the block cut is minimal. The ``known'' arm hands the block partition to the same placer and router, so its wirelength, channel width and critical-path delay are what VPR achieves from a good clustering, not a bound; ratios below one are possible.
\paragraph{{Designs.}} Nine sizes ($B=4$ to $1024$), four topologies (chain, mesh, tree, random sparse), two styles (\code{{dp}}: a datapath slice whose HDL has the vector \code{{r[9:0]}}; \code{{ctl}}: scalar registers, random logic with no vector), generated deterministically from the seed 20261026. Two levels: NL, the netlist written directly as BLIF (no Odin III, no ABC), and HDL, the same specifications as Verilog through Odin III. Arms: \code{{stock}} VPR; \code{{norns}} (HDL level only: the round-four headline packer, affinity source \code{{word}}, $\beta=4$, which needs provenance); \code{{known}} (the Norns binary with the block membership as affinity groups, $\beta=100$). Three VPR seeds each. Synthesis keeps the construction in {hk['kept']} of {hk['n']} HDL designs under the amended label rule (original, literal rule: {ho['kept']}); the netlist check passes on {nlit['kept']} of {nlit['n']} designs under the literal zero-violation rule, {nk['kept']} of {nk['n']} under the slack rule of entry (c) (chosen after the data) and {n5['kept']} of {n5['n']} at a 5\% slack bound. H19 to H24 use the {hk['kept']} designs of the amended rule; H25 to H27 the {nk['kept']} designs of entry (c). Excluded by the rule fixed in advance: {', '.join(tex(d) for d in failing) if failing else 'none'}.
Rules, thresholds and statuses are in the protocol (\code{{docs/plan/round5.md}}, SHA \code{{{PROTOCOL_SHA}}}) and six dated entries; the paper repeats none of them.
""")
    rr = []
    rr.append(room_rows(res, "room_NL_stock", "NL stock vs known", "H25"))
    rr.append(room_rows(res, "room_HDL_stock", "HDL stock vs known", "H19"))
    rr.append(room_rows(res, "room_HDL_norns", "HDL norns vs known", "H20"))
    gr = [growth_rows(res, "growth_NL_stock", "NL stock", "H26"), growth_rows(res, "growth_HDL_stock", "HDL stock", "H21"),
          growth_rows(res, "growth_HDL_norns", "HDL norns", "H21")]
    cl = res["close_HDL"]
    close_rows = "\n".join(
        f"H22 & HDL norns vs stock: {m} & {tex(cl[m]['status'])} & geomean {f3(cl[m]['gmean'])}, 90\\% CI [{f3(cl[m]['ci90'][0])}, {f3(cl[m]['ci90'][1])}], Holm ${peq(cl[m]['p_holm'])}$, n={cl[m]['n']} \\\\"
        for m in ("CLB", "WL", "CPD"))
    h23, rpH, rpN = res["h23"], res["repro_HDL"], res["repro_NL"]
    write("r5-results.tex", fr"""
\subsection{{Round five: results}}
\label{{sec:r5-results}}
Table~\ref{{tab:r5status}} gives every hypothesis with its status and deciding number. Table~\ref{{tab:r5gap}} gives the geometric-mean ratio of each packer to the known clustering per size (routed wirelength, then logic CLB count). The netlist level is the headroom number; the HDL level is the Norns question.
\begin{{table*}}[t]
\caption{{Round-five hypotheses (protocol \code{{{PROTOCOL_SHA}}}). A star marks a labelled variant whose rule was introduced after data; H25 to H27 are decided on the designs passing the starred H28 rule. Ratios are packer / known clustering, geometric mean over designs of the geometric mean over three seeds.}}
\label{{tab:r5status}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}lp{{4.4cm}}p{{2.6cm}}p{{9.0cm}}@{{}}}}
\toprule
H & test & status & deciding number \\
\midrule
H18 & HDL: synthesis keeps the construction (literal: original label rule) & {tex(ho['status'])} & {ho['kept']} of {ho['n']} kept ({pct(ho['share'])}) \\
H18$^\ast$ & variant: amended label rule (entry (a), after the labels were seen) & {tex(hk['status'])} & {hk['kept']} of {hk['n']} kept ({pct(hk['share'])}) \\
H28 & NL: netlist check passes (literal: entry (b), zero improving swaps) & {tex(nlit['status'])} & {nlit['kept']} of {nlit['n']} pass ({pct(nlit['share'])}) \\
H28$^\ast$ & variant: slack $\le 10$\% (entry (c), chosen after the data) & {tex(nk['status'])} & {nk['kept']} of {nk['n']} pass ({pct(nk['share'])}) \\
H28$^\ast$ & variant: slack $\le 5$\% (sensitivity) & {tex(n5['status'])} & {n5['kept']} of {n5['n']} pass ({pct(n5['share'])}) \\
H24 & HDL: forced clustering reproduces the blocks & {tex(rpH['status'])} & mean reproduction {f3(rpH['mean'])}, {pct(rpH['share_full'])} of runs exact, n={rpH['n']} runs \\
H27 & NL: forced clustering reproduces the blocks & {tex(rpN['status'])} & mean reproduction {f3(rpN['mean'])}, {pct(rpN['share_full'])} of runs exact, n={rpN['n']} runs \\
{rr[0]}
{rr[1]}
{rr[2]}
{gr[0]}
{gr[1]}
{gr[2]}
{close_rows}
H23 & purity gain, \code{{dp}} minus \code{{ctl}} & {tex(h23['status'])} & median {f3(h23['median'])}, ${peq(h23['p'])}$, {pct(h23['frac_positive'])} of pairs positive, n={h23['n']} pairs \\
\bottomrule
\end{{tabular}}
\end{{table*}}
\begin{{table}}[t]
\caption{{Gap to the known clustering per size B: routed wirelength ratio (left three) and logic CLB ratio (right three); NL stock, HDL stock, HDL norns.}}
\label{{tab:r5gap}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}rrrr@{{\hspace{{6pt}}}}rrr@{{}}}}
\toprule
B & NL & stock & norns & NL & stock & norns \\
\midrule
{gap_table_pair(res)}
\bottomrule
\end{{tabular}}
\end{{table}}
Variants (labelled, no status changed): sizes $B\ge32$ only: {variant_summary(res)}. Reported, not tested: the channel-width ratio and the cut ratio of each packer ({report_summary(res)}); the largest null purity of any packing against the known blocks was {f3(res.get('null_purity_max'))}. The Odin III attribution agreed with VPR's critical-path delay (0.5\% tolerance) in {attr_agree(res)}; the share of member-to-member hops on the reported critical paths that cross CLBs is {attr_cross(res)}.
\paragraph{{Exploratory (dated entry (e), no status changed): by topology.}} {topo_text(res)}
\paragraph{{Exploratory, computed (dated entry (f), no status changed): promised variants.}} {variants_f(res)}
""")
    write("r5-discussion.tex", fr"""
\subsection{{Round five: discussion}}
\label{{sec:r5-discussion}}
{discussion(res)}
""")
    write("r5-appendix.tex", appendix())
    return 0


def room_summary(res: dict, key: str) -> str:
    v = res[key]
    return "CLB count x" + f3(v["CLB"]["gmean"]) + ", wirelength x" + f3(v["WL"]["gmean"]) + ", critical-path delay x" + f3(v["CPD"]["gmean"])


def gap_table_pair(res: dict) -> str:
    cols = [("NL", "stock"), ("HDL", "stock"), ("HDL", "norns")]
    sizes = sorted({int(b) for lv, pk in cols for b in res[f"gap_by_size_{lv}_{pk}"]["WL"]})
    rows = []
    for b in sizes:
        cells = []
        for metric in ("WL", "CLB"):
            for lv, pk in cols:
                v = res[f"gap_by_size_{lv}_{pk}"][metric].get(str(b))
                cells.append(f3(v) if v is not None else "n/a")
        rows.append(f"{b} & " + " & ".join(cells) + r" \\")
    return "\n".join(rows)


def attr_agree(res: dict) -> str:
    a = res["attribution"]
    return f"{sum(v['runs'] - v['disagree'] for v in a.values())} of {sum(v['runs'] for v in a.values())} runs"


def attr_cross(res: dict) -> str:
    return ", ".join(f"{tex(k)} {pct(v['crossing_share'])}" for k, v in sorted(res["attribution"].items()))


def topo_text(res: dict) -> str:
    g = res["exploratory_topology_gap"]
    rows = []
    for key in ("NL_stock_WL", "HDL_stock_WL", "HDL_norns_WL", "NL_stock_CLB", "HDL_stock_CLB", "HDL_norns_CLB"):
        rows.append(f"{tex(key)}: " + ", ".join(f"{t} {f3(v)}" for t, v in g[key].items()))
    return "Ratio to the known clustering by topology (geometric mean over designs): " + "; ".join(rows) + "."


def variant_summary(res: dict) -> str:
    parts = []
    for key, lab in (("room_NL_stock_B32", "NL stock"), ("room_HDL_stock_B32", "HDL stock"), ("room_HDL_norns_B32", "HDL norns")):
        v = res[key]
        parts.append(f"{lab} CLB {f3(v['CLB']['gmean'])}, WL {f3(v['WL']['gmean'])}, CPD {f3(v['CPD']['gmean'])} ({tex(v['WL']['status'])} for WL)")
    return "; ".join(parts)


def report_summary(res: dict) -> str:
    parts = []
    for lv, pk in (("NL", "stock"), ("HDL", "stock"), ("HDL", "norns")):
        parts.append(f"{lv} {pk}: W {f3(res[f'report_{lv}_{pk}_W']['gmean'])}, cut {f3(res[f'report_{lv}_{pk}_CUT']['gmean'])}")
    return "; ".join(parts)


def variants_f(res: dict) -> str:
    gc = res["gap_closed_HDL"]
    out = ["Fraction of the gap closed by the HDL-aware packer, (r$_{\\mathrm{stock}}$ - r$_{\\mathrm{norns}}$) / (r$_{\\mathrm{stock}}$ - 1), on HDL designs with r$_{\\mathrm{stock}}\\ge1.03$: " +
           "; ".join(f"{m} mean {f3(v['mean'])}, median {f3(v['median'])}, n={v['n']}" for m, v in gc.items()) + ". "]
    parts = []
    for lv, pk in (("NL", "stock"), ("HDL", "stock"), ("HDL", "norns")):
        r = res[f"room_by_topology_{lv}_{pk}"]
        parts.append(f"{lv} {pk}: " + ", ".join(f"{t} {tex(v['WL']['status'])} (WL {f3(v['WL']['gmean'])}, n={v['WL']['n']})" for t, v in r.items()))
    out.append("The H19/H20/H25 rule applied per topology (wirelength): " + "; ".join(parts) + ". ")
    s = res["room_NL_stock_literal_subset"]
    out.append(f"H25 on the {s['WL']['n']} netlist designs that pass the literal zero-violation check (H28): CLB {f3(s['CLB']['gmean'])} ({tex(s['CLB']['status'])}), WL {f3(s['WL']['gmean'])} ({tex(s['WL']['status'])}), CPD {f3(s['CPD']['gmean'])} ({tex(s['CPD']['status'])}); those designs are mostly chains and trees (mesh and random graphs rarely pass), so this is not the same population. ")
    lk = res["leak_HDL"]
    out.append(f"Leak measurement: in \\code{{dp}} the Norns \\code{{.net}} equals the stock \\code{{.net}} on all three seeds for {lk['dp']['net_equal_stock']} of {lk['dp']['designs']} designs (mean purity against the blocks {f4(lk['dp']['purity_norns'])} against {f4(lk['dp']['purity_stock'])}); in \\code{{ctl}} for {lk['ctl']['net_equal_stock']} of {lk['ctl']['designs']} (purity {f4(lk['ctl']['purity_norns'])} against {f4(lk['ctl']['purity_stock'])}).")
    return "".join(out)


def size_shape(res: dict) -> str:
    g = res["gap_by_size_NL_stock"]["WL"]
    sizes = sorted(int(b) for b in g)
    peak = max(sizes, key=lambda b: g[str(b)])
    return (f"the netlist-level wirelength ratio is {f3(g[str(sizes[0])])} at $B={sizes[0]}$, peaks at {f3(g[str(peak)])} at $B={peak}$ and is {f3(g[str(sizes[-1])])} at $B={sizes[-1]}$, "
            f"so it does not grow monotonically with size")


def discussion(res: dict) -> str:
    out = []
    s = res["room_NL_stock"]
    out.append(f"At the netlist level the stock packer's wirelength is {f3(s['WL']['gmean'])} times, its CLB count {f3(s['CLB']['gmean'])} times and its critical-path delay {f3(s['CPD']['gmean'])} times those obtained from the known clustering (statuses: WL {s['WL']['status']}, CLB {s['CLB']['status']}, CPD {s['CPD']['status']}), on the designs passing the slack rule of entry (c); the literal exactness check (H28) is {res['keep_NL_literal']['status']}, so the cut is not shown to be minimal and only the CLB count is exact. ")
    g = res["growth_NL_stock"]["WL"]
    out.append(f"The wirelength gap changes by {f3(g['median_slope'])} (natural-log ratio) per doubling of the block count (median of the cell slopes; status {g['status']}). ")
    h = res["room_HDL_norns"]
    c = res["close_HDL"]
    cs = res["close_HDL_by_style"]
    lk = res["leak_HDL"]
    hb = res["room_HDL_norns_B32"]["WL"]
    out.append(f"At the HDL level the HDL-aware packer's wirelength ratio to the known clustering is {f3(h['WL']['gmean'])}, against the stock packer's {f3(res['room_HDL_stock']['WL']['gmean'])}; the direct comparison norns against stock gives wirelength {f3(c['WL']['gmean'])} ({c['WL']['status']}), CLB count {f3(c['CLB']['gmean'])} ({c['CLB']['status']}) and critical-path delay {f3(c['CPD']['gmean'])} ({c['CPD']['status']}). The H20 wirelength result is not robust to size: for $B\\ge32$ (n={hb['n']}) it is {hb['status']} (geometric mean {f3(hb['gmean'])}, Holm {peq(hb['p_holm'])}). ")
    out.append(f"The gain is a leak, not a result about HDL knowledge. By style, norns against stock gives wirelength {f3(cs['dp']['WL']['gmean'])} ({cs['dp']['WL']['status']}) for \\code{{dp}}, where word recovery returns one word per block, so the word affinity file is the block partition on the flip-flops (purity {f4(lk['dp']['purity_norns'])} against the stock packer's {f4(lk['dp']['purity_stock'])}), and {f3(cs['ctl']['WL']['gmean'])} ({cs['ctl']['WL']['status']}) for \\code{{ctl}}, where there are no words and {lk['ctl']['net_equal_stock']} of {lk['ctl']['designs']} Norns \\code{{.net}} files equal the stock files. This round is therefore no evidence of an HDL-knowledge gain beyond the leak. ")
    h23 = res["h23"]
    out.append(f"H23 is {h23['status']} under the literal rule (median purity-gain difference {f3(h23['median'])} per pair, {peq(h23['p'])}, {pct(h23['frac_positive'])} of pairs positive, n={h23['n']}), but its ceiling makes that outcome close to forced: in {h23['pairs_zero']} of {h23['n']} pairs d is exactly 0, because the stock purity of the \\code{{dp}} design is already 1.0 (chains at small $B$ and all random graphs), and the mean headroom (one minus the stock purity of the \\code{{dp}} design, the largest gain possible) is {f3(h23['mean_headroom'])}, which is about the {f3(0.05)} threshold the median must reach. ")
    t = res["exploratory_topology_gap"]
    w, cp = t["NL_stock_WL"], t["NL_stock_CPD"]
    out.append(f"Exploratory: the stock gap sits in the mesh (WL {f3(w['mesh'])}, CPD {f3(cp['mesh'])}) and the tree (WL {f3(w['tree'])}, CPD {f3(cp['tree'])}); chains (WL {f3(w['chain'])}, CPD {f3(cp['chain'])}) and random sparse graphs (WL {f3(w['rand'])}, CPD {f3(cp['rand'])}) leave almost none. Conjecture, not tested: a chain packs well by connectivity alone, and a random graph has no locality that a clustering could use. ")
    out.append(f"\\paragraph{{What this round establishes.}} On clustering-optimum-by-construction designs the stock VPR packer leaves about {pct(s['WL']['gmean'] - 1)} of wirelength and {pct(s['CPD']['gmean'] - 1)} of critical-path delay on average at the netlist level (geometric mean over all topologies), concentrated in the mesh and tree constructions (WL {pct(w['mesh'] - 1)} and {pct(w['tree'] - 1)}; CPD {pct(cp['mesh'] - 1)} and {pct(cp['tree'] - 1)}) and absent in chains and random sparse graphs; {size_shape(res)}. These numbers are against what VPR achieves from the forced block clustering, not against a proven optimum. What the round does not show is that HDL knowledge closes any of it. A non-leaky test of that needs designs where the HDL words do not coincide with the optimal blocks: words that span several blocks, or blocks that mix several words. That is the next question. ")
    out.append("Limits: the optimum is a clustering optimum by construction, the cut is an upper bound on the minimum cut within the stated slack (and the exactness check is not supported under its literal rule), and ratios are against what VPR achieves from the known clustering, not against a proven placement optimum. The generated functions are random or XOR-heavy, which is not the structure of human RTL (compare the distribution-shift reading of Loki's round three). Sizes stop at 1024 blocks and no dedicated critical-chain design was built.")
    return "".join(out)


def appendix() -> str:
    lines = PLAN.read_text().splitlines()
    quotes = [x[2:].strip('"') for x in lines if x.startswith("> ")]
    return fr"""
\subsection{{Round five: research log}}
\label{{sec:r5-appendix}}
\paragraph{{2026-10-26, round five.}} Peter: ``{quotes[0]}'' and ``{quotes[1]}'' Peter (2026-10-26) then asked for a netlist-level arm (pure TPEKO, exact optimum) beside the HDL level, reported separately. Question N Q1.6 (area, speed, wirelength); protocol \code{{{PROTOCOL_SHA}}}, with dated entries: (a) generator changes found by the keep check (outputs, chain I/O, rand cycle, \code{{ctl}} functions, viability filter, spec labels for port-named flip-flops), (b) the netlist level, (c) the netlist check rule (local-search slack, changed after seeing three checks), (d) \code{{ctl}} scalar ports (a word was found where none was intended), (e) exploratory analyses after the data, (f) review fixes (the literal pre-data rules for H18 and H28 made primary, H21 Holm over four tests with 10000 permutations, local-search convergence, the leak). Disclosures: HDL generation and synthesis preceded entries (a) to (d); a pilot VPR run of the two smallest designs preceded the batch and is included; the inconclusive case of the H22 rule test in \code{{tests/test\_r5.py}} was rewritten after the data (its first input was ``not supported'' by the written rule; the rule did not change); the netlist check rule of entry (c) and the label rule of entry (a) were changed after data and are reported as variants beside the literal rules.
Research question N Q1.6 (area, speed, wirelength): on designs with a known optimal clustering, how far are the VPR packer and the Norns packer from it, and how does the gap grow with size? The answer is in Table~\ref{{tab:r5status}} (statuses), Table~\ref{{tab:r5gap}} (gap per size) and the discussion; the RQ table of the research log gains the row

\begin{{table}}[t]
\caption{{Research question added in round five.}}
\label{{tab:r5rq}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}lp{{6.4cm}}@{{}}}}
\toprule
RQ & question (measures) \\
\midrule
N Q1.6 & On designs with a known optimal clustering, how far are the VPR packer and the Norns HDL-aware packer from it, and how does the gap grow with size? (area, speed, wirelength) \\
\bottomrule
\end{{tabular}}
\end{{table}}
Regeneration: \code{{python scripts/write\_round5.py}} from \code{{data/analysis/r5-results.json}} (\code{{scripts/r5stats.py}}); the steps that need \code{{runs/}} (VPR logs, flat placements, BLIFs) are \code{{r5.py synth, words, arms, attr, hops}}, and their outputs are committed in \code{{data/r5/}} (\code{{keep.json}}, \code{{runs.jsonl}}, \code{{designs.json}}).
"""


if __name__ == "__main__":
    sys.exit(main())
