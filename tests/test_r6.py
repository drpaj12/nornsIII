"""Round-6 tests (docs/plan/round6.md, Tests). Run from the repo root with the experiment environment (it needs scipy):
    . scripts/env.sh; $NR_PY tests/test_r6.py
Without scipy the file skips cleanly (exit 0, a message on stderr)."""

import hashlib
import math
import random
import sys
import unittest
from pathlib import Path

try:
    import scipy  # noqa: F401
except ImportError:
    print("tests/test_r6.py skipped: scipy missing; run `. scripts/env.sh; $NR_PY tests/test_r6.py`", file=sys.stderr)
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "scripts"))
import r5gen  # noqa: E402
import r6gen  # noqa: E402
import r6stats as st  # noqa: E402


def digest(name):
    return hashlib.sha256(r6gen.verilog(r6gen.build_spec(name)).encode()).hexdigest()


def lns(r, n, jitter=0.0, seed=1):
    """n values with mean exactly ln r (alternating signs, jittered magnitudes)."""
    rnd = random.Random(seed)
    half = [rnd.uniform(0.2, 1.0) * jitter for _ in range(n // 2)]
    d = [x for h in half for x in (h, -h)] + ([0.0] if n % 2 else [])
    return [math.log(r) + x for x in d]


class Gen(unittest.TestCase):
    def test_deterministic_and_seed(self):
        n = "r6_mesh_a50_16"
        self.assertEqual(digest(n), digest(n))
        old = r6gen.SEED
        r6gen.SEED = old + 1
        try:
            self.assertNotEqual(digest(n), hashlib.sha256(b"").hexdigest())
            self.assertNotEqual(r6gen.layout(n), self._layout_old(n, old))
        finally:
            r6gen.SEED = old

    @staticmethod
    def _layout_old(n, old):
        cur = r6gen.SEED
        r6gen.SEED = old
        try:
            return r6gen.layout(n)
        finally:
            r6gen.SEED = cur

    def test_layouts_are_bijections_and_monotone(self):
        for topo in r6gen.TOPOLOGIES:
            for b in r6gen.SIZES:
                pur = []
                for lv in r6gen.LEVELS:
                    n = f"r6_{topo}_a{lv}_{b}"
                    slot = r6gen.layout(n)
                    flat = [tuple(x) for blk in slot for x in blk]
                    self.assertEqual(len(set(flat)), 10 * b, n)
                    self.assertEqual(set(flat), {(w, p) for w in range(b) for p in range(10)}, n)
                    disp = [sum(1 for i, x in enumerate(blk) if tuple(x) != (k, i)) for k, blk in enumerate(slot)]
                    self.assertLessEqual(max(disp) - min(disp), 2, n)
                    pur.append(r6gen.designed_alignment(slot)["purity"])
                self.assertEqual(pur[-1], 1.0)
                self.assertLessEqual(pur[0], 0.11)
                self.assertEqual(pur, sorted(pur))

    def test_logic_equals_round5_dp(self):
        spec = r6gen.build_spec("r6_tree_a25_32")
        ref = r5gen.build_spec("r5_tree_dp_32")
        self.assertEqual(spec["blocks"], ref["blocks"])
        self.assertEqual(spec["edges"], ref["edges"])
        self.assertEqual(spec["designed_cut"], ref["designed_cut"])

    def test_verilog_has_no_bus_inside_blocks_and_b_word_vectors(self):
        text = r6gen.verilog(r6gen.build_spec("r6_mesh_a0_16"))
        self.assertEqual(text.count("wire [9:0] w"), 16)
        self.assertNotIn("reg [9:0]", text)
        self.assertNotIn("output [9:0]", text)


class Keep(unittest.TestCase):
    """The keep rule flags a perturbed LUT count (k1) and a word file that covers too few flip-flops (k5)."""

    def test_k1_and_k5(self):
        import tempfile
        import nornlib as nl
        import r5lib as rl
        import r5nl
        import r6
        spec = r5gen.build_spec("r5_chain_dp_8")
        text = r5nl.blif(spec)
        old = nl.RUNS
        tmp = tempfile.mkdtemp(prefix="nr6-", dir="/tmp/claude-1000")
        if True:
            nl.RUNS = Path(tmp)
            try:
                d = "t6"
                spec["name"] = d
                nl.ensure_dir(rl.src_dir(d))
                nl.write_json(rl.src_dir(d) / "spec.json", spec)
                out = nl.runs_dir(d, "netlist", f"{d}.blif")
                nl.ensure_dir(out.parent)
                out.write_text(text, encoding="utf-8")
                self.assertTrue(rl.keep_check(d)["k1"])
                lines = text.split("\n")
                i = next(j for j, x in enumerate(lines) if x.startswith(".names") and x.endswith(" b0_l0"))
                k = i + 1
                while not lines[k].startswith("."):
                    k += 1
                out.write_text("\n".join(lines[:i] + lines[k:]), encoding="utf-8")
                rec = rl.keep_check(d)
                self.assertFalse(rec["k1"])
                self.assertFalse(rec["kept"])
            finally:
                nl.RUNS = old
        self.assertTrue(r6.k5_ok(0.90))
        self.assertFalse(r6.k5_ok(0.89))


class Rules(unittest.TestCase):
    def test_keep(self):
        ds = {f"d{i}": f"g{i % 3}" for i in range(30)}
        self.assertEqual(st.decide_keep6({d: True for d in ds}, ds)["status"], "supported")
        self.assertEqual(st.decide_keep6({d: i < 24 for i, d in enumerate(ds)}, ds)["status"], "inconclusive")
        self.assertEqual(st.decide_keep6({d: i < 10 for i, d in enumerate(ds)}, ds)["status"], "not supported")
        # >= 90% kept but a group with < 5 kept is inconclusive
        flags = {d: not (g == "g0" and i > 3) for i, (d, g) in enumerate(ds.items())}
        self.assertEqual(st.decide_keep6(flags, {d: ("g0" if g == "g0" else g) for d, g in ds.items()})["status"] != "supported", True)

    def test_align(self):
        lv = [0, 25, 50, 75, 100] * 6
        good = [{0: .1, 25: .26, 50: .5, 75: .75, 100: 1.0}[x] for x in lv]
        self.assertEqual(st.decide_align(lv, good)["status"], "supported")
        bad = [0.9 for _ in lv]
        self.assertEqual(st.decide_align(lv, [0.9 + 0.001 * i for i in range(len(lv))])["status"], "not supported")
        self.assertEqual(st.decide_align(lv, bad)["status"], "inconclusive")  # constant -> rho undefined
        mid = [{0: .1, 25: .26, 50: .5, 75: .75, 100: .9}[x] for x in lv]
        self.assertEqual(st.decide_align(lv, mid)["status"], "inconclusive")

    def test_repro_room_reused(self):
        self.assertEqual(st.s5.decide_repro([1.0] * 20)["status"], "supported")
        self.assertEqual(st.s5.decide_repro([0.8] * 20)["status"], "not supported")
        self.assertEqual(st.s5.decide_repro([1.0] * 17 + [0.9] * 3)["status"], "inconclusive")
        self.assertEqual(st.s5.decide_room({"WL": lns(1.2, 14, 0.02)})["WL"]["status"], "supported")
        self.assertEqual(st.s5.decide_room({"WL": lns(1.0, 14, 0.005)})["WL"]["status"], "not supported")
        self.assertEqual(st.s5.decide_room({"WL": lns(1.1, 14, 0.4)})["WL"]["status"], "inconclusive")
        self.assertEqual(st.s5.decide_room({"WL": lns(1.2, 5, 0.02)})["WL"]["status"], "inconclusive (n too small)")

    def test_leak(self):
        d = lambda v: st.decide_leak({"WL": v})["WL"]["status"]  # noqa: E731
        self.assertEqual(d(lns(0.85, 14, 0.02)), "supported")
        self.assertEqual(d(lns(1.0, 14, 0.005)), "not supported")
        self.assertEqual(d(lns(0.97, 14, 0.3)), "inconclusive")
        self.assertEqual(d(lns(0.85, 6, 0.02)), "inconclusive (n too small)")
        # geometric mean passes (0.95 or less) but the p value does not: a big spread around a low mean, signs mixed
        v = lns(0.94, 14, 0.0)
        v = [x + (0.6 if i % 2 else -0.6) for i, x in enumerate(v)]
        self.assertEqual(d(v), "inconclusive")

    def test_benefit_all_statuses_and_holm(self):
        r = st.decide_benefit({0: lns(0.9, 14, 0.02), 25: lns(1.05, 14, 0.02), 50: lns(0.995, 14, 0.2), 75: lns(0.9, 5, 0.02)})
        self.assertEqual(r["0"]["status"], "supported")
        self.assertEqual(r["25"]["status"], "not supported")
        self.assertEqual(r["50"]["status"], "inconclusive")
        self.assertEqual(r["75"]["status"], "inconclusive (n too small)")

    def test_hurt(self):
        # H35 reachability: n too small, and gm >= 1.02 with the Holm p failing
        self.assertEqual(st.decide_hurt({0: lns(1.08, 5, 0.02)})["0"]["status"], "inconclusive (n too small)")
        v = [x + (0.6 if i % 2 else -0.6) for i, x in enumerate(lns(1.05, 14, 0.0))]
        self.assertEqual(st.decide_hurt({0: v})["0"]["status"], "inconclusive")
        r = st.decide_hurt({0: lns(1.08, 14, 0.02), 25: lns(0.95, 14, 0.01), 50: lns(1.015, 14, 0.2)})
        self.assertEqual(r["0"]["status"], "supported")
        self.assertEqual(r["25"]["status"], "not supported")
        self.assertEqual(r["50"]["status"], "inconclusive")

    def test_dose(self):
        def cells(slope, n=14, noise=0.01, seed=3):
            rnd = random.Random(seed)
            out = {}
            for c in range(n):
                out[f"c{c}"] = [(a, slope * a + rnd.uniform(-noise, noise)) for a in (0.1, 0.3, 0.5, 0.75, 1.0)]
            return out
        self.assertEqual(st.decide_dose({"WL": cells(-0.2)})["WL"]["status"], "supported")
        self.assertEqual(st.decide_dose({"WL": cells(0.0)})["WL"]["status"], "not supported")
        self.assertEqual(st.decide_dose({"WL": cells(-0.06)})["WL"]["status"], "inconclusive")
        self.assertEqual(st.decide_dose({"WL": cells(-0.2, n=5)})["WL"]["status"], "inconclusive (n too small)")
        # slope strong in the median but the Wilcoxon cannot reach 0.05 after Holm over 3 metrics when the others are flat
        # H36: median slope strong but fewer than 70% of the cells negative -> not "supported"
        mixed = {c: pts for c, pts in cells(-0.2).items()}
        flip = {c: [(a, -y) for a, y in pts] for c, pts in list(mixed.items())[:6]}
        mixed.update(flip)
        self.assertEqual(st.decide_dose({"WL": mixed})["WL"]["status"], "inconclusive")
        r = st.decide_dose({"WL": cells(-0.2), "CLB": cells(0.0, seed=5), "CPD": cells(0.0, seed=7)})
        self.assertEqual(r["WL"]["status"], "supported")

    def test_control(self):
        # H37 not supported by the gm >= 1.03 branch (the harm side, as observed on chain)
        self.assertEqual(st.decide_control(lns(1.10, 35, 0.01))["status"], "not supported")
        self.assertEqual(st.decide_control(lns(1.0, 35, 0.005))["status"], "supported")
        self.assertEqual(st.decide_control(lns(0.9, 35, 0.01))["status"], "not supported")
        self.assertEqual(st.decide_control(lns(1.0, 35, 0.2))["status"], "inconclusive")
        self.assertEqual(st.decide_control(lns(1.0, 5, 0.005))["status"], "inconclusive (n too small)")


if __name__ == "__main__":
    unittest.main()
