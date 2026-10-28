"""Run records for Mimir III: one `mimir-run.json` per Norns run (stdlib only; Norns does not import mimir).

The record carries the full how-obtained data of a run: tool commits (how found, clean or dirty), binary
sha256 and `--version` text, the exact command lines (paths replaced by placeholders), every parameter as
{value, conf, source}, seed, host alias, time and peak RSS, input and artifact sha256 with relative paths.
The format is specified in mimirIII, docs/specs/2026-10-28-mimir-run-record.md (record_version 1); the
importer is `mimir import-runrecords`. Nothing here deletes a file.

    rec = RunRecorder(source, design, arm, seed, family, arch, roots={"run": cwd, ...})
    rec.add_step(name, argv, rc, time_s, rss_mib)         # one per tool run (vpr, nextpnr)
    rec.add_tool("vpr", tree, binary, ...)                # commit, clean flag, binary sha256 and version text
    rec.add_vpr_params(argv, log) / rec.add_nextpnr_params(argv, tree)
    rec.add_input(role, path) / rec.add_artifact(role, path)
    rec.write(cwd / "mimir-run.json")
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import re
import subprocess
import time
import tomllib
from pathlib import Path

RECORD_VERSION = 1
SHA40 = re.compile(r"[0-9a-f]{40}")
OPT_LINE = re.compile(r"^([A-Za-z_]\w*\.[\w.]+)\s*[:=]\s*(.*)$")
VPR_OPTIONS_HEAD = "VPR was run with the following options:"
UNMAPPED = "host-unmapped"


# ---------------------------------------------------------------- host alias

def host_alias(real: str | None = None, map_path: str | None = None) -> str:
    """The alias of this host from the TOML map in $MIMIR_HOST_MAP (`"real name" = "host-1"`, flat or in a
    [hosts] table). An unknown host gets the next `host-<n>` and is appended; no map gives `host-unmapped`.
    The real name is never returned."""
    real = real or platform.node()
    path = map_path or os.environ.get("MIMIR_HOST_MAP", "")
    if not path:
        return UNMAPPED
    p = Path(path)
    data = tomllib.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    table = data.get("hosts", data)
    for name, alias in table.items():
        if isinstance(alias, str) and name.lower() == real.lower():
            return alias
    nums = [int(m.group(1)) for v in table.values() if isinstance(v, str) and (m := re.fullmatch(r"host-(\d+)", v))]
    alias = f"host-{max(nums, default=0) + 1}"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(f'"{real}" = "{alias}"\n')
    return alias


# ---------------------------------------------------------------- git and binaries

def git(root: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_entry(tree: Path | None, binary: Path, env: dict[str, str] | None = None, version_args: tuple[str, ...] | None = ("--version",)) -> dict[str, object]:
    """Facts about one tool: HEAD of its source tree and how it was found, whether the tree is clean (and the
    sha256 of its diff when it is not), the binary's sha256 and `--version` text, and whether that text
    names the tree's HEAD (the evidence that the binary was built from it)."""
    head = git(tree, "rev-parse", "HEAD") if tree else ""
    head = head if SHA40.fullmatch(head) else ""
    clean = None
    diff_sha = ""
    if head and tree:
        clean = git(tree, "status", "--porcelain", "--untracked-files=no") == ""
        if not clean:
            diff_sha = hashlib.sha256(git(tree, "diff", "HEAD").encode()).hexdigest()
    version = ""
    if binary.is_file() and version_args is not None:
        res = subprocess.run([str(binary), *version_args], capture_output=True, text=True, check=False, timeout=60,
                             env={**os.environ, **(env or {})})
        version = (res.stdout + res.stderr).strip()
    return {"commit": head, "commit_how": "git rev-parse HEAD of the source tree" if head else "no git source tree",
            "clean": clean, "dirty_diff_sha256": diff_sha,
            "binary_sha256": file_sha256(binary) if binary.is_file() else "",
            "binary_version": version,
            # a script run from its tree (version_args None) is that tree's HEAD when the tree is clean
            "version_names_commit": (clean is True) if version_args is None else (bool(head) and head[:10] in version)}


