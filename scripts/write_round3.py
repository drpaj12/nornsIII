"""Write the round-3 paper text: docs/paper/r3-*.tex, included by norns.tex.

Every number comes from data/analysis/r3-results.json (scripts/r3stats.py) and the data/ records, so
the text regenerates byte-identically. Text uses @@key@@ tokens in raw strings (LaTeX braces).
Usage: python scripts/write_round3.py
"""

from __future__ import annotations

import math
import sys

import affinity as af
import nornlib as nl
import r3stats

PAPER = nl.WS / "docs" / "paper"
PROTOCOL_SHA = "4fb8b60"
PROTOCOL_TIME = "2026-10-24 21:26 (UTC-4)"
QUOTE1 = ("For Norns, one question is does the clustering step of FPGA mapping become the problem - how is "
          "the initial seeding for an hdl construct get clustered? We might have to make our version of "
          "clustering for this information (how is it done - just with TVpack?). Second, if we map designs "
          "and have provenance (including the clustering) what do we learn from the placed (just by "
          "aneealing results) can we make some questions like (what is close to one another and using the "
          "provenance info (why are things close to one another?)")
QUOTE2 = ("Also, the outputs (words) and the inputs as words also provide hints of where the words are in "
          "norns. Let's build our own Norns based packer from scratch (include it in Norns as a "
          "copy/modification to Apack to allow us to our controlled experiements).")
SRC = {"module": "module", "word": "word", "wordio": "word+io"}


def fill(text: str, **kw: object) -> str:
    for k, v in kw.items():
        text = text.replace(f"@@{k}@@", str(v))
    assert "@@" not in text, text[text.index("@@"):][:80]
    return text


def f3(x) -> str:
    return r3stats.f3(x)


def f2(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}\\%"


def pf(p) -> str:
    return r3stats.pfmt(p)


def peq(p) -> str:
    """'p<0.001' or 'p=0.090'."""
    t = r3stats.pfmt(p)
    return f"$p{t}$" if t.startswith("<") else f"$p={t}$"


def esc(s: str) -> str:
    return s.replace("_", "\\_")


def code(s: str) -> str:
    return "\\code{" + esc(s) + "}"


def load() -> dict:
    r3stats.RESULT.parent.mkdir(parents=True, exist_ok=True)
    return nl.read_json(r3stats.RESULT)


def stat(s: str) -> str:
    return s.replace("_", "\\_")


def n8_table() -> str:
    rows = []
    for d in nl.DESIGN_ORDER:
        r = nl.read_json(nl.DATA / d / "n8.json")
        s, n = r["stock"], r["null"]
        rows.append(f"{esc(d)} & {s['logic_clbs']} & {f2(s['word']['share'])} & {f2(n['word']['share'])} & "
                    f"{f2(s['word']['split'])} & {f2(s['module']['share'])} & {pct(r['decompose']['loss_abc'])} & "
                    f"{pct(r['decompose']['loss_pack'])} \\\\")
    return "\n".join(rows)


def n10_table() -> str:
    rows = []
    for d in nl.DESIGN_ORDER:
        r = nl.read_json(nl.DATA / d / "iowords.json")
        rows.append(f"{esc(d)} & {r['io_words']} & {pct(r['lut_cov_word'])} & {pct(r['lut_cov_union'])} \\\\")
    return "\n".join(rows)


def diffstat() -> tuple[int, int, int]:
    """(files, added lines, removed lines) of packer/ against the pinned VTR commit (packer/DIFFSTAT.txt)."""
    files = add = dele = 0
    for line in (nl.WS / "packer" / "DIFFSTAT.txt").read_text().splitlines():
        tok = line.split()
        files += 1
        add += int(tok[2][1:])
        dele += int(tok[3][1:])
    return files, add, dele


