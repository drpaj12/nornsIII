"""Which new family is the best (lowest geomean soft-full wirelength ratio over all designs)."""
import nornlib as nl
import report

NEW = ("words", "slices", "hier", "words_partial")


def best_family():
    data, designs = report.load_all()
    scores = {}
    for fam in NEW:
        vals = []
        for d in designs:
            base = report.pick(data[d], "baseline")
            r = report.ratio(report.pick(data[d], "soft", fam, "full"), base, "wirelength")
            if r is not None:
                vals.append(r)
        if vals and len(vals) == len(designs):
            scores[fam] = nl.geomean(vals)
    if not scores:
        return None
    return min(NEW, key=lambda f: scores.get(f, float("inf")))
