"""Round-5 tests (docs/plan/round5.md, Tests). Run: python tests/test_r5.py  (from the repo root, with scipy)."""

import hashlib
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "scripts"))
import r5gen  # noqa: E402
import r5nl  # noqa: E402
import r5stats as st  # noqa: E402


def digest(name):
    return hashlib.sha256(r5gen.verilog(r5gen.build_spec(name)).encode()).hexdigest()


class Gen(unittest.TestCase):
    def test_deterministic(self):
        for n in ("r5_rand_ctl_16", "r5_mesh_dp_8"):
            self.assertEqual(digest(n), digest(n))

    def test_seed_changes_output(self):
        a = digest("r5_rand_ctl_16")
        old = r5gen.SEED
        r5gen.SEED = old + 1
        try:
            self.assertNotEqual(a, digest("r5_rand_ctl_16"))
        finally:
            r5gen.SEED = old

    def test_functions_depend_on_all_inputs(self):
        spec = r5gen.build_spec("r5_tree_ctl_16")
        for blk in spec["blocks"]:
            for f in blk["funcs"]:
                self.assertTrue(r5gen.tt_depends_on_all(f["expr"]))

    def test_capacity_and_cut_all_small_designs(self):
        for n in r5gen.names():
            if r5gen.parse_name(n)[2] > 64:
                continue
            spec = r5gen.build_spec(n)
            self.assertEqual(len(spec["blocks"]), spec["b"])
            for blk in spec["blocks"]:
                self.assertEqual(len(blk["funcs"]), 10)
                self.assertLessEqual(len(blk["slots"]), r5gen.MAX_SLOTS)
                self.assertLessEqual(blk["n_out"], r5gen.MAX_DEG)
                self.assertLessEqual(len(blk["slots"]), r5gen.CLB_INPUTS)
            nets, cells = r5nl.cell_nets(spec)
            part = {c: c[0] for c in cells}
            self.assertEqual(r5nl.cut_value(nets, part), spec["designed_cut"], n)

    def test_netlist_blif_has_expected_counts(self):
        spec = r5gen.build_spec("r5_chain_dp_8")
        text = r5nl.blif(spec)
        self.assertEqual(text.count("\n.names "), 80)
        self.assertEqual(text.count("\n.latch "), 80)


class Rules(unittest.TestCase):
    def test_room_reaches_all_statuses(self):
        n = 20
        sup = st.decide_room({"WL": [math.log(1.2) + 0.01 * i for i in range(n)]})["WL"]["status"]
        nots = st.decide_room({"WL": [0.0] * n})["WL"]["status"]
        inc = st.decide_room({"WL": [math.log(1.03)] * n})["WL"]["status"]
        small = st.decide_room({"WL": [math.log(1.2)] * 5})["WL"]["status"]
        self.assertEqual((sup, nots, inc), ("supported", "not supported", "inconclusive"))
        self.assertIn("n too small", small)

    def test_close_reaches_all_statuses(self):
        n = 20
        self.assertEqual(st.decide_close({"WL": [math.log(0.9) - 0.01 * i for i in range(n)]})["WL"]["status"], "supported")
        self.assertEqual(st.decide_close({"WL": [math.log(1.03)] * n})["WL"]["status"], "not supported")
        self.assertEqual(st.decide_close({"WL": [math.log(0.995)] * n})["WL"]["status"], "inconclusive")

    def test_growth_reaches_all_statuses(self):
        def cells(sl):
            return {"WL": {f"c{i}": [(2 ** j, sl * j + 0.001 * i) for j in range(2, 11)] for i in range(8)}}
        self.assertEqual(st.decide_growth(cells(0.05))["WL"]["status"], "supported")
        self.assertEqual(st.decide_growth(cells(0.0))["WL"]["status"], "not supported")
        self.assertEqual(st.decide_growth(cells(0.005))["WL"]["status"], "inconclusive")

    def test_h23_reaches_all_statuses(self):
        self.assertEqual(st.decide_h23([0.2 + 0.01 * i for i in range(20)])["status"], "supported")
        self.assertEqual(st.decide_h23([0.0] * 20)["status"], "not supported")
        self.assertEqual(st.decide_h23([0.03 + 0.001 * i for i in range(20)])["status"], "inconclusive")

    def test_keep_and_repro(self):
        cell = {f"d{i}": f"c{i % 8}" for i in range(72)}
        self.assertEqual(st.decide_keep({d: True for d in cell}, cell)["status"], "supported")
        self.assertEqual(st.decide_keep({d: i < 40 for i, d in enumerate(cell)}, cell)["status"], "not supported")
        self.assertEqual(st.decide_keep({d: i < 60 for i, d in enumerate(cell)}, cell)["status"], "inconclusive")
        self.assertEqual(st.decide_repro([1.0] * 20)["status"], "supported")
        self.assertEqual(st.decide_repro([0.5] * 20)["status"], "not supported")
        self.assertEqual(st.decide_repro([1.0] * 17 + [0.9] * 3)["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