def method(R: dict) -> str:
    g = R.get("gate", {})
    nfiles, nadd, ndel = diffstat()
    grid = R.get("grid", {})
    gridtxt = "; ".join(
        f"{SRC[s]}: $\\beta_m={grid['sources'][s]['beta_m']:g}$, grid {{{', '.join(f'{b:g}' for b in grid['sources'][s]['grid'])}}}"
        for s in af.SOURCES) if grid else "not yet frozen"
    gate_txt = (f"{g['n_checks']} comparisons over {g['designs']} designs, "
                f"{'all byte-identical' if g['all_identical'] else 'NOT all identical'}") if g else "not yet run"
    fx = R.get("fix", {})
    if fx.get("gate2"):
        gate_txt += (f"; the same $\\beta=0$ check for the module and word+io affinity files (\\code{{--pack}}, seed 1): "
                     f"{fx['gate2']['identical']} of {fx['gate2']['n_checks']} byte-identical")
    growth = max(max(grid["sources"][x]["median_clb_growth"].values()) for x in af.SOURCES) if grid else 0.0
    limits = proposal_limits(R)
    return fill(r"""\subsection{Round three: packing, I/O words and placement proximity}
\label{sec:r3-method}

Round two found every soft seed within a few percent of the baseline. Round three asks whether the
packing step, which runs before placement and decides which atoms share a CLB, is where the HDL
structure is lost, builds a packer that keeps it, and then asks what the annealed placement itself
says about provenance. The two questions that started it are quoted in the research log
(Section~\ref{sec:r3-appendix}).

\paragraph{The Norns packer.} VPR's packer is AAPack, the greedy clusterer in \code{vpr/src/pack} (not
T-VPack); in VTR's default analytical flow the same clusterer runs as APPack, with candidate gains
attenuated by distance in the global placement. The Norns packer is a copy of the changed files of that
clusterer (VTR commit \code{3c9a4d23b2}, MIT licence kept) with one added term: an atom carries a group id
read from a file (\code{--norns\_affinity}); a cluster's dominant group is the plurality group of its atoms so
far; a candidate molecule gets $+\beta$ (\code{--norns\_affinity\_weight}) for every atom in that group, and up
to 30 unclustered members of the group are proposed as candidates, because the bits of a word are parallel and
no net links them. The stock per-atom gain lies in $[0,1]$, so $\beta$ is in the units of one connected atom's
gain. Legality stays with AAPack's legalizer. The change is @@files@@ files, @@lines@@ added lines and @@dele@@ removed.
\emph{Control gate:} with the option absent and with $\beta=0$, the packer must write a \code{.net}
byte-identical to the stock \code{vpr}'s in \code{--pack} and in the analytical flow on all 15 designs, before
any experiment run: @@gate@@.

@@limits@@

\paragraph{RQ-N8, dilution (no VPR).} On the stock packings of round one, per design: purity (plurality share of the
labelled atoms of a logic CLB, atom-weighted), and the split factor (CLBs a word spans over the fewest CLBs that
could hold it, 1.0 being best), at word and module level, against a null that assigns the same atoms at random to
CLBs of the same sizes (50 samples). Round two's word coverage loss is split into the front end (atoms with no
word) and packing (word atoms not in a CLB where their word is the plurality word under the 1/3 rule).

\paragraph{RQ-N10, I/O words.} A top-level bus \code{name[i]} is an io-word; its identity is propagated inward
over LUT and flip-flop atoms, two hops past the atom next to the pad, through nets of fanout at most 16, giving
an atom that has no round-two word the io-word it reaches from exactly one bit of exactly one io-word.

\paragraph{RQ-N9, packing experiments.} Arms: the stock packer, and the Norns packer with affinity source module,
word or word+io (word, else io-word) at three values of $\beta$ each, with the analytic start or with the round-two
\code{words\_partial} seed rebuilt on that run's own packing, three VPR seeds (1 to 3) per configuration. The grid was
chosen on a pilot of the four smallest designs that reads only purity and CLB count (never wirelength): $\beta_m$ is
the largest value in $\{0.05,0.1,0.2,0.5,1,2,4\}$ whose median CLB-count growth is at most 5\%, and the grid is its
neighbours (@@grid@@). \emph{The pilot did not discriminate between the betas.} The median logic-CLB growth over the
four pilot designs was negative at every $\beta$ of the list (largest value @@growth@@), so the 5\% growth rule passed
all of them and took the end of the list, and the purity gain of the word sources was the same at $\beta=2$ and $\beta=4$
(module: zero throughout). The grid $\{1,2,4\}$ is therefore not informed by the pilot, and a larger gain scale is untested. Each claim is reported on all 15 designs and without the four pilot designs; a status
that differs between the two is called inconclusive (pilot-sensitive).

\paragraph{RQ-N11, proximity.} On the stock-packing, analytic-start runs, logic CLB pairs by relation (same word,
same module, same statement, net-connected, same io-word) against the direct net count, which is stratified
out: the stratified mean distance difference of related over unrelated pairs, as a fraction of the unrelated
distance (negative is closer). A stratum counts only with at least 5 related and 30 unrelated pairs. The status
is computed under the protocol text (\code{@@sha@@}: no design excluded, the sign rule needs at least 12 of the 15
designs, so a relation defined for fewer designs cannot be supported), which is the primary status, and the
following variants are reported beside it, labelled. (i) The sign rule scaled to $\lceil 12n/15\rceil$ designs, which the
first analysis code used; the protocol does not register it. (ii) The amendment \code{d805789}: a design is
left out of a relation when 95\% or more of the sampled pairs are related (applied to the module relation and to
the word relation, per design on the mean over the three seeds, with the scaled and the literal count), and the
label permutations are 200 per design and seed. The primary permutation test is the protocol's 1000 label permutations pooled
over designs; it is reported, not used in a status. The entry of 2026-10-25 in \code{docs/plan/round3.md} records these deviations.

\paragraph{Decision rules and their provenance.} Every hypothesis, metric, arm and numeric rule (including the margins
$\pm$2\% and 1\% for wirelength, 5 percentage points of purity, 5\% CLB growth) is in \code{docs/plan/round3.md},
committed as \code{@@sha@@} on @@ptime@@, before any round-three measurement or VPR run. Two later dated entries
exist and the earlier entries are not edited. The entry \code{d805789} (2026-10-24) is titled a clarification, but it is an
amendment: besides definitions it changed two H11 rules (the label permutations, 1000 pooled over designs, became 200 per
design and seed; a new exclusion of designs with 95\% or more related pairs). It was committed at 22:27:05, before any
Stage-4 result was analysed, but the Stage-4 runs of \code{ch\_intrinsics} (60 runs, finished 22:26:38) and 40 of the 60 of \code{stereovision3} had
already finished. The entry of 2026-10-25 (the fix round after review) records what the analysis code did beyond the
protocol text. Where the code deviated, the primary status in this paper is the one under the text of \code{@@sha@@} and
the deviating variant is reported alongside, labelled.
""", files=nfiles, lines=nadd, dele=ndel, gate=gate_txt, grid=gridtxt, sha=PROTOCOL_SHA, ptime=PROTOCOL_TIME,
                growth=pct(growth), limits=limits)


