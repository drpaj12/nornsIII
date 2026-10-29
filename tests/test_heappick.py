"""Tests of the heap-picking helpers (scripts/heappick_lib.py, heappick_run.py aggregation helpers).
Run from the repo root: python3 tests/test_heappick.py"""
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import heap_lib as hl  # noqa: E402
import heappick_lib as pl  # noqa: E402


def write(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False)
    f.write(text)
    f.close()
    return f.name


CENSUS = "\n".join([
    "M\t1\t0\tseed\t0\t1\t0\t0\t0\t1\t-1\ta",
    "A\t1\t0\ta\t0\t0\t0\t0",
    "P\t1\ta\tn0\t0.95",
    "Q\t1\tb\t1\t0.5",
    "Q\t1\tc\t1\t0.5",
    "Q\t1\td\t3\t0.2",
    "M\t1\t1\tcand\t1\t1\t0.5\t0\t0\t1\t-1\tb",
    "A\t1\t1\tb\t0\t0\t0.4\t0.5",
    "F\t1\tc\t1\t1",
    "K\t1\t2\t1\t1",
    "M\t2\t0\tseed\t0\t1\t0\t0\t0\t1\t-1\td",
    "A\t2\t0\td\t0\t0\t0\t0",
    "",
])


class Census(unittest.TestCase):
    def test_parse(self):
        c = pl.parse_census_full(write(CENSUS))
        self.assertEqual(len(c["mols"]), 3)
        self.assertEqual(c["mols"][1]["atoms"], ["b"])
        self.assertEqual(c["fails"], [(8, 1, "c", 1, 1)])
        self.assertIn(1, c["closed"])
        self.assertNotIn(2, c["closed"])  # cluster 2 never closed
        self.assertEqual(c["pins"][(1, "a")], [("n0", 0.95)])

    def test_molecule_of_closed_only(self):
        c = pl.parse_census_full(write(CENSUS))
        mol = pl.molecule_of(c)
        self.assertEqual(set(mol), {"a", "b"})  # d is in an unclosed cluster


class Ties(unittest.TestCase):
    def test_tie_events(self):
        c = pl.parse_census_full(write(CENSUS))
        evs = pl.tie_events(c["events"])
        self.assertEqual(len(evs), 1)  # only b is a candidate pick with another molecule pending
        e = evs[0]
        self.assertEqual(e["root"], "b")
        self.assertTrue(e["is_top"])
        self.assertAlmostEqual(e["second"], 0.5)  # c and b both 0.5: exact tie
        self.assertEqual(e["tied"][0.0], ["c"])
        self.assertEqual(e["tied"][0.05], ["c"])

    def test_not_top(self):
        ev = [(0, "Q", 1, "x", 1, 0.9), (1, "Q", 1, "y", 1, 0.3), (2, "M", 1, "y", 1, 0.3)]
        e = pl.tie_events(ev)[0]
        self.assertFalse(e["is_top"])  # a better molecule was pending (the queue was cleared or the molecule is not eligible)


class Paths(unittest.TestCase):
    loc = {"a": (0, 0), "b": (0, 1), "c": (1, 0), "d": (1, 1), "e": (0, 2)}
    typ = {"a": "ff", "b": "lut", "c": "lut", "d": "ff", "e": "lut"}

    def test_cores_drop_launch_ff_and_split_at_pads(self):
        subs = pl.path_cores(["a", "b", "HARD", "c", "d"], self.loc, self.typ)
        self.assertEqual(subs, [["b"], ["c", "d"]])

    def test_segments_count_returns(self):
        segs = pl.segments(["b", "c", "e"], self.loc)
        self.assertEqual([s[0] for s in segs], [0, 1, 0])

    def test_floor(self):
        self.assertEqual(pl.path_floor(1), 1)
        self.assertEqual(pl.path_floor(10), 1)
        self.assertEqual(pl.path_floor(11), 2)
        self.assertEqual(pl.path_floor(11, 20), 1)
        self.assertEqual(pl.path_floor(0), 1)


