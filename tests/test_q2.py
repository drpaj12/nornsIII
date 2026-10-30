"""Tests for scripts/q2gap.py and scripts/q2pool.py (Q-N2). Run: python -m unittest tests.test_q2 (from the repository root)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import q2gap  # noqa: E402
import q2pool  # noqa: E402


def tiny():
    mk = lambda cs, idx, root, src, q: {"cseq": cs, "idx": idx, "kind": "seed" if idx == 0 else "cand", "src": src, "n": 1, "qgain": q,
                                         "bonus": 0, "attr": 0, "base": 0, "dom": -1, "root": root, "pos": 0, "atoms": [root]}
    mols = [mk(1, 0, "a1", 0, 0.0), mk(1, 1, "a3", 1, 0.9), mk(2, 0, "a2", 0, 0.0), mk(2, 1, "a4", 1, 0.4)]
    events = [(1, "M", 1, "a1", 0, 0.0), (2, "Q", 1, "a2", 1, 0.5), (3, "Q", 1, "a3", 1, 0.9), (4, "M", 1, "a3", 1, 0.9),
              (5, "M", 2, "a2", 0, 0.0), (6, "Q", 2, "a4", 1, 0.4), (7, "M", 2, "a4", 1, 0.4)]
    census = {"mols": mols, "atoms": {}, "pins": {}, "events": events,
              "closed": {1: {"pos": 0, "n_added": 2, "n_proposed": 2, "queue_left": 0}, 2: {"pos": 0, "n_added": 2, "n_proposed": 1, "queue_left": 0}},
              "fails": []}
    cmap = {"a1": 1, "a2": 1, "a3": 2, "a4": 2}
    atom_loc = {"a1": (("clb", 0), 0), "a3": (("clb", 0), 1), "a2": (("clb", 1), 0), "a4": (("clb", 1), 1)}
    clbs = {("clb", 0): {"fles": 2}, ("clb", 1): {"fles": 2}}
    g = {"comb": {"a1": ("lut", []), "a2": ("lut", []), "a3": ("lut", ["n1"]), "a4": ("lut", ["n2"])}, "seq": {}, "alias": {},
         "net_atom": {"n1": "a1", "n2": "a2"}, "pos": [], "pis": set(), "hard": set(), "cin": {}}
    return census, cmap, atom_loc, clbs, g


class TestQ2(unittest.TestCase):
    def test_attribution(self):
        r = q2gap.analyse_run(*tiny())
        self.assertEqual(r["S"], 2)
        self.assertEqual(r["T"], 4)
        self.assertEqual(r["waste"], {"b": 8, "a": 8})
        self.assertEqual(r["events"]["b"], 1)
        self.assertEqual(r["events"]["filler"], 1)
        self.assertEqual(r["b"]["below"], 1)
        self.assertEqual(r["b"]["rank1"], 1)  # rank among the queue without the pick
        self.assertEqual(r["a_sub"], {"b": 8.0})
        self.assertEqual(r["cut"]["stock"], 0)
        self.assertEqual(r["cut"]["C"], 2)

    def test_waste_sums_to_gap(self):
        r = q2gap.analyse_run(*tiny())
        self.assertEqual(sum(r["waste"].values()), 10 * r["S"] - r["T"])

    def test_pct(self):
        self.assertEqual(q2pool.pct([1, 2, 3, 4, 5], 0.5), 3)
        self.assertAlmostEqual(q2pool.pct([0, 10], 0.1), 1.0)
        self.assertIsNone(q2pool.pct([], 0.5))


if __name__ == "__main__":
    unittest.main()