def parse_time_v(text: str) -> tuple[float, float]:
    """(elapsed wall seconds, peak RSS MiB) from `/usr/bin/time -v` output; (0, 0) when absent."""
    el = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([0-9:.]+)", text)
    rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", text)
    secs = 0.0
    if el:
        for part in el.group(1).split(":"):
            secs = secs * 60 + float(part)
    return secs, (int(rss.group(1)) / 1024.0 if rss else 0.0)


# ---------------------------------------------------------------- defaults read from tool source

def option_default(src: Path, option: str) -> tuple[str, str] | None:
    """(value, 'first-last') of the `.default_value("x")` after the argparse entry of `option` in a VPR source file."""
    lines = src.read_text(encoding="utf-8", errors="replace").split("\n") if src.is_file() else []
    for i, ln in enumerate(lines):
        if f'"{option}")' in ln:
            for j in range(i, min(i + 20, len(lines))):
                m = re.search(r'\.default_value\("([^"]*)"\)', lines[j])
                if m:
                    return m.group(1), f"{i + 1}-{j + 1}"
            return None
    return None


def line_of(src: Path, needle: str) -> int:
    """1-based line of the first line of `src` containing `needle`; 0 when absent."""
    lines = src.read_text(encoding="utf-8", errors="replace").split("\n") if src.is_file() else []
    return next((i + 1 for i, ln in enumerate(lines) if needle in ln), 0)


# nextpnr defaults: (key, value, file in the nextpnr tree, text of the line that sets it)
NEXTPNR_COMMON = (
    ("timing_driven", "true", "common/kernel/command.cc", 'ctx->settings[ctx->id("timing_driven")] = true;'),
    ("target_freq", "12e6", "common/kernel/command.cc", 'ctx->settings[ctx->id("target_freq")] = std::to_string(12e6);'),
)
NEXTPNR_HEAP = (
    ("placerHeap/alpha", "0.1", "common/kernel/command.cc", 'ctx->settings[ctx->id("placerHeap/alpha")] = std::to_string(0.1);'),
    ("placerHeap/beta", "0.9", "common/kernel/command.cc", 'ctx->settings[ctx->id("placerHeap/beta")] = std::to_string(0.9);'),
    ("placerHeap/criticalityExponent", "2", "common/kernel/command.cc", 'ctx->settings[ctx->id("placerHeap/criticalityExponent")] = std::to_string(2);'),
    ("placerHeap/timingWeight", "10", "common/kernel/command.cc", 'ctx->settings[ctx->id("placerHeap/timingWeight")] = std::to_string(10);'),
    ("placerHeap/parallelRefine", "false", "common/place/placer_heap.cc", 'ctx->setting<bool>("placerHeap/parallelRefine", false)'),
    ("placerHeap/netShareWeight", "0", "common/place/placer_heap.cc", 'ctx->setting<float>("placerHeap/netShareWeight", 0)'),
    ("placerHeap/noCtrlSet", "false", "common/place/placer_heap.cc", 'ctx->setting<bool>("placerHeap/noCtrlSet", false)'),
    ("placerHeap/cellPlacementTimeout", "8", "common/place/placer_heap.cc", 'ctx->setting<int>("placerHeap/cellPlacementTimeout", 8)'),
)
NEXTPNR_SA = (
    ("placer1/constraintWeight", "10", "common/place/placer1.cc", 'ctx->setting<float>("placer1/constraintWeight", 10)'),
    ("placer1/netShareWeight", "0", "common/place/placer1.cc", 'ctx->setting<float>("placer1/netShareWeight", 0)'),
    ("placer1/minBelsForGridPick", "64", "common/place/placer1.cc", 'ctx->setting<int>("placer1/minBelsForGridPick", 64)'),
    ("placer1/startTemp", "1", "common/place/placer1.cc", 'ctx->setting<float>("placer1/startTemp", 1)'),
)


