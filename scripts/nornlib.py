"""Shared helpers of the Norns III experiment (stdlib only).

The experiment's data flow, one design at a time:

    Verilog --odin3--> provenance BLIF --nornlib--> graph.json --loki L2--> partitions
              |                                            |
              +----------------> VPR atom names <---------+
    partitions + provenance hierarchy --build_seeds--> .place / flat / constraints
    VPR run (heavy lock) --> vpr.out metrics + final placement --> retention/QoR

Every number in the paper traces to a JSON record this module writes (or parses).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import lzma
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

WS = Path(__file__).resolve().parents[1]
REPO_NORNS = WS  # this worktree
DESIGN_ORDER = (
    "ch_intrinsics", "stereovision3", "diffeq2", "diffeq1", "mkPktMerge", "raygentop",
    "sha", "boundtop", "mkSMAdapter4B", "or1200", "stereovision0", "stereovision1",
    "mkDelayWorker32B", "stereovision2", "blob_merge",
)
SEED_FAMILIES = ("urd", "louvain", "spectral", "affinity", "kmeans_k", "kmeans_2k", "kmeans_4k")
# defaults assume the Yggdrasil III workspace layout (scripts/env.sh); every path is overridable
WS_ROOT = Path(os.environ.get("WS_ROOT", str(Path.home() / "odin3-ws")))
VTR_ROOT = Path(os.environ.get("VTR_ROOT", str(WS_ROOT / "external" / "vtr-verilog-to-routing")))
VPR = VTR_ROOT / "build" / "vpr" / "vpr"
ARCH = Path(os.environ.get("NORNS_ARCH") or str(VTR_ROOT / "vtr_flow" / "arch" / "timing" / "k6_frac_N10_frac_chain_mem32K_40nm.xml"))  # NORNS_ARCH: an architecture file (E10 sweep); default the Norns architecture
BENCH = VTR_ROOT / "vtr_flow" / "benchmarks" / "verilog"
ODIN3_ROOT = Path(os.environ.get("ODIN3_ROOT", str(WS_ROOT / "odin3")))
ODIN3 = ODIN3_ROOT / "build" / "release" / "odin3"
ODIN3_LIB = ODIN3_ROOT / "build" / "release" / "libodin3.so"
LOCK = Path(os.environ.get("NORNS_LOCK", "/tmp/claude-1000/odin3-heavy.lock"))
RUNS = Path(os.environ.get("NORNS_RUNS", str(WS / "runs")))  # raw run outputs (not committed); override to keep them elsewhere
DATA = Path(os.environ.get("NORNS_DATA", str(WS / "data")))  # committed result records; override for a smoke test


def design_verilog(design: str) -> Path:
    return BENCH / f"{design}.v"


def runs_dir(design: str, *parts: str) -> Path:
    return RUNS.joinpath(design, *parts)


def data_crossover(design: str, name: str) -> Path:
    """Committed copy of a crossover/checkpointing sweep result (runs/ is not committed)."""
    return DATA / design / "crossover" / name


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------
# BLIF

_CONT = re.compile(r"\\$")


def logical_lines(path: Path) -> list[str]:
    """BLIF lines with VPR/writer continuations (trailing backslash) joined."""
    out: list[str] = []
    buf = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip()
        if buf:
            buf += " " + line
        else:
            buf = line
        if _CONT.search(buf):
            buf = _CONT.sub("", buf)
            continue
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return out


_SRC = re.compile(r"^(?P<path>.*?)/(?P<leaf>[^/]+)@(?P<file>.*):(?P<line>[0-9]+)$")


def provenance_parts(name: str) -> tuple[str, str, str, int]:
    """(module_path, leaf, hdl_file, hdl_line) of a provenance name; ('', name, '', 0) else."""
    m = _SRC.match(name)
    if m is None:
        return "", name, "", 0
    return m.group("path"), m.group("leaf"), m.group("file"), int(m.group("line"))


def module_of(name: str) -> str:
    return provenance_parts(name)[0]


def arch_output_ports(arch_xml: Path) -> dict[str, set[str]]:
    """model name -> output port names, from the VPR architecture's <model> definitions."""
    import xml.etree.ElementTree as ET
    root = ET.parse(str(arch_xml)).getroot()
    out: dict[str, set[str]] = {}
    for model in root.iter("model"):
        name = model.get("name")
        if not name:
            continue
        ports = {p.get("name") for p in model.findall("output_ports/port") if p.get("name")}
        out[name] = ports
    return out


