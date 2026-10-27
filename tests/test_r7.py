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
import r7net as rnet  # noqa: E402
import r7stats as rstats  # noqa: E402
import r7fstats as rfstats  # noqa: E402
import r7netcheck as rcheck  # noqa: E402

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

    def test_dup_candidates_logic_sinks_only(self):
        view = Stub(1)
        view.kind = {"d": "lut"}
        view.outs = {"d": ["n"]}
        view.sinks = {"n": ["s1", "out:n", "hard"]}
        # one logic CLB plus a pad and a hard block: not a candidate; counted apart
        clb = {"s1": 1, "d": 1}
        self.assertEqual(lib.dup_candidates(view, clb), [])
        self.assertEqual(lib.dup_other_sinks(view, clb, set())["other_only"], 1)
        clb = {"s1": 1, "d": 1, "s2": 2}
        view.sinks = {"n": ["s1", "s2", "out:n"]}
        self.assertEqual(lib.dup_candidates(view, clb), ["d"])
        self.assertEqual(lib.dup_other_sinks(view, clb, {"d"})["cand_with_pad_sink"], 1)

    def test_family_leave_out(self):
        self.assertEqual(mine.family("diffeq1"), mine.family("diffeq2"))
        self.assertEqual(mine.family("stereovision0"), mine.family("stereovision3"))
        self.assertNotEqual(mine.family("sha"), mine.family("boundtop"))
        self.assertEqual(mine.family("n5_mesh_dp_16"), mine.family("n5_mesh_dp_256"))
        self.assertNotEqual(mine.family("n5_mesh_dp_16"), mine.family("n5_tree_dp_16"))

    def test_recovery_threshold_and_no_forced_one(self):
        import math
        vals = {("d", "stock"): 100.0, ("d", "h"): 99.0, ("d", "known"): 98.0}

        def rd(design, arm, seed):
            return {"rc": 0, "wirelength": vals[(design, arm)]}
        r = rstats.recovery("d", "stock", "h", "known", "wirelength", (1, 2, 3), rd)
        self.assertIsNone(r["value"])  # known only 2% better: nothing to recover
        vals[("d", "known")] = 50.0
        r = rstats.recovery("d", "stock", "h", "known", "wirelength", (1, 2, 3), rd)
        self.assertAlmostEqual(r["value"], math.log(100 / 99) / math.log(2))
        # a design with no gain never enters the pooled medians
        recs = [{"design": "n5_x_16", "recovery": {"WL": {"value": None, "note": "no gain found"}, "CLB": {"value": 0.5}, "CPD": {"value": 0.5}}}]
        p = rfstats.pooled_recovery(recs)["all"]["WL"]
        self.assertIsNone(p["median"])
        self.assertEqual(p["n_nogain"], 1)

    def test_net_legality_rules(self):
        class U:
            def __init__(self, ins, outs, clk=None):
                self.in_nets, self.out_nets, self.clk = ins, outs, clk

        class M:
            units = {i: U([f"x{i}"], [f"y{i}"], "clk") for i in range(12)}
        m = M()
        self.assertTrue(rnet.legal(m, set(range(10))))
        self.assertFalse(rnet.legal(m, set(range(11))))  # 11 > 10 logic elements
        m.units[0].clk = "other"
        self.assertFalse(rnet.legal(m, {0, 1}))  # two clocks
        m.units[0].clk = "clk"
        m.units[0].in_nets = [f"e{k}" for k in range(41)]
        self.assertFalse(rnet.legal(m, {0}))  # 41 external input nets
        m.units[1].out_nets = [f"e{k}" for k in range(5)]
        self.assertTrue(rnet.legal(m, {0, 1}))  # five nets now come from unit 1: 36 + 1 external input nets
        m.units[0].in_nets = [f"e{k}" for k in range(41)][:40]
        self.assertTrue(rnet.legal(m, {0}))

    def test_net_writer_identity_and_legality(self):
        for d in ("ch_intrinsics", "n5_mesh_dp_16", "diffeq1"):
            p = rnet.stock_net_path(d)
            if not p.is_file():
                self.skipTest("runs/r7 not present")
            import gzip
            import xml.etree.ElementTree as ET
            m = rnet.load_model(p)
            for key in set(m.stock.values()):
                if key not in m.frozen_keys:
                    self.assertTrue(rnet.legal(m, {u for u, k in m.stock.items() if k == key}), (d, key))

            def canon(e):
                return (e.tag, tuple(sorted(e.attrib.items())), (e.text or "").strip(), tuple(canon(c) for c in e))
            with gzip.open(p) as fh:
                orig = ET.parse(fh).getroot()
            self.assertEqual(canon(orig), canon(rnet.build_tree(m, dict(m.stock)).getroot()))
            # a swap of two logic elements between CLBs still writes a tree with the same elements and legal CLBs
            keys = sorted(k for k in set(m.stock.values()) if k not in m.frozen_keys)
            if len(keys) >= 2:
                a = next(u for u, k in m.stock.items() if k == keys[0])
                b = next(u for u, k in m.stock.items() if k == keys[1])
                asg = dict(m.stock)
                asg[a], asg[b] = keys[1], keys[0]
                if all(rnet.legal(m, {u for u, k in asg.items() if k == kk}) for kk in keys[:2]):
                    t = rnet.build_tree(m, asg).getroot()
                    names = sorted(x.get("name") for x in t.iter("block") if x.get("instance", "").startswith("fle[") and x.get("name") != "open")
                    onames = sorted(x.get("name") for x in orig.iter("block") if x.get("instance", "").startswith("fle[") and x.get("name") != "open")
                    self.assertEqual(names, onames)

    # ---- fixture tests: a committed 3-CLB cut of the n5_mesh_dp_16 stock .net (tests/fixtures), runs on a clean clone ----

    FIXTURE = ROOT / "tests" / "fixtures" / "n5_mesh_dp_16_trim.net.gz"

    @staticmethod
    def _issues(r):
        """Nonzero problem counters of rcheck.check. E (clb input nets driven outside) is not used: the fixture is a 3-clb cut, so the
        nets of the removed clbs have no driver in it."""
        return {k: v for k, v in r.items() if isinstance(v, int) and not isinstance(v, bool) and v
                and k.startswith(("A_missing", "A_extra", "B_", "C_", "D_needed", "D_clbout_pin", "duplicate"))}

    def _swap_assign(self, m):
        """A legal swap of one fle between two different CLBs of the fixture; returns (assign, keys)."""
        keys = sorted(set(m.stock.values()))
        for i, ka in enumerate(keys):
            for kb in keys[i + 1:]:
                for a in [u for u, k in m.stock.items() if k == ka]:
                    for b in [u for u, k in m.stock.items() if k == kb]:
                        asg = dict(m.stock)
                        asg[a], asg[b] = kb, ka
                        if rnet.legal(m, {u for u, k in asg.items() if k == ka}) and rnet.legal(m, {u for u, k in asg.items() if k == kb}):
                            return asg, (ka, kb)
        self.fail("no legal swap in the fixture")

    def test_fixture_writer_pins_clbouts_and_nets_after_move(self):
        m = rnet.load_model(self.FIXTURE)
        self.assertGreater(len(m.units), 20)
        stock = rcheck.read_net(self.FIXTURE)
        base = rcheck.check(stock, None, stock)
        self.assertEqual(self._issues(base), {})
        asg, (ka, kb) = self._swap_assign(m)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "moved.net.gz"
            rnet.write_net(m, asg, out)
            moved = rcheck.read_net(out)
        r = rcheck.check(moved, None, stock)
        # every atom sees the same nets on its input pins as before the move, the clbouts pins point at fle outputs, every net read
        # outside its clb has a clbout pin, and every clb input pin is driven outside the clb
        self.assertEqual((r["C_lut_vs_stock"], r["C_ff_vs_stock"], r["C_atoms_not_in_stock"]), (0, 0, 0))
        self.assertEqual((r["D_needed_output_without_clbout"], r["D_clbout_pin_bad"]), (0, 0))

        def undriven(n):   # nets read by some clb and driven nowhere in the cut (they come from the clbs the fixture drops)
            return set().union(*n["in_nets"]) - set().union(*n["driven"]) - n["top_in"]
        self.assertEqual(undriven(moved), undriven(stock))
        self.assertEqual(moved["dup"], 0)
        self.assertEqual(sorted(moved["lut"]), sorted(stock["lut"]))
        self.assertEqual(self._issues(r), {})

    def test_fixture_writer_keeps_pins_of_the_stock_clustering(self):
        # identity on the full designs is tested above (needs runs/); on the cut, outputs read only by the dropped blocks get no
        # clbouts pin, so identity holds for everything else: input pins, fle placement and names
        import gzip
        import xml.etree.ElementTree as ET
        m = rnet.load_model(self.FIXTURE)
        with gzip.open(self.FIXTURE) as fh:
            orig = ET.parse(fh).getroot()
        new = rnet.build_tree(m, dict(m.stock)).getroot()
        for ob, nb in zip(orig.findall("block"), new.findall("block")):
            self.assertEqual(ob.get("instance"), nb.get("instance"))
            self.assertEqual([p.text for p in ob.findall("inputs/port")], [p.text for p in nb.findall("inputs/port")])
            self.assertEqual([(c.get("instance"), c.get("name")) for c in ob.findall("block")],
                             [(c.get("instance"), c.get("name")) for c in nb.findall("block")])

    def test_check_detects_a_wrong_pin_and_a_missing_clbout(self):
        import copy
        import xml.etree.ElementTree as ET
        m = rnet.load_model(self.FIXTURE)
        tree = rnet.build_tree(m, dict(m.stock))
        stock = rcheck.read_net(self.FIXTURE)

        def read(t):
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "x.net"
                t.write(p, encoding="UTF-8", xml_declaration=True)
                return rcheck.read_net(p)
        # (1) one crossbar input of one fle opened: its atoms see a different net
        t1 = ET.ElementTree(copy.deepcopy(tree.getroot()))
        port = next(p for p in t1.getroot().iter("port") if p.get("name") == "in" and "crossbar" in (p.text or ""))
        toks = port.text.split()
        toks[0] = "open"
        port.text = " ".join(toks)
        self.assertGreater(rcheck.check(read(t1), None, stock)["C_lut_vs_stock"] + rcheck.check(read(t1), None, stock)["C_ff_vs_stock"], 0)
        # (2) a clbout pin closed although the net is read in another clb of the fixture
        base = rcheck.check(read(tree), None, stock)
        self.assertEqual(self._issues(base), {})
        t2 = ET.ElementTree(copy.deepcopy(tree.getroot()))
        n_before = 0
        for clb in t2.getroot().findall("block"):
            op = next(p for p in clb.findall("outputs/port") if p.get("name") == "O")
            toks = op.text.split()
            for j, t in enumerate(toks):
                if t != "open":
                    toks[j] = "open"
                    n_before += 1
                    break
            op.text = " ".join(toks)
        self.assertGreater(rcheck.check(read(t2), None, stock)["D_needed_output_without_clbout"], 0)
        self.assertGreater(n_before, 0)

    def _stub_view_and_flat(self, m):
        """One pseudo-atom per fle unit: it reads the unit's input nets and drives its output nets; CLBs sit in a row at x = 1, 2, 3."""
        class V:
            design = "fixture"
            clock: set = set()
        v = V()
        v.kind, v.driver, v.sinks = {}, {}, {}
        v.ins, v.outs = {}, {}
        atom = {u: un.atoms[0] for u, un in m.units.items()}
        for u, un in m.units.items():
            a = atom[u]
            v.kind[a] = "lut"
            v.ins[a] = [n for n in un.in_nets if n]
            v.outs[a] = [n for n in un.out_nets if n]
            for n in v.outs[a]:
                v.driver[n] = a
        for u, un in m.units.items():
            for n in un.in_nets:
                if n:
                    v.sinks.setdefault(n, []).append(atom[u])
        v.sinks = {n: ss for n, ss in v.sinks.items() if n in v.driver}
        v.terminals = lambda net: [v.driver[net]] + v.sinks[net]
        xs = {k: i + 1 for i, k in enumerate(sorted(set(m.stock.values())))}
        flat = Flat({atom[u]: (xs[m.stock[u]], 1, 0, 0, f"#{m.stock[u]}", "lut") for u in m.units})
        return v, flat

    def test_net_recluster_capacity_and_legality(self):
        m = rnet.load_model(self.FIXTURE)
        view, flat = self._stub_view_and_flat(m)
        assign, st = rnet.recluster(m, view, dict(m.stock), flat, {})
        self.assertEqual(set(assign), set(m.units))                         # every fle placed exactly once
        self.assertEqual(len(set(m.units) & set(assign)), len(m.units))
        by = {}
        for u, k in assign.items():
            by.setdefault(k, set()).add(u)
        for k, us in by.items():
            self.assertLessEqual(len(us), rnet.CAP_FLE, k)                  # <= 10 fle
            self.assertTrue(rnet.legal(m, us), k)                           # <= 40 external input nets, one clock
        self.assertLessEqual(st["cost_after"], st["cost_before"] + 1e-9)    # greedy: never worse
        # a CLB at the capacity is never made bigger; the written tree of the result passes the equivalence check
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "r.net.gz"
            rnet.write_net(m, assign, out)
            r = rcheck.check(rcheck.read_net(out), None, rcheck.read_net(self.FIXTURE))
        self.assertEqual(self._issues(r), {}, r)

    def test_net_recluster_leaves_frozen_clbs_and_respects_full_clbs(self):
        m = rnet.load_model(self.FIXTURE)
        view, flat = self._stub_view_and_flat(m)
        full = [k for k in set(m.stock.values()) if sum(1 for kk in m.stock.values() if kk == k) == rnet.CAP_FLE]
        assign, _ = rnet.recluster(m, view, dict(m.stock), flat, {})
        for k in full:
            self.assertLessEqual(sum(1 for kk in assign.values() if kk == k), rnet.CAP_FLE)
        m.frozen_keys = set(m.stock.values())    # everything frozen: nothing may move
        assign2, st2 = rnet.recluster(m, view, dict(m.stock), flat, {})
        self.assertEqual(assign2, dict(m.stock))
        self.assertEqual(st2["units_moved"], 0)

    def test_output_pin_cap_assert(self):
        m = rnet.load_model(self.FIXTURE)
        self.assertEqual(rnet.CAP_OUT, 20)
        # no stock clb of the fixture exceeds 20 output pins, and the written clb output port has exactly CAP_OUT tokens
        t = rnet.build_tree(m, dict(m.stock)).getroot()
        for clb in t.findall("block"):
            op = next(p for p in clb.findall("outputs/port") if p.get("name") == "O")
            self.assertEqual(len(op.text.split()), rnet.CAP_OUT)

    def test_model_loop_never_trains_on_the_held_out_family(self):
        from sklearn.preprocessing import StandardScaler
        seen = []
        orig = StandardScaler.fit

        def rec(self_, X, *a, **k):
            seen.append(np.unique(X[:, 0]).copy())     # column 0 of the baseline block carries the design id
            return orig(self_, X, *a, **k)

        class SD:
            def __init__(self, name, ident):
                self.design = name
                rng = np.random.default_rng(ident)
                self.n = 40
                self.E = np.arange(400)
                self.ident = ident
                self.y = (rng.random(400) < 0.4).astype(np.uint8)
                self.src = np.full(400, 4 | 8, dtype=np.uint8)
                self.dist5 = rng.random(400).astype(np.float32) + 1
                self.co_stock = (rng.random(400) < 0.4).astype(np.float32)
                self.co_net = self.y
                self.rng = rng

            def target(self, name):
                return self.y

            def dist_r2(self, target):
                return self.dist5

            def rel_from(self, perm, idx):
                return {f: (self.rng.random(len(idx)) < 0.5) for f in mine.HDL_FEATS}

            def base_matrix(self, idx, target="aff"):
                X = self.rng.random((len(idx), len(mine.BASE_FEATS))).astype(np.float32)
                X[:, 0] = self.ident
                return X
        ds = [SD("diffeq1", 1), SD("diffeq2", 2), SD("sha", 3), SD("boundtop", 4), SD("or1200", 5)]
        StandardScaler.fit = rec
        try:
            mine.N_SHUF_MODEL = 1
            mine.model_loop(ds, 0, "aff", ds)
        finally:
            StandardScaler.fit = orig
        self.assertTrue(seen)
        ids = {d.design: d.ident for d in ds}
        # each fit trains on every design but the held-out one and its family: the ids missing from the training block are
        # exactly {held-out id}, or both diffeq ids when a diffeq design is held out
        expected = [{ids["diffeq1"], ids["diffeq2"]}, {ids["sha"]}, {ids["boundtop"]}, {ids["or1200"]}]
        for u in seen:
            missing = set(ids.values()) - set(int(x) for x in u)
            self.assertIn(missing, expected)
        self.assertEqual({frozenset(set(ids.values()) - set(int(x) for x in u)) for u in seen}, {frozenset(e) for e in expected})

    def test_boot_ci_resamples_families(self):
        vals = [0.1, 0.1, 0.1, 0.1, 0.3]
        fam = ["a", "a", "a", "a", "b"]
        lo, hi = mine.boot_mean_ci(vals, fam)
        lo2, hi2 = mine.boot_mean_ci(vals)
        # two families: the interval over families is much wider than the interval over five designs
        self.assertGreater(hi - lo, hi2 - lo2 - 1e-12)
        self.assertTrue(np.isnan(mine.boot_mean_ci([0.1, 0.2], ["a", "a"])[0]))


if __name__ == "__main__":
    unittest.main()
