#!/usr/bin/env python3
"""Count the verdicts of the hypothesis register (docs/paper/hypotheses.md).

Usage:
    python3 docs/paper/check_register.py [--register docs/paper/hypotheses.md]

Every register table has a ``verdict`` column; the first word of a verdict cell is the verdict
(USEFUL, POSSIBLY GOOD, DISMISSED, INCONCLUSIVE or MEASUREMENT). The script prints the counts and
exits 1 if a row has no recognised verdict word. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

VERDICTS = ("USEFUL", "POSSIBLY GOOD", "DISMISSED", "INCONCLUSIVE", "MEASUREMENT")


def split_row(raw: str) -> list[str]:
    """Split one markdown table row into stripped cells (``\\|`` stays inside a cell)."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", raw.strip().strip("|"))]


def read_rows(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Return (H-ID, verdict word) pairs and a list of problems."""
    rows: list[tuple[str, str]] = []
    problems: list[str] = []
    column = -1
    for raw in text.splitlines():
        if not raw.startswith("|"):
            column = -1
            continue
        cells = split_row(raw)
        lowered = [c.lower() for c in cells]
        if "verdict" in lowered:
            column = lowered.index("verdict")
            continue
        if column < 0 or set(cells[0]) <= {"-", ":", " "}:
            continue
        if column >= len(cells):
            problems.append(f"{cells[0]}: no verdict cell")
            continue
        cell = cells[column].upper()
        word = next((v for v in VERDICTS if cell.startswith(v)), "")
        if word:
            rows.append((cells[0], word))
        else:
            problems.append(
                f"{cells[0]}: verdict cell starts with '{cells[column][:30]}'"
            )
    return rows, problems


def main(argv: list[str]) -> int:
    """Command-line entry."""
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--register", type=Path, default=here / "hypotheses.md")
    args = parser.parse_args(argv)
    rows, problems = read_rows(args.register.read_text(encoding="utf-8"))
    counts = Counter(word for _, word in rows)
    print(f"rows: {len(rows)}")
    for word in VERDICTS:
        print(f"{word}: {counts.get(word, 0)}")
    for problem in problems:
        print(f"PROBLEM {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
