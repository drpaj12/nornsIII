"""Q-N6 helpers: BLIF copy edit (copy inside the top model, sink rewired), report parsing."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import q6_dup

BLIF = ".model top\n.inputs a b\n.outputs z\n.names a b s\n11 1\n.names s a q\n10 1\n.names q z\n1 1\n.end\n.model sub\n.inputs x\n.outputs y\n.names x y\n1 1\n.end\n"


class Edit(unittest.TestCase):
    def test_copy(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "a.blif", Path(d) / "b.blif"
            src.write_text(BLIF)
            q6_dup.edit_blif(src, [("s", "s__dup1_0", "q")], dst)
            t = dst.read_text()
            self.assertIn(".names a b s__dup1_0", t)
            self.assertIn(".names s__dup1_0 a q", t)
            self.assertLess(t.index(".names a b s__dup1_0"), t.index(".end"))   # inside the first model
            b = q6_dup.Blif(src)
            self.assertEqual(b.fan["s"], 1)      # fanout one: a plain move
            self.assertEqual(b.fan["a"], 2)

    def test_parse(self):
        rpt = "#Path 1\nStartpoint: x\nPoint Incr Path\na.inpad[0] (.input)  0.000  0.000\ns.in[0] (.names)  1.5  1.5\ns.out[0] (.names)  0.2  1.7\ndata arrival time  1.7\n"
        p = q6_dup.parse_paths(rpt)
        self.assertEqual(p[0][0], 1.7)
        self.assertEqual(q6_dup.atom_of(p[0][1][1][0]), "s")


if __name__ == "__main__":
    unittest.main()
