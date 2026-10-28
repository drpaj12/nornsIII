"""Run-record writer tests (scripts/runrecord.py, stdlib only). Run from the repo root:
    python3 tests/test_runrecord.py
No VPR or nextpnr run is needed. The cross-checks against Mimir's own `hostalias` run when `mimir` is importable
(PYTHONPATH=<mimirIII checkout>) and are skipped otherwise; a map written by Mimir is committed as a fixture."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runrecord as rr  # noqa: E402

FIXTURE_MAP = ROOT / "tests" / "fixtures" / "mimir-hosts.toml"  # written by mimir.hostalias.init_map / alias_of
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
G = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def make_map(d: Path, text: str | None = None) -> Path:
    m = d / "hosts.toml"
    m.write_text(text if text is not None else "# Private map of real host names to aliases.\n[hosts]\n", encoding="utf-8")
    return m


def init_repo(tree: Path, files: dict[str, str]) -> str:
    tree.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(tree), "init", "-q"], check=True)
    for name, text in files.items():
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text(text)
    subprocess.run(["git", "-C", str(tree), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tree), *G, "commit", "-q", "-m", "x"], check=True)
    return rr.git(tree, "rev-parse", "HEAD")


def fake_binary(path: Path, text: str) -> Path:
    path.write_text(f"#!/bin/sh\necho '{text}'\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class HostAlias(unittest.TestCase):
    def test_alias_stable_case_insensitive_and_appended_under_hosts_table(self):
        with tempfile.TemporaryDirectory() as d:
            m = make_map(Path(d))
            self.assertEqual(rr.host_alias("alpha", m), "host-1")
            self.assertEqual(rr.host_alias("ALPHA", m), "host-1")
            self.assertEqual(rr.host_alias("beta", m), "host-2")
            self.assertEqual(rr.host_alias("host-7", m), "host-7")  # an alias maps to itself
            self.assertEqual(tomllib.loads(m.read_text())["hosts"], {"alpha": "host-1", "beta": "host-2"})
            self.assertEqual(stat.S_IMODE(m.with_name("hosts.toml.lock").stat().st_mode), 0o600)  # lock file beside the map

    def test_no_flat_keys_and_names_are_toml_escaped(self):
        with tempfile.TemporaryDirectory() as d:
            m = make_map(Path(d))
            weird = 'we"ird\\name'
            self.assertEqual(rr.host_alias(weird, m), "host-1")
            data = tomllib.loads(m.read_text())
            self.assertEqual(list(data), ["hosts"])  # nothing outside [hosts]
            self.assertEqual(data["hosts"], {weird: "host-1"})

    def test_append_after_a_map_without_final_newline(self):
        with tempfile.TemporaryDirectory() as d:
            m = make_map(Path(d), '[hosts]\n"alpha" = "host-1"')  # no trailing newline
            self.assertEqual(rr.host_alias("beta", m), "host-2")
            self.assertEqual(tomllib.loads(m.read_text())["hosts"], {"alpha": "host-1", "beta": "host-2"})

    def test_missing_map_is_an_error_naming_the_variable_and_nothing_is_created(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "nohosts.toml"
            with self.assertRaises(rr.HostMapError) as cm:
                rr.host_alias("alpha", m)
            self.assertIn("MIMIR_HOST_MAP", str(cm.exception))
            self.assertFalse(m.exists())
            self.assertFalse(m.with_name("nohosts.toml.lock").exists())
            with mock.patch.dict(os.environ, {"MIMIR_HOST_MAP": str(m)}), self.assertRaises(rr.HostMapError):
                rr.RunRecorder("s", "d", "a", 1, "analytic", "arch", roots={})

    def test_reads_a_map_that_mimir_wrote(self):
        self.assertEqual(rr.host_alias("alpha-box", FIXTURE_MAP), "host-1")
        self.assertEqual(rr.host_alias("ALPHA-BOX", FIXTURE_MAP), "host-1")
        self.assertEqual(rr.host_alias('we"ird\\name', FIXTURE_MAP), "host-2")
        with tempfile.TemporaryDirectory() as d:  # appending to a copy numbers on from Mimir's last alias
            m = Path(d) / "hosts.toml"
            m.write_text(FIXTURE_MAP.read_text())
            self.assertEqual(rr.host_alias("gamma", m), "host-3")

    def test_mimir_reads_a_map_this_writer_appended_to(self):
        try:
            from mimir import hostalias
        except ImportError:
            self.skipTest("mimir not importable (set PYTHONPATH to the mimirIII checkout)")
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "hosts.toml"
            hostalias.init_map(m)
            self.assertEqual(hostalias.alias_of("first", m), "host-1")
            self.assertEqual(rr.host_alias("second", m), "host-2")  # this writer appends
            self.assertEqual(rr.host_alias("first", m), "host-1")
            self.assertEqual(hostalias.alias_of("second", m), "host-2")  # Mimir reads it
            self.assertEqual(hostalias.alias_of("third", m), "host-3")  # and numbers on from it
            self.assertEqual(rr.host_alias("third", m), "host-3")
            self.assertEqual(hostalias.load_map(m), {"first": "host-1", "second": "host-2", "third": "host-3"})


class BuildCopy(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.d = Path(self.t.name)
        self.tree, self.copy = self.d / "tree", self.d / "copy"
        init_repo(self.tree, {"a.txt": "a\n", "b.txt": "b\n", "gen/CMake.txt": "one\ntwo\n"})
        self.copy.mkdir()
        (self.copy / "gen").mkdir()
        (self.copy / "a.txt").write_text("a\n")
        (self.copy / "b.txt").write_text("b\n")
        (self.copy / "gen" / "CMake.txt").write_text("one\ntwo\n")

    def tearDown(self):
        self.t.cleanup()

    def test_copy_differs_lists_changed_and_missing_files(self):
        (self.copy / "b.txt").write_text("changed\n")
        self.assertEqual(rr.copy_differs(self.tree, self.copy), ["b.txt"])
        (self.copy / "b.txt").unlink()
        self.assertEqual(rr.copy_differs(self.tree, self.copy), ["b.txt"])
        (self.copy / "b.txt").write_text("b\n")
        self.assertEqual(rr.copy_differs(self.tree, self.copy), [])

    def test_extra_files_and_exemptions_are_listed_hashed_and_checked_by_content(self):
        (self.copy / "gen" / "k6").mkdir()
        (self.copy / "gen" / "k6" / "k6.cc").write_text("overlay\n")
        (self.copy / "gen" / "CMake.txt").write_text("one\n  k6/k6.cc\ntwo\n")
        ex = {"gen/CMake.txt": ("k6/k6.cc",)}
        st = rr.copy_state(self.tree, self.copy, ("gen/k6/k6.cc",), ex)
        self.assertEqual((st["differs"], st["extra"], st["unlisted"], st["is_head"]), (["gen/CMake.txt"], ["gen/k6/k6.cc"], [], True))
        self.assertEqual(set(st["sha256"]), {"gen/CMake.txt", "gen/k6/k6.cc"})
        # an extra file that is not listed, a different added line, a removed line: each makes the copy differ from HEAD
        self.assertEqual(rr.copy_state(self.tree, self.copy, (), ex)["unlisted"], ["gen/k6/k6.cc"])
        (self.copy / "gen" / "CMake.txt").write_text("one\n  other.cc\ntwo\n")
        self.assertEqual(rr.copy_state(self.tree, self.copy, ("gen/k6/k6.cc",), ex)["unlisted"], ["gen/CMake.txt"])
        (self.copy / "gen" / "CMake.txt").write_text("one\n  k6/k6.cc\n")
        self.assertEqual(rr.copy_state(self.tree, self.copy, ("gen/k6/k6.cc",), ex)["is_head"], False)

    def test_nextpnr_commit_is_given_only_for_a_listed_copy(self):
        head = rr.git(self.tree, "rev-parse", "HEAD")
        binary = fake_binary(self.d / "np", "no commit in this text")
        with tempfile.TemporaryDirectory() as t2:
            m = make_map(Path(t2))
            with mock.patch.dict(os.environ, {"MIMIR_HOST_MAP": str(m)}):
                r = rr.RunRecorder("s", "d", "a", 1, "analytic", "arch", roots={})
                r.add_tool("nextpnr", rr.tool_entry(self.tree, binary, copy=self.copy))
                self.assertEqual(r.rec["params"]["tool.nextpnr_commit"]["conf"], "given")
                (self.copy / "stray.o").write_text("x")
                r2 = rr.RunRecorder("s", "d", "a", 1, "analytic", "arch", roots={})
                r2.add_tool("nextpnr", rr.tool_entry(self.tree, binary, copy=self.copy))
                p = r2.rec["params"]
                self.assertEqual((p["tool.nextpnr_commit"]["conf"], p["tool.nextpnr_commit"]["value"]), ("unknown", head))
                self.assertTrue(p["tool.nextpnr_commit"]["source"].startswith("inferred at record time"))
                self.assertEqual(p["tool.nextpnr_build_copy_extra[stray.o]"]["conf"], "given")
                self.assertIn("NOT a listed exemption", p["tool.nextpnr_build_copy_extra[stray.o]"]["source"])


class ToolCommit(unittest.TestCase):
    def rec(self, entry, name="vpr"):
        with tempfile.TemporaryDirectory() as t2:
            with mock.patch.dict(os.environ, {"MIMIR_HOST_MAP": str(make_map(Path(t2)))}):
                r = rr.RunRecorder("s", "d", "a", 1, "analytic", "arch", roots={})
        r.add_tool(name, entry)
        return r.rec["params"]

    def test_commit_given_only_when_built_clean_and_named_by_the_binary(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            head = init_repo(d / "tree", {"f.txt": "x\n"})
            clean_bin = fake_binary(d / "vpr_clean", f"Version: 9-g{head[:10]}")
            dirty_bin = fake_binary(d / "vpr_dirty", f"Version: 9-g{head[:10]}-dirty")
            other_bin = fake_binary(d / "vpr_other", "Version: 9-gdeadbeef00")
            p = self.rec(rr.tool_entry(d / "tree", clean_bin))
            self.assertEqual((p["tool.vpr_commit"]["conf"], p["tool.vpr_built_dirty"]["value"]), ("given", "false"))
            p = self.rec(rr.tool_entry(d / "tree", dirty_bin))  # built from a dirty tree: the commit is only inferred
            self.assertEqual((p["tool.vpr_commit"]["conf"], p["tool.vpr_commit"]["value"], p["tool.vpr_built_dirty"]["value"]), ("unknown", head, "true"))
            self.assertIn("inferred at record time", p["tool.vpr_commit"]["source"])
            p = self.rec(rr.tool_entry(d / "tree", other_bin))
            self.assertEqual(p["tool.vpr_commit"]["conf"], "unknown")

    def test_dirty_flag_and_diff_hash_are_their_own_parameters_labelled_record_time(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            head = init_repo(d / "tree", {"f.txt": "x\n"})
            (d / "tree" / "f.txt").write_text("changed\n")
            p = self.rec(rr.tool_entry(d / "tree", fake_binary(d / "v", f"Version: 9-g{head[:10]}")))
            self.assertEqual(p["tool.vpr_source_clean"]["value"], "false")
            self.assertTrue(p["tool.vpr_source_clean"]["source"].startswith("at record time"))
            self.assertEqual(len(p["tool.vpr_dirty_diff_sha256"]["value"]), 64)
            self.assertTrue(p["tool.vpr_dirty_diff_sha256"]["source"].startswith("at record time"))

    def test_script_commit_given_only_for_a_clean_tree(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            init_repo(d / "tree", {"s.py": "x\n"})
            e = rr.tool_entry(d / "tree", d / "tree" / "s.py", version_args=None)
            self.assertEqual(self.rec(e, "norns")["tool.norns_commit"]["conf"], "given")
            (d / "tree" / "s.py").write_text("y\n")
            e = rr.tool_entry(d / "tree", d / "tree" / "s.py", version_args=None)
            self.assertEqual(self.rec(e, "norns")["tool.norns_commit"]["conf"], "unknown")


NEXTPNR_FILES = {
    "common/kernel/command.cc": '''void f() {
    if (vm.count("starttemp"))
        ctx->settings[ctx->id("placer1/startTemp")] = std::to_string(vm["starttemp"].as<float>());
    if (ctx->settings.find(ctx->id("target_freq")) == ctx->settings.end())
        ctx->settings[ctx->id("target_freq")] = std::to_string(12e6);
    if (ctx->settings.find(ctx->id("timing_driven")) == ctx->settings.end())
        ctx->settings[ctx->id("timing_driven")] = true;
    ctx->rngseed(ctx->setting<uint64_t>("seed"));
}
''',
    "common/kernel/timing.cc": 'x = ctx->setting<float>("target_freq");\nbool_or_default(ctx->settings, ctx->id("timing/ignoreLoops"), false);\n',
    "common/place/placer1.cc": 'a = ctx->setting<float>("placer1/startTemp", 1);\nb = ctx->setting<float>("placer1/constraintWeight", 10);\nc = ctx->setting<int>("placer1/mystery");\n',
    "common/place/placer_heap.cc": 'a = ctx->setting<float>("placerHeap/alpha", 0.5);\n',
    "common/place/place_common.cc": 'bool t = ctx->setting<bool>("timing_driven");\n',
    "generic/arch.cc": 'auto placer = str_or_default(settings, id("placer"), defaultPlacer);\nauto router = str_or_default(settings, id("router"), defaultRouter);\n',
    "generic/pack.cc": 'bool_or_default(ctx->settings, ctx->id("disable_iobs"));\n',
    "common/kernel/util.h": "inline bool bool_or_default(const A &ct, const K &key, bool def = false)\n{ return 1; }\n",
}


class NextpnrSettings(unittest.TestCase):
    def test_enumerate_reads_and_defaults(self):
        reads, defaults = rr.enumerate_settings({p: t.split("\n") for p, t in NEXTPNR_FILES.items()})
        names = {n: (p, ln, lit) for n, p, ln, lit in reads}
        self.assertEqual(names["placer1/startTemp"], ("common/place/placer1.cc", 1, "1"))
        self.assertEqual(names["placer1/mystery"][2], None)
        self.assertEqual(names["disable_iobs"][2], "bool()")
        self.assertEqual(defaults["target_freq"], ("common/kernel/command.cc", 5, "std::to_string(12e6)"))
        self.assertEqual(defaults["bool()"][2], "false")
        self.assertEqual(rr.cli_settings(NEXTPNR_FILES["common/kernel/command.cc"].split("\n")), {"starttemp": "placer1/startTemp"})

    def run_params(self, placer, argv, files=None, patch_files=True):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            files = NEXTPNR_FILES if files is None else files
            for p in rr.NEXTPNR_COMMON_FILES + tuple(rr.NEXTPNR_PLACER_FILE.values()):
                files = {**{p: "// nothing\n"}, **files}
            head = init_repo(d / "tree", files)
            m = make_map(d)
            with mock.patch.dict(os.environ, {"MIMIR_HOST_MAP": str(m)}):
                r = rr.RunRecorder("s", "d", "a", 1, "analytic", "arch", roots={})
            r.add_nextpnr_params(argv, d / "tree", head, "nextpnr", placer)
            return r.rec["params"], head

    def test_every_read_setting_is_a_default_with_citation_or_default_unrecorded(self):
        p, head = self.run_params("sa", ["np", "--placer", "sa", "--seed", "3", "--starttemp", "2", "--no-route", "--vopt", "n=10"])
        self.assertNotIn("nextpnr.placer", p)  # --placer is on the command line
        self.assertEqual((p["nextpnr.router"]["value"], p["nextpnr.router"]["conf"]), ("none", "given"))  # --no-route: the router does not run
        self.assertEqual(p["nextpnr.cmd.starttemp"]["value"], "2")
        self.assertNotIn("nextpnr.placer1/startTemp", p)  # given on the command line
        self.assertNotIn("nextpnr.seed", p)
        self.assertEqual(p["nextpnr.placer1/constraintWeight"], {"value": "10", "conf": "default", "source": f"nextpnr {head[:8]} common/place/placer1.cc:2"})
        self.assertEqual(p["nextpnr.target_freq"]["value"], "12e6")
        self.assertEqual(p["nextpnr.target_freq"]["source"], f"nextpnr {head[:8]} common/kernel/command.cc:5")
        self.assertEqual(p["nextpnr.timing_driven"]["value"], "true")
        self.assertEqual((p["nextpnr.timing/ignoreLoops"]["value"], p["nextpnr.timing/ignoreLoops"]["conf"]), ("false", "default"))
        self.assertEqual((p["nextpnr.disable_iobs"]["value"], p["nextpnr.disable_iobs"]["source"]), ("false", f"nextpnr {head[:8]} common/kernel/util.h:1"))
        self.assertEqual(p["nextpnr.placer1/mystery"]["conf"], "default-unrecorded")  # read, no default in the source
        self.assertNotIn("nextpnr.placerHeap/alpha", p)  # the heap placer's file is not read for the SA placer

    def test_heap_placer_file_and_an_unreadable_file(self):
        p, _ = self.run_params("heap", ["np", "--placer", "heap", "--seed", "1"])
        self.assertEqual(p["nextpnr.placerHeap/alpha"]["value"], "0.5")
        self.assertNotIn("nextpnr.placer1/constraintWeight", p)
        with tempfile.TemporaryDirectory() as t:  # a source file missing at the commit: an unknown row
            d = Path(t)
            head = init_repo(d / "tree", {"only.txt": "x\n"})
            with mock.patch.dict(os.environ, {"MIMIR_HOST_MAP": str(make_map(d))}):
                r = rr.RunRecorder("s", "d", "a", 1, "analytic", "arch", roots={})
            r.add_nextpnr_params(["np", "--seed", "1"], d / "tree", head, "nextpnr", "heap")
            self.assertEqual(r.rec["params"]["nextpnr.settings_source[common/kernel/command.cc]"]["conf"], "unknown")


class Parsing(unittest.TestCase):
    def test_time_and_options(self):
        self.assertEqual(rr.parse_time_v(TIME_V), (62.5, 2.0))
        self.assertEqual(rr.parse_time_v("no time output here"), (None, None))  # absent is None, never 0
        self.assertEqual(rr.cmd_options(["--a", "1", "2", "--b"]), [("a", ["1", "2"]), ("b", [])])

    def test_default_read_from_source_with_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "read_options.cpp"
            p.write_text(SRC)
            self.assertEqual(rr.option_default(p, "--seed"), ("1", "1-3"))
            self.assertEqual(rr.line_of(p, ".default_value"), 3)
            self.assertIsNone(rr.option_default(p, "--nope"))

    def test_default_cited_from_the_commit_not_the_working_tree(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "tree"
            head = init_repo(tree, {"vpr/src/base/read_options.cpp": SRC})
            (tree / "vpr/src/base/read_options.cpp").write_text(SRC.replace('"1"', '"99"'))  # working tree edited after the commit
            self.assertEqual(rr.option_default(tree, "--seed", head, "vpr/src/base/read_options.cpp"), ("1", "1-3"))


class Recorder(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.d = Path(self.t.name).resolve()
        self.patch = mock.patch.dict(os.environ, {"MIMIR_HOST_MAP": str(make_map(self.d))})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.t.cleanup()

    def make(self, log: str = VPR_LOG, time_s=1.5, rss=100.0) -> rr.RunRecorder:
        d = self.d
        (d / "run").mkdir(exist_ok=True)
        (d / "run" / "vpr.out").write_text(log)
        tree = d / "tree"
        head = init_repo(tree, {"vpr/src/base/read_options.cpp": SRC})
        r = rr.RunRecorder("norns-placers-t", "dsn", "vpr_sa", 3, "annealing", "arch1", roots={"run": d / "run"}, roles={d / "x.blif": "<blif>"})
        argv = [str(d / "vpr"), str(d / "arch.xml"), str(d / "x.blif"), "--seed", "3", "--write_flat_place", str(d / "run" / "f.place")]
        r.add_step("vpr", argv, 0, time_s, rss, True)
        r.add_vpr_params(argv, d / "run" / "vpr.out", tree, head)
        (d / "x.blif").write_text("b")
        r.add_input("netlist", d / "x.blif")
        return r

    def test_record_has_params_with_sources_and_no_absolute_paths(self):
        r = self.make()
        r.write(self.d / "run" / "mimir-run.json")
        rec = json.loads((self.d / "run" / "mimir-run.json").read_text())
        self.assertEqual(rec["record_version"], 1)
        self.assertRegex(rec["host"], r"host-\d+")
        self.assertEqual(rec["steps"][0]["argv"][2:], ["<blif>", "--seed", "3", "--write_flat_place", "<run>/f.place"])
        p = rec["params"]
        self.assertEqual(p["run.seed"]["value"], "3")
        self.assertRegex(p["run.seed_default"]["source"], r"^vtr-tree [0-9a-f]{8} vpr/src/base/read_options.cpp:1-3$")
        self.assertEqual(p["run.seed_default"]["conf"], "default")
        self.assertEqual(p["vpr.router_opts.routing_failure_predictor"]["value"], "SAFE")  # `=` echo lines count
        self.assertEqual(p["vpr.netlist_opts.absorb_buffer_luts"]["source"].split(" ")[0], "vpr.out:7")
        self.assertTrue(all(v["source"] for v in p.values()))
        self.assertNotIn(str(self.d), json.dumps(rec))

    def test_missing_vpr_echo_header_is_an_unknown_row(self):
        r = self.make(log=VPR_LOG.replace("VPR was run with the following options:", "VPR options:"))
        row = r.rec["params"]["vpr.options_echo"]
        self.assertEqual(row["conf"], "unknown")
        self.assertNotIn("vpr.netlist_opts.absorb_buffer_luts", r.rec["params"])

    def test_missing_time_output_is_null_and_unknown_never_zero(self):
        r = self.make(time_s=None, rss=None)
        r.write(self.d / "run" / "mimir-run.json")
        rec = json.loads((self.d / "run" / "mimir-run.json").read_text())
        self.assertEqual((rec["time_s"], rec["time_conf"], rec["peak_rss_mib"]), (None, "unknown", None))
        self.assertEqual((rec["steps"][0]["time_s"], rec["steps"][0]["time_conf"], rec["steps"][0]["peak_rss_mib"]), (None, "unknown", None))

    def test_step_times_placer_time_and_shared_steps(self):
        r = self.make()
        r.add_step("nextpnr", ["np"], 1, 4.0, 10.0, False)
        r.add_step("nextpnr", ["np"], 0, 5.0, 20.0, True)
        r.add_step("flatplace_chains", ["python3", "s.py"], 0, 7.0, None, False, script=ROOT / "scripts" / "runrecord.py", shared=True)
        r.write(self.d / "run" / "mimir-run.json")
        rec = json.loads((self.d / "run" / "mimir-run.json").read_text())
        self.assertEqual((rec["time_s"], rec["placer_time_s"], rec["peak_rss_mib"]), (1.5 + 4.0 + 5.0, 5.0, 100.0))  # the shared step's 7 s is not in the run
        self.assertEqual([s["locked"] for s in rec["steps"]], [True, False, True, False])
        self.assertEqual(len(rec["steps"][3]["script_sha256"]), 64)
        self.assertIs(rec["ok"], True)  # the last step exited 0

    def test_step_roles_keep_per_seed_paths_out_of_the_command_text(self):
        r = self.make()
        r.add_step("flatplace_chains", ["python3", str(self.d / "run" / "s1" / "in.fp")], 0, 1.0, None, False, roles={self.d / "run" / "s1" / "in.fp": "<collapse_in>"})
        r.add_step("flatplace_chains", ["python3", str(self.d / "run" / "s1" / "in.fp")], 0, 1.0, None, False)
        self.assertEqual(r.rec["steps"][1]["argv"][1], "<collapse_in>")
        self.assertEqual(r.rec["steps"][2]["argv"][1], "<run>/s1/in.fp")  # the role applies to its own step only

    def test_missing_input_artifact_and_required_role_are_unknown_rows(self):
        r = self.make()
        r.add_input("arch", self.d / "arch.xml")  # absent file
        r.add_artifact("vpr_out", self.d / "run" / "vpr.out")
        r.write(self.d / "run" / "mimir-run.json", required_inputs=("netlist", "arch", "anchors"), required_artifacts=("vpr_out", "flat_place"))
        p = json.loads((self.d / "run" / "mimir-run.json").read_text())["params"]
        self.assertEqual(p["inputs.arch_sha256"]["conf"], "unknown")
        self.assertEqual(p["inputs.anchors_sha256"]["conf"], "unknown")
        self.assertEqual(p["artifacts.flat_place_sha256"]["conf"], "unknown")
        self.assertNotIn("inputs.netlist_sha256", p)
        self.assertNotIn("artifacts.vpr_out_sha256", p)

    def test_private_string_refuses_to_write_and_names_rule_and_key_not_value(self):
        r = self.make()
        r.param("x.y", "v", "given", "read from /ho" + "me/someone/file")  # built from parts: no literal home path here
        with self.assertRaises(rr.RecordRefused) as cm:
            r.write(self.d / "run" / "mimir-run.json")
        self.assertIn("home-path at record.params.x.y.source", cm.exception.hits)
        self.assertNotIn("someone", str(cm.exception))
        self.assertFalse((self.d / "run" / "mimir-run.json").exists())
        self.assertTrue(rr.private_strings())  # the home directory is always in the list

    def test_absolute_path_rule(self):
        for text, bad in (("/tmp/x", True), ("--o=/tmp/x", True), ("a:/tmp/x", True), ("/Us" + "ers/x", True), ("/dev/null", False),
                          ("vpr/src/a.cpp:1-2", False), ("a / b", False), ("<run>/x", False), ("https://e.org/p", False)):
            self.assertEqual(bool(rr.privacy_hits({"k": text})), bad, text)
        self.assertEqual(rr.privacy_hits({"k": ["/Us" + "ers/x"]}), ["home-path at record.k[0]"])

    def test_real_host_name_in_the_map_is_a_privacy_hit(self):
        m = Path(os.environ["MIMIR_HOST_MAP"])
        rr.host_alias("some-real-box", m)
        self.assertIn("host-map-name at record.k", rr.privacy_hits({"k": "built on Some-Real-Box today"}))


if __name__ == "__main__":
    unittest.main()
