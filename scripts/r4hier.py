"""RQ-N13 hierarchy measures per design (docs/plan/round4.md): from the provenance module paths of the logic atoms.

  python scripts/r4hier.py [design ...]       writes data/<d>/r4hier.json

M modules (distinct module instance paths), D depth (path components), A_med median atoms per module, S logic
atoms, and a per-level Rent exponent: at level l the atoms are grouped by the first l components of their module
path; B = atoms in the group, T = nets with a pin inside and a pin outside the group (primary inputs and outputs
count as outside); log T = log t + p log B by least squares over the groups with B >= 2 and T >= 1; a level
counts when it has >= 4 such groups.
"""

from __future__ import annotations

import collections
import math
import statistics
import sys

import r4census as rc

import nornlib as nl


def path_prefix(path: str, level: int) -> str:
    parts = [p for p in path.split("/") if p]
    return "/".join(parts[:level])


def rent_fit(points: list[tuple[int, int]]) -> float | None:
    xs = [math.log(b) for b, _ in points]
    ys = [math.log(t) for _, t in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den


def measure(design: str) -> dict:
    nlist = rc.Netlist(design)
    atoms = sorted(nlist.kind)
    mod = {a: nl.module_of(a) for a in atoms}
    counts = collections.Counter(m for m in mod.values() if m)  # atoms without a module path are top-level
    depth = max((len([p for p in m.split("/") if p]) for m in counts), default=0)
    res: dict = {"design": design, "S": len(atoms), "M": max(len(counts), 1), "D": depth,
                 "top_level_atoms": sum(1 for m in mod.values() if not m),
                 "A_med": statistics.median(counts.values()) if counts else len(atoms), "rent": {}}
    # pins of each net: driver + sinks, restricted to the atoms we know (others are 'outside')
    for level in range(1, depth + 1):
        grp = {a: path_prefix(mod[a], level) for a in atoms}
        size = collections.Counter(grp.values())
        terms: collections.Counter = collections.Counter()
        for net, sinks in nlist.sinks.items():
            members = {grp[s] for s in sinks if s in grp}
            d = nlist.driver.get(net)
            if d in grp:
                members.add(grp[d])
            outside = any(s not in grp for s in sinks) or d not in grp
            for g in members:
                if outside or len(members) > 1:
                    terms[g] += 1
        pts = [(size[g], terms[g]) for g in size if size[g] >= 2 and terms[g] >= 1]
        if len(pts) >= 4:
            res["rent"][str(level)] = {"groups": len(pts), "p": rent_fit(pts)}
    return res


def run(designs: list[str]) -> int:
    for design in designs:
        res = measure(design)
        nl.write_json(nl.DATA / design / "r4hier.json", res)
        print(design, {k: res[k] for k in ("S", "M", "D", "A_med")}, res["rent"], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or list(nl.DESIGN_ORDER)))
