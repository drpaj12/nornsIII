"""rent_split.py: set assignment and summary (no store needed). Run from the repo root: python3 tests/test_rent_split.py"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rent_split as rs  # noqa: E402


class RentSplitTest(unittest.TestCase):
    def test_groups(self) -> None:
        self.assertEqual(rs.group_of("mcnc", "lut", "alu4"), "MCNC")
        self.assertEqual(rs.group_of("norns-netlist", "lut", "r5_mesh_dp_16"), "synthetic r5")
        self.assertEqual(rs.group_of("norns-netlist", "lut", "n5_tree_ctl_8"), "synthetic n5")
        self.assertEqual(rs.group_of("norns-netlist", "lut", "r6_chain_a50_4"), "synthetic r6")
        self.assertEqual(rs.group_of("norns-netlist", "lut", "diffeq1"), "real VTR Verilog")
        self.assertEqual(rs.group_of("loki:x", "gate", "d"), "Loki (gate level)")
        self.assertIsNone(rs.group_of("norns-r5", "lut", "d"))

    def test_summary(self) -> None:
        runs = [("a", 0.5, False), ("a", 0.7, False), ("b", -0.2, True), ("b", -0.4, True)]
        s = rs.summarise(runs)
        self.assertEqual((s["n_designs"], s["n_runs"]), (2, 4))
        self.assertEqual(s["negative_runs"], 2)
        self.assertEqual(s["negative_designs"], 1)
        self.assertEqual(s["low_confidence_runs"], 2)
        self.assertAlmostEqual(s["confident_mean"], 0.6)


if __name__ == "__main__":
    unittest.main()
