"""Round 9 tests (docs/plan/round9-tpeko-real.md, Stage 1): the CLB bound is exact on a toy, the cut is the one recomputed from
the written BLIF, the margin holds and an independent partitioner finds nothing better, and the shuffles are deterministic and
only rename and reorder. VPR is replaced by a stub (the clustering is given), so nothing here needs a VPR binary.
Run from the repo root: python3 tests/test_r9.py   (the METIS test skips without pymetis; use the Mimir venv python to run it)."""

import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import r9build as rb  # noqa: E402


def toy_blif(n: int = 34, seed: int = 5) -> str:
    rnd = random.Random(seed)
    pis = [f"p{i}" for i in range(12)]
    out = [".model toy", ".inputs clk " + " ".join(pis), ".outputs " + " ".join(f"q{i}" for i in range(n - 4, n))]
    pool = list(pis)
    for i in range(n):
        k = rnd.choice([2, 3, 4, 5])
        ins = rnd.sample(pool, k)
        out.append(".names " + " ".join(ins) + f" l{i}")
        out.append("1" * k + " 1")
        out.append(f".latch l{i} q{i} re clk 2")
        pool.append(f"q{i}")
    out.append(".end")
    return "\n".join(out) + "\n"


def build_toy(tmp: Path, n: int = 34, per: int = 8):
    cb = rb.clean(rb.parse_blif(toy_blif(n)))
    atom_cl = {}
    for i in range(n):
        atom_cl[f"l{i}"] = i // per
        atom_cl[f"q{i}"] = i // per

    saved = (rb.run_vpr_pack, rb.read_net)
    rb.run_vpr_pack = lambda blif, outdir, affinity=None: tmp / "stub.net"
    rb.read_net = lambda path: (atom_cl, {"lut": len(cb.luts), "ff": len(cb.ffs), "adder": 0})
    try:
        rec = rb.build_from("toy", cb, tmp / "toy.clean.blif", "own", tmp, False, 0, 0, 1)
    finally:
        rb.run_vpr_pack, rb.read_net = saved
    return rec


def cut_from_blif(path: Path, aff_path: Path) -> tuple:
    """Cut recomputed from the written file alone: atoms to clusters from the affinity file; pads are their own clusters."""
    b = rb.parse_blif(path.read_text())
    aff = {}
    for line in aff_path.read_text().splitlines():
        a, c = line.split("\t")
        aff[a] = int(c)
    pins: dict = {}
    for o, (ins, _tt) in b.luts.items():
        pins.setdefault(o, set()).add(("L", aff[o]))
        for x in ins:
            pins.setdefault(x, set()).add(("L", aff[o]))
    for q, d in b.ffs.items():
        pins.setdefault(q, set()).add(("L", aff[q]))
        pins.setdefault(d, set()).add(("L", aff[q]))
    for x in b.inputs:
        if x != b.clk:
            pins.setdefault(x, set()).add(("pad", x))
    for x in b.outputs:
        pins.setdefault(x, set()).add(("pad", x))
    # the LUT-to-flip-flop net of a cell is private: both its pins sit in one cluster
    cut = sum(1 for n, p in pins.items() if n != b.clk and n not in rb.CONST and len(p) > 1)
    return cut, b


def txt_of(path: Path) -> str:
    return path.read_text()


