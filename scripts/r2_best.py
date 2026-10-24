"""Which new family is the best (lowest geomean soft-full wirelength ratio over the designs where
all round-2 soft arms ran)."""
import nornlib as nl
import report

NEW = ("words", "slices", "hier", "words_partial")
SOFT = NEW + ("random", "urd_shuf")


def round2_designs(data, designs):
    """Designs on which every round-2 soft arm has a successful scale-1 run."""
    return [d for d in designs
            if all(report.pick(data[d], "soft", f, "full") is not None for f in SOFT)
            and report.pick(data[d], "soft", "words", "inter") is not None]


FROZEN = nl.DATA / "analysis" / "best.json"


def best_family():
    """The frozen choice (data/analysis/best.json, written by `round2.py freeze`) if there is
    one, else the current best."""
    if FROZEN.is_file():
        return nl.read_json(FROZEN)["family"]
    return current_best()


def current_best():
    data, designs = report.load_all()
    designs = round2_designs(data, designs)
    if not designs:
        return None
    scores = {}
    for fam in NEW:
        vals = []
        for d in designs:
            base = report.pick(data[d], "baseline")
            r = report.ratio(report.pick(data[d], "soft", fam, "full"), base, "wirelength")
            if r is not None:
                vals.append(r)
        if len(vals) == len(designs):
            scores[fam] = nl.geomean(vals)
    if not scores:
        return None
    return min(NEW, key=lambda f: scores.get(f, float("inf")))