def parse_blif(path: Path, atom_names: set[str] | None = None,
               model_outputs: dict[str, set[str]] | None = None) -> dict[str, Any]:
    """Blocks of a VTR-dialect BLIF: name, kind (lut/latch/hard/const), inputs, table.

    The block name is the output net of a ``.names``/``.latch`` and the ``out=`` actual of a
    ``.subckt`` (the name VPR's atom netlist gives the block).
    """
    blocks: list[dict[str, Any]] = []
    ports_in: list[str] = []
    ports_out: list[str] = []
    model = ""
    cur: dict[str, Any] | None = None
    for line in logical_lines(path):
        tok = line.split()
        if not tok:
            continue
        head = tok[0]
        if head == ".model":
            model = " ".join(tok[1:])
        elif head == ".inputs":
            ports_in.extend(tok[1:])
        elif head == ".outputs":
            ports_out.extend(tok[1:])
        elif head == ".names":
            names = tok[1:]
            out = names[-1] if names else ""
            inputs = names[:-1]
            cur = {"name": out, "kind": "lut", "inputs": inputs, "rows": []}
            blocks.append(cur)
        elif head in ("0", "1"):
            if cur is not None and len(tok) >= 2:
                cur["rows"].append((tok[0], tok[1]))
        elif head == ".latch":
            # .latch <input> <output> [<type> <control>] [<init>]
            inp = tok[1] if len(tok) > 1 else ""
            out = tok[2] if len(tok) > 2 else ""
            blocks.append({"name": out, "kind": "latch", "inputs": [inp] if inp else [],
                           "rows": []})
        elif head == ".subckt":
            model_name = tok[1] if len(tok) > 1 else ""
            pins = {}
            for item in tok[2:]:
                if "=" in item:
                    formal, actual = item.split("=", 1)
                    pins[formal] = actual
            outs = []
            if model_outputs is not None and model_name in model_outputs:
                outs = [actual for formal, actual in pins.items()
                        if formal.split("[")[0] in model_outputs[model_name]]
            if not outs:
                outs = [actual for formal, actual in pins.items()
                        if formal.lower().startswith("out")
                        or formal.lower() in ("o", "q", "z")]
            if atom_names and not outs:
                # VPR names a hard block after one of its port nets; the atom list is the truth
                matched = [actual for actual in pins.values() if actual in atom_names]
                outs = matched or outs
            if not outs:
                outs = list(pins.values())
            blocks.append({"name": outs[0] if outs else "", "kind": "hard",
                           "inputs": list(pins.values()), "pins": pins,
                           "model": model_name, "rows": []})
    for b in blocks:
        b.setdefault("rows", [])
        b["module"] = module_of(b["name"])
        b["leaf"] = provenance_parts(b["name"])[1]
    return {"model": model, "inputs": ports_in, "outputs": ports_out, "blocks": blocks}


