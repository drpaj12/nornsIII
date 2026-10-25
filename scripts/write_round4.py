"""Write the round-4 paper text: docs/paper/r4-*.tex, included by norns.tex.

Every number comes from data/analysis/r4-results.json (scripts/r4stats.py), r4-gate.json, r4-join.json and the
data/<d>/ records, so the text regenerates byte-identically. Usage: python scripts/write_round4.py
"""

from __future__ import annotations

import math
import sys

import nornlib as nl
import r4stats as st

PAPER = nl.WS / "docs" / "paper"
PROTOCOL_SHA = "fbddfa0"
PROTOCOL_TIME = "2026-10-25 12:51 (UTC-4)"
PLAN = nl.WS / "docs" / "plan" / "round4.md"
DESIGNS = list(nl.DESIGN_ORDER)


def tex(s: str) -> str:
    return s.replace("_", r"\_").replace("%", r"\%")


def trel(s: str) -> str:
    """Escape a relation text for LaTeX text mode (comparison signs would print as other glyphs in OT1)."""
    return tex(s).replace("<=", r"$\le$").replace(">=", r"$\ge$").replace(">", r"$>$").replace("<", r"$<$")


def f3(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def f2(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}\\%"


def pf(p) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def peq(p) -> str:
    """'p=0.012' or 'p<0.001' (never 'p=<0.001')."""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "p=n/a"
    return "p<0.001" if p < 0.001 else f"p={p:.3f}"


def quotes() -> tuple[str, str]:
    lines = PLAN.read_text().splitlines()
    blocks: list[str] = []
    cur: list[str] = []
    for x in lines:
        if x.startswith("> "):
            cur.append(x[2:])
        elif cur:
            blocks.append(" ".join(cur))
            cur = []
    return blocks[0].strip('"'), blocks[1].strip('"')


def write(name: str, text: str) -> None:
    (PAPER / name).write_text(text, encoding="utf-8")


def gate_numbers() -> dict:
    g = nl.read_json(nl.DATA / "analysis" / "r4-gate.json")
    out = {"a": [0, 0], "b": [0, 0], "c": [0, 0], "info_same": 0, "info": 0}
    for rows in g.values():
        for r in rows:
            if r["gate"] == "info":
                out["info"] += 1
                out["info_same"] += 1 if r["same_packing"] else 0
            else:
                out[r["gate"]][1] += 1
                out[r["gate"]][0] += 1 if r["identical"] else 0
    return out


def join_table() -> str:
    j = nl.read_json(nl.DATA / "analysis" / "r4-join.json")
    rows = []
    for d in DESIGNS:
        v = j[d]
        cells = []
        for s in ("module", "word", "wordio"):
            a, b = v[s]["r3"], v[s]["r4"]
            cells.append(f"{a['matched']}/{a['entries']} & {b['matched']}/{b['entries']}")
        rev = []
        for s in ("module", "word", "wordio"):
            c = v["reverse"][s]["r4"]
            rev.append(f"{sum(c[k][0] for k in c)}/{sum(c[k][1] for k in c)}")
        adders = v["reverse"]["module"]["r3"]["adder"]
        rows.append(f"{tex(d)} & " + " & ".join(cells) + " & " + " & ".join(rev) + f" & {adders[0]}/{adders[1]}" + r" \\")
    return "\n".join(rows)


def main() -> int:
    res = nl.read_json(st.RESULT)
    n17, n12, n13, arms, h15 = res["n17"], res["n12"], res["n13"], res["arms"], res["h15"]
    gate = gate_numbers()
    q1, q2 = quotes()
    a = n17["H17a"]
    # ---- abstract
    write("r4-abstract.tex", fr"""
\par\smallskip\noindent\emph{{Round four.}} A log-only census of the packer, fixes to the Norns packer (proposal counting, the
affinity join) and a post-route critical-path attribution from Odin~III answer what gets clustered: over @@n@@ designs the stock
packer's CLB pairs are, by median, {pct(a['median_SC'])} series-critical, {pct(a['median_SI_OR'])} shared-input or orthogonal and
{pct(a['median_SN_FL'])} series-noncritical or filler (SN+FL, the non-critical remainder; medians SN {pct(a['median_SN'])}, FL {pct(a['median_FL'])}).
Peter's illustration was 10/75/15: shape {a['shape']}, literal numbers {a['numbers']} (orthogonal is a lower bound: the words cover about half the LUTs, and the registered rule's ``t$<$0.40'' arm is sensitive to it).
Near-critical edges are split across CLBs less often than edges in general (H17c {n17['H17c']['status']} by the literal rule: median rate ratio {f3(n17['H17c']['median_ratio'])}, ${peq(n17['H17c'].get('p'))}$, {n17['H17c']['n']} designs with at least 20 hops; with an n$<$12 clause, a reading outside the registered rule, {n17['H17c']['status_n12_variant']}).
Hierarchy versus chip size: H13a {n13['status']['H13a']}, H13b {n13['status']['H13b']}. The norns packer against stock on critical-path delay: {arms['all']['H14']['cpd_ns'].get('status')}; the stage-by-bit seed: see Table~\ref{{tab:r4status}}.
Found in this round: the round-three affinity files lacked every adder (carry-chain) atom, so round three's affinity results describe a packer that did not see carry chains (Section~\ref{{sec:r4-method}}).
""".replace("@@n@@", str(n17["n"])))
    # ---- method
    j = nl.read_json(nl.DATA / "analysis" / "r4-join.json")
    summ = n17["summary"]
    chk = arms["checks"]
    method = rf"""
\subsection{{Round four: method}}
\label{{sec:r4-method}}
Protocol \code{{docs/plan/round4.md}}, committed as \code{{{PROTOCOL_SHA}}} on {PROTOCOL_TIME}, before any round-four
measurement or VPR run (the packer fixes and the Stage-1 gate runs followed it; a later dated entry fixes construction details
and amends N16 items 5 and 6, before any N16 data, keeping the old text; a fix-round entry records corrections and disclosures; no hypothesis rule changed). Small test runs on \code{{ch\_intrinsics}} (options parse, census writes) preceded the gates; they were deleted and no result uses them. Designs, flow and the Norns headline (source \code{{word}}, $\beta=4$) are those of round three.

\paragraph{{Packer fixes and gates.}} The proposal step now counts molecules that entered the candidate queue
(\code{{--norns\_proposal\_count queued}}); \code{{attempted}} is the round-three behaviour. A log-only census
(\code{{--norns\_pack\_census}}) writes, per molecule added to a cluster, the candidate source, the gain terms VPR held, the
pack-time criticality of each input pin, the molecules offered to the candidate queue and the candidates the legalizer refused. Gates
(15 designs, seed 1, byte comparison of the \code{{.net}}): (a) stock against the Norns binary with the option absent and beta~0, {gate['a'][0]} of {gate['a'][1]} identical;
(b) census on against off, \code{{--pack}} and the analytical flow, stock and headline arm, {gate['b'][0]} of {gate['b'][1]};
(c) \code{{attempted}} counting against the round-three binary on the 45 headline configs (\code{{.net}} and flat placement), {gate['c'][0]} of {gate['c'][1]}.
No experiment ran before all passed.

\paragraph{{Affinity join.}} Round three's affinity files matched few entries for mkDelayWorker32B ({j['mkDelayWorker32B']['word']['r3']['matched']} of {j['mkDelayWorker32B']['word']['r3']['entries']}
word entries). The cause was not a name form: the file listed buffer LUTs that VPR absorbs, dead logic that VPR sweeps, and
(a bug found in this round) it named every adder after its first pin instead of its \code{{cout}} net, so adder atoms were never in a round-three file.
The round-four builder drops absorbed buffers and swept blocks and names adders as VPR does; every entry of every file now matches an atom
(Table~\ref{{tab:r4join}}). The round-four files were final at 13:08 (join check 13:12), after the first dated entry described them as ``the same atoms as round three's minus buffers''; the entry of the fix round records the correction. Because the adders are now labelled, the round-four files change the packing of {gate['info'] - gate['info_same']} of {gate['info']} (design, source) pairs against round three's (information rows of the gate).

\paragraph{{Census classes.}} Every pair of LUT, FF and adder atoms in one logic CLB falls in the first class that applies:
series-critical (a local net, fanout $\le32$, from one to the other, with pack-time sink criticality $\ge0.5$), series-noncritical (the same below 0.5),
shared-input (sinks of one common local net), orthogonal (same round-two word, or sinks of one common broadcast net),
filler. Fifty null packings (same CLB sizes, random assignment) give the chance level. Post-route criticality comes from the Odin~III
critical-path attribution (V1.1.1) of the routed runs; because the Norns BLIFs already carry provenance names the tool's
two-BLIF input does not exist for them, so \code{{scripts/timing4.py}} builds the name map from the Norns BLIF and calls the tool's own functions
(a labelled workaround; the odin3 checkout is not edited). Coverage: the share of critical-path nodes the attribution matches to a provenance name is at least {chk['coverage_min']:.2f} in every one of the {chk['coverage_runs']} routed runs, and {chk['coverage_excl_port_min']:.2f} in every run when port nodes (which have no HDL line) are excluded. The routed report holds one path per endpoint (at most 1000), so near-critical counts are per reported path, not per start and end pair.

\paragraph{{Depth estimate (H15).}} The HDL statement of a span is the statement that starts on the span's source line or, if none does, the nearest statement start within 12 lines above (a rule written in \code{{scripts/r4depth.py}} before any data, not stated in the protocol text).

\paragraph{{Stage-by-bit seed.}} Stage = register-to-register level of the atom graph (back edges removed by a DFS), bit = round-two word bit,
control = CLBs holding the driver of a net of fanout $>32$. Moved CLBs (no carry-chain CLBs) permute among their own analytic slots, each taking the nearest free slot to
(stage, bit), control in the centre; all other CLBs keep their position.

\begin{{table*}}[t]
\caption{{Affinity join. Forward: affinity-file entries that match a VPR atom, round three (r3) and round four (r4), per source. Reverse (r4 files): VPR LUT, FF and adder atoms in logic CLBs that carry a label (by their own name) and have an entry in the file; the last column is the same for the round-three module file's adder atoms (it had none).}}
\label{{tab:r4join}}
\centering\scriptsize\setlength{{\tabcolsep}}{{3pt}}
\begin{{tabular}}{{@{{}}lrrrrrrrrrr@{{}}}}
\toprule
 & \multicolumn{{2}}{{c}}{{module}} & \multicolumn{{2}}{{c}}{{word}} & \multicolumn{{2}}{{c}}{{word+io}} & \multicolumn{{3}}{{c}}{{reverse, r4 file}} & r3 \\
design & r3 & r4 & r3 & r4 & r3 & r4 & module & word & word+io & adders \\
\midrule
{join_table()}
\bottomrule
\end{{tabular}}
\end{{table*}}

\begin{{table}}[t]
\caption{{Proposal step, median over designs (census runs, seed 1): fraction of offered molecules that entered the queue and of proposal calls that queued nothing.}}
\label{{tab:r4proposals}}
\centering\small
\begin{{tabular}}{{@{{}}lrr@{{}}}}
\toprule
arm & queued / offered & calls with 0 queued \\
\midrule
round-three counting & {pct(summ['r3']['median_hit_rate'])} & {pct(summ['r3']['median_zero_share'])} \\
fixed counting & {pct(summ['r4']['median_hit_rate'])} & {pct(summ['r4']['median_zero_share'])} \\
\bottomrule
\end{{tabular}}
\end{{table}}
"""
    write("r4-method.tex", method)
    # ---- results
    rows_c = []
    sent = []
    near = n17["near"]
    for d in n17["designs"]:
        s = n17["arms"]["stock"][d]["share"]
        r = n17["arms"].get("r4", {}).get(d, {}).get("share")
        nm = n17["arms"]["stock"][d]["null"]
        stn = near[d].get("stock")
        k = stn["m10"]["k"] if stn else None
        m = stn["m10"]["split"] if stn else None
        rows_c.append(f"{tex(d)} & {n17['arms']['stock'][d]['logic_clbs']} & {s['SC']*100:.1f} & {s['SN']*100:.1f} & {s['SI']*100:.1f} & {s['OR']*100:.1f} & {s['FL']*100:.1f} & "
                      f"{(r['SC'] * 100 if r else float('nan')):.1f} & {(nm['SC'] + nm['SN']) * 100:.1f} & {k if k is not None else 'n/a'} & {m if m is not None else 'n/a'} \\\\")
        sent.append(f"\\item \\emph{{{tex(d)}}}: {pct(s['SI'])} shared-input, {pct(s['OR'])} orthogonal, {pct(s['SC'])} series-critical, "
                    f"{pct(s['SN'] + s['FL'])} SN+FL (non-critical remainder: SN {pct(s['SN'])}, FL {pct(s['FL'])}); "
                    + (f"{k} near-critical reported path{'' if k == 1 else 's'} (within 10\\%), {m} of them split across CLBs." if stn else "no routed run."))
    h17b, h17c, h17d = n17["H17b"], n17["H17c"], n17["H17d"]
    eu = h17d["exploratory_units"]
    status_rows = [
        ("N17", "H17a shape (10/75/15)", a["shape"], f"medians SC {pct(a['median_SC'])}, SI+OR {pct(a['median_SI_OR'])}, SN+FL {pct(a['median_SN_FL'])}, n={a['n']}"),
        ("N17", "H17a literal numbers", a["numbers"], "same medians against 10/75/15 $\\pm0.10$"),
        ("N17", "H17b packer changes SC share", h17b["status"], f"median $\\Delta$SC {f3(h17b.get('median_dSC'))}, Holm ${peq(h17b.get('p_holm_SC'))}$, n={h17b['n']}"),
        ("N17", "H17c critical edges kept together", h17c["status"], f"median ratio {f3(h17c.get('median_ratio'))}, Wilcoxon ${peq(h17c.get('p'))}$, n={h17c['n']} (literal rule; reading with an n$<$12 clause: {h17c['status_n12_variant']})"),
        ("N17", "H17d series share above the atom-shuffle null (not a clustering-quality result)", h17d["status"],
         f"median excess {f3(h17d.get('median_excess'))}, {h17d.get('positive')}/{h17d['n']} positive; exploratory molecule-unit null: excess {f3(eu['median_excess'])}, {peq(eu['p'])}, {eu['status_same_rule']}"),
        ("N13", "H13a module count vs grid area", n13["status"]["H13a"], f"n={n13['n']} (M only: depth not measurable from provenance names)"),
        ("N13", "H13b beyond design size", n13["status"]["H13b"], f"n={n13['n']}"),
        ("N13", "H13c packer effect vs hierarchy", n13["status"]["H13c"], f"n={n13['n']}"),
        ("N15", "H15 depth estimate predicts critical statements", h15["status"], f"median $\\rho$ {f3(h15.get('median_rho'))}, n={h15['n']}"),
    ]
    for m in ("wirelength", "chan_width", "cpd_ns"):
        b = arms["all"]["H14"][m]
        status_rows.append(("N14", f"H14 norns vs stock: {m}", b["status"], f"geomean {f3(b.get('gm'))}, {b.get('better')}/{b['n']} better, Holm ${peq(b.get('p_holm'))}$"))
    for k, b in arms["all"]["H16"].items():
        status_rows.append(("N16", f"H16 stage$\\times$bit seed: {tex(k)}", b["status"], f"geomean {f3(b.get('gm'))}, {b.get('better')}/{b['n']} better, Holm ${peq(b.get('p_holm'))}$"))
    srows = "\n".join(f"{r} & {tex(h) if '$' not in h else h} & {s} & {d} \\\\" for r, h, s, d in status_rows)
    krows = "\n".join(f"{r['id']} & {trel(r['relation'])} & {r['holds']}/{r['n']} & {pf(r['p'])} & {'yes' if r['known'] else ('no' if r['known'] is not None else 'n/a')} & {'yes' if r.get('known_scaled') else ('no' if r.get('known_scaled') is not None else 'n/a')} \\\\" for r in n12["rows"])
    k_by = {r["id"]: r for r in n12["rows"]}
    k_note = (f"K1 is defined on {k_by['K1']['n']} designs, so the literal count of 12 is unreachable by construction and its ``no'' is guaranteed whatever the data; the scaled column is a labelled variant. "
              f"K3 is two registered conditions: A (share $\\le0.80$) holds in {k_by['K3']['holds']}/{k_by['K3']['n']} designs (needs 12) and B (above the null) in {k_by['K3']['cond_b']}/{k_by['K3']['n']} (needs all 15); it is known iff both hold. "
              f"K8 is registered across the seeds within a design: per packing it holds for {k_by['K8 stock']['holds']}/{k_by['K8 stock']['n']} designs (stock) and {k_by['K8 norns']['holds']}/{k_by['K8 norns']['n']} (norns), known iff both reach 12; "
              f"the pooled row (6 points per design, both packings) is a labelled variant and is not counted.")
    hrows = "\n".join(f"{tex(r['design'])} & {r['S']} & {r['M']} & {r['D']} & {r['elab']['instances'] if r.get('elab') else 'n/a'} & {r['elab']['depth'] if r.get('elab') else 'n/a'} & {f2(r['stock']['area']) if 'stock' in r else 'n/a'} & {f2(r['norns']['area']) if 'norns' in r else 'n/a'} \\\\" for r in n13["rows"])
    ex = n13["exploratory_elab"]
    n_rent = sum(1 for r in n13["rows"] if r["rent"])
    ex_txt = ""
    if "tests" in ex:
        t = ex["tests"]
        lab = {"logE": "instances", "De": "depth", "logE|S": "instances given design size"}
        ex_txt = (" Exploratory (not registered; instances and depth of Odin~III's elaborated design before flattening against log grid area): "
                  + "; ".join(f"{k.split('.')[0]} packing, {lab[k.split('.')[1]]}: $\\rho={v['rho']:.2f}$, Holm ${peq(v['p_holm'])}$" for k, v in t.items())
                  + f" (Holm over {len(t)} tests; depth runs from {min(ex['depth_values'].values())} to {max(ex['depth_values'].values())} modules).")
    wrows, rrows = [], []
    for pack in ("stock", "norns"):
        for wk, wl in (("unweighted", "unweighted"), ("w1", "pack-time $w_1$"), ("w2", "post-route $w_2$")):
            w = n17["weighted"][pack][wk]
            wrows.append(f"{pack} & {wl} & " + " & ".join(f"{100 * w[c]:.1f}" for c in ("SC", "SN", "SI", "OR", "FL")) + f" & {w['n']} \\\\")
        for mk, ml in (("0.05", "5"), ("0.1", "10")):
            q = n17["split_reasons"][pack][mk]
            rr = q["reasons"]
            rrows.append(f"{pack} & {ml}\\% & {q['designs']} & {q['median_k']:g} & {q['designs_with_split']} & {q['crossings']}/{q['hops']} & {rr['R1']} & {rr['R2']} & {rr['R3']} & {rr['R0']} \\\\")
    arow = []
    for m in ("wirelength", "chan_width", "cpd_ns"):
        b = arms["all"]["H14"][m]
        arow.append(f"{tex(m)} & norns/stock, analytic & {f3(b.get('gm'))} & {b.get('better')}/{b['n']} \\\\")
        for k, v in arms["all"]["H16"].items():
            if k.endswith(m):
                arow.append(f"{tex(m)} & {tex(k.split('.')[0])}: stagebit/analytic & {f3(v.get('gm'))} & {v.get('better')}/{v['n']} \\\\")
        for k, v in arms["all"]["ref"].items():
            if k.endswith(m):
                arow.append(f"{tex(m)} & {tex(k.rsplit('.', 1)[0])} & {f3(v.get('gm'))} & {v.get('better')}/{v['n']} \\\\")
    results = rf"""
\subsection{{Round four: results}}
\label{{sec:r4-results}}
\paragraph{{What gets clustered (N17).}} Table~\ref{{tab:r4census}} gives, per benchmark, the share of CLB member pairs in each class for the stock packing
(seed 1; SC series-critical, SN series-noncritical, SI shared-input, OR orthogonal, FL filler), the SC share of the headline Norns packing, the chance level of
SC+SN under 50 null packings, and the near-critical paths within 10\% of the critical path (k) and how many of them are split across CLBs (m). Per benchmark:
\begin{{itemize}}\small
{chr(10).join(sent)}
\end{{itemize}}
Table~\ref{{tab:r4weighted}} weights the pairs by criticality (median over designs) and Table~\ref{{tab:r4reasons}} gives the near-critical counts at both margins and the reasons for the crossings; per-design values are in
\code{{data/analysis/r4-results.json}} and \code{{data/<design>/r4near.json}}. Source shares of the molecules added: stock {', '.join(f"{tex(k)} {pct(v)}" for k, v in summ['stock']['source_share'].items())}.

\begin{{table}}[t]
\caption{{Median class shares (percent) over designs, unweighted and weighted by pack-time ($w_1$, minimum atom criticality) and post-route ($w_2$, minimum path-criticality ratio) criticality; $n$ = designs (w2 needs a routed run whose packing equals the census packing).}}
\label{{tab:r4weighted}}
\centering\scriptsize\setlength{{\tabcolsep}}{{3pt}}
\begin{{tabular}}{{@{{}}llrrrrrr@{{}}}}
\toprule
packing & weight & SC & SN & SI & OR & FL & $n$ \\
\midrule
{chr(10).join(wrows)}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{table}}[t]
\caption{{Near-critical reported paths at the 5\% and 10\% margins (seed 1, routed run): designs, median count $k$, designs with at least one path split across CLBs, member-member hop crossings and hops (pooled), and the reason of each crossing (R1 refused by the legalizer, R2 queued and not taken, R3 never proposed, R0 no census record).}}
\label{{tab:r4reasons}}
\centering\scriptsize\setlength{{\tabcolsep}}{{2pt}}
\begin{{tabular}}{{@{{}}llrrrrrrrr@{{}}}}
\toprule
packing & margin & designs & median $k$ & with split & crossings/hops & R1 & R2 & R3 & R0 \\
\midrule
{chr(10).join(rrows)}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{table}}[t]
\caption{{Pair classes in the stock packing (percent of pairs), headline-packer SC share, chance SC+SN, near-critical paths (k) and split ones (m).}}
\label{{tab:r4census}}
\centering\scriptsize\setlength{{\tabcolsep}}{{2pt}}
\begin{{tabular}}{{@{{}}lrrrrrrrrrr@{{}}}}
\toprule
design & CLBs & SC & SN & SI & OR & FL & SC(r4) & null SC+SN & k & m \\
\midrule
{chr(10).join(rows_c)}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{table*}}[t]
\caption{{Round-four hypotheses (n=15 unless stated; literal rules of \code{{docs/plan/round4.md}}).}}
\label{{tab:r4status}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}lp{{4.6cm}}p{{3.4cm}}p{{8.4cm}}@{{}}}}
\toprule
RQ & hypothesis & status & deciding number \\
\midrule
{srows}
\bottomrule
\end{{tabular}}
\end{{table*}}

\paragraph{{Knowns (N12).}} Table~\ref{{tab:r4knowns}}: {n12['n_known']} relations meet the literal rule (at least 12 of 15 designs, and the stated test);
{n12['n_known_scaled']} with the count scaled to the designs defined (labelled, not registered). {k_note}
\begin{{table*}}[t]
\caption{{Knowns from the dataset: holds in $k$ of $n$ designs, test $p$, known under the literal rule and under the scaled count.}}
\label{{tab:r4knowns}}
\centering\scriptsize\setlength{{\tabcolsep}}{{3pt}}
\begin{{tabular}}{{@{{}}lp{{10.5cm}}rrcc@{{}}}}
\toprule
 & relation & holds & $p$ & known & scaled \\
\midrule
{krows}
\bottomrule
\end{{tabular}}
\end{{table*}}

\paragraph{{Hierarchy and chip size (N13).}} The designs are small (n=15). Provenance names carry one \code{{module/leaf@file:line}} level, so the depth $D$ read from them is 1 in every design by construction: depth is not measurable from the provenance names, and H13 as registered tests the module count $M$ only. The per-level Rent exponent is therefore a single-level fit, defined for {n_rent} designs and empty for {len(n13['rows']) - n_rent}; it is not reported further.{ex_txt}
Table~\ref{{tab:r4hier}} lists atoms $S$, modules $M$, depth $D$ from the names, the instance count and depth of the elaborated design (exploratory), and the mean grid area under stock and norns packing.
\begin{{table}}[t]
\caption{{Hierarchy and grid area (mean of 3 seeds, analytic start). $M$, $D$: from provenance names; instances, depth: elaborated design before flattening (exploratory).}}
\label{{tab:r4hier}}
\centering\scriptsize\setlength{{\tabcolsep}}{{3pt}}
\begin{{tabular}}{{@{{}}lrrrrrrr@{{}}}}
\toprule
design & $S$ & $M$ & $D$ & instances & depth & area stock & area norns \\
\midrule
{hrows}
\bottomrule
\end{{tabular}}
\end{{table}}

\paragraph{{Packing and placement start with critical-path delay (N14, N16).}} Table~\ref{{tab:r4arms}} gives the geometric mean of per-design ratios (3 seeds); below 1 is better.
Checks: VPR's log CPD equals path~1 of the timing report (arrival minus required time, i.e.\ minus its slack) within {chk['cpd_max_diff']:.4f}~ns (report precision) in {chk['cpd_agree']} of {chk['cpd_total']} runs (the data arrival time alone is {chk['cpd_minus_arrival_median']:.3f}~ns below the CPD by median, at most {chk['cpd_minus_arrival_max']:.3f}~ns: the setup time); the attribution's own CPD is read from the same log line and is not an independent check; the stock arm reproduces round three's WL, W and CPD in {chk['stock_repro']} of {chk['stock_repro_n']} runs.
\begin{{table}}[t]
\caption{{Arm ratios (geomean over designs).}}
\label{{tab:r4arms}}
\centering\scriptsize\setlength{{\tabcolsep}}{{2pt}}
\begin{{tabular}}{{@{{}}llrr@{{}}}}
\toprule
metric & comparison & geomean & better \\
\midrule
{chr(10).join(arow)}
\bottomrule
\end{{tabular}}
\end{{table}}
"""
    write("r4-results.tex", results)
    # ---- discussion
    disc = rf"""
\subsection{{Round four: discussion}}
\label{{sec:r4-discussion}}
The census answers Peter's question with data. In the stock packing the pairs that are neither series-critical nor shared-input nor orthogonal are {pct(a['median_SN_FL'])} by median (SN+FL, the non-critical remainder: series-noncritical {pct(a['median_SN'])}, filler {pct(a['median_FL'])}; a series-noncritical pair does share a direct net, so this is not a share of pairs without a net). Series-critical pairs are
{pct(a['median_SC'])} and shared-input plus orthogonal pairs {pct(a['median_SI_OR'])}; the illustration of 10/75/15 is {a['shape']} in shape and {a['numbers']} in numbers.
The orthogonal class counts same-word pairs, and words cover about half the LUTs, so it is a lower bound; ``not supported'' for the shape rests partly on that bound (the rule's $t<0.40$ arm). The headline packer changes the series-critical share by {f3(h17b.get('median_dSC'))} (median).
Near-critical paths are counted per benchmark (reported paths) in Table~\ref{{tab:r4census}}; most designs have few reported paths within 10\%, so H17c rests on {h17c['n']} designs that pass the registered 20-hop filter: by the literal rule it is {h17c['status']} (median ratio {f3(h17c['median_ratio'])}, one-sided Wilcoxon ${peq(h17c.get('p'))}$); under the labelled reading with an n$<$12 clause (not in the registered rule) it is {h17c['status_n12_variant']}.
H17d is {h17d['status']} against the registered null, which shuffles atoms (excess {f3(h17d['median_excess'])} of series pairs over the null's {pct(eu['median_null_atoms'])}, observed {pct(eu['median_observed'])}). That null ignores that the prepacker forces a LUT and its FF into one CLB and that carry chains fill CLBs in sequence. An exploratory null that keeps those molecules as units and leaves the {pct(eu['median_fixed_clb_share'])} (median) of CLBs that hold an adder as they are gives a null of {pct(eu['median_null_units'])} and an excess of {f3(eu['median_excess'])} ({eu['status_same_rule']} by the same rule, {peq(eu['p'])}). H17d therefore says that the packed pairs include forced ones; it is not a measure of clustering quality.
The hierarchy test (N13) is on {n13['n']} small designs, and the provenance names expose one level, so it tests the module count, not depth. The round-three affinity files lacked every adder atom; the round-four headline
packing is therefore not the round-three packing, and round three's purity and wirelength results describe a packer that did not see carry chains.
Limits: the depth estimate is a text heuristic; the attribution workaround uses the tool's functions on BLIFs that carry provenance names; the packing is APPack inside the analytical flow.
"""
    write("r4-discussion.tex", disc)
    # ---- appendix
    appendix = rf"""
\paragraph{{2026-10-25, round four.}} Peter (2026-10-24): ``{tex(q1)}'' Peter (2026-10-25): ``{tex(q2)}''
What round three suggested: the Norns packer raised purity but not wirelength, and the proposal counter and the affinity join were suspect.
Questions: N17 what gets clustered and why; N12 knowns; N13 hierarchy against chip size; N14 to N16 the packer, a timing-from-provenance estimate and a stage-by-bit seed with critical-path delay everywhere.
Disclosures (entry of the fix round in the protocol): small test runs on \code{{ch\_intrinsics}} preceded the gates and were deleted (no result uses them: every census and arm record is dated after the gates passed, and the rule scripts were last edited before); four affinity-join passes and one restarted gate ran for builder and compare bugs; the first dated entry amended N16 items 5 and 6 before any N16 data and the final round-four affinity files (adders added) postdate it.
Outcomes: Table~\ref{{tab:r4status}}. Protocol \code{{{PROTOCOL_SHA}}}. Next: fix the seed selector and scan order, rerun round three's purity claims with the adder-complete files, and larger designs.

\begin{{table*}}[t]
\caption{{Round-four research questions with status and deciding number (extends Table~\ref{{tab:r3log}}).}}
\label{{tab:r4log}}
\centering\scriptsize
\begin{{tabular}}{{@{{}}lp{{4.6cm}}p{{3.4cm}}p{{8.4cm}}@{{}}}}
\toprule
RQ & hypothesis & status & deciding number \\
\midrule
{srows}
\bottomrule
\end{{tabular}}
\end{{table*}}
"""
    write("r4-appendix.tex", appendix)
    return 0


if __name__ == "__main__":
    sys.exit(main())
