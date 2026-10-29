"""Seed-signal tests (docs/plan/seed-signal.md): a toy build (two clusters of C, a chain of LUT/FF cells, one dummy) checks the
Mimir netlist, the cluster and LUT features, the labels against a hand-written stock .net, and the statistics helpers.
Run: . scripts/env.sh; $NR_PY tests/test_seed_signal.py   (needs numpy, scipy and the Mimir checkout)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import seed_features as sf  # noqa: E402
import seed_signal as ss  # noqa: E402

BLIF = """.model toy
.inputs clk p0 p1
.outputs q3
.names p0 p1 l0
11 1
.latch l0 q0 re clk 2
.names q0 p1 l1
10 1
01 1
.latch l1 q1 re clk 2
.names q1 q0 l2
11 1
.latch l2 q2 re clk 2
.names q2 q1 l3
1- 1
-1 1
.latch l3 q3 re clk 2
.names q0 q3 d0
10 1
01 1
.latch d0 e0 re clk 2
.names gnd
.end
"""
# vertices: 0..3 real cells (clusters 0,0,1,1), 4 const, 5 dummy (cluster 1)
ATOMS = [["l0", "q0"], ["l1", "q1"], ["l2", "q2"], ["l3", "q3"], ["gnd"], ["d0", "e0"]]
CL = [0, 0, 1, 1, 1, 1]


def make_build(tmp: Path) -> Path:
    d = tmp / "toy" / "own"
    sh = d / "sh1"
    (sh / "run-abcdef0123").mkdir(parents=True)
    (sh / "design.blif").write_text(BLIF)
    (sh / "vatoms.json").write_text(json.dumps(ATOMS))
    aff = {a: CL[v] for v, atoms in enumerate(ATOMS) for a in atoms}
    (sh / "affinity.tsv").write_text("".join(f"{a}\t{c}\n" for a, c in sorted(aff.items())))
    (d / "struct.json").write_text(json.dumps({"hn": [], "cl": CL, "K": 2, "K0": 0, "w": [1] * 6}))
    rec = {"cells_real": 4, "const_generators": 1, "dummies": 1, "K": 2,
           "shuffles": {str(s): {"sha256": "abcdef0123" + "0" * 54} for s in (1, 2, 3)}}
    (d / "build.json").write_text(json.dumps(rec))
    for s in (2, 3):
        (d / f"sh{s}").mkdir()
        for f in ("design.blif", "vatoms.json", "affinity.tsv"):
            (d / f"sh{s}" / f).write_text((sh / f).read_text())
        (d / f"sh{s}" / "run-abcdef0123").mkdir()
    # stock packing: l0,q0,l1 in clb 0; q1 split off with l2,q2 into clb 1; the rest of cluster 1 in clb 2
    net = """<block name="t">
 <block name="a" instance="clb[0]"><block name="l0" instance="lut"/><block name="q0"/><block name="l1"/></block>
 <block name="b" instance="clb[1]"><block name="l2"/><block name="q2"/><block name="q1"/></block>
 <block name="c" instance="clb[2]"><block name="l3"/><block name="q3"/><block name="d0"/><block name="e0"/><block name="gnd"/></block>
</block>"""
    for s in (1, 2, 3):
        r = d / f"sh{s}" / "run-abcdef0123"
        for v in (1, 2):
            (r / f"stock.s{v}").mkdir(parents=True)
            (r / f"stock.s{v}" / "design.net").write_text(net)
    return d


class Toy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = make_build(Path(self.tmp.name))
        self.b = sf.Build(self.d, 1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_netlist(self):
        nl = self.b.nl
        self.assertEqual(nl.count("latch"), 5)
        self.assertEqual(nl.count("comb"), 5)
        self.assertEqual(self.b.loop_edges_cut, 0)
        self.assertEqual(self.b.is_dummy, [False] * 5 + [True])

    def test_cluster_features(self):
        rows = {(r["cluster"], r["view"]): r for r in self.b.cluster_rows()}
        self.assertEqual(rows[(1, "r")]["n_vertices"], 2)
        self.assertEqual(rows[(1, "a")]["n_vertices"], 3)
        self.assertAlmostEqual(rows[(1, "r")]["real_fill"], 0.2)
        self.assertEqual(rows[(1, "a")]["dummies"], 1)
        self.assertIn("R2d2.struct.n_comb", rows[(0, "r")])
        self.assertIn("R4g.rent_lowconf", rows[(0, "r")])
        self.assertEqual(rows[(0, "r")]["R4g.rent_lowconf"], 1.0)

    def test_lut_rows_and_function_class(self):
        lr = {r["atom"]: r for r in (self.b.lut_row(n) for n in self.b.lut_nodes())}
        self.assertEqual(lr["l0"]["fn_class"], "and_or_like")
        self.assertEqual(lr["l1"]["fn_class"], "xor_like")
        self.assertEqual(lr["l3"]["fn_class"], "and_or_like")  # OR over two inputs: one zero minterm
        self.assertEqual(lr["d0"]["is_dummy"], 1)
        self.assertEqual(lr["l0"]["drives_ff"], 1)
        self.assertIn("L2d2.struct.depth", lr["l0"])

    def test_labels(self):
        lab = ss.labels(self.b, 1)
        self.assertTrue(lab["net_identical_across_seeds"])
        c0, c1 = lab["clusters"][0], lab["clusters"][1]
        self.assertEqual(c0["exact"], 0)  # q1 left the stock cluster of l0,q0,l1
        self.assertAlmostEqual(c0["purity"], 3 / 4)
        self.assertEqual(c1["exact"], 0)  # l2,q2 sit in clb 1: not exact
        self.assertAlmostEqual(c1["purity"], 5 / 7)
        self.assertAlmostEqual(lab["luts"]["l0"]["mates_kept"], 1 / 2)
        self.assertEqual(lab["seed_source"][:4], "none")

    def test_stats(self):
        x = np.array([[1.0], [2.0], [3.0], [4.0]])
        auc, rho = ss.stats_of(x, np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9]))
        self.assertAlmostEqual(auc[0], 1.0)
        self.assertAlmostEqual(rho[0], 1.0)
        q = ss.bh(np.array([0.01, 0.02, 0.5]))
        self.assertTrue(np.all(q >= np.array([0.01, 0.02, 0.5])))
        self.assertAlmostEqual(ss.holm(np.array([0.01, 0.04]))[1], 0.04)

    def test_clean_drops_degenerate(self):
        x = np.column_stack([np.r_[np.ones(98), [2.0, 3.0]], np.arange(100.0), np.zeros(100)])
        out, names = ss.clean(x.copy(), ["near_const", "ok", "const"])
        self.assertEqual(names, ["ok"])

    def test_classify(self):
        self.assertEqual(sf.classify([["-", "1"]], 1)[1], "const")
        self.assertEqual(sf.classify([["10", "1"], ["01", "1"]], 2)[1], "xor_like")
        self.assertEqual(sf.classify([["1", "1"]], 1)[1], "buf_inv")


if __name__ == "__main__":
    unittest.main()