def cmd_options(flags: list[str]) -> list[tuple[str, list[str]]]:
    """[(option name without --, [values])] of a command line's `--name v1 v2` groups."""
    out: list[tuple[str, list[str]]] = []
    for a in flags:
        if a.startswith("--"):
            out.append((a[2:], []))
        elif out:
            out[-1][1].append(a)
    return out


# ---------------------------------------------------------------- the recorder

class RunRecorder:
    """Builds one run record. `roots` maps a placeholder name to a directory: a path under it is written as
    `<name>/relative`; any other absolute path as `<abs>/basename`; a file in `roles` as `<role>`."""

    def __init__(self, source: str, design: str, arm: str, seed: int, family: str, arch: str,
                 roots: dict[str, Path], roles: dict[Path, str] | None = None):
        self.rec: dict[str, object] = {
            "record_version": RECORD_VERSION, "kind": "norns-run", "source": source, "design": design,
            "arm": arm, "seed": int(seed), "family": family, "arch": arch, "host": host_alias(),
            "kernel": platform.release(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "steps": [], "tools": {}, "params": {}, "inputs": {}, "artifacts": {}}
        self.roots = {k: v.resolve() for k, v in roots.items()}
        self.roles = {k.resolve(): v for k, v in (roles or {}).items()}
        self.t0 = time.monotonic()

    # paths
    def ph(self, text: str) -> str:
        """A path (or a value that is one) as a placeholder."""
        if "=" in text and text.split("=", 1)[1].startswith("/") and not text.startswith("/"):
            k, v = text.split("=", 1)
            return f"{k}={self.ph(v)}"
        if not text.startswith("/"):
            return text
        p = Path(text)
        if p == Path("/dev/null"):
            return text
        rp = p.resolve()
        if rp in self.roles:
            return self.roles[rp]
        for name, root in sorted(self.roots.items(), key=lambda kv: -len(str(kv[1]))):
            if rp == root or root in rp.parents:
                return f"<{name}>/{rp.relative_to(root).as_posix()}".rstrip("/")
        return f"<abs>/{p.name}"

    def argv(self, argv: list[str]) -> list[str]:
        return [self.ph(a) for a in argv]

    # contents
    def add_step(self, name: str, argv: list[str], rc: int, time_s: float, rss_mib: float, locked: bool = True) -> None:
        steps = self.rec["steps"]
        assert isinstance(steps, list)
        steps.append({"name": name, "argv": self.argv(argv), "exit_code": int(rc), "time_s": round(time_s, 3),
                      "peak_rss_mib": round(rss_mib, 1), "locked": locked})

    def add_tool(self, name: str, entry: dict[str, object]) -> None:
        tools = self.rec["tools"]
        assert isinstance(tools, dict)
        tools[name] = entry
        c = str(entry["commit"])
        ok = bool(c) and bool(entry["version_names_commit"])
        self.param(f"tool.{name}_commit", c, "given" if ok else "unknown",
                   f"{name}: HEAD of its source tree, named by its --version text (or a clean tree for a script)" if ok else
                   f"{name}: HEAD of the source tree is not named by the binary's --version text, or there is no tree")
        self.param(f"tool.{name}_source_clean", "unknown" if entry["clean"] is None else str(entry["clean"]).lower(),
                   "given" if entry["clean"] is not None else "unknown",
                   "git status --porcelain of the source tree (tracked files)")
        if entry["dirty_diff_sha256"]:
            self.param(f"tool.{name}_dirty_diff_sha256", str(entry["dirty_diff_sha256"]), "given", "sha256 of git diff HEAD of the source tree")
        self.param(f"tool.{name}_binary_sha256", str(entry["binary_sha256"]), "given" if entry["binary_sha256"] else "unknown", "sha256 of the binary file")

    def param(self, key: str, value: str, conf: str, source: str) -> None:
        params = self.rec["params"]
        assert isinstance(params, dict)
        params[key] = {"value": self.ph(value), "conf": conf, "source": source}

    def add_input(self, role: str, path: Path) -> None:
        self._file("inputs", role, path)

    def add_artifact(self, role: str, path: Path) -> None:
        self._file("artifacts", role, path)

    def _file(self, table: str, role: str, path: Path) -> None:
        if path.is_file():
            tab = self.rec[table]
            assert isinstance(tab, dict)
            tab[role] = {"path": self.ph(str(path.resolve())), "sha256": file_sha256(path)}

    # parameters of the tools
    def add_vpr_params(self, argv: list[str], log: Path, src: Path | None, tree_label: str) -> None:
        """VPR: every option VPR echoed in its log (its own statement of the effective value, cited vpr.out:line),
        the options on the command line, the seed, and the seed's default read from `src` (read_options.cpp)."""
        lines = log.read_text(encoding="utf-8", errors="replace").split("\n") if log.is_file() else []
        if VPR_OPTIONS_HEAD in lines:
            for n in range(lines.index(VPR_OPTIONS_HEAD) + 1, len(lines)):
                m = OPT_LINE.match(lines[n])
                if m:
                    self.param(f"vpr.{m.group(1)}", m.group(2).strip() or "(empty)", "given", f"vpr.out:{n + 1} (VPR's echo of the effective option)")
                elif lines[n].strip() and not lines[n].startswith(" ") and not lines[n].startswith("Using up to"):
                    break
        for key, vals in cmd_options(argv[3:]):  # argv is vpr, arch, blif, then the options
            if key == "seed":
                self.param("run.seed", vals[0], "given", "command line --seed")
            else:
                self.param(f"vpr.cmd.{key}", " ".join(self.ph(v) for v in vals) or "(flag)", "given", "command line")
        self.param("vpr.cmd.arch_file", self.ph(argv[1]), "given", "command line")
        found = option_default(src, "--seed") if src else None
        if found and src:
            self.param("run.seed_default", found[0], "default", f"{tree_label} vpr/src/base/read_options.cpp:{found[1]}")
        else:
            self.param("run.seed_default", "", "default-unrecorded", "VPR source tree not available")

    def add_nextpnr_params(self, argv: list[str], src: Path | None, label: str, placer: str) -> None:
        """nextpnr: the command-line options as given, and the defaults of the settings the chosen placer reads,
        each cited file:line in the nextpnr source tree `src`."""
        for key, vals in cmd_options(argv[1:]):
            val = " ".join(vals) or "(flag)"
            if key == "seed":
                self.param("run.seed", val, "given", "command line --seed")
            elif key == "vopt":
                k, _, v = val.partition("=")
                self.param(f"nextpnr.vopt.{k}", v, "given", "command line --vopt")
            else:
                self.param(f"nextpnr.cmd.{key}", val, "given", "command line")
        table = NEXTPNR_COMMON + (NEXTPNR_HEAP if placer == "heap" else NEXTPNR_SA)
        for key, value, path, needle in table:
            n = line_of(src / path, needle) if src else 0
            if key == "placer1/startTemp" and "--starttemp" in argv:
                continue  # given on the command line (ctx setting placer1/startTemp)
            if n:
                self.param(f"nextpnr.{key}", value, "default", f"{label} {path}:{n}")
            else:
                self.param(f"nextpnr.{key}", "", "default-unrecorded", f"{path}: line not found in the nextpnr source tree")

    # output
    def write(self, path: Path) -> None:
        steps: list[dict[str, float]] = self.rec["steps"]  # type: ignore[assignment]
        self.rec["time_s"] = round(sum(s["time_s"] for s in steps), 3)
        self.rec["peak_rss_mib"] = max((s["peak_rss_mib"] for s in steps), default=0.0)
        self.rec["ok"] = bool(steps) and steps[-1]["exit_code"] == 0  # the last step decides (earlier attempts may have failed)
        text = json.dumps(self.rec, indent=1, sort_keys=True) + "\n"
        assert_clean(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def private_strings() -> list[str]:
    """Strings no record may hold: the home directory, user name and host name of this machine."""
    return [s for s in (str(Path.home()), getpass.getuser(), platform.node()) if len(s) >= 3]


def assert_clean(text: str) -> None:
    low = text.lower()
    bad = [s for s in private_strings() if s.lower() in low]
    if bad or "/home/" in text:
        raise ValueError("run record holds a private string or a home path; not written")
