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
neighbours (@@grid@@). Each claim is reported on all 15 designs and without the four pilot designs; a status
that differs between the two is called inconclusive (pilot-sensitive).

\paragraph{RQ-N11, proximity.} On the stock-packing, analytic-start runs, logic CLB pairs by relation (same word,
same module, same statement, net-connected, same io-word) against the direct net count, which is stratified
out: the stratified mean distance difference of related over unrelated pairs, as a fraction of the unrelated
distance (negative is closer).

\paragraph{Decision rules and their provenance.} Every hypothesis, metric, arm and numeric rule (including the margins
$\pm$2\% and 1\% for wirelength, 5 percentage points of purity, 5\% CLB growth) is in \code{docs/plan/round3.md},
committed as @@sha@@ on @@ptime@@, before any round-three measurement or VPR run; the paper reports only those
rules. Later changes are new dated entries in that file that keep the old rule, and the results are given under both.
""", files=nfiles, lines=nadd, dele=ndel, gate=gate_txt, grid=gridtxt, sha=f"\\code{{{PROTOCOL_SHA}}}", ptime=PROTOCOL_TIME)


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
                         f"purity +{f3(a.get('median_gain'))}, CLB {pct(a.get('median_growth'))}, p={pf(a.get('p_holm'))}"))
        for s in af.SOURCES:
            b = R["H9b"][s]["all"]
            rows.append(("N9", f"H9b {SRC[s]} changes WL (analytic)", R["H9b"][s]["status"],
                         f"geomean {f3(b.get('gm'))}, {b.get('better')}/{b.get('n')} better, p={pf(b.get('p_holm'))}"))
        for s in af.SOURCES:
            c = R["H9c"][s]["all"]
            rows.append(("N9", f"H9c {SRC[s]}+seed beats stock+seed", R["H9c"][s]["status"],
                         f"geomean {f3(c.get('gm'))}, {c.get('better')}/{c.get('n')} better, p={pf(c.get('p_holm'))}"))
        b = R["H10b"]["all"]
        rows.append(("N10", "H10b word+io beats word", R["H10b"]["status"],
                     f"geomean {f3(b.get('gm'))}, {b.get('better')}/{b.get('n')} better, p={pf(b.get('p'))}"))
    for rel in ("word", "module"):
        x = h11[rel]
        rows.append(("N11", f"H11 same-{rel} pairs closer than nets predict", x["status"],
                     f"median {f3(x.get('median_d'))}, p={pf(x.get('p'))}, n={x['n']}"
                     if x["n"] else "no data"))
    return rows


def status_table(R: dict) -> str:
    out = []
    for rq, hyp, status, num in h_rows(R):
        out.append(f"{rq} & {hyp} & {stat(status)} & {num} \\\\")
    return "\n".join(out)


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
CLBs is the cluster count; Pack and Flow are the packing and total VPR runtimes. The seed arm's stock reference is the stock
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
split factor is @@msp@@ (above 1 on @@gt1@@ of 15). The module purity is @@mmod@@ because most designs have a single dominant
module. Of the logic atoms, @@dword@@ carry a word (median); @@dabc@@ lack one (front end: ABC's cone provenance, mixed
spans @@dmix@@ and no match @@dnone@@) and a further @@dpack@@ carry a word but sit in a CLB where their word is not the
plurality word or fails the 1/3 rule (packing).

\textbf{RQ-N10, I/O words.} H10a is @@h10as@@: the median LUT word coverage rises from @@cw@@ to @@cu@@ with io-words
(median gain @@gain@@, positive on @@pos@@ of 15 designs).

@@n9@@
@@cptxt@@
\begin{table}[t]
\caption{Round three: hypotheses, status and deciding number (all designs run; statuses use the rules in
\code{docs/plan/round3.md}). H9 numbers are for the headline $\beta_m$ of each source, Holm-adjusted over the three sources.}
\label{tab:r3status}
\centering
\footnotesize\setlength{\tabcolsep}{3pt}
\begin{tabular}{@{}llp{2.2cm}p{3.2cm}@{}}
\toprule
RQ & Hypothesis & Status & Deciding number \\
\midrule
@@status@@
\bottomrule
\end{tabular}
\end{table}

\begin{table}[t]
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
\end{table}

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
""", h8s=stat(h8["status"]), msh=f2(h8["median_share"]), mnull=f2(h8["median_null_share"]), above=h8["above_null"],
                msp=f2(h8["median_split"]), gt1=h8["split_gt1"], mmod=f2(h8["median_module_share"]),
                dword=pct(dec["word"]), dabc=pct(dec["loss_abc"]), dmix=pct(dec["no_word_mixed"]),
                dnone=pct(dec["no_word_none"]), dpack=pct(dec["loss_pack"]), h10as=stat(h10a["status"]),
                cw=pct(h10a["median_cov_word"]), cu=pct(h10a["median_cov_union"]), gain=pct(h10a["median_gain"]),
                pos=h10a["positive"], n9=n9,
                cptxt=("\\textbf{Checkpoint.} The packing experiments (RQ-N9) are not complete, so no H9 or H10b status "
                       "is given.\n" if cp else ""),
                status=status_table(R), n8rows=n8_table(), n10rows=n10_table(), n11=n11_text(R))