def h_rows(R: dict) -> list[tuple[str, str, str, str]]:
    h8, h10a, h11 = R["H8"], R["H10a"], R["H11"]
    rows = [("N8", "H8 packing dilutes structure", h8["status"],
             f"median word purity {f2(h8['median_share'])}, split {f2(h8['median_split'])} (n={h8['n']})"),
            ("N10", "H10a io-words add coverage", h10a["status"],
             f"median gain {pct(h10a['median_gain'])}, {h10a['positive']}/{h10a['n']} designs")]
    if "H9a" in R and not R.get("checkpoint_only"):
        for s in af.SOURCES:
            a = R["H9a"][s]["all"]
            rows.append(("N9", f"H9a {SRC[s]} purity up, CLBs within +5\\%", R["H9a"][s]["status"],
                         f"purity +{f3(a.get('median_gain'))} (without pilot +{f3(R['H9a'][s]['no_pilot'].get('median_gain'))}), "
                         f"CLB {pct(a.get('median_growth'))}, {peq(a.get('p_holm'))}"))
        for s in af.SOURCES:
            b = R["H9b"][s]["all"]
            rows.append(("N9", f"H9b {SRC[s]} changes WL (analytic)", R["H9b"][s]["status"],
                         f"geomean {f3(b.get('gm'))}, {b.get('better')}/{b.get('n')} better, {peq(b.get('p_holm'))}; "
                         f"without pilot {f3(R['H9b'][s]['no_pilot'].get('gm'))}, {peq(R['H9b'][s]['no_pilot'].get('p_holm'))}"))
        for s in af.SOURCES:
            c = R["H9c"][s]["all"]
            rows.append(("N9", f"H9c {SRC[s]}+seed beats stock+seed", R["H9c"][s]["status"],
                         f"geomean {f3(c.get('gm'))}, {c.get('better')}/{c.get('n')} better, {peq(c.get('p_holm'))}"))
        b = R["H10b"]["all"]
        rows.append(("N10", "H10b word+io beats word", R["H10b"]["status"],
                     f"geomean {f3(b.get('gm'))}, {b.get('better')}/{b.get('n')} better, {peq(b.get('p'))}"))
    for rel in ("word", "module"):
        x = h11[rel]
        sc = h11["variants"]["registered_scaled"][rel]
        rows.append(("N11", f"H11 same-{rel} pairs closer than nets predict", x["status"],
                     f"median {f3(x.get('median_d'))}, {peq(x.get('p'))}, n={x['n']}; {x['consistent']} of {x['n']} "
                     f"designs sign-consistent, {x['need']} needed; with the unregistered scaling ({sc['need']} needed): "
                     f"{stat(sc['status'])}"
                     if x["n"] else "no data"))
    rows.append(("N11", "H11 overall (both relations)", h11["status"],
                 f"supported only if both are; unregistered scaling: {stat(h11['variants']['registered_scaled']['status'])}"))
    return rows


def status_table(R: dict) -> str:
    out = []
    for rq, hyp, status, num in h_rows(R):
        out.append(f"{rq} & {hyp} & {stat(status)} & {num} \\\\")
    return "\n".join(out)


def proposal_limits(R: dict) -> str:
    fx = R.get("fix", {})
    idn = fx.get("ident")
    if not idn:
        return ""
    hq, zq = idn["hit_rate_median"], idn["zero_share_median"]
    tot = idn["totals"]
    same = (f"{idn['net_identical']} of {idn['n']} \\code{{.net}} files byte-identical to the previous binary's, "
            f"{idn['flat_identical']} of {idn['n']} flat placements identical to the Stage-4 run")
    qs = " / ".join(pct(hq[x]) for x in af.SOURCES)
    zs = " / ".join(pct(zq[x]) for x in af.SOURCES)
    ts = " / ".join(pct(tot[x]["queued"] / tot[x]["attempted"]) for x in af.SOURCES)
    return fill(r"""\paragraph{Limits of the proposal step.} The step hands up to 30 unclustered members of a cluster's dominant
group to the candidate queue, scanning the group in netlist (atom id) order. Its counter counts the molecules handed over, not
the molecules the queue accepted, so the cap of 30 can be spent on molecules the queue ignores (already queued, or beyond
APPack's distance threshold), and the scan always starts at the lowest atom ids of the group: which members are tried first is
biased by netlist order. The behaviour is unchanged in this paper (Stage-4 results stand); it was measured with a log-only counter
added to the packer, which leaves the packing unchanged (@@same@@; pack-only style runs of the headline configurations, seed 1,
no routing). Share of handed-over molecules that entered the queue, median over designs (module / word / word+io): @@qs@@
(pooled over all calls: @@ts@@); proposal calls (one per cluster) that queued nothing: @@zs@@ (Table~\ref{tab:r3diag}).
The fix (count only queued molecules, return a bool from the queue step, a scan order not tied to atom ids) is queued for round 4.
""", same=same, qs=qs, zs=zs, ts=ts)


