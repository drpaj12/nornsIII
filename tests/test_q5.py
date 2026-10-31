"""Q-N5 helpers: cluster budget and threshold (q5_prep.budget), win/loss/tie counts, the near-critical share (q5_stats.mech_share)."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import os
os.environ.setdefault("NORNS_VPR", "/nonexistent")
import q5_prep
import q5_stats


class Budget(unittest.TestCase):
    def test_eq7(self):
        crits = [0.9, 0.8, 0.7, 0.6, 0.5]
        self.assertEqual(q5_prep.budget(1, 2, 10, crits), (5, 0.5))      # floor(1 x 10 / 2) = 5 = all clusters
        self.assertEqual(q5_prep.budget(1, 4, 10, crits), (2, 0.8))      # floor(10 / 4) = 2: the two most critical seeds
        self.assertEqual(q5_prep.budget(36, 2, 10, crits)[0], 5)         # capped at the stock logic clusters
        n, t = q5_prep.budget(0, 2, 10, crits)
        self.assertEqual(n, 0)
        self.assertGreater(t, 1e6)                                       # no cluster qualifies

    def test_wlt(self):
        self.assertEqual(q5_stats.wlt([0.9, 1.1, 1.003, 0.997]), (1, 1, 2))


class Share(unittest.TestCase):
    def test_share(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "spare.dump").write_text("1\t0.9\t1\t8\ta\tb\n2\t0.5\t0\t10\tc\td\te\tf\n")
            rpt = ("#Path 1\nStartpoint: a.out[0] (x)\nPoint Incr Path\na.out[0] (.names) 1 1\nc.in[0] (.names) 1 2\n"
                   "data arrival time   2.000\n\n#Path 2\nb.out[0] (.names) 1 1\nd.in[0] (.names) 1 1\ndata arrival time   1.000\n")
            (d / "report_timing.setup.rpt").write_text(rpt)
            r = q5_stats.mech_share(d)
            self.assertEqual((r["near_paths"], r["near_atom_occ"], r["in_qualified"]), (1, 2, 1))   # only path 1 is within 90% of the longest
            self.assertAlmostEqual(r["base_rate"], 2 / 6)


if __name__ == "__main__":
    unittest.main()
