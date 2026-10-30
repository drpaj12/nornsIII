"""HS0 seed-gap runner: the oracle seed list (atom rule, cluster order), the random orders and the pooling rule on hand-made inputs.
Run from the repo root: python3 tests/test_hs0.py"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
TMP = tempfile.mkdtemp()
os.environ["R9_V2"] = TMP
os.environ["HS0_OUT"] = str(Path(TMP) / "out")
import hs0run as hs  # noqa: E402


def make_design() -> None:
    base = Path(TMP) / "d" / "own"
    (base / "sh0").mkdir(parents=True)
    (base / "sh0" / "design.blif").write_text(".model t\n.end\n")
    (base / "build.json").write_text(json.dumps({"K": 2, "shuffles": {"0": {"sha256": "ab"}}}))
    # vertices 0..5; clusters: {0,1,2} -> 0, {3,4,5} -> 1. Nets: (0,1) (0,2) (0,1,2) (3,4) (3,5) (4,5) (2,3) cut net.
    nets = [[0, 1], [0, 2], [0, 1, 2], [3, 4], [3, 5], [4, 5], [2, 3]]
    (base / "struct.json").write_text(json.dumps({"hn": nets, "cl": [0, 0, 0, 1, 1, 1], "K": 2, "w": [1] * 6}))
    (base / "sh0" / "vatoms.json").write_text(json.dumps([["a0"], ["a1"], ["a2"], ["a3"], ["a4"], ["a5"]]))
    (base / "sh0" / "affinity.tsv").write_text("".join(f"a{i}\t{0 if i < 3 else 1}\n" for i in range(6)))


class Oracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        make_design()
        cls.b = hs.Build("d")

    def test_atom_rule(self) -> None:
        # intra-cluster nets: v0 3, v1 2, v2 2 (the cut net (2,3) is not intra); v3 2, v4 2, v5 2 (tie -> lowest vertex)
        self.assertEqual(self.b.seed_atom_of_clusters(), {0: "a0", 1: "a3"})

    def test_cluster_order_follows_stock_dump(self) -> None:
        dump = Path(TMP) / "dump.tsv"
        dump.write_text("0\tpad\n1\ta5\n2\ta1\n3\ta0\n")  # cluster 1 appears first (a5 at 1), cluster 0 at 2
        self.assertEqual(self.b.oracle_list(dump), ["a3", "a0"])
        dump.write_text("0\ta2\n1\ta4\n")  # cluster 0 first
        self.assertEqual(self.b.oracle_list(dump), ["a0", "a3"])

    def test_cluster_without_dump_atoms_goes_last(self) -> None:
        dump = Path(TMP) / "dump2.tsv"
        dump.write_text("0\ta4\n")
        self.assertEqual(self.b.oracle_list(dump), ["a3", "a0"])

    def test_random_lists_fixed(self) -> None:
        self.assertEqual(self.b.random_list(1), self.b.random_list(1))
        self.assertNotEqual(self.b.random_list(1), self.b.random_list(2))
        self.assertEqual(sorted(self.b.random_list(3)), [f"a{i}" for i in range(6)])


class Stats(unittest.TestCase):
    def test_median_and_holm(self) -> None:
        self.assertAlmostEqual(hs.median_log([1.0, 3.0, 2.0]), 2.0)
        self.assertAlmostEqual(hs.median_log([1.0, 2.0, 3.0, 4.0]), 2.5)
        adj = hs.holm([0.01, 0.04, 0.03])
        self.assertAlmostEqual(adj[0], 0.03)
        self.assertAlmostEqual(adj[2], 0.06)
        self.assertAlmostEqual(adj[1], 0.06)

    def test_per_design_gaps(self) -> None:
        import math
        runs = {}
        for s in hs.SEEDS:
            runs[("x", "stock", s)] = {"n_c": 10, "logic_clbs": 12, "wirelength": 100, "cpd_ns": 5.0}
            runs[("x", "oracle", s)] = {"n_c": 10, "logic_clbs": 10, "wirelength": 80, "cpd_ns": 5.0}
            for r in range(1, hs.R + 1):
                runs[("x", f"rand{r}", s)] = {"n_c": 10, "logic_clbs": 11 + (r % 2), "wirelength": 100, "cpd_ns": 5.0}
        row = hs.per_design(runs, "x", {"x": 10})
        self.assertAlmostEqual(math.exp(row["logic_clbs:oracle"]), 1.2)
        self.assertAlmostEqual(math.exp(row["logic_clbs:best8"]), 12 / 11)
        self.assertAlmostEqual(math.exp(row["logic_clbs:median8"]), 12 / math.sqrt(11 * 12))
        self.assertAlmostEqual(math.exp(row["wirelength:oracle"]), 1.25)
        self.assertAlmostEqual(math.exp(row["logic_clbs:oracle_over_nc"]), 1.0)


if __name__ == "__main__":
    unittest.main()
