"""Tests for scripts/q3feat.py and scripts/q3stats.py (Q-N3). Run: python -m unittest tests.test_q3 (from the repository root)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import q2gap  # noqa: E402
import q3feat  # noqa: E402
import q3stats  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_q2 import tiny  # noqa: E402


def graph():
    # a -> b, a -> c, b -> d; e unrelated. all LUTs.
    return {"comb": {"a": ("lut", []), "b": ("lut", ["a"]), "c": ("lut", ["a"]), "d": ("lut", ["b"]), "e": ("lut", [])}, "seq": {}, "alias": {},
            "net_atom": {"a": "a", "b": "b", "c": "c", "d": "d", "e": "e"}, "pos": ["d"], "pis": set(), "hard": set(), "cin": {}}


class TestFeat(unittest.TestCase):
    def test_features(self):
        ctx = q3feat.Ctx(graph(), {"b": [("a", 0.95)], "c": [("a", 0.2)]})
        st = q3feat.EventState(ctx, {"a"})
        fb = st.feats({"b"}, "b")
        fc = st.feats({"c"}, "c")
        fe = st.feats({"e"}, "e")
        self.assertEqual(fb[0], 1)  # shared nets: net a
        self.assertEqual(fe[0], 0)
        self.assertEqual(fb[3], 0)  # net a also has pins in c: not absorbed
        self.assertEqual(fb[7], 1)  # near-critical edge a -> b
        self.assertEqual(fc[7], 0)
        self.assertGreater(fb[1] + 1, fe[1])
        self.assertEqual(ctx.lvl.get("a"), None)  # no primary input reaches a: unreached

    def test_absorbed(self):
        ctx = q3feat.Ctx(graph(), {})
        st = q3feat.EventState(ctx, {"a", "c"})
        self.assertEqual(st.feats({"b"}, "b")[3], 1)  # net a now has pins only in a, c, b

    def test_dummy_view(self):
        ctx = q3feat.Ctx(graph(), {}, drop=frozenset({"c"}))
        st = q3feat.EventState(ctx, {"a", "c"})
        self.assertEqual(st.cl, {"a"})
        self.assertIsNone(st.feats({"c"}, "c"))

    def test_replay_callback_inert(self):
        a = q2gap.analyse_run(*tiny())
        seen = []
        b = q2gap.analyse_run(*tiny(), on_pick=lambda k, i: seen.append(k))
        self.assertEqual(a["waste"], b["waste"])
        self.assertEqual(seen, ["b"])


class TestStats(unittest.TestCase):
    def test_auc_top1(self):
        s = np.array([0.3, 0.9, 0.5])
        right = np.array([True, False, False])
        self.assertEqual(q3stats.auc_event(s, right, 1), 0.0)
        self.assertEqual(q3stats.auc_event(np.array([0.9, 0.3, 0.5]), right, 1), 1.0)
        self.assertEqual(q3stats.top1_event(np.array([0.9, 0.3, 0.5]), right), 1.0)
        self.assertEqual(q3stats.top1_event(np.array([0.5, 0.5, 0.1]), np.array([True, False, False])), 0.5)
        self.assertEqual(q3stats.auc_event(np.array([np.nan, 0.3, 0.5]), right, 1), 0.5)

    def test_bh(self):
        q = q3stats.bh([0.01, 0.04, 0.03, 0.5])
        self.assertAlmostEqual(q[0], 0.04)
        self.assertAlmostEqual(q[3], 0.5)

    def test_logistic_recovers_sign(self):
        rng = np.random.default_rng(1)
        D = rng.normal(size=(500, 2))
        D[:, 0] += 1.0
        w = q3stats.fit_logistic(D, np.ones(500), lam=1.0)
        self.assertGreater(w[0], 0)



class TestSeed(unittest.TestCase):
    def test_order_and_closeness(self):
        import q3seed
        blif = ".model m\\n.inputs a\\n.names a x\\n1 1\\n.latch x q re clk 0\\n.names q y\\n1 1\\n"
        blif = blif.replace("\\n", "\n")
        pos = q3seed.statement_order(blif)
        self.assertLess(pos["x"], pos["q"])
        self.assertLess(pos["q"], pos["y"])
        c = q3seed.closeness(["a", "b", "c"], {"a": {"b"}, "b": {"a", "c"}, "c": {"b"}})
        self.assertGreater(c["b"], c["a"])


if __name__ == "__main__":
    unittest.main()