def diag_table(R: dict) -> str:
    fx = R.get("fix", {})
    if not fx.get("ident") or not fx.get("match"):
        return ""
    rows = []
    for d in nl.DESIGN_ORDER:
        m = fx["match"]["rows"][d]
        pr = fx["ident"]["proposals"][d]
        cells = [esc(d)]
        cells += [pct(m[x]["matched"] / m[x]["entries"]) for x in af.SOURCES]
        cells += [pct(pr[x]["hit_rate"]) if x in pr else "n/a" for x in af.SOURCES]
        cells += [pct(pr[x]["zero_share"]) if x in pr else "n/a" for x in af.SOURCES]
        rows.append(" & ".join(cells) + " \\\\")
    worst = fx["match"]["worst"]
    wtxt = "; ".join(f"{SRC[x]} {pct(worst[x]['fraction'])} on {esc(worst[x]['design'])}" for x in af.SOURCES)
    return fill(r"""\begin{table*}[t]
\caption{Packer diagnostics per design at the headline $\beta$ (seed 1). Matched: share of affinity-file entries that
named an atom of the netlist (from the VPR log; the lowest per source: @@wtxt@@). Queued: share of molecules handed to the
candidate queue by the proposal step that entered it. 0-queued: share of proposal calls (one per cluster) that queued
nothing. Columns in each group: module, word, word+io.}
\label{tab:r3diag}
\centering
\footnotesize\setlength{\tabcolsep}{3pt}
\begin{tabular}{lrrrrrrrrr}
\toprule
 & \multicolumn{3}{c}{Matched} & \multicolumn{3}{c}{Queued} & \multicolumn{3}{c}{0-queued} \\
\cmidrule(lr){2-4}\cmidrule(lr){5-7}\cmidrule(lr){8-10}
Design & Mod. & Word & W+io & Mod. & Word & W+io & Mod. & Word & W+io \\
\midrule
@@rows@@
\bottomrule
\end{tabular}
\end{table*}
""", wtxt=wtxt, rows="\n".join(rows))


H11_LABEL = {"registered": "Protocol text, 12 of 15 designs (primary)",
             "registered_scaled": "Scaled count (not registered)",
             "amended": "Amendment d805789, 12 of 15",
             "amended_scaled": "Amendment d805789, scaled count"}


def h11_table(R: dict) -> str:
    h = R["H11"]
    if not h.get("variants"):
        return ""
    rows = []
    for title, src in (("All 15 designs", h["variants"]), ("Without the four pilot designs", h["no_pilot"])):
        rows.append(f"\\multicolumn{{11}}{{l}}{{\\emph{{{title}}}}} \\\\")
        for key, label in H11_LABEL.items():
            v = src[key]
            cells = [label]
            for rel in ("word", "module"):
                x = v[rel]
                cells += [str(x["n"]), f3(x.get("median_d")), f"{x.get('consistent', 'n/a')}/{x.get('need', 'n/a')}",
                          pf(x.get("p_perm")), stat(x["status"])]
            rows.append(" & ".join(cells) + " \\\\")
    return fill(r"""\begin{table*}[t]
\caption{RQ-N11, H11 under the protocol text and the labelled variants. n is the number of designs in which the relation is
defined (and not excluded); median is the median over those designs of the stratified distance difference; k/need is the
number of designs negative in two of three seeds over the number the rule needs; perm p is the permutation p of the median
over designs (1000 label permutations pooled over designs for the protocol text and the scaled count, 200 for the amendment),
reported and not used in the status. The status uses the median, the one-sided Wilcoxon test and k/need. The count of
the pilot-free rows is shown scaled in the scaled rows only; with 11 designs the literal 12 cannot be met.}
\label{tab:r3h11}
\centering
\footnotesize\setlength{\tabcolsep}{3pt}
\begin{tabular}{@{}lrrrrlrrrrl@{}}
\toprule
 & \multicolumn{5}{c}{Same word} & \multicolumn{5}{c}{Same module} \\
\cmidrule(lr){2-6}\cmidrule(lr){7-11}
Variant & n & median & k/need & perm p & status & n & median & k/need & perm p & status \\
\midrule
@@rows@@
\bottomrule
\end{tabular}
\end{table*}
""", rows="\n".join(rows))


def pack_ratio_text(R: dict) -> str:
    fx = R.get("fix", {})
    sn, tm = fx.get("stockn"), fx.get("timing")
    if not sn and not tm:
        return ""
    out = [r"""\textbf{Packing time on one binary.} The stock arm of Stage 4 ran on the stock \code{vpr} and the Norns arms on the
Norns \code{vpr}, two builds, so the ratios of Table~\ref{tab:r3qor} compare different binaries (and the Flow column includes
routing)."""]
    if tm:
        a = tm["ratio"]
        w = tm["window"]
        out.append(fill(r"""Primary same-binary measurement (pack-only style, no routing, seed 1 to 3, @@nr@@ runs): on the Norns
\code{vpr}, for each design and seed the stock arm (option absent) and the three Norns arms ran back to back, so any load affects the arms alike.
The geomean over designs of the Norns to stock packing time ratio is @@a@@ (module / word / word+io). These runs took place
@@w0@@ to @@w1@@ (UTC-4) \emph{with a concurrent load}: another lane ran CPU work outside the heavy lock (the one-minute load
average at the start of a run had median @@lm@@, maximum @@lx@@). Packing times of the small designs are a few tenths of a second,
so the ratio is coarse and approximate.""", nr=tm["n_runs"], a=" / ".join(f3(a[x]) for x in af.SOURCES),
                       w0=w[0].replace("T", " "), w1=w[1].replace("T", " "), lm=f"{tm['load1_median']:.1f}",
                       lx=f"{tm['load1_max']:.1f}"))
    if sn:
        a, b = sn["pack_ratio_same_binary"], sn["pack_ratio_other_build"]
        out.append(fill(r"""Not interleaved, hence approximate: the Stage-4 Norns packing times over a separate rerun of the stock arm
on the Norns \code{vpr} (@@nr@@ runs, @@fi@@ flat placements identical to the Stage-4 stock run, taken at another time and load) give @@same@@,
against @@other@@ with the stock arm on the other build, as first reported.""", nr=sn["n_runs"], fi=sn["flat_identical"],
                        same=" / ".join(f3(a[x]) for x in af.SOURCES), other=" / ".join(f3(b[x]) for x in af.SOURCES)))
    return "\n\n".join(out) + "\n"


