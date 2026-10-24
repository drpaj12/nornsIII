"""Front end: Odin III O leg -> provenance BLIF per design (VTR dialect, K=6).

Usage: python scripts/frontend.py [design ...]
Writes runs/<design>/netlist/<design>.blif and .log; records module count from the stats log.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import nornlib as nl


def module_count(log: Path) -> int | None:
    text = log.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"stats: design: modules (\d+), top (\S+)", text)
    return int(m.group(1)) if m else None


def build(design: str) -> None:
    out = nl.runs_dir(design, "netlist", f"{design}.blif")
    nl.ensure_dir(out.parent)
    log = nl.runs_dir(design, "netlist", "frontend.log")
    rc = nl.run([str(nl.ODIN3), "-p", nl.odin_script(design, out)],
                cwd=out.parent, env=nl.odin_env(), stdout=log)
    if rc != 0 or not out.is_file():
        print(f"{design}: FRONTEND FAIL rc={rc} (see {log})")
        return
    count = module_count(log)
    info = nl.runs_dir(design, "netlist", "info.json")
    nl.write_json(info, {"design": design, "modules": count, "blif": str(out),
                         "blif_sha256": __import__("hashlib").sha256(out.read_bytes()).hexdigest()})
    print(f"{design}: ok modules={count}")


def main(argv: list[str]) -> int:
    designs = argv or list(nl.DESIGN_ORDER)
    for design in designs:
        build(design)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
