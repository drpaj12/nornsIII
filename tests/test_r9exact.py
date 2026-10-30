"""Round 9 stage 3a tests: the per-cluster netlists of scripts/r9exact.py partition the logic statements, nets that cross a cluster
boundary become pads (inputs on the reader's side, outputs on the driver's side), and the clock stays out of the pad list.
No VPR binary is needed. Run from the repo root: python3 tests/test_r9exact.py"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import r9exact as ex  # noqa: E402

BLIF = """.model t
.inputs CLK a b c
.outputs q2
.names a b l0
11 1
.latch l0 q0 re CLK 2
.names q0 c l1
11 1
.latch l1 q1 re CLK 2
.names q1 a l2
11 1
.latch l2 q2 re CLK 2
.end
"""
AFF = "l0\t0\nq0\t0\nl1\t1\nq1\t1\nl2\t1\nq2\t1\n"


class ClusterBlifs(unittest.TestCase):
    def test_split(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            b, a = Path(d) / "t.blif", Path(d) / "t.aff"
            b.write_text(BLIF)
            a.write_text(AFF)
            cb = ex.cluster_blifs(b, a, set())
        self.assertEqual(sorted(cb), [0, 1])
        c0, c1 = cb[0], cb[1]
        self.assertIn(".inputs CLK a b", c0)  # clock first, then the nets from outside
        self.assertIn(".outputs q0", c0)  # q0 is read by cluster 1
        self.assertNotIn("l1", c0)
        self.assertIn(".inputs CLK a c q0", c1)
        self.assertIn(".outputs q2", c1)  # a primary output
        self.assertNotIn(".names a b l0", c1)

    def test_dangling_adder_sumout_is_no_pad(self) -> None:
        blif = (".model t\n.inputs CLK a\n.outputs o\n.names a o\n1 1\n"
                ".subckt adder a=a b=gnd cin=gnd cout=c1 sumout=s0\n.subckt adder a=a b=gnd cin=c1 cout=c2 sumout=s1\n.end\n")
        with tempfile.TemporaryDirectory() as d:
            b, a = Path(d) / "t.blif", Path(d) / "t.aff"
            b.write_text(blif)
            a.write_text("o\t0\nc1\t0\nc2\t0\n")
            cb = ex.cluster_blifs(b, a, set())[0]
        outs = next(ln for ln in cb.splitlines() if ln.startswith(".outputs")).split()[1:]
        self.assertEqual(outs, ["o"])  # s0, s1 and c2 are dangling: VPR leaves the pins open

    def test_inputs_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            net = Path(d) / "x.net"
            net.write_text('<block name="x" instance="FPGA_packed_netlist[0]"><block name="m" instance="clb[0]">'
                           '<inputs><port name="I">a b open</port></inputs></block></block>')
            self.assertTrue(ex.inputs_ok(net, ".model m\n.inputs CLK a b\n"))
            self.assertFalse(ex.inputs_ok(net, ".model m\n.inputs CLK a b c\n"))


if __name__ == "__main__":
    unittest.main()
