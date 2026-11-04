# The Norns III paper

`norns.tex` — IEEEtran, Overleaf-uploadable (compile with pdfLaTeX; `IMAGE/` holds the shared
TikZ styles and `fig_norns.tex`, `joined.bib` the bibliography). Every number in the paper
traces to the experiment records: the run logs under `docs/plan/` and the kept data (or the
scripts that regenerate it). Tables marked `[TODO: ...]` fill in as runs land.

The Yggdrasil III tree figure is no longer in this paper (it appears only in the Odin III paper and on GitHub); the Introduction has `IMAGE/fig_norns_flow.tex`, the overarching flow figure of this tool, and the Background has one sentence naming the suite with a link to the hub.

Step 2 (2026-10-28): `norns.tex` is now the hypothesis, experiment, verdict rewrite and inputs `n-*.tex`. The legacy `r2-*` to `r8-*.tex` files are no longer inputs (kept as the pre-restructure text). Gates: `python3 docs/paper/check_terms.py --tex docs/paper/norns.tex` (0 violations), `python3 docs/paper/check_register.py` (verdict counts), `python3 -m unittest discover -s tests`. Build: from `docs/paper`, `latexmk -pdf -interaction=nonstopmode -outdir=build norns.tex` with the system TeX Live (`IEEEtran.cls` and `IEEEtran.bst` sit beside `norns.tex`, see `IEEEtran-NOTICE.md`). Last checked: 30 pages, 0 undefined references.

Cleanup (2026-11-02): the main text is the current story (Introduction, Background, Methodology, The Yardstick and the Packer Arms, Results, Discussion and Limits, Future Work, Conclusion). `a-records.tex` holds the appendices: A, instruments of the earlier rounds; B, one record per round or question in time order (including the known-optimal clustering, TPEKO-style, record); `n-log.tex` is the research register (Appendix C, four tables). `n-results.tex` replaced `n-experiments.tex` and `n-summary.tex`. The legacy `r2-*` to `r8-*.tex` files are still not inputs.

Background and results rewrite (2026-11-02): the Background is descriptive prose (who introduced each idea, how it ties to our experiments) and `n-results.tex` is a set of structured arguments (hypothesis, implication, experiment, methodology, measurements, interpretation, conclusion). `check_terms.py --write` rewrites the defined-at and first-used-at columns of `terms.md` from the first `\emph{}` use of each term; `python3 docs/paper/check_terms.py --tex docs/paper/norns.tex` reports 0 violations.
