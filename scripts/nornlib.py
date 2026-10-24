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

import json
import math
import os
import re
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
VTR_ROOT = Path(os.environ.get("VTR_ROOT", "/home/jamiespa/odin3-ws/external/vtr-verilog-to-routing"))
VPR = VTR_ROOT / "build" / "vpr" / "vpr"
ARCH = VTR_ROOT / "vtr_flow" / "arch" / "timing" / "k6_frac_N10_frac_chain_mem32K_40nm.xml"
BENCH = VTR_ROOT / "vtr_flow" / "benchmarks" / "verilog"
ODIN3_ROOT = Path(os.environ.get("ODIN3_ROOT", "/home/jamiespa/odin3-ws/odin3"))
ODIN3 = ODIN3_ROOT / "build" / "release" / "odin3"
ODIN3_LIB = ODIN3_ROOT / "build" / "release" / "libodin3.so"
LOCK = Path("/tmp/claude-1000/odin3-heavy.lock")
RUNS = WS / "runs"
DATA = WS / "data"


def design_verilog(design: str) -> Path:
    return BENCH / f"{design}.v"


def runs_dir(design: str, *parts: str) -> Path:
    return RUNS.joinpath(design, *parts)


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
                           "inputs": list(pins.values()), "model": model_name, "rows": []})
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
        rows: list[dict[str, float]] = []
        rx = re.compile(r"^\s*(\d+)\s+([0-9.]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+"
                        r"([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)")
        for line in text.splitlines():
            m = rx.match(line)
            if not m:
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
    return ["flock", "-x", str(LOCK), str(VPR), str(ARCH), str(blif)] + extra


def run_vpr(blif: Path, cwd: Path, extra: list[str], log: Path,
            timeout: int | None = None) -> int:
    """One VPR run under the heavy lock; the log is the caller's record."""
    return run(vpr_command(blif, extra), cwd=cwd, stdout=log, timeout=timeout)


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
