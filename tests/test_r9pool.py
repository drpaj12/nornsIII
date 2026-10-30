"""Round 9 pool script: the corrected N_C (counting bound on the netlist VPR packed) on small hand-made inputs, and the p-value format.
Run from the repo root: python3 tests/test_r9pool.py"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import r9pool as rp  # noqa: E402


def blif(n_lut6: int, n_small: int, chains: list) -> str:
    out = [".model t", ".inputs clk a", ".outputs o"]
    for i in range(n_lut6):
        out.append(".names " + " ".join(f"i{i}_{j}" for j in range(6)) + f" l{i}")
        out.append("1" * 6 + " 1")
    for i in range(n_small):
        out.append(f".names gnd s{i}\n1 1")
    for c, ln in enumerate(chains):
        for k in range(ln):
            cin = "gnd" if k == 0 else f"co{c}_{k - 1}"
            out.append(f".subckt adder a=x b=y cin={cin} cout=co{c}_{k} sumout=su{c}_{k}")
    out.append(".end")
    return "\n".join(out) + "\n"


class Bound(unittest.TestCase):
    def test_exact_when_nothing_extra(self):
        t = blif(40, 0, [])
        b = rp.corrected_bound(t, {"lut": 40}, set())
        self.assertEqual((b["Kc"], b["Kc_half"], b["small_luts"]), (4, 4, 0))

    def test_small_luts_add_demand(self):
        # 40 six-input LUTs fill 4 CLBs; 3 constant/buffer LUTs VPR kept: full count 43 fle -> 5 CLBs; half count 41.5 -> 5 CLBs
        t = blif(40, 3, [])
        b = rp.corrected_bound(t, {"lut": 43}, set())
        self.assertEqual((b["Kc"], b["Kc_half"], b["small_luts"]), (5, 5, 3))
        # 36 six-input + 8 small: 44 fle -> 5; half: 40 -> 4 (valid even if VPR pairs the small LUTs)
        b = rp.corrected_bound(blif(36, 8, []), {"lut": 44}, set())
        self.assertEqual((b["Kc"], b["Kc_half"]), (5, 4))

    def test_swept_adders_lower_demand(self):
        # one chain of 7 adders needs 4 fle; VPR keeps the first 4 (the tail was swept): 2 fle
        t = blif(36, 0, [7])
        kept = {f"co0_{k}" for k in range(4)}
        b = rp.corrected_bound(t, {"lut": 36}, kept)
        self.assertEqual((b["adders_swept"], b["adder_fle"], b["adder_fle_written"]), (3, 2, 4))
        self.assertEqual(b["Kc"], 4)  # 36 + 2 = 38 -> 4 (written file would give 40 -> 4 as well)
        full = rp.corrected_bound(t, {"lut": 36}, {f"co0_{k}" for k in range(7)})
        self.assertEqual((full["adders_swept"], full["adder_fle"]), (0, 4))

    def test_two_chains_counted_apart(self):
        t = blif(0, 0, [3, 3])
        names = {"co0_0", "co0_1", "co0_2", "co1_0"}
        b = rp.corrected_bound(t, {"lut": 0}, names)
        self.assertEqual((b["adder_fle"], b["adders_swept"]), (2 + 1, 2))


class Format(unittest.TestCase):
    def test_p(self):
        self.assertEqual(rp.fmt_p(0.0), "< 0.0001")
        self.assertEqual(rp.fmt_p(0.0123), "0.0123")


if __name__ == "__main__":
    unittest.main()
