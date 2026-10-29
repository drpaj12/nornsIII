"""placers_main.py must create NORNS_DATA/placers itself: a sweep root that is new (no data/placers) crashed every design
after its first VPR run with FileNotFoundError when the result file was saved (2026-10-29 keep sweep).
placers_main.py is a script that parses argv at import, so this test reads its source: the save() helper creates the parent.
Run from the repo root: python3 tests/test_placers_data_dir.py"""
import re
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "scripts" / "placers_main.py").read_text()


class SaveCreatesDir(unittest.TestCase):
    def test_save_makes_parent_before_write(self):
        m = re.search(r"def save\(\):\n(.*?)\n\n", SRC, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("dst.parent.mkdir(parents=True, exist_ok=True)", body)
        self.assertLess(body.index("mkdir"), body.index("write_text"))


if __name__ == "__main__":
    unittest.main()