class Toy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rec = build_toy(cls.tmp)
        cls.g, cls.cl = cls.rec["_graph"]

    def test_clb_bound_exact(self):
        r = self.rec
        self.assertTrue(r["full_clusters"])
        self.assertEqual(r["demand_padded"], 10 * r["K"])
        self.assertEqual(r["clb_lower_bound"], r["K"])  # ceil(demand / 10) = number of clusters of C
        self.assertTrue(r["all_luts_6"])
        self.assertTrue(r["distinct_inputs"])
        self.assertGreaterEqual(r["K"], 4)  # 34 cells at 9 per cluster
        self.assertLessEqual(r["max_pins"], rb.MAX_IN)

    def test_cut_matches_written_file_and_margin(self):
        sh = rb.write_shuffled(self.g, self.cl, self.g.des, self.tmp / "s1", 1, "toy", "own")
        cut, _b = cut_from_blif(self.tmp / "s1" / sh["blif"], self.tmp / "s1" / "affinity.tsv")
        self.assertEqual(cut, self.rec["cut_C"])
        self.assertGreaterEqual(self.rec["margin"]["min_adjacent_swap_delta"], 1)
        self.assertEqual(self.rec["margin"]["swaps_le_0_other"], 0)

    def test_independent_partitioner_finds_nothing_better(self):
        try:
            import pymetis  # noqa: F401
        except ImportError:
            self.skipTest("pymetis missing")
        res = rb.independent_check(self.g, self.cl, self.rec["K"], 30, 30, "toy")
        self.assertFalse(res["below_C_found"])

    def test_shuffle_determinism_and_structure(self):
        a = rb.write_shuffled(self.g, self.cl, self.g.des, self.tmp / "a", 1, "toy", "own")
        b = rb.write_shuffled(self.g, self.cl, self.g.des, self.tmp / "b", 1, "toy", "own")
        c = rb.write_shuffled(self.g, self.cl, self.g.des, self.tmp / "c", 2, "toy", "own")
        self.assertEqual(a["sha256"], b["sha256"])
        self.assertNotEqual(a["sha256"], c["sha256"])
        ca, ba = cut_from_blif(self.tmp / "a" / a["blif"], self.tmp / "a" / "affinity.tsv")
        cc, bc = cut_from_blif(self.tmp / "c" / c["blif"], self.tmp / "c" / "affinity.tsv")
        self.assertEqual(ca, cc)
        self.assertEqual(sorted(len(i) for i, _t in ba.luts.values()), sorted(len(i) for i, _t in bc.luts.values()))
        self.assertEqual(len(ba.ffs), len(bc.ffs))
        # no name of the original design survives (tokens p<i>, l<i>, q<i> of the toy)
        import re
        toks = set(re.findall(r"[^\s=]+", txt_of(self.tmp / "c" / c["blif"])))
        self.assertFalse([t for t in toks if re.fullmatch(r"[plq]\d+", t)])

    def test_ordered_control_is_cluster_by_cluster(self):
        o = rb.write_shuffled(self.g, self.cl, self.g.des, self.tmp / "o", 0, "toy", "own")
        aff = [int(x.split("\t")[1]) for x in (self.tmp / "o" / "affinity.tsv").read_text().splitlines()]
        self.assertEqual(len(aff), o["atoms_labelled"])
        lines = [ln for ln in (self.tmp / "o" / o["blif"]).read_text().splitlines() if ln.startswith(".names")]
        names = {}
        for line in (self.tmp / "o" / "affinity.tsv").read_text().splitlines():
            a, c = line.split("\t")
            names[a] = int(c)
        seq = [names[ln.split()[-1]] for ln in lines if ln.split()[-1] in names]
        self.assertEqual(seq, sorted(seq))


class Parts(unittest.TestCase):
    def test_cover_and_widen(self):
        c = rb.Cell(0, "L", ["a", "b"], 0b1000, "o", "o", False, 2)  # AND
        rb.widen(c, ["x", "y"])
        self.assertEqual(len(c.ins), 4)
        for m in range(16):
            a, b_, x, y = (m & 1), (m >> 1) & 1, (m >> 2) & 1, (m >> 3) & 1
            self.assertEqual((c.tt >> m) & 1, (a & b_) ^ x ^ y)  # depends on every added input

    def test_reduce_lut_drops_constants_and_duplicates(self):
        ins, tt = rb.reduce_lut(["a", "gnd", "b", "a"], rb.cover_tt(4, [("1-1-", "1")]))
        self.assertEqual(ins, ["a", "b"])

    def test_chain_segments(self):
        self.assertEqual(rb.seg_chain(5), [5])
        s = rb.seg_chain(34)
        self.assertEqual(sum(s), 34)
        self.assertTrue(all(x <= rb.CHAIN_SEG for x in s))
        self.assertTrue(all(x % 2 == 0 for x in s[:-1]))


if __name__ == "__main__":
    unittest.main()
