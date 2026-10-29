# The Norns III paper

`norns.tex` — IEEEtran, Overleaf-uploadable (compile with pdfLaTeX; `IMAGE/` holds the shared
TikZ styles and `fig_norns.tex`, `joined.bib` the bibliography). Every number in the paper
traces to the experiment records: the run logs under `docs/plan/` and the kept data (or the
scripts that regenerate it). Tables marked `[TODO: ...]` fill in as runs land.

The suite tree (`IMAGE/fig_yggdrasil.tex`, with `IMAGE/odin3-tikz-styles.tex`) is a byte-identical copy of
the hub's `images/src/` files (Yggdrasil III hub, `drpaj12/YggdrasilIII`). `make_blind_tree.py` (run in
`docs/paper`) writes `IMAGE/blind/fig_yggdrasil.tex`, the same figure with the suite and tool names, the three
wells and the self-cited baseline replaced by placeholders, as the Odin III paper's `make_blind.py` does. No
build uses it yet (there is no blind build of this paper).

Step 2 (2026-10-28): `norns.tex` is now the hypothesis, experiment, verdict rewrite and inputs `n-*.tex`. The legacy `r2-*` to `r8-*.tex` files are no longer inputs (kept as the pre-restructure text). Gates: `python3 docs/paper/check_terms.py --tex docs/paper/norns.tex` (0 violations), `python3 docs/paper/check_register.py` (verdict counts), `python3 -m unittest discover -s tests`. Build: `tectonic -X compile build/norns-local.tex -Z search-path=docs/paper` (the wrapper selects OT1 fonts).
