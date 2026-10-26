"""Round-7 tests (docs/plan/round7.md). Run from the repo root with the experiment environment:
    . scripts/env.sh; $NR_PY tests/test_r7.py
Without numpy (the Loki venv has it) the file skips cleanly (exit 0, a message on stderr). No VPR run is needed."""

import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("tests/test_r7.py skipped: numpy missing; run `. scripts/env.sh; $NR_PY tests/test_r7.py`", file=sys.stderr)
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import r7lib as lib  # noqa: E402
import r7mine as mine  # noqa: E402

REPORT = """#Timing report of worst 2 path(s)
# Unit scale: 1e-09 seconds

#Path 1
Startpoint: top/a@/x/y/d.v:3.Q[0] (.latch clocked by clk)
Endpoint  : top/c@/x/y/d.v:9.D[0] (.latch clocked by clk)
Path Type : setup

Point                                       Incr      Path
-----------------------------------------------------------
clock clk (rise edge)                      0.000     0.000
clk.inpad[0] (.input)                      0.000     0.000
top/a@/x/y/d.v:3.Q[0] (.latch) [clock-to-output]   0.124     0.124
top/b@/x/y/d.v:5.in[0] (.names)            1.500     1.624
top/b@/x/y/d.v:5.out[0] (.names)           0.200     1.824
top/c@/x/y/d.v:9.D[0] (.latch)             2.000     3.824
-----------------------------------------------------------
data required time                                   -0.024
data arrival time                                    -3.824
-----------------------------------------------------------
slack (VIOLATED)                                     -3.848

#Path 2
Startpoint: top/a@/x/y/d.v:3.Q[0] (.latch clocked by clk)
Endpoint  : top/e@/x/y/d.v:11.D[0] (.latch clocked by clk)
Path Type : setup

Point                                       Incr      Path
-----------------------------------------------------------
top/a@/x/y/d.v:3.Q[0] (.latch) [clock-to-output]   0.124     0.124
top/e@/x/y/d.v:11.D[0] (.latch)            1.000     1.124
-----------------------------------------------------------
data required time                                   -0.024
data arrival time                                    -1.124
-----------------------------------------------------------
slack (VIOLATED)                                     -1.148
"""


class Stub:
    """A tiny netlist view: LUT atoms 0..n-1 chained a0 -> a1 -> ... (series), each its own net."""

    def __init__(self, n: int):
        self.design = "stub"
        self.kind = {f"a{i}": "lut" for i in range(n)}
        self.driver = {f"a{i}": f"a{i}" for i in range(n)}
        self.sinks = {f"a{i}": ([f"a{i + 1}"] if i + 1 < n else []) for i in range(n)}
        self.clock = set()
        self.ins = {f"a{i}": ([f"a{i - 1}"] if i else []) for i in range(n)}
        self.outs = {f"a{i}": [f"a{i}"] for i in range(n)}

    def terminals(self, net):
        return [self.driver[net]] + self.sinks[net]


class Flat:
    def __init__(self, atoms):
        self.atoms = atoms