class Cause(unittest.TestCase):
    def ctx(self, fles0=10, fail=None, queued=None):
        return {"loc": {"u": (0, 0), "v": (1, 0)}, "cseq_of_clb": {0: 1, 1: 2}, "fles": {0: fles0, 1: 3},
                "root": {"u": "u", "v": "v"}, "fail": fail or {}, "queued": queued or set()}

    def test_full_wins_even_if_refused(self):
        self.assertEqual(pl.crossing_cause("u", "v", self.ctx(fail={(1, "v"): 1})), ("full", True))

    def test_full(self):
        self.assertEqual(pl.crossing_cause("u", "v", self.ctx()), ("full", False))

    def test_refused_when_not_full(self):
        self.assertEqual(pl.crossing_cause("u", "v", self.ctx(8, fail={(1, "v"): 2})), ("refused_route", True))
        self.assertEqual(pl.crossing_cause("u", "v", self.ctx(8, fail={(1, "v"): 1}))[0], "refused_pins")

    def test_queued_and_not_proposed(self):
        self.assertEqual(pl.crossing_cause("u", "v", self.ctx(8, queued={(1, "v")}))[0], "queued_not_taken")
        self.assertEqual(pl.crossing_cause("u", "v", self.ctx(8))[0], "not_proposed")

    def test_earlier_cluster_is_read(self):
        c = self.ctx(8)
        c["cseq_of_clb"] = {0: 5, 1: 2}  # v's cluster is the earlier one: it has 3 fles, so not full; u is the atom left behind
        c["queued"] = {(2, "u")}
        self.assertEqual(pl.crossing_cause("u", "v", c)[0], "queued_not_taken")


BLIF = """.model m
.inputs a[0] a[1] en
.outputs q[0]
.names a[0] en x
11 1
.names x y
1 1
.names y z
1 1
.latch z q[0] re clk 0
.names a[1] x w
11 1
.latch w r re clk 0
.end
"""


class Netlist(unittest.TestCase):
    def test_fanout(self):
        fo = pl.net_fanout(BLIF)
        self.assertEqual(fo["x"], 2)  # the buffer 'y' input and w
        self.assertEqual(fo["en"], 1)

    def test_adjacency_and_ties(self):
        g = hl.parse_blif_graph(BLIF)
        fo = pl.net_fanout(BLIF)
        succ, pred = pl.build_adjacency(g, fo, hl._resolve)
        # x feeds w; the buffers y and z are absorbed, so x also feeds the latch q[0]; w feeds latch r
        self.assertIn("w", succ["x"])
        self.assertIn("q[0]", succ["x"])
        self.assertEqual(pl.pair_tied("x", "w", succ, pred), (True, True))
        # q[0] and r: both fed through x->? q[0]'s pred x, r's pred w; x->w->r so x and r are two apart
        self.assertEqual(pl.pair_tied("x", "r", succ, pred), (True, True))
        # q[0] and w share a source x: tied only in the 'any' sense
        self.assertEqual(pl.pair_tied("q[0]", "w", succ, pred), (False, True))

    def test_hub_rule(self):
        g = hl.parse_blif_graph(BLIF)
        fo = pl.net_fanout(BLIF)
        succ, _pred = pl.build_adjacency(g, fo, hl._resolve, hub=1)  # x has 2 sinks: above a hub of 1, no edge from x
        self.assertNotIn("x", succ)


class Sampling(unittest.TestCase):
    def test_all_pairs(self):
        self.assertEqual(len(pl.sample_pairs(list("abcd"), 100, random.Random(1))), 6)

    def test_sampled_distinct(self):
        p = pl.sample_pairs(list(range(50)), 100, random.Random(1))
        self.assertEqual(len(p), 100)
        self.assertEqual(len({tuple(sorted(x)) for x in p}), 100)


class Auc(unittest.TestCase):
    def test_auc(self):
        self.assertEqual(pl.auc([3, 4], [1, 2]), 1.0)
        self.assertEqual(pl.auc([1, 2], [3, 4]), 0.0)
        self.assertEqual(pl.auc([1], [1]), 0.5)
        self.assertIsNone(pl.auc([], [1]))


NET = """<block name="x.net" instance="FPGA_packed_netlist[0]">
\t<block name="a" instance="clb[0]" mode="default">
\t\t<block name="a" instance="fle[0]" mode="n2_lut5">
\t\t\t<block name="a" instance="lut[0]">
\t\t\t</block>
\t\t\t<block name="b" instance="ff[0]"/>
\t\t</block>
\t\t<block name="open" instance="fle[1]" mode="n2_lut5">
\t\t</block>
\t\t<block name="c" instance="fle[2]" mode="n2_lut5">
\t\t\t<block name="c" instance="adder[0]">
\t\t\t</block>
\t\t</block>
\t</block>
\t<block name="p" instance="io[0]" mode="inpad">
\t\t<block name="p" instance="inpad[0]">
\t\t</block>
\t</block>
</block>
"""


class NetFile(unittest.TestCase):
    def test_parse(self):
        loc, clbs, others = pl.parse_net_clusters(write(NET))
        self.assertEqual(loc["a"], (("clb", 0), 0))
        self.assertEqual(loc["b"], (("clb", 0), 0))
        self.assertEqual(loc["c"], (("clb", 0), 2))
        self.assertEqual(clbs[("clb", 0)]["fles"], 2)  # the 'open' fle is not counted
        self.assertIn(("io", 0), others)


if __name__ == "__main__":
    unittest.main()
