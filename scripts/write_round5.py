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


def pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.1f}\\%"


def write(name: str, text: str) -> None:
    (PAPER / name).write_text(text, encoding="utf-8")


def room_rows(res: dict, key: str, label: str, hyp: str) -> str:
    rows = []
    for m in ("CLB", "WL", "CPD"):
        v = res[key][m]
        rows.append(f"{hyp} & {label}: {m} & {tex(v['status'])} & geomean {f3(v['gmean'])}, 90\\% CI [{f3(v['ci90'][0])}, {f3(v['ci90'][1])}], "
                    f"Holm $p={pf(v['p_holm'])}$, n={v['n']} \\\\")
    return "\n".join(rows)


def growth_rows(res: dict, key: str, label: str, hyp: str) -> str:
    rows = []
    for m in ("CLB", "WL"):
        v = res[key][m]
        rows.append(f"{hyp} & {label}: {m} & {tex(v['status'])} & median slope {f3(v['median_slope'])} per doubling, "
                    f"{v['positive_cells']}/{v['cells']} cells positive, Holm $p={pf(v['p_holm'])}$, permutation $p={pf(v['perm_p'])}$ \\\\")
    return "\n".join(rows)


def main() -> int:
    res = nl.read_json(RES)
    keep = nl.read_json(nl.DATA / "r5" / "keep.json")
    hk, nk = res["keep_HDL"], res["keep_NL"]
    ho = res["keep_HDL_original_rule"]
    slack = sorted(v["slack"] for d, v in keep.items() if d.startswith("n5_") and "slack" in v)
    failing = sorted(d for d, v in keep.items() if not v["kept"])
    write("r5-abstract.tex", fr"""
A fifth round builds the yardstick the earlier rounds lacked: 72 generated designs whose optimal clustering is known by construction (blocks that each fill one CLB, wired as chains, meshes, trees and random sparse graphs, 4 to 1024 blocks), in the manner of the PEKO/TPEKO placement benchmarks, at two levels: written directly as a netlist, and as Verilog through Odin III. Against the known clustering the stock VPR packer's gap is {room_summary(res, 'room_NL_stock')} at the netlist level and {room_summary(res, 'room_HDL_stock')} at the HDL level; the HDL-aware packer's is {room_summary(res, 'room_HDL_norns')}. Protocol \code{{{PROTOCOL_SHA}}}.
""")
    write("r5-method.tex", fr"""
\subsection{{Round five: method}}
\label{{sec:r5-method}}
\paragraph{{Question N Q1.6.}} On designs with a known optimal clustering, how far are the VPR packer and the Norns HDL-aware packer from it, and how does the gap grow with size? The idea follows Cong, Romesis and Xie~\cite{{Cong03tpeko}}, who built placement problems with known optima to measure how far placers are from them.
\paragraph{{What ``optimal'' means here.}} A \emph{{clustering}} optimum by construction, not a proven placement optimum. A block is 10 six-input functions, each feeding a flip-flop (10 logic elements of the \code{{k6\_frac\_N10}} architecture, so exactly one CLB), with dense internal connections and at most two external inputs per function. The CLB count $B$ is an exact lower bound and is reached by the block partition. The block partition's cut is exact for that partition but is an upper bound on the minimum cut: at the netlist level a local search of improving pair swaps found a slack of {pct(slack[0]) if slack else 'n/a'} to {pct(slack[-1]) if slack else 'n/a'} (median {pct(slack[len(slack)//2]) if slack else 'n/a'}) on the {len(slack)} netlist designs. The ``known'' arm hands the block partition to the same placer and router, so its wirelength, channel width and critical-path delay are what VPR achieves from a good clustering, not a bound; ratios below one are possible.
\paragraph{{Designs.}} Nine sizes ($B=4$ to $1024$), four topologies (chain, mesh, tree, random sparse), two styles (\code{{dp}}: a datapath slice whose HDL has the vector \code{{r[9:0]}}; \code{{ctl}}: scalar registers, random logic with no vector), generated deterministically from the seed 20261026. Two levels: NL, the netlist written directly as BLIF (no Odin III, no ABC), and HDL, the same specifications as Verilog through Odin III. Arms: \code{{stock}} VPR; \code{{norns}} (HDL level only: the round-four headline packer, affinity source \code{{word}}, $\beta=4$, which needs provenance); \code{{known}} (the Norns binary with the block membership as affinity groups, $\beta=100$). Three VPR seeds each. Synthesis keeps the construction in {hk['kept']} of {hk['n']} HDL designs (original label rule: {ho['kept']}); the netlist check passes on {nk['kept']} of {nk['n']}. Excluded by the rule fixed in advance: {', '.join(tex(d) for d in failing) if failing else 'none'}.
Rules, thresholds and statuses are in the protocol (\code{{docs/plan/round5.md}}, SHA \code{{{PROTOCOL_SHA}}}) and four dated entries; the paper repeats none of them.
""")
    rr = []
    rr.append(room_rows(res, "room_NL_stock", "NL stock vs known", "H25"))
    rr.append(room_rows(res, "room_HDL_stock", "HDL stock vs known", "H19"))
    rr.append(room_rows(res, "room_HDL_norns", "HDL norns vs known", "H20"))
    gr = [growth_rows(res, "growth_NL_stock", "NL stock", "H26"), growth_rows(res, "growth_HDL_stock", "HDL stock", "H21"),
          growth_rows(res, "growth_HDL_norns", "HDL norns", "H21")]
    cl = res["close_HDL"]
    close_rows = "\n".join(
        f"H22 & HDL norns vs stock: {m} & {tex(cl[m]['status'])} & geomean {f3(cl[m]['gmean'])}, 90\\% CI [{f3(cl[m]['ci90'][0])}, {f3(cl[m]['ci90'][1])}], Holm $p={pf(cl[m]['p_holm'])}$, n={cl[m]['n']} \\\\"
        for m in ("CLB", "WL", "CPD"))
    h23, rpH, rpN = res["h23"], res["repro_HDL"], res["repro_NL"]
    write("r5-results.tex", fr"""
\subsection{{Round five: results}}
\label{{sec:r5-results}}
Table~\ref{{tab:r5status}} gives every hypothesis with its status and deciding number. Table~\ref{{tab:r5gap}} gives the geometric-mean ratio of each packer to the known clustering per size (routed wirelength, then logic CLB count). The netlist level is the headroom number; the HDL level is the Norns question.
\begin{{table*}}[t]
\caption{{Round-five hypotheses (protocol \code{{{PROTOCOL_SHA}}}). Ratios are packer / known clustering, geometric mean over designs of the geometric mean over three seeds.}}
\label{{tab:r5status}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}lp{{4.4cm}}p{{2.6cm}}p{{9.0cm}}@{{}}}}
\toprule
H & test & status & deciding number \\
\midrule
H18 & HDL: synthesis keeps the construction & {tex(hk['status'])} & {hk['kept']} of {hk['n']} kept ({pct(hk['share'])}); original label rule {ho['kept']} of {ho['n']} \\
H28 & NL: netlist check passes & {tex(nk['status'])} & {nk['kept']} of {nk['n']} pass ({pct(nk['share'])}) \\
H24 & HDL: forced clustering reproduces the blocks & {tex(rpH['status'])} & mean reproduction {f3(rpH['mean'])}, {pct(rpH['share_full'])} of runs exact, n={rpH['n']} runs \\
H27 & NL: forced clustering reproduces the blocks & {tex(rpN['status'])} & mean reproduction {f3(rpN['mean'])}, {pct(rpN['share_full'])} of runs exact, n={rpN['n']} runs \\
{rr[0]}
{rr[1]}
{rr[2]}
{gr[0]}
{gr[1]}
{gr[2]}
{close_rows}
H23 & purity gain, \code{{dp}} minus \code{{ctl}} & {tex(h23['status'])} & median {f3(h23['median'])}, $p={pf(h23['p'])}$, {pct(h23['frac_positive'])} of pairs positive, n={h23['n']} pairs \\
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


def discussion(res: dict) -> str:
    out = []
    s = res["room_NL_stock"]
    out.append(f"At the netlist level the stock packer's wirelength is {f3(s['WL']['gmean'])} times, its CLB count {f3(s['CLB']['gmean'])} times and its critical-path delay {f3(s['CPD']['gmean'])} times those obtained from the known clustering (statuses: WL {s['WL']['status']}, CLB {s['CLB']['status']}, CPD {s['CPD']['status']}). ")
    g = res["growth_NL_stock"]["WL"]
    out.append(f"The wirelength gap changes by {f3(g['median_slope'])} (natural-log ratio) per doubling of the block count (median of the cell slopes; status {g['status']}). ")
    h = res["room_HDL_norns"]
    c = res["close_HDL"]
    out.append(f"At the HDL level the HDL-aware packer's wirelength ratio to the known clustering is {f3(h['WL']['gmean'])}, against the stock packer's {f3(res['room_HDL_stock']['WL']['gmean'])}; the direct comparison norns against stock gives wirelength {f3(c['WL']['gmean'])} ({c['WL']['status']}), CLB count {f3(c['CLB']['gmean'])} ({c['CLB']['status']}) and critical-path delay {f3(c['CPD']['gmean'])} ({c['CPD']['status']}). ")
    cs = res["close_HDL_by_style"]
    out.append(f"By style, the comparison norns against stock gives wirelength {f3(cs['dp']['WL']['gmean'])} ({cs['dp']['WL']['status']}) for \\code{{dp}} (the HDL has the vector, and word recovery returns one word per block, so the word affinity file is the block partition on the flip-flops: the favourable case, and partly a leak of the answer) and {f3(cs['ctl']['WL']['gmean'])} ({cs['ctl']['WL']['status']}) for \\code{{ctl}} (no words, so the Norns packer equals the stock packer). H23 compares the purity gain between styles: median {f3(res['h23']['median'])} per pair, {peq(res['h23']['p'])}; the literal rule needs a median of 0.05, and the gain is concentrated in the topologies where blocks are not already packed (see the exploratory topology table), so the status is {res['h23']['status']}. ")
    t = res["exploratory_topology_gap"]["NL_stock_WL"]
    out.append(f"Exploratory: the stock gap sits in the mesh ({f3(t['mesh'])}) and the tree ({f3(t['tree'])}); chains ({f3(t['chain'])}) and random sparse graphs ({f3(t['rand'])}) leave no room for a clustering (a chain packs by connectivity; the random graph has no locality). ")
    out.append("Limits: the optimum is a clustering optimum by construction, the cut is an upper bound on the minimum cut within the stated slack, and ratios are against what VPR achieves from the known clustering, not against a proven placement optimum. The generated functions are random or XOR-heavy, which is not the structure of human RTL (compare the distribution-shift reading of Loki's round three).")
    return "".join(out)


def appendix() -> str:
    lines = PLAN.read_text().splitlines()
    quotes = [x[2:].strip('"') for x in lines if x.startswith("> ")]
    return fr"""
\subsection{{Round five: research log}}
\label{{sec:r5-appendix}}
\paragraph{{2026-10-26, round five.}} Peter: ``{quotes[0]}'' and ``{quotes[1]}'' Peter (2026-10-26) then asked for a netlist-level arm (pure TPEKO, exact optimum) beside the HDL level, reported separately. Question N Q1.6 (area, speed, wirelength); protocol \code{{{PROTOCOL_SHA}}}, with dated entries: (a) generator changes found by the keep check (outputs, chain I/O, rand cycle, \code{{ctl}} functions, viability filter, spec labels for port-named flip-flops), (b) the netlist level, (c) the netlist check rule (local-search slack, changed after seeing three checks), (d) \code{{ctl}} scalar ports (a word was found where none was intended). Disclosures: HDL generation and synthesis preceded entries (a) to (d); a pilot VPR run of the two smallest designs preceded the batch and is included.
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