class T(unittest.TestCase):
    def test_parse_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.rpt"
            p.write_text(REPORT)
            paths = lib.parse_report(p)
        self.assertEqual(len(paths), 2)
        self.assertAlmostEqual(paths[0]["arrival"], 3.824)
        self.assertAlmostEqual(paths[0]["slack"], -3.848)
        names = [n[0] for n in paths[0]["nodes"] if n[0] != "clk"]
        self.assertEqual(names[0], "top/a@/x/y/d.v:3")
        self.assertEqual(paths[0]["nodes"][-1][3], 2.0)
        pc, sl, cpd = lib.path_crit(paths)
        self.assertAlmostEqual(cpd, 3.824)
        self.assertAlmostEqual(pc["top/a@/x/y/d.v:3"], 1.0)
        self.assertAlmostEqual(pc["top/e@/x/y/d.v:11"], 1.124 / 3.824)

    def test_base_name(self):
        self.assertEqual(lib.base_name("m/x[0]@/home/u/vtr/bench/d.v:42"), "m/x[0]@d.v:42")
        self.assertEqual(lib.base_name("b3_l4"), "b3_l4")

    def test_dup_saving(self):
        paths = [{"arrival": 4.0, "slack": 0.0, "nodes": [("d", "Q", "x", 0.1), ("s", "in", "y", 1.5), ("t", "in", "y", 0.5)]},
                 {"arrival": 3.0, "slack": 0.0, "nodes": [("q", "Q", "x", 0.1), ("r", "in", "y", 0.5)]}]
        clb = {"d": 1, "s": 2, "t": 2, "q": 1, "r": 1}
        out = lib.dup_saving(paths, {"d"}, clb)
        self.assertAlmostEqual(out["cpd"], 4.0)
        self.assertAlmostEqual(out["cpd_after"], 3.0)  # path 1 loses the 1.5 hop (-> 2.5), path 2 stays 3.0
        self.assertEqual(out["paths_with_hop"], 1)
        self.assertEqual(lib.dup_saving([], set(), {})["saved"], 0.0)

    def test_fidelity(self):
        tgt = {"a": 0, "b": 0, "c": 1, "d": 1, "e": 2}
        real = {"a": 5, "b": 5, "c": 6, "d": 7, "e": 8}
        f = lib.fidelity(tgt, real)
        self.assertEqual((f["groups"], f["groups_whole"]), (2, 1))
        self.assertAlmostEqual(f["share"], 0.5)

    def test_recluster_moves_and_respects_capacity(self):
        n = 6
        view = Stub(n)
        # two CLBs at x=1 and x=2; chain a0-a1-a2-a3-a4-a5; a1 sits in the wrong CLB
        place = {"a0": (1, 1, 0, 0, "#0", "lut"), "a1": (2, 1, 0, 0, "#1", "lut"), "a2": (1, 1, 0, 0, "#0", "lut"),
                 "a3": (2, 1, 0, 0, "#1", "lut"), "a4": (2, 1, 0, 0, "#1", "lut"), "a5": (2, 1, 0, 0, "#1", "lut")}
        group, st = lib.recluster(view, Flat(place), {})
        self.assertLessEqual(st["cost_after"], st["cost_before"])
        self.assertLess(st["cost_after"], st["cost_before"])
        sizes = {}
        for a, g in group.items():
            sizes[g] = sizes.get(g, 0) + 1
        self.assertTrue(all(v <= lib.CAP_LUT for v in sizes.values()))
        self.assertEqual(set(group), set(view.kind))

    def test_recluster_capacity_blocks(self):
        view = Stub(12)
        place = {f"a{i}": (1, 1, 0, 0, "#0", "lut") for i in range(10)}
        place["a10"] = (2, 1, 0, 0, "#1", "lut")
        place["a11"] = (2, 1, 0, 0, "#1", "lut")
        group, st = lib.recluster(view, Flat(place), {})
        counts = {}
        for g in group.values():
            counts[g] = counts.get(g, 0) + 1
        self.assertTrue(all(v <= lib.CAP_LUT for v in counts.values()))

    def test_frozen_adder_clb_is_not_touched(self):
        view = Stub(4)
        view.kind["a0"] = "adder"
        place = {"a0": (1, 1, 0, 0, "#0", "adder"), "a1": (1, 1, 0, 0, "#0", "lut"), "a2": (2, 1, 0, 0, "#1", "lut"),
                 "a3": (2, 1, 0, 0, "#1", "lut")}
        group, st = lib.recluster(view, Flat(place), {})
        self.assertEqual(st["frozen_clbs"], 1)
        self.assertEqual(group["a0"], group["a1"])

    def test_d_r_sign(self):
        rng = np.random.default_rng(1)
        rel = rng.random(4000) < 0.3
        dist = np.where(rel, 2.0, 6.0) + rng.random(4000)
        ns = np.zeros(4000, dtype=np.uint8)
        self.assertLess(mine.d_r(dist, rel, ns), -0.4)
        # no relation: near zero
        self.assertLess(abs(mine.d_r(dist, rng.random(4000) < 0.3, ns)), 0.1)

    def test_affinity_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.tsv"
            lib.write_affinity(p, {"x": 7, "y": 7, "z": 9})
            back = lib.read_aff(p)
        self.assertEqual(back["x"], back["y"])
        self.assertNotEqual(back["x"], back["z"])


if __name__ == "__main__":
    unittest.main()