def results(R: dict) -> str:
    h8, h10a = R["H8"], R["H10a"]
    dec = h8["decompose_median"]
    cp = R.get("checkpoint_only", True) and "H9a" not in R
    n9 = ""
    if "H9a" in R:
        sec = R["secondary"]
        noise = R["seed_noise"]
        lines = []
        for st in ("analytic", "seed"):
            for s in af.SOURCES:
                r = sec[f"{s}.{st}"]
                lines.append(f"{SRC[s]}, {'analytic' if st == 'analytic' else 'word seed'} & {f3(r['wirelength'])} & "
                             f"{f3(r['chan_width'])} & {f3(r['cpd_ns'])} & {f3(r['logic_clbs'])} & {f3(r['pack_s'])} & "
                             f"{f3(r['flow_s'])} \\\\")
        n9 = fill(r"""\begin{table}[t]
\caption{Round three, headline configurations (the $\beta_m$ of each source): geomean ratio over the
@@nd@@ completed designs against the stock packer with the same start, same VPR seeds. Below 1.0 is better;
CLBs is the number of logic CLBs; Pack and Flow are the packing and total VPR runtimes. The stock arm ran on the stock \code{vpr} and
the Norns arms on the Norns \code{vpr}, two builds, so Pack and Flow are not a same-binary comparison (the same-binary packing time
ratio is in the text). The seed arm's stock reference is the stock
packing with the same \code{words\_partial} seed rebuilt on it.}
\label{tab:r3qor}
\centering
\footnotesize\setlength{\tabcolsep}{3pt}
\begin{tabular}{lcccccc}
\toprule
Arm & WL & Chan.\ & Delay & CLBs & Pack & Flow \\
\midrule
@@rows@@
\bottomrule
\end{tabular}
\end{table}

\textbf{Seed noise.} The stock packer's routed wirelength varies across the three VPR seeds with a median coefficient of variation
@@cvm@@ (maximum @@cvx@@, n=@@cvn@@ designs), which is the floor under any wirelength difference below a few percent.
""", nd=len(R["designs_done"]), rows="\n".join(lines), cvm=pct(noise["cv_median"]), cvx=pct(noise["cv_max"]),
                  cvn=noise["n"])
    return fill(r"""\subsection{Round three results}
\label{sec:r3-results}

\textbf{RQ-N8, does packing dilute structure?} H8 is @@h8s@@: over the 15 stock packings the median word purity
(plurality share) is @@msh@@ against @@mnull@@ for a random grouping of the same atoms (higher on @@above@@ of 15), and the median
split factor is @@msp@@ (above 1 on @@gt1@@ of 15). The median module purity is @@mmod@@, so module affinity has little to gain on most designs. Of the logic atoms, @@dword@@ carry a word (median); @@dabc@@ lack one (front end: ABC's cone provenance, mixed
spans @@dmix@@ and no match @@dnone@@) and a further @@dpack@@ carry a word but sit in a CLB where their word is not the
plurality word or fails the 1/3 rule (packing).

\textbf{RQ-N10, I/O words.} H10a is @@h10as@@: the median LUT word coverage rises from @@cw@@ to @@cu@@ with io-words
(median gain @@gain@@, positive on @@pos@@ of 15 designs).

\textbf{Without the four pilot designs.} H8, H10a and H11 use the stock packings and no beta, so the pilot, which only chose
beta, cannot affect them; the n=11 pass is reported beside the n=15 status, which stays the primary one. H8 on the 11 designs: @@h8np@@.
H10a on the 11 designs: @@h10np@@.

@@n9@@
@@n9p@@
@@packratio@@
@@cptxt@@
\begin{table*}[t]
\caption{Round three: hypotheses, status and deciding number (all designs run; statuses use the rules in
\code{docs/plan/round3.md}). H9 numbers are for the headline $\beta_m$ of each source, Holm-adjusted over the three sources;
a status that differs between all 15 designs and the 11 without the pilot designs is shown as pilot-sensitive.}
\label{tab:r3status}
\centering
\footnotesize\setlength{\tabcolsep}{4pt}
\begin{tabular}{@{}lp{5.4cm}p{3.4cm}p{6.6cm}@{}}
\toprule
RQ & Hypothesis & Status & Deciding number \\
\midrule
@@status@@
\bottomrule
\end{tabular}
\end{table*}

\begin{table*}[t]
\caption{RQ-N8 per design on the stock packing: logic CLBs, word purity (plurality share), the random-grouping null
purity, word split factor (1.0 best), module purity, and the share of logic atoms lost to the front end (no word) and to
packing (word atom not in its word's CLB).}
\label{tab:r3n8}
\centering
\footnotesize\setlength{\tabcolsep}{3pt}
\begin{tabular}{lrrrrrrr}
\toprule
Design & CLBs & Purity & Null & Split & Module & Lost: FE & Lost: pack \\
\midrule
@@n8rows@@
\bottomrule
\end{tabular}
\end{table*}

\begin{table}[t]
\caption{RQ-N10: I/O words per design (buses of at least two bits) and the LUT word coverage without and with io-words.}
\label{tab:r3n10}
\centering
\footnotesize\setlength{\tabcolsep}{3pt}
\begin{tabular}{lrrr}
\toprule
Design & io-words & Word cov. & + io-words \\
\midrule
@@n10rows@@
\bottomrule
\end{tabular}
\end{table}

@@n11@@

@@h11tab@@
@@diag@@
""", h8s=stat(h8["status"]), msh=f2(h8["median_share"]), mnull=f2(h8["median_null_share"]), above=h8["above_null"],
                msp=f2(h8["median_split"]), gt1=h8["split_gt1"], mmod=f2(h8["median_module_share"]),
                dword=pct(dec["word"]), dabc=pct(dec["loss_abc"]), dmix=pct(dec["no_word_mixed"]),
                dnone=pct(dec["no_word_none"]), dpack=pct(dec["loss_pack"]), h10as=stat(h10a["status"]),
                cw=pct(h10a["median_cov_word"]), cu=pct(h10a["median_cov_union"]), gain=pct(h10a["median_gain"]),
                pos=h10a["positive"], n9=n9,
                h8np=(f"{stat(h8['no_pilot']['status'])} (median purity {f2(h8['no_pilot']['median_share'])}, split "
                      f"{f2(h8['no_pilot']['median_split'])})"),
                h10np=(f"{stat(h10a['no_pilot']['status'])} (median gain {pct(h10a['no_pilot']['median_gain'])}, positive on "
                       f"{h10a['no_pilot']['positive']} of {h10a['no_pilot']['n']}; the rule's 12 of 15 scaled to "
                       f"{h10a['no_pilot']['need']}, not registered)"),
                n9p=n9_prose(R) if "H9a" in R else "",
                cptxt=("\\textbf{Checkpoint.} The packing experiments (RQ-N9) are not complete, so no H9 or H10b status "
                       "is given.\n" if cp else ""),
                status=status_table(R), n8rows=n8_table(), n10rows=n10_table(), n11=n11_text(R),
                packratio=pack_ratio_text(R), h11tab=h11_table(R), diag=diag_table(R))


