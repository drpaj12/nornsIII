"""Keep the benchmark sizes (post-techmap CLBs and auto-sized grid) as small data.

runs/ is local, so the paper's tab:benchmarks reads this committed extraction instead of the
run logs. Per design, from the baseline vpr.out: the packed CLB, I/O, memory and mult_36 block
counts, the total placeable blocks (``Netlist num_blocks``), and the device grid VPR auto-sizes
from the packed netlist. The packed netlist is the same in every run of a design, so if the
baseline log is missing a cold run's log is used and the entry records which one.

Writes data/benchmark-sizes.json, the source ``scripts/fill_paper.py`` turns into the table rows.

Usage: python scripts/benchmark_sizes.py [design ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import nornlib as nl

GRID = re.compile(r"FPGA sized to (\d+) x (\d+): (\d+) grid tiles")
BLOCKS = re.compile(r"Netlist num_blocks: (\d+)")
PACKED = {
    "clbs": re.compile(r"Netlist clb blocks: (\d+)\."),
    "io": re.compile(r"Netlist io blocks: (\d+)\."),
    "memory": re.compile(r"Netlist memory blocks: (\d+)\."),
    "mult_36": re.compile(r"Netlist mult_36 blocks: (\d+)\."),
}


def log_of(design: str) -> Path | None:
    """The baseline log, or a cold run's log (same netlist -> same packed counts)."""
    baseline = nl.runs_dir(design, "runs", "baseline", "vpr.out")
    if baseline.is_file():
        return baseline
    cold = sorted(nl.runs_dir(design, "runs").glob("cold-*/vpr.out"))
    if cold:
        return cold[0]
    return None


def parse(design: str) -> dict[str, object] | None:
    log = log_of(design)
    if log is None:
        print(f"{design}: no vpr.out (run scripts/matrix.py baseline first)")
        return None
    text = log.read_text(encoding="utf-8", errors="replace")
    grid = GRID.search(text)
    blocks = BLOCKS.search(text)
    packed = {key: rx.search(text) for key, rx in PACKED.items()}
    if not grid or not blocks or not all(packed.values()):
        print(f"{design}: vpr.out is missing the packed netlist or grid lines ({log})")
        return None
    gx, gy, tiles = (int(v) for v in grid.groups())
    entry: dict[str, object] = {
        "suite": "VTR 8.0",
        "blocks": int(blocks.group(1)),
        "grid": [gx, gy],
        "tiles": tiles,
        "source": str(log.relative_to(nl.WS)),
    }
    entry.update({key: int(m.group(1)) for key, m in packed.items()})
    return entry


def main(argv: list[str]) -> int:
    designs = argv or list(nl.DESIGN_ORDER)
    out: dict[str, object] = {
        "designs": {},
        "note": "Extracted by scripts/benchmark_sizes.py from each design's baseline "
                "runs/<design>/runs/baseline/vpr.out (or a cold run's log when the baseline "
                "is missing); runs/ is local, this file is the committed copy.",
    }
    for design in designs:
        entry = parse(design)
        if entry is not None:
            out["designs"][design] = entry
            print(f"{design}: {entry['clbs']} CLBs, {entry['grid'][0]}x{entry['grid'][1]}")
    nl.write_json(nl.DATA / "benchmark-sizes.json", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
