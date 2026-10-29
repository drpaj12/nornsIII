"""Tests of nornlib.keep_timing (report gz, attribution xz, blif + map kept once, off switch).
Run from the repo root: python3 tests/test_keep_timing.py
No VPR or Odin III run: the report is fake and odin3-timing is a stub script."""
import gzip
import json
import lzma
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import nornlib as nl  # noqa: E402

REPORT = "#Path 1\nPoint Incr Path\ndata arrival time 1.0\nslack (MET) 0.5\n\n#Path 2\nPoint Incr Path\ndata arrival time 0.9\n"
STUB_OK = "#!/bin/sh\nmkdir -p \"$1/timing\"\nprintf '{\"paths\": 2}' > \"$1/timing/attribution.json\"\n"
STUB_BAD = "#!/bin/sh\necho 'AttributionError: stale map' >&2\nexit 1\n"


class KeepTiming(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.vpr = self.t / "vpr"
        self.vpr.mkdir()
        (self.vpr / "report_timing.setup.rpt").write_text(REPORT)
        self.blif = self.t / "d.blif"
        self.blif.write_text(".model d\n.end\n")
        self.map = self.t / "d.blif.names"
        self.map.write_text("map\n")
        self.out = self.t / "out"
        tree = self.t / "odin" / "tools" / "flow"
        tree.mkdir(parents=True)
        self.tool = tree / "odin3-timing"
        env = {"NORNS_ODIN_TREE": str(self.t / "odin"), "NORNS_KEEP_STORE": str(self.t / "store")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("NORNS_KEEP_TIMING", None)

    def stub(self, text):
        self.tool.write_text(text)
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)

    def test_keeps_everything(self):
        self.stub(STUB_OK)
        rec = nl.keep_timing(self.out, self.vpr, "d", self.blif, self.map)
        self.assertTrue(rec["keep_timing"])
        self.assertEqual(rec["paths_kept"], 2)
        self.assertTrue(rec["attribution"])
        with gzip.open(self.out / "report_timing.setup.rpt.gz", "rt") as fh:
            self.assertEqual(fh.read(), REPORT)
        with lzma.open(self.out / "attribution.json.xz", "rt") as fh:
            self.assertEqual(json.loads(fh.read()), {"paths": 2})
        self.assertEqual(rec["blif_sha256"], nl.file_sha256(self.blif))
        self.assertEqual(rec["map_sha256"], nl.file_sha256(self.map))
        self.assertEqual(json.loads((self.out / "keep-timing.json").read_text())["paths_kept"], 2)

    def test_inputs_kept_once(self):
        self.stub(STUB_OK)
        first = nl.keep_timing(self.out, self.vpr, "d", self.blif, self.map)
        second = nl.keep_timing(self.t / "out2", self.vpr, "d", self.blif, self.map)
        self.assertIn("blif_bytes", first)
        self.assertNotIn("blif_bytes", second)  # already in the store
        self.assertEqual(first["blif_sha256"], second["blif_sha256"])
        self.assertEqual(len(list((self.t / "store" / "d").iterdir())), 1)

    def test_no_name_map_keeps_report_only(self):
        self.stub(STUB_OK)
        rec = nl.keep_timing(self.out, self.vpr, "d", self.blif, None)
        self.assertFalse(rec["attribution"])
        self.assertIn("no name map", rec["attribution_note"])
        self.assertTrue((self.out / "report_timing.setup.rpt.gz").is_file())
        self.assertFalse((self.out / "attribution.json.xz").exists())

    def test_tool_failure_is_recorded_not_raised(self):
        self.stub(STUB_BAD)
        rec = nl.keep_timing(self.out, self.vpr, "d", self.blif, self.map)
        self.assertFalse(rec["attribution"])
        self.assertIn("stale map", rec["attribution_note"])
        self.assertTrue((self.out / "report_timing.setup.rpt.gz").is_file())

    def test_paths_tokenised(self):
        vtr, ws, home = self.t / "vtrroot", self.t / "wsroot", "/home/someone"
        span = f"{vtr}/vtr_flow/benchmarks/verilog/d.v:82"
        att = json.dumps({"paths": [{"nodes": [{"span": span, "src": f"{ws}/odin3/x.v:3", "other": f"{home}/stuff/y.v:1"}]}]})
        self.tool.write_text("#!/bin/sh\nmkdir -p \"$1/timing\"\ncat > \"$1/timing/attribution.json\" <<'EOF'\n" + att + "\nEOF\n")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        self.map.write_text(f"a {span}\nb {ws}/q.v:1\nc {home}/z.v:2\n")
        self.blif.write_text(f".model d\n# {home}/gen\n.end\n")
        with mock.patch.object(nl, "VTR_ROOT", vtr), mock.patch.object(nl, "WS_ROOT", ws):
            rec = nl.keep_timing(self.out, self.vpr, "d", self.blif, self.map)
        with lzma.open(self.out / "attribution.json.xz", "rt") as fh:
            a = fh.read()
        self.assertNotIn("/home/", a)
        self.assertNotIn(str(self.t), a)
        n = json.loads(a)["paths"][0]["nodes"][0]
        self.assertEqual(n["span"], "$VTR_ROOT/vtr_flow/benchmarks/verilog/d.v:82")
        self.assertEqual(n["src"], "$WS/odin3/x.v:3")
        self.assertEqual(n["other"], "~/stuff/y.v:1")
        store = self.t / "store" / "d" / rec["blif_sha256"]
        for f in ("d.blif.names.xz", "d.blif.xz"):
            with lzma.open(store / f, "rt") as fh:
                self.assertNotIn("/home/", fh.read())
        self.assertEqual(rec["map_sha256"], nl.file_sha256(self.map))  # sha is of the original
        self.assertEqual(rec["paths_rewritten"], {"$VTR_ROOT": 2, "$WS": 2, "~": 3})
        self.assertEqual(json.loads((self.out / "keep-timing.json").read_text())["paths_rewritten"], rec["paths_rewritten"])

    def test_kept_artifacts_ignores_stale_files(self):
        self.stub(STUB_BAD)
        self.out.mkdir()
        (self.out / "attribution.json.xz").write_bytes(b"stale")  # left by an earlier attempt
        rec = nl.keep_timing(self.out, self.vpr, "d", self.blif, self.map)
        roles = [r for r, _ in nl.kept_artifacts(rec)]
        self.assertEqual(roles, ["timing_report_gz", "keep_timing"])
        self.assertEqual(nl.kept_artifacts(None), [])
        self.assertEqual(nl.kept_artifacts({"keep_timing": False}), [])
        self.stub(STUB_OK)
        rec = nl.keep_timing(self.out, self.vpr, "d", self.blif, self.map)
        self.assertIn("timing_attribution", [r for r, _ in nl.kept_artifacts(rec)])

    def test_off_switch(self):
        self.stub(STUB_OK)
        with mock.patch.dict(os.environ, {"NORNS_KEEP_TIMING": "0"}):
            rec = nl.keep_timing(self.out, self.vpr, "d", self.blif, self.map)
            self.assertEqual(rec, {"keep_timing": False})
            self.assertEqual(nl.npaths(200), 200)
        self.assertFalse(self.out.exists())
        self.assertEqual(nl.npaths(200), 1000)


if __name__ == "__main__":
    unittest.main()