def n9_prose(R: dict) -> str:
    out = []
    for s in af.SOURCES:
        a, b, c = R["H9a"][s], R["H9b"][s], R["H9c"][s]
        out.append(f"\\textbf{{{SRC[s]} affinity.}} H9a is {stat(a['status'])}: the {SRC[s]}-level purity moves by "
                   f"{f3(a['all'].get('median_gain'))} (median, n={a['all']['n']}; {f3(a['no_pilot'].get('median_gain'))} without the pilot designs) "
                   f"with a median change of {pct(a['all'].get('median_growth'))} in logic CLBs "
                   f"(largest {pct(a['all'].get('max_growth'))}). H9b is {stat(b['status'])}: with the analytic start the routed "
                   f"wirelength is {f3(b['all'].get('gm'))} of the stock packer's (better on {b['all'].get('better')} of "
                   f"{b['all'].get('n')}; 90\\% interval {f3(b['all'].get('lo90'))} to {f3(b['all'].get('hi90'))}; "
                   f"{f3(b['no_pilot'].get('gm'))} without the pilot designs, status there {stat(b['no_pilot']['status'])}). "
                   f"H9c is {stat(c['status'])}: with the word seed it is {f3(c['all'].get('gm'))} "
                   f"(better on {c['all'].get('better')} of {c['all'].get('n')}).")
    h = R["H10b"]
    out.append(f"\\textbf{{I/O words in the affinity (H10b).}} {stat(h['status'])}: word+io over word is {f3(h['all'].get('gm'))} "
               f"(better on {h['all'].get('better')} of {h['all'].get('n')}, {peq(h['all'].get('p'))}).")
    return "\n\n".join(out) + "\n"


def n11_text(R: dict) -> str:
    h = R["H11"]
    if not h["n_designs"]:
        return ""
    var = h["variants"]
    parts = []
    for rel in ("word", "module"):
        x = h[rel]
        if not x["n"]:
            continue
        parts.append(f"same-{rel} pairs: median stratified distance difference {f3(x['median_d'])} "
                     f"(one-sided Wilcoxon {peq(x['p'])}, n={x['n']} designs; negative in at least two of three seeds on "
                     f"{x['consistent']} designs, {x['need']} needed; status {stat(x['status'])})")
    sc = var["registered_scaled"]
    am = var["amended"]
    ams = var["amended_scaled"]

    def one(v: dict) -> str:
        return (f"word {stat(v['word']['status'])} (n={v['word']['n']}), module {stat(v['module']['status'])} "
                f"(n={v['module']['n']}), overall {stat(v['status'])}")

    stab = ""
    if h.get("stability") is not None:
        stab = (f" Neighbour stability across VPR seeds (mean Jaccard of each CLB's four nearest neighbours): "
                f"{f3(h['stability'])} against {f3(h['stability_null'])} for a permuted placement.")
    npl = h["no_pilot"]
    return fill(r"""\textbf{RQ-N11, what the annealed placement says.} H11 is @@st@@ under the protocol text (no design excluded; the sign
rule needs 12 of the 15 designs, so a relation defined for fewer than 12 designs cannot be supported): @@parts@@.
The variants of Table~\ref{tab:r3h11}, labelled: with the sign rule scaled to $\lceil 12n/15\rceil$ designs, which the
first analysis code used and the protocol does not register (the previous primary status): @@sc@@; with the 95\%
exclusion of the amendment \code{d805789}: @@am@@ (scaled count: @@ams@@). Without the four pilot designs the protocol-text
statuses are @@np@@; the literal 12 is unreachable there.@@stab@@ The per-design ``why are these neighbours'' tables
(direct nets, shared high-fanout net, carry chain) are in \code{data/analysis/n11-why/}.
""", st=stat(h["status"]), parts="; ".join(parts), sc=one(sc), am=one(am), ams=one(ams),
                np=one(npl["registered"]), stab=stab)


def pos_txt(names: list[str]) -> str:
    if not names:
        return "none of the designs"
    return f"{len(names)} designs ({', '.join(code(x) for x in names)})"


