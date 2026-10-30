"""Q-N3b: unit test of the 2-hop index header (packer/vpr/src/pack/norns_twohop.h) on a tiny netlist, compiled with g++."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "packer" / "tests" / "twohop_test.cpp"


@unittest.skipUnless(shutil.which("g++"), "g++ not found")
class TwoHopTest(unittest.TestCase):
    def test_members_2hop_tiny_netlist(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / "twohop_test"
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Werror", "-o", str(exe), str(SRC)], check=True)
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