def lut_table_hex(block: dict[str, Any]) -> tuple[str, int]:
    """(truth-table hex MSB first, width) of a ``.names`` block; ('', width) for const/wide."""
    inputs = block.get("inputs") or []
    width = len(inputs)
    if width == 0:
        return ("1" if block.get("rows") else "0"), 0
    if width > 8:
        return "", width
    tt = 0
    for pattern, val in block.get("rows", []):
        if len(pattern) != width or val not in ("0", "1"):
            continue
        index = int(pattern, 2)
        if val == "1":
            tt |= 1 << index
    digits = max(1, (1 << width) // 4)
    return format(tt, "0{}x".format(digits)), width


# ---------------------------------------------------------------------------------------
# Flat placement / place files

class Flat:
    """Atom-level flat placement: name -> (x, y, layer, subtile, clb, pb_type)."""

    def __init__(self, path: Path):
        self.atoms: dict[str, tuple[float, float, int, int, str, str]] = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            tok = line.split()
            if len(tok) < 7:
                continue
            self.atoms[tok[0]] = (float(tok[1]), float(tok[2]), int(tok[3]), int(tok[4]),
                                  tok[5], tok[6])

    def clb_types(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for _name, (_x, _y, _l, _s, clb, pb) in self.atoms.items():
            out.setdefault(clb, set()).add(pb)
        return out

    def clb_of(self, atom: str) -> str | None:
        hit = self.atoms.get(atom)
        return hit[4] if hit else None


class Place:
    """CLB-level placement file (VPR .place); preserves header and block order."""

    def __init__(self, path: Path):
        self.header: list[str] = []
        self.rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            if line.startswith("#") or line.startswith("Netlist_File:") \
                    or line.startswith("Array size:"):
                self.header.append(line)
                continue
            tok = line.split()
            if len(tok) < 5:
                continue
            self.rows.append({"name": tok[0], "x": tok[1], "y": tok[2], "sub": tok[3],
                              "layer": tok[4], "num": tok[5] if len(tok) > 5 else ""})

    def write(self, path: Path) -> None:
        ensure_dir(path.parent)
        out = ["Netlist_File: (null) Netlist_ID: (null)"]
        out += [h for h in self.header if h.startswith("Array size:")]
        out += ["", "#block name\tx\ty\tsubblk\tlayer\tblock number",
                "#----------\t--\t--\t------\t-----\t------------"]
        for r in self.rows:
            out.append("{}\t{}\t{}\t{}\t{}\t{}".format(r["name"], r["x"], r["y"], r["sub"],
                                                       r["layer"], r["num"]))
        path.write_text("\n".join(out) + "\n", encoding="utf-8")

    def coords(self) -> dict[str, tuple[int, int, int, int]]:
        return {r["name"]: (int(r["x"]), int(r["y"]), int(r["sub"]), int(r["layer"]))
                for r in self.rows}


def grid_size(place: Place) -> tuple[int, int]:
    for h in place.header:
        m = re.match(r"Array size: (\d+) x (\d+)", h)
        if m:
            return int(m.group(1)), int(m.group(2))
    raise ValueError("no Array size line")


# ---------------------------------------------------------------------------------------
# VPR log

class Metrics:
    """Metrics parsed out of a VPR run's stdout log."""

    FIELDS = {
        "wirelength": re.compile(r"\tTotal wirelength: ([0-9.eE+-]+),"),
        "cpd_ns": re.compile(r"Final critical path delay \(least slack\): ([0-9.eE+-]+) ns"),
        "chan_width": re.compile(r"Best routing used a channel width factor of ([0-9]+)\."),
        "place_s": re.compile(r"Analytical Placement took ([0-9.eE+-]+) seconds"),
        "route_s": re.compile(r"# Routing took ([0-9.eE+-]+) seconds"),
        "flow_s": re.compile(r"The entire flow of VPR took ([0-9.eE+-]+) seconds"),
        "init_t": None,  # first temperature row, parsed from the cost table
        "bb_initial": re.compile(r"Initial placement BB estimate of wirelength: ([0-9.eE+-]+)"),
        "bb_final": re.compile(r"BB estimate of min-dist \(placement\) wire length: ([0-9.eE+-]+)"),
    }

    def __init__(self, log: Path):
        text = log.read_text(encoding="utf-8", errors="replace")
        self.values: dict[str, Any] = {}
        for key, rx in self.FIELDS.items():
            if rx is None:
                continue
            m = rx.search(text)
            if m:
                try:
                    self.values[key] = float(m.group(1))
                except ValueError:
                    self.values[key] = m.group(1)
        self.curve = self._curve(text)
        self.values["n_temperatures"] = len(self.curve)
        if self.curve:
            self.values["init_t"] = self.curve[0]["T"]

    @staticmethod
    def _curve(text: str) -> list[dict[str, float]]:
        """The annealing cost-curve rows, between their header and the next blank/header line."""
        rows: list[dict[str, float]] = []
        header = re.compile(r"Tnum\s+Time\s+T\s+AvCost\s+Av BB Cost")
        rx = re.compile(r"^\s*(\d+)\s+([0-9.]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+"
                        r"([0-9.eE+-]+)\s+([0-9.eE+-]+)")
        inside = False
        for line in text.splitlines():
            if header.search(line):
                inside = True
                continue
            if not inside:
                continue
            if line.lstrip().startswith("----"):
                continue
            m = rx.match(line)
            if not m:
                if rows and not line.strip():
                    inside = False
                continue
            rows.append({"tnum": int(m.group(1)), "time": float(m.group(2)),
                         "T": float(m.group(3)), "cost": float(m.group(4)),
                         "bb_cost": float(m.group(5))})
        return rows


# ---------------------------------------------------------------------------------------
# Running

def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
        stdout: Path | None = None, timeout: int | None = None) -> int:
    ensure_dir(cwd) if cwd else None
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    if stdout is not None:
        ensure_dir(stdout.parent)
        with stdout.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(cmd, cwd=cwd, env=full_env, stdout=fh,
                                  stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return proc.returncode
    return subprocess.run(cmd, cwd=cwd, env=full_env, timeout=timeout, check=False).returncode


def vpr_command(blif: Path, extra: list[str]) -> list[str]:
    ensure_dir(LOCK.parent)
    if os.environ.get("NORNS_LOCK_HELD") == "1":
        # the caller holds the heavy lock for this whole process (scripts/round2.py chunk):
        # still one VPR at a time, the lock is taken once per chunk instead of once per run
        return [str(VPR), str(ARCH), str(blif)] + extra
    return ["flock", "-x", str(LOCK), str(VPR), str(ARCH), str(blif)] + extra


def run_vpr(blif: Path, cwd: Path, extra: list[str], log: Path,
            timeout: int | None = None) -> int:
    """One VPR run under the heavy lock; the log is the caller's record."""
    return run(vpr_command(blif, extra), cwd=cwd, stdout=log, timeout=timeout)


# ---- keep timing (purpose: Mimir fills timing_path / hdl_edge for Norns runs; hub RQ W Q3.3, speed)
KEEP_NPATHS = 1000  # --timing_report_npaths of every kept-timing VPR run (200 and 1000 give the same placement, docs/keep-timing.md)


KEEP_ARTIFACTS = (("timing_report_gz", "report_timing.setup.rpt.gz"), ("timing_attribution", "attribution.json.xz"),
                  ("keep_timing", "keep-timing.json"))  # run-record roles of the files keep_timing writes


def kept_artifacts(keep: dict[str, Any] | None) -> list[tuple[str, str]]:
    """(role, file name) of the files this run's keep_timing result says it wrote; nothing from a stale directory."""
    if not keep or not keep.get("keep_timing"):
        return []
    out = []
    if "report_bytes" in keep:
        out.append(KEEP_ARTIFACTS[0])
    if keep.get("attribution"):
        out.append(KEEP_ARTIFACTS[1])
    out.append(KEEP_ARTIFACTS[2])
    return out


def keep_timing_on() -> bool:
    """On by default; NORNS_KEEP_TIMING=0 turns it off."""
    return os.environ.get("NORNS_KEEP_TIMING", "1") != "0"


def npaths(default: int) -> int:
    """Paths a run asks VPR to report: KEEP_NPATHS with the switch on, else the caller's own number."""
    return KEEP_NPATHS if keep_timing_on() else default


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _compress(src: Path, dst: Path, opener: Any) -> int:
    ensure_dir(dst.parent)
    with src.open("rb") as fi, opener(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    return dst.stat().st_size


_HOME_RX = re.compile(r"/home/[^/\s\"':,;()<>]+")  # as mimir/scrub.py _HOME


def scrub_roots() -> list[tuple[str, str]]:
    """(root, token) pairs, longest root first. Token spellings follow the Mimir scrubber
    (mimir/mimir/structcli.py make_scrub: "$VTR_ROOT", "$WS"; mimir/mimir/scrub.py Scrubber: longest root first,
    then any other /home/<user> path). Copied here, not imported: Norns does not depend on Mimir."""
    pairs = [(str(VTR_ROOT).rstrip("/"), "$VTR_ROOT"), (str(WS_ROOT).rstrip("/"), "$WS")]
    return sorted(pairs, key=lambda x: -len(x[0]))


def scrub_text(text: str, counts: dict[str, int] | None = None) -> str:
    """Rewrite VTR root -> $VTR_ROOT, workspace root -> $WS, any other home dir -> ~ (counts: occurrences per token)."""
    for root, token in scrub_roots():
        n = text.count(root)
        if n:
            text = text.replace(root, token)
            if counts is not None:
                counts[token] = counts.get(token, 0) + n
    text, n = _HOME_RX.subn("~", text)
    if n and counts is not None:
        counts["~"] = counts.get("~", 0) + n
    return text


def _compress_scrubbed(src: Path, dst: Path, counts: dict[str, int]) -> int:
    """xz of src with scrub_text applied line by line (a path never spans lines; JSON from odin3-timing is read whole)."""
    ensure_dir(dst.parent)
    with src.open("r", encoding="utf-8", errors="surrogateescape", newline="") as fi, \
            lzma.open(dst, "wt", encoding="utf-8", errors="surrogateescape", newline="") as fo:
        for line in fi:
            fo.write(scrub_text(line, counts))
    return dst.stat().st_size


def keep_store() -> Path:
    """Where each (design, blif sha256) input pair is kept once; NORNS_KEEP_STORE overrides."""
    return Path(os.environ.get("NORNS_KEEP_STORE", str(RUNS / "_keep-inputs")))


def odin_timing_tool() -> Path:
    tree = Path(os.environ.get("NORNS_ODIN_TREE", str(ODIN3_ROOT)))
    return tree / "tools" / "flow" / "odin3-timing"


def keep_inputs(design: str, blif: Path, name_map: Path | None) -> dict[str, Any]:
    """Keep blif + name map once per (design, blif sha256) in the store; return their sha256 and sizes."""
    sha = file_sha256(blif)
    out: dict[str, Any] = {"blif_sha256": sha, "map_sha256": None}  # shas are of the original files, kept copies are path-scrubbed
    counts: dict[str, int] = {}
    out["_rewritten"] = counts
    d = keep_store() / design / sha
    if not (d / f"{design}.blif.xz").is_file():
        out["blif_bytes"] = _compress_scrubbed(blif, d / f"{design}.blif.xz", counts)
    if name_map is not None and name_map.is_file():
        out["map_sha256"] = file_sha256(name_map)
        if not (d / f"{design}.blif.names.xz").is_file():
            out["map_bytes"] = _compress_scrubbed(name_map, d / f"{design}.blif.names.xz", counts)
    return out


def _attribute(vpr_cwd: Path, design: str, blif: Path, name_map: Path, dest: Path,
               counts: dict[str, int]) -> tuple[bool, str]:
    """Run odin3-timing over a small flow directory pointing at the run; xz the attribution to dest."""
    tool = odin_timing_tool()
    if not tool.is_file():
        return False, f"odin3-timing not found at {tool.name}"
    flow = vpr_cwd / "keep-flow"
    ensure_dir(flow / "timing")
    (flow / "timing" / "inputs.json").write_text(json.dumps(
        {"top": design, "blif": str(blif), "name_map": str(name_map), "vpr_run_dir": str(vpr_cwd),
         "paths_requested": KEEP_NPATHS}, indent=1, sort_keys=True))
    r = subprocess.run([str(tool), str(flow)], capture_output=True, text=True, check=False)
    att = flow / "timing" / "attribution.json"
    if r.returncode != 0 or not att.is_file():
        return False, (r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else f"rc {r.returncode}"
    _compress_scrubbed(att, dest, counts)  # every string field, spans included
    return True, ""


def keep_timing(run_dir: Path, vpr_cwd: Path, design: str, blif: Path, name_map: Path | None = None) -> dict[str, Any]:
    """Keep the timing evidence of one finished VPR run (report gz, attribution xz, blif + name map once);
    returns the fields the caller adds to its run record, and writes them to run_dir/keep-timing.json."""
    if not keep_timing_on():
        return {"keep_timing": False}
    rec: dict[str, Any] = {"keep_timing": True, "paths_requested": KEEP_NPATHS, "paths_kept": 0,
                           "attribution": False, "blif_sha256": None, "map_sha256": None}
    ensure_dir(run_dir)
    rpt = vpr_cwd / "report_timing.setup.rpt"
    if rpt.is_file():
        rec["report_bytes"] = _compress(rpt, run_dir / "report_timing.setup.rpt.gz", gzip.open)
        rec["paths_kept"] = sum(1 for ln in rpt.read_text(errors="replace").splitlines() if ln.startswith("#Path "))
    else:
        rec["note"] = "no report_timing.setup.rpt"
    counts: dict[str, int] = {}
    if blif.is_file():
        inp = keep_inputs(design, blif, name_map)
        for k, v in inp.pop("_rewritten").items():
            counts[k] = counts.get(k, 0) + v
        rec.update(inp)
    if rec["map_sha256"] is None:
        rec["attribution_note"] = "no name map for this call site: report kept only"
    elif rpt.is_file() and name_map is not None:
        ok, why = _attribute(vpr_cwd, design, blif, name_map, run_dir / "attribution.json.xz", counts)
        rec["attribution"] = ok
        if ok:
            rec["attribution_bytes"] = (run_dir / "attribution.json.xz").stat().st_size
        else:
            rec["attribution_note"] = why
    rec["paths_rewritten"] = {t: counts.get(t, 0) for t in ("$VTR_ROOT", "$WS", "~")}
    (run_dir / "keep-timing.json").write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    return rec


def name_map_of(blif: Path) -> Path | None:
    """The Odin III name map written beside a blif (<top>.blif.names), if any."""
    m = blif.with_name(blif.name + ".names")
    return m if m.is_file() else None


def odin_env() -> dict[str, str]:
    pp = str(ODIN3_ROOT / "plugins" / "python")
    return {"ODIN3_ROOT": str(ODIN3_ROOT), "ODIN3_LIB": str(ODIN3_LIB),
            "PYTHONPATH": pp, "VTR_ROOT": str(VTR_ROOT)}


def odin_script(design: str, out_blif: Path, name_style: str = "provenance") -> str:
    src = design_verilog(design)
    style = f" --name-style {name_style}" if name_style else ""
    return ("read_arch {arch}; read_verilog --nolatches --vtr-compat {v}; proc; fsm; opt; "
            "flatten; opt -full; wreduce; hardmap; lower; abc --lut 6; stats; "
            "write_blif --vtr --lut-k 6{style} {out}").format(
                arch=ARCH, v=src, style=style, out=out_blif)


def geomean(values: list[float]) -> float:
    vals = [v for v in values if v and v > 0]
    if not vals:
        return float("nan")
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def fmt(x: Any, digits: int = 3) -> str:
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def die(msg: str) -> "NoReturn":  # noqa: F821 - typing only
    print(f"norns: {msg}", file=sys.stderr)
    raise SystemExit(2)