def discussion(R: dict) -> str:
    out = ["\\subsection{Round three discussion}", "\\label{sec:r3-discussion}", ""]
    h8, h10a, h11 = R["H8"], R["H10a"], R["H11"]
    out.append(f"Packing does dilute word structure (H8 {stat(h8['status'])}): a word's atoms are spread over about "
               f"{f2(h8['median_split'])} times the CLBs they would need, and the purity of the stock CLBs "
               f"({f2(h8['median_share'])}) is well above a random grouping ({f2(h8['median_null_share'])}) but far from word-pure. "
               f"Of the logic atoms, {pct(h8['decompose_median']['loss_abc'])} have no word at all (the front end) and a further "
               f"{pct(h8['decompose_median']['loss_pack'])} are word atoms packed away from their word (packing); these are two "
               f"separate per-design medians, and the median front-end loss is larger than the median packing loss.")
    out.append(f"I/O words are a cheap way to recover part of the front-end loss (H10a {stat(h10a['status'])}: LUT word coverage "
               f"{pct(h10a['median_cov_word'])} to {pct(h10a['median_cov_union'])}).")
    if "H9a" in R and not R.get("checkpoint_only"):
        sec = R["secondary"]
        w = R["H9a"]["word"]["all"]
        wb = R["H9b"]["word"]["all"]
        wc = R["H9c"]["word"]["all"]
        out.append(f"The Norns packer does what it was built to do: with the word affinity the word purity rises by "
                   f"{f3(w.get('median_gain'))} at a median CLB change of {pct(w.get('median_growth'))} (H9a {stat(R['H9a']['word']['status'])}; "
                   f"module {stat(R['H9a']['module']['status'])}, word+io {stat(R['H9a']['wordio']['status'])}). "
                   f"The module source has almost nothing to act on, because the designs are close to one module each "
                   f"(median module purity {f2(h8['median_module_share'])}).")
        out.append(f"Purer clusters did not give shorter wires. With the analytic start the word-affinity packing routes at "
                   f"{f3(wb.get('gm'))} of the stock packer's wirelength (better on {wb.get('better')} of {wb.get('n')} designs, "
                   f"90\\% interval {f3(wb.get('lo90'))} to {f3(wb.get('hi90'))}), so H9b is {stat(R['H9b']['word']['status'])}: the sign is "
                   f"positive (worse) on every source, the two-sided test reaches the 5\\% level only without the four pilot designs, "
                   f"and the status is therefore not stated as a change. With the round-two word seed rebuilt on the new packing the ratio is "
                   f"{f3(wc.get('gm'))} (H9c {stat(R['H9c']['word']['status'])}): giving the round-two seed word-pure CLBs does not "
                   f"rescue it. The packing time grows by a factor {f3(sec['word.analytic']['pack_s'])} (word) and "
                   f"{f3(sec['module.analytic']['pack_s'])} (module). The seed noise (median coefficient of variation "
                   f"{pct(R['seed_noise']['cv_median'])}, up to {pct(R['seed_noise']['cv_max'])}) is of the same order as the "
                   f"effect, which is why the statistics use the design as the unit with three seeds each.")
        out.append("These runs do not remove the start-temperature confound of round two for the seeded arms, "
                   "because a seeded start still carries its own start temperature; the analytic-start arm (H9b) "
                   "does not have it, since the packing is the only difference.")
    if h11["n_designs"]:
        w, m = h11["word"], h11["module"]
        var = h11["variants"]
        pos = h11["d_positive"]

        def v_txt(v: dict) -> str:
            return (f"word {stat(v['word']['status'])} (n={v['word']['n']}), module {stat(v['module']['status'])} "
                    f"(n={v['module']['n']}), overall {stat(v['status'])}")

        out.append(fill(r"""In the median design both relations sit closer than their direct nets alone predict (stratified distance difference
@@wd@@ for same-word pairs, @@md@@ for same-module pairs), but not on every design: the same-word difference is positive on
@@posw@@ and the same-module difference on @@posm@@. H11 is @@st@@ under the protocol text, because its rule needs both
relations to pass: same word, n=@@wn@@, status @@ws@@ (negative in two of three seeds on @@wc@@ designs, @@wneed@@ needed);
same module, n=@@mn@@, status @@ms@@ (@@mc@@ designs, @@mneed@@ needed). Two deviations of the analysis from the protocol text are reported
beside it, not instead of it: the unregistered scaling of the count to $\lceil 12n/15\rceil$ designs, which the first analysis used
(\code{r3stats.py}), gives @@sc@@; the amendment \code{d805789}, which excludes a design from a relation when 95\% or more of its
sampled pairs are related, for the word relation as well as the module relation, gives @@am@@. Both are recorded in the entry of
2026-10-25 of \code{docs/plan/round3.md} and in the Method. The neighbours are only partly stable: the mean Jaccard of
each CLB's four nearest neighbours between VPR seeds is @@stab@@, against @@stabn@@ for a permuted placement.
""", wd=f3(w.get("median_d")), md=f3(m.get("median_d")), posw=pos_txt(pos["word"]), posm=pos_txt(pos["module"]),
                        st=stat(h11["status"]), wn=w["n"], ws=stat(w["status"]), wc=w.get("consistent"), wneed=w.get("need"),
                        mn=m["n"], ms=stat(m["status"]), mc=m.get("consistent"), mneed=m.get("need"),
                        sc=v_txt(var["registered_scaled"]), am=v_txt(var["amended"]),
                        stab=f3(h11["stability"]), stabn=f3(h11["stability_null"])))
    out.append("Round three leaves open the effort curve (N3), larger designs (N5), region looseness (N6), "
               "a seed-selector change in the Norns packer, and whether a different gain scale (the grid ended at the largest beta "
               "of the pilot list; the pilot did not discriminate the betas, so the grid is not informed by it) changes the sign of H9b. "
               "The packing time ratios of Stage 4 compare two builds and the proposal step has the counting and ordering "
               "limits described in the Method, both to be fixed in round 4.")
    return "\n\n".join(out) + "\n"


