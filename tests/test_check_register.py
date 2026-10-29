"""Tests for docs/paper/check_register.py (stdlib only). Run from the repo root:
    python3 tests/test_check_register.py"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs" / "paper"))
import check_register as cr

TABLE = """| H-ID | hypothesis | verdict | main paper? |
|---|---|---|---|
| A1 | x | USEFUL (reason) | yes |
| A2 | y | POSSIBLY GOOD (narrow) | yes |
| A3 | z | INCONCLUSIVE / DISMISSED (mixed) | no |
| A4 | w | DISMISSED | log |

| H-ID | idea | experiment |
|---|---|---|
| U1 | idea | experiment |
"""


class CheckRegister(unittest.TestCase):
    def test_counts(self) -> None:
        rows, problems = cr.read_rows(TABLE)
        self.assertEqual(problems, [])
        self.assertEqual(
            [w for _, w in rows], ["USEFUL", "POSSIBLY GOOD", "INCONCLUSIVE", "DISMISSED"]
        )

    def test_bad_verdict(self) -> None:
        _, problems = cr.read_rows(TABLE.replace("USEFUL (reason)", "GREAT"))
        self.assertEqual(len(problems), 1)

    def test_split_keeps_escaped_bar(self) -> None:
        self.assertEqual(cr.split_row("| a \\| b | c |"), ["a \\| b", "c"])


if __name__ == "__main__":
    unittest.main()
