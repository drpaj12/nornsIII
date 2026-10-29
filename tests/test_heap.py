"""Tests of the critical-heap helpers: the kind join (innermost structure), the enrichment ratio, the bootstrap, Spearman, the census parser.
Run from the repo root: python3 tests/test_heap.py"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import heap_lib as hl  # noqa: E402


class Join(unittest.TestCase):
    def test_innermost_wins(self):
        k = hl.innermost_kind([("logic", {"a", "b", "c", "d"}), ("adder", {"a", "b"}), ("mux", {"d"})])
        self.assertEqual(k, {"a": "adder", "b": "adder", "c": "logic", "d": "mux"})

    def test_tie_by_name(self):
        k = hl.innermost_kind([("mux", {"a"}), ("adder", {"a"})])
        self.assertEqual(k["a"], "adder")


class Ratio(unittest.TestCase):
    def test_enrichment(self):
        # 6 of 10 heap atoms are adders; 20 of 100 atoms are adders -> 0.6 / 0.2 = 3
        self.assertAlmostEqual(hl.enrichment(6, 10, 20, 100), 3.0)

    def test_undefined(self):
        self.assertIsNone(hl.enrichment(0, 0, 5, 10))
        self.assertIsNone(hl.enrichment(1, 5, 0, 10))

    def test_zero_when_never_near(self):
        self.assertEqual(hl.enrichment(0, 10, 20, 100), 0.0)


class Boot(unittest.TestCase):
    def test_constant(self):
        m, lo, hi, n = hl.boot_median([2.0] * 7)
        self.assertEqual((m, lo, hi, n), (2.0, 2.0, 2.0, 7))

    def test_interval_brackets_median(self):
        m, lo, hi, n = hl.boot_median([1, 2, 3, 4, 5, 6, 7, 8, 9], b=500)
        self.assertEqual(m, 5)
        self.assertLessEqual(lo, m)
        self.assertGreaterEqual(hi, m)

    def test_none_dropped(self):
        self.assertEqual(hl.boot_median([None, None])[3], 0)


class Spear(unittest.TestCase):
    def test_monotone(self):
        self.assertAlmostEqual(hl.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(hl.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)

    def test_ties_and_constant(self):
        self.assertIsNone(hl.spearman([1, 2, 3], [5, 5, 5]))
        self.assertIsNotNone(hl.spearman([1, 1, 2, 3], [1, 2, 2, 3]))


class Census(unittest.TestCase):
    def test_parse(self):
        txt = ("M\t1\t0\tseed\t0\t1\t0\t0\t0\t1\t-1\ta1\nA\t1\t0\ta1\t0\t0\t0\t0\nP\t1\ta1\tn1\t0.4\nP\t1\ta1\tn2\t0.9\n"
               "M\t1\t1\tcand\t1\t1\t0\t0\t0\t1\t-1\tb1\nA\t1\t1\tb1\t0\t0\t0\t0\nP\t1\tb1\tn1\t0.2\nK\t1\t2\t0\t0\n"
               "M\t2\t0\tseed\t0\t1\t0\t0\t0\t1\t-1\tc1\nA\t2\t0\tc1\t0\t0\t0\t0\nP\t2\tc1\tn1\t0.7\n"  # cluster 2 never closed: destroyed
               "M\t3\t0\tseed\t0\t1\t0\t0\t0\t1\t-1\tp1\nA\t3\t0\tp1\t0\t0\t0\t0\nK\t3\t1\t0\t0\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.tsv"
            p.write_text(txt)
            c = hl.pack_rank(hl.parse_census(p, pads={"p1"}))
        self.assertEqual(set(c), {"a1", "b1"})
        self.assertEqual(c["a1"]["pc"], 0.9)
        self.assertEqual(c["b1"]["idx"], 1)
        self.assertEqual(c["a1"]["seq"], 0.0)
        self.assertEqual(c["b1"]["seq"], 1.0)


BLIF = """.model m
.inputs a b clk
.outputs o1 o2
.names a b x
11 1
.names x y1
1 1
.names y1 b z
11 1
.latch z q re clk 0
.names q x w
11 1
.names w o1
1 1
.names z o2
1 1
.end
"""


class Netlist(unittest.TestCase):
    def test_levels_and_buffers(self):
        g = hl.parse_blif_graph(BLIF)
        self.assertEqual(g["alias"], {"y1": "x", "o1": "w", "o2": "z"})
        self.assertEqual(set(g["comb"]), {"x", "z", "w"})
        lv = hl.comb_levels(g)
        self.assertEqual(lv, {"x": 1, "z": 2, "w": 2})  # w reads register q (level 0) and x (level 1)

    def test_cones_one_group_per_endpoint(self):
        g = hl.parse_blif_graph(BLIF)
        lv = hl.comb_levels(g)
        grp, size = hl.assign_cones(g, lv)
        # endpoints: latch q (D = z, hint 2), out:o1 (driver w, hint 2), out:o2 (driver z, hint 2); ties by name
        self.assertEqual(set(grp), {"x", "z", "w"})
        self.assertEqual(sum(size.values()), 3)  # every comb atom in exactly one group
        # equal hints, so name order: out:o1 first takes w and its cone x; out:o2 then takes z (x is taken); q gets nothing new
        self.assertEqual((grp["w"], grp["x"], grp["z"]), ("out:o1", "out:o1", "out:o2"))
        self.assertEqual(size["q"], 0)

    CHAIN = "\n".join([".model m", ".inputs a b c d", ".outputs s",
                        ".subckt adder a[0]=a b[0]=b cin[0]=c cout[0]=c1 sumout[0]=s0",
                        ".subckt adder a[0]=d b[0]=d cin[0]=c1 cout[0]=c2 sumout[0]=s", ".end", ""])

    def test_carry_chain_counts_once(self):
        g = hl.parse_blif_graph(self.CHAIN)
        self.assertEqual(len(g["comb"]), 2)
        self.assertEqual(sorted(hl.comb_levels(g).values()), [1, 1])

    def test_adder_chain_positions(self):
        g = hl.parse_blif_graph(self.CHAIN, {"c1", "c2"})
        self.assertEqual(sorted(hl.adder_chains(g).values()), [(0, 2), (1, 2)])


class Bins(unittest.TestCase):
    def test_bins(self):
        self.assertEqual([hl.crit_bin(x) for x in (None, 1.0, 0.95, 0.6, 0.1)], ["unseen", ">=0.99", "0.90-0.99", "0.50-0.90", "<0.50"])


if __name__ == "__main__":
    unittest.main()