def outcomes_text(R: dict) -> str:
    parts = [f"H8 {stat(R['H8']['status'])}", f"H10a {stat(R['H10a']['status'])}"]
    if "H9a" in R:
        for h in ("H9a", "H9b", "H9c"):
            parts.append(h + " " + ", ".join(f"{SRC[s]} {stat(R[h][s]['status'])}" for s in af.SOURCES))
        parts.append(f"H10b {stat(R['H10b']['status'])}")
    parts.append(f"H11 {stat(R['H11']['status'])} (word {stat(R['H11']['word']['status'])}, module {stat(R['H11']['module']['status'])})")
    return "; ".join(parts) + "."


def appendix(R: dict) -> str:
    rows = [(rq, hyp, stat(st), num) for rq, hyp, st, num in h_rows(R)]
    tab = "\n".join(f"{rq} & {hyp} & 3 & {st} & {num} \\\\" for rq, hyp, st, num in rows)
    return fill(r"""\paragraph{2026-10-24, round three: Peter's two questions.} ``@@q1@@''
and ``@@q2@@''
Reading: the clustering step (VPR's AAPack, not T-VPack) may be where the HDL structure is lost before placement
starts; the I/O buses are words too, and say where words sit; and the annealed placement, read with provenance, may
answer which constructs end up near each other and why.

\paragraph{2026-10-24, what round two suggested.} Every soft seed stayed within 0.980 to 1.029 of the baseline:
the seeds were applied after packing, to whole CLBs, and ABC had already merged cones (only about half of the LUTs get a
word), so packing dilution was untested (N8) and word structure at the pad level was unused (N10). The T0 confound of
round two (a seeded start also changes VPR's start temperature) is still open for the seeded arms: round three does not
remove it. The analytic-start comparison (H9b) addresses it for the packing question, because there the packing is the only difference.

\paragraph{2026-10-24, round three: questions and hypotheses.} N8: H8. N10: H10a, H10b. N9: H9a, H9b, H9c with the
Norns packer. N11: H11. All rules, margins and the grid-selection rule are fixed in \code{docs/plan/round3.md}, committed as
\code{@@sha@@} before any measurement.

\paragraph{2026-10-24, round three: outcomes.} @@outcomes@@ The numbers are in Table~\ref{tab:r3status}.

\paragraph{2026-10-25, round three fix round (after review).} The rule-provenance description was corrected: the entry
\code{d805789}, called a clarification, is an amendment that changed two H11 rules (label permutations; the 95\% exclusion), and two
designs had Stage-4 runs finished before it was committed (Method). H11 is now given under the protocol text (no exclusion,
12 of the 15 designs, 1000 pooled permutations) as the primary status: @@h11now@@; the status of the first analysis (the sign rule
scaled to $\lceil 12n/15\rceil$ designs, not registered) was @@h11old@@, and the amendment's exclusion gives @@h11am@@. The n=11 pass was added for
H8, H10a and H11, Holm now keeps $m=3$ (no status changed), and the positional null uses 200 permutations. The packer got a log-only proposal
counter and an integer-parse error; the packing is unchanged (Method), and the per-design matched-entry and proposal tables
are in Table~\ref{tab:r3diag}. Not done: the proposal-counting behaviour (round 4).

\paragraph{2026-10-24, next.} The effort curve (N3), larger designs (N5), a seed-selector change and a larger gain scale in the Norns packer, and the
packing-time cost of the affinity term. Added 2026-10-25: fix the proposal counter (count queued molecules only; return a bool from the
candidate-queue step) and the scan order of the group members, then rerun the packing experiments.

\begin{table}[t]
\caption{Round-three research questions and hypotheses with status and the deciding number (extends Table~\ref{tab:r2log}).}
\label{tab:r3log}
\centering
\footnotesize\setlength{\tabcolsep}{3pt}
\begin{tabular}{@{}lp{2.5cm}lp{1.5cm}p{2.2cm}@{}}
\toprule
RQ & Hypothesis & Round & Status & Deciding number \\
\midrule
@@tab@@
\bottomrule
\end{tabular}
\end{table}
""", q1=QUOTE1, q2=QUOTE2, sha=PROTOCOL_SHA, tab=tab,
                outcomes=outcomes_text(R),
                h11now=f"word {stat(R['H11']['word']['status'])}, module {stat(R['H11']['module']['status'])}, overall {stat(R['H11']['status'])}",
                h11old=(f"word {stat(R['H11']['variants']['registered_scaled']['word']['status'])}, module "
                        f"{stat(R['H11']['variants']['registered_scaled']['module']['status'])}, overall "
                        f"{stat(R['H11']['variants']['registered_scaled']['status'])}"),
                h11am=(f"word {stat(R['H11']['variants']['amended']['word']['status'])}, module "
                       f"{stat(R['H11']['variants']['amended']['module']['status'])}"))


def main(argv: list[str]) -> int:
    R = load()
    texts = {"r3-method.tex": method(R), "r3-results.tex": results(R),
             "r3-discussion.tex": discussion(R), "r3-appendix.tex": appendix(R)}
    for name, text in texts.items():
        (PAPER / name).write_text(text, encoding="utf-8")
        print("wrote", name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