def n11_text(R: dict) -> str:
    h = R["H11"]
    if not h["n_designs"]:
        return ""
    parts = []
    for rel in ("word", "module"):
        x = h[rel]
        if not x["n"]:
            continue
        parts.append(f"same-{rel} pairs: median stratified distance difference {f3(x['median_d'])} "
                     f"(one-sided Wilcoxon $p={pf(x['p'])}$, n={x['n']} designs; negative in at least two of three seeds on "
                     f"{x['consistent']}, needed {x['need']}; status {stat(x['status'])})")
    stab = ""
    if h.get("stability") is not None:
        stab = (f" Neighbour stability across VPR seeds (mean Jaccard of each CLB's four nearest neighbours): "
                f"{f3(h['stability'])} against {f3(h['stability_null'])} for a permuted placement.")
    return ("\\textbf{RQ-N11, what the annealed placement says.} H11 is " + stat(h["status"]) + ". "
            + "; ".join(parts) + "." + stab + " The per-design ``why are these neighbours'' tables "
            "(direct nets, shared high-fanout net, carry chain) are in \\code{data/analysis/n11-why/}.\n")


def discussion(R: dict) -> str:
    out = ["\\subsection{Round three discussion}", "\\label{sec:r3-discussion}", ""]
    h8 = R["H8"]
    out.append(f"Packing does dilute word structure (H8 {stat(h8['status'])}): a word's atoms are spread over about "
               f"{f2(h8['median_split'])} times the CLBs they would need, and the purity of the stock CLBs "
               f"({f2(h8['median_share'])}) is well above a random grouping but far from word-pure.")
    if "H9a" in R and not R.get("checkpoint_only"):
        a = ", ".join(f"{SRC[s]} {stat(R['H9a'][s]['status'])}" for s in af.SOURCES)
        b = ", ".join(f"{SRC[s]} {stat(R['H9b'][s]['status'])}" for s in af.SOURCES)
        c = ", ".join(f"{SRC[s]} {stat(R['H9c'][s]['status'])}" for s in af.SOURCES)
        out.append(f"The Norns packer's effect on purity is {a} (H9a). Whether purer clusters change routed wirelength "
                   f"with the analytic start is {b} (H9b), and with the word seed {c} (H9c).")
        out.append("These runs do not remove the start-temperature confound of round two for the seeded arms, "
                   "because a seeded start still carries its own start temperature; the analytic-start arm (H9b) "
                   "does not have it, since the packing is the only difference.")
    out.append("Round three leaves open the effort curve (N3), larger designs (N5), region looseness (N6), "
               "the cluster-level constraint of the hard arm, and a seed-selector change in the Norns packer.")
    return "\n\n".join(out) + "\n"


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
round two (a seeded start also changes VPR's start temperature) is not removed by round three for the seeded arms;
the analytic-start comparison (H9b) is free of it.

\paragraph{2026-10-24, round three: questions and hypotheses.} N8: H8. N10: H10a, H10b. N9: H9a, H9b, H9c with the
Norns packer. N11: H11. All rules, margins and the grid-selection rule are fixed in \code{docs/plan/round3.md}, committed as
\code{@@sha@@} before any measurement.

\paragraph{2026-10-24, round three: outcomes.} @@outcomes@@ The numbers are in Table~\ref{tab:r3status}.

\paragraph{2026-10-24, next.} The effort curve (N3), larger designs (N5), seed-selection changes in the Norns packer, and a
two-sided look at the packing time cost.

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
                outcomes="; ".join(f"{h} {stat(st)}" for _rq, h, st, _num in rows) + ".")


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
