"""Run-record writer tests (scripts/runrecord.py, stdlib only). Run from the repo root:
    python3 tests/test_runrecord.py
No VPR or nextpnr run is needed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runrecord as rr  # noqa: E402

VPR_LOG = """VPR FPGA Placement and Routing.
VPR was run with the following command-line:
vpr a b --seed 3

VPR was run with the following options:

netlist_opts.absorb_buffer_luts            : true
router_opts.router_heap: FOUR_ARY_HEAP
router_opts.routing_failure_predictor = SAFE

Circuit file: x.blif
"""
SRC = """    place_grp.add_argument(args.seed, "--seed")
        .help("seed")
        .default_value("1")
"""
TIME_V = "\tElapsed (wall clock) time (h:mm:ss or m:ss): 1:02.50\n\tMaximum resident set size (kbytes): 2048\n"


class HostAlias(unittest.TestCase):
    def test_alias_stable_appended_and_unmapped(self):
        with tempfile.TemporaryDirectory() as d:
            m = str(Path(d) / "hosts.toml")
            self.assertEqual(rr.host_alias("alpha", ""), rr.UNMAPPED)
            self.assertEqual(rr.host_alias("alpha", m), "host-1")
            self.assertEqual(rr.host_alias("ALPHA", m), "host-1")  # stable, case-insensitive
            self.assertEqual(rr.host_alias("beta", m), "host-2")
            self.assertEqual(rr.host_alias("alpha", m), "host-1")
            self.assertEqual(len(Path(m).read_text().splitlines()), 2)


class Parsing(unittest.TestCase):
    def test_time_and_options(self):
        self.assertEqual(rr.parse_time_v(TIME_V), (62.5, 2.0))
        self.assertEqual(rr.cmd_options(["--a", "1", "2", "--b"]), [("a", ["1", "2"]), ("b", [])])

    def test_default_read_from_source_with_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "read_options.cpp"
            p.write_text(SRC)
            self.assertEqual(rr.option_default(p, "--seed"), ("1", "1-3"))
            self.assertEqual(rr.line_of(p, ".default_value"), 3)
            self.assertIsNone(rr.option_default(p, "--nope"))


class Recorder(unittest.TestCase):
    def make(self, d: Path) -> rr.RunRecorder:
        (d / "run").mkdir()
        (d / "run" / "vpr.out").write_text(VPR_LOG)
        src = d / "read_options.cpp"
        src.write_text(SRC)
        r = rr.RunRecorder("norns-placers-t", "dsn", "vpr_sa", 3, "annealing", "arch1", roots={"run": d / "run"},
                           roles={d / "x.blif": "<blif>"})
        argv = [str(d / "vpr"), str(d / "arch.xml"), str(d / "x.blif"), "--seed", "3", "--write_flat_place", str(d / "run" / "f.place")]
        r.add_step("vpr", argv, 0, 1.5, 100.0)
        r.add_vpr_params(argv, d / "run" / "vpr.out", src, "vtr-tree")
        return r

    def test_record_has_params_with_sources_and_no_absolute_paths(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t).resolve()
            r = self.make(d)
            r.write(d / "run" / "mimir-run.json")
            rec = json.loads((d / "run" / "mimir-run.json").read_text())
            self.assertEqual(rec["record_version"], 1)
            self.assertEqual(rec["steps"][0]["argv"][2:], ["<blif>", "--seed", "3", "--write_flat_place", "<run>/f.place"])
            p = rec["params"]
            self.assertEqual(p["run.seed"]["value"], "3")
            self.assertEqual(p["run.seed_default"], {"value": "1", "conf": "default", "source": "vtr-tree vpr/src/base/read_options.cpp:1-3"})
            self.assertEqual(p["vpr.router_opts.routing_failure_predictor"]["value"], "SAFE")  # `=` echo lines count
            self.assertEqual(p["vpr.netlist_opts.absorb_buffer_luts"]["source"].split(" ")[0], "vpr.out:7")
            self.assertTrue(all(v["source"] for v in p.values()))
            self.assertNotIn(str(d), json.dumps(rec))

    def test_private_string_refuses_to_write(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t).resolve()
            r = self.make(d)
            r.param("x.y", "v", "given", "read from /ho" + "me/someone/file")  # built from parts: no literal home path here
            with self.assertRaises(ValueError):
                r.write(d / "run" / "mimir-run.json")
            self.assertFalse((d / "run" / "mimir-run.json").exists())
            self.assertTrue(rr.private_strings())  # the home directory is always in the list


if __name__ == "__main__":
    unittest.main()
