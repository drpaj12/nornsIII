#!/usr/bin/env python3
"""Make IMAGE/blind/fig_yggdrasil.tex, the double-blind copy of the Yggdrasil III tree figure.

Run in docs/paper. The same mapping as the Odin III paper's make_blind.py: suite and tool names to
placeholders, the three wells to "Well 1/2/3" with neutral glosses, and every comment line dropped.
No build uses the output yet; it is there so a blind build can pick it up.
"""
import re
import sys
from pathlib import Path

SRC = Path("IMAGE/fig_yggdrasil.tex")
OUT = Path("IMAGE/blind/fig_yggdrasil.tex")

# Longest first, so "The Norns III" is replaced before "Norns III".
NAMES = [
    ("Leman~Russ~III", "AnonHT"), ("The Norns~III", "AnonPlace"), ("Norns~III", "AnonPlace"),
    ("Yggdrasil~III", "AnonSuite"), ("Wyrd~III", "AnonGUI"), ("Loki~III", "AnonRE"),
    ("Verdandi~III", "AnonTrace~III"), ("Midgard~III", "AnonGame"), ("Bifrost~III", "AnonSim"),
    ("M\\'{\\i}mir~III", "AnonData"), ("Odin~III", "AnonSynth"), ("Odin III", "AnonSynth"),
]
WELLS = [
    ("Mimisbrunnr", "Well 1"), ("Urdarbrunnr", "Well 2"), ("Hvergelmir", "Well 3"),
    ("{Mimir's well of wisdom: prior work, benchmarks}", "{prior work, benchmarks}"),
    ("{the Norns' well: FPGA CAD and its views}", "{FPGA CAD and its views}"),
    ("{the spring of all rivers: synthesis sources}", "{synthesis sources}"),
    ("Gate-Breaker", "netlist-to-RTL baseline"),
    ("\\odinsub{(verilogTown)}", "\\odinsub{(Verilog teaching game)}"),
]
THEME = ("Yggdrasil", "Wyrd", "Loki", "Midgard", "Bifrost", "Leman", "Norns", "Verdandi", "Mimir",
         "M\\'{\\i}mir", "Mimisbrunnr", "Urdarbrunnr", "Hvergelmir", "Gate-Breaker", "verilogTown",
         "Odin~III", "Odin III")


def blind(text: str) -> str:
    """Return the blind copy of the figure source."""
    text = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("%")) + "\n"
    for old, new in NAMES + WELLS:
        text = text.replace(old, new)
    return re.sub(r"\\input\{IMAGE/fig_", r"\\input{IMAGE/blind/fig_", text)


def main() -> int:
    text = blind(SRC.read_text())
    for bad in THEME:
        if bad in text:
            i = text.index(bad)
            print("leak: " + text[max(0, i - 60):i + 40])
            return 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
