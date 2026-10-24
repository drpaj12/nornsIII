"""Audit of the round-two seed files (no VPR run): do the committed seed builders reproduce the
seed files VPR ran from, and where does the slices column-major bit-order fallback matter?

Builds the seven round-two seed families again in a scratch tree (runs/<design>/{netlist,words,
runs} linked from this checkout, seeds written to the scratch tree only), once as committed and
once with NORNS_NO_BIT_FALLBACK=1 (slices only), and compares every .place, .flat_place and
.xml file byte for byte with runs/<design>/seeds. Writes data/analysis/seed_audit.json.

Usage: python scripts/audit_seeds.py <scratch dir (new, empty)> [design ...]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import nornlib as nl

FAMILIES = "words,slices,hier,words_partial,random,words_partial_shuf,urd_shuf"
SUFFIXES = (".place", ".flat_place", ".xml")


def scratch_tree(root: Path, designs: list[str]) -> None:
    shutil.copytree(nl.WS / "scripts", root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    for d in designs:
        (root / "runs" / d).mkdir(parents=True)
        for sub in ("netlist", "words", "runs"):
            os.symlink(nl.runs_dir(d, sub), root / "runs" / d / sub)


def build(root: Path, only: str, extra_env: dict[str, str]) -> None:
    env = dict(os.environ, **extra_env)
    env["PYTHONPATH"] = f"{root / 'scripts'}:{env.get('PYTHONPATH', '')}"
    designs = sorted(p.name for p in (root / "runs").iterdir())
    subprocess.run([sys.executable, str(root / "scripts" / "build_word_seeds.py"), f"--only={only}",
                    *designs], env=env, check=True, stdout=subprocess.DEVNULL)


def same_files(root: Path, design: str, names: list[str]) -> bool:
    return all((root / "runs" / design / "seeds" / n).read_bytes()
               == nl.runs_dir(design, "seeds", n).read_bytes() for n in names)


def main(argv: list[str]) -> int:
    scratch = Path(argv[0])
    designs = argv[1:] or list(nl.DESIGN_ORDER)
    committed, nofb = scratch / "committed", scratch / "nofallback"
    for root in (committed, nofb):
        scratch_tree(root, designs)
    build(committed, FAMILIES, {})
    build(nofb, "slices", {"NORNS_NO_BIT_FALLBACK": "1"})
    rows = {}
    for d in designs:
        names = sorted(p.name for p in (committed / "runs" / d / "seeds").iterdir()
                       if p.name.endswith(SUFFIXES))
        slices = [n for n in names if n.startswith("slices-")]
        rows[d] = {"files": len(names), "identical_to_runs": same_files(committed, d, names),
                   "fallback_changes_slices": not same_files(nofb, d, slices),
                   "slices_equals_words": all(
                       (committed / "runs" / d / "seeds" / n).read_bytes()
                       == (committed / "runs" / d / "seeds" / n.replace("slices-", "words-")).read_bytes()
                       for n in slices if n.endswith(".place")),
                   "hier_equals_urd": all(
                       (committed / "runs" / d / "seeds" / n).read_bytes()
                       == nl.runs_dir(d, "seeds", n.replace("hier-", "urd-")).read_bytes()
                       for n in names if n.startswith("hier-") and n.endswith(".place"))}
        print(d, rows[d])
    nl.write_json(nl.DATA / "analysis" / "seed_audit.json", {"designs": rows})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
