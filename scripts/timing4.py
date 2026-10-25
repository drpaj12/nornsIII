"""Critical-path attribution of a Norns run directory (round 4), through the Odin III V1.1.1 library.

WORKAROUND, labelled (docs/plan/round4.md "Odin III attribution"): `odin3-timing` / `odin3.timing_attribution`
read an `odin3-flow --timing-attr` directory: a short-name BLIF that VPR reads, a provenance-name BLIF of the
same run (`timing/prov.blif`) and `timing/inputs.json`. The Norns BLIFs are already written with
provenance names, so VPR's atoms carry them and there is no short BLIF to pair. This module builds the
name map from the Norns BLIF itself (a provenance-named net maps to its own hierarchy, file and line),
reads VPR's `report_timing.setup.rpt`, and calls the V1.1.1 functions `timing_report.read_report`,
`timing_attr.Resolver` and `timing_attr.build_report` unchanged. It uses `write_json --odin3` of the same Odin III script (`ensure_json`) for the port-named atoms. The odin3 checkout is imported, never edited.

Usage: python scripts/timing4.py RUN_DIR BLIF [--out FILE]     (RUN_DIR holds report_timing.setup.rpt, vpr.out)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import nornlib as nl

FLOW = Path(os.environ.get("ODIN3_ROOT", str(nl.ODIN3_ROOT))) / "tools" / "flow"
if str(FLOW) not in sys.path:
    sys.path.insert(0, str(FLOW))

import timing_attr as ta  # noqa: E402  (the Odin III V1.1.1 tool)
import timing_report as tr  # noqa: E402


def identity_name_map(blif: Path) -> "ta.NameMap":
    """Every provenance-named net of the BLIF maps to its own (hierarchy, net, file, line)."""
    result = ta.NameMap()
    for line in ta.logical_lines(blif):
        tok = line.split()
        if tok[0] == ".inputs":
            result.inputs.update(tok[1:])
        elif tok[0] == ".outputs":
            result.outputs.update(tok[1:])
        elif tok[0] in (".names", ".latch", ".subckt"):
            result.blocks += 1
        for item in tok[1:]:
            net = ta.net_of(item)
            ta.record_name(result, net, net, blif.name)
    return result


def top_of(blif: Path) -> str | None:
    for line in ta.logical_lines(blif):
        if line.startswith(".model"):
            return line.split()[1]
    return None


def ensure_json(design: str) -> Path | None:
    """`write_json --odin3` of the design's Odin III session (the file the V1.1.1 tool uses for port-named atoms),
    from the identical script that wrote the kept BLIF; used only when that BLIF is reproduced byte for byte."""
    out = nl.runs_dir(design, "netlist", "netlist.odin3.json")
    if out.is_file():
        return out
    import hashlib
    kept = nl.runs_dir(design, "netlist", f"{design}.blif")
    tmp = nl.runs_dir(design, "netlist", "rerun.blif")
    script = nl.odin_script(design, tmp) + f"; write_json --odin3 {out}"
    rc = nl.run([str(nl.ODIN3), "-p", script], cwd=out.parent, env=nl.odin_env(), stdout=out.parent / "json.log")
    same = rc == 0 and tmp.is_file() and hashlib.sha256(tmp.read_bytes()).digest() == hashlib.sha256(kept.read_bytes()).digest()
    tmp.unlink(missing_ok=True)
    if not same:
        out.unlink(missing_ok=True)
        return None
    return out


def attribute(run_dir: Path, blif: Path, paths: int | None = None, netlist_json: Path | None = None) -> dict:
    """The attribution dict of one VPR run (schema of docs/user/timing-attribution.md)."""
    report = tr.read_report(run_dir / "report_timing.setup.rpt")
    logs = [(run_dir / n).read_text(errors="replace") for n in ("vpr.crit_path.out", "vpr.out")
            if (run_dir / n).is_file()]
    top = top_of(blif)
    names = identity_name_map(blif)
    kept = report.paths[:paths] if paths else report.paths
    index = ta.load_json_index(netlist_json, top) if netlist_json else None
    meta = {"top": top, "flow_dir": str(run_dir), "report": str(run_dir / "report_timing.setup.rpt"),
            "blif": str(blif), "provenance_blif": str(blif),
            "netlist_json": str(netlist_json) if netlist_json and netlist_json.is_file() else None}
    counts = ta.PathCounts(None, paths, len(report.paths), report.skipped)
    sources = ta.SourceFiles([run_dir], [])
    return ta.build_report(kept, ta.Resolver(names, index, top), tr.final_cpd(logs), meta, counts, sources)


def main(argv: list[str]) -> int:
    run_dir, blif = Path(argv[0]), Path(argv[1])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else run_dir / "attribution.json"
    report = attribute(run_dir, blif)
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(ta.summary_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
