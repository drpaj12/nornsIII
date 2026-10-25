"""RQ-N17 part 2: near-critical paths, splits across CLBs and the post-route weighting
(docs/plan/round4.md), from the routed Stage-2b runs (seed 1) and the census of the same packing.

  python scripts/r4near.py [design ...]       writes data/<d>/r4near.json
                                              needs runs/<d>/r4/<pack>.analytic.s1/ and runs/<d>/r4/census-<arm>/

pack stock <-> census arm stock; pack norns <-> census arm r4. The routed run's `.net` hash must equal the census
run's (recorded in both metrics.json files), else the design/arm is marked "packing differs" and not used.
"""

from __future__ import annotations

import collections
import gzip
import json
import sys

import nornlib as nl
import r3lib
import r4census as rc

MARGINS = (0.05, 0.10)
MEMBER_TYPES = (".names", ".latch", "adder")
PAIRS = (("stock", "stock"), ("norns", "r4"))
NPATHS = 1000


def load_paths(design: str, pack: str, seed: int = 1) -> list[dict]:
    d = nl.runs_dir(design, "r4", f"{pack}.analytic.s{seed}")
    with gzip.open(d / "paths.json.gz", "rt") as fh:
        data: list[dict] = json.load(fh)
    return data


def reason(cen: "rc.Census", cseq_a: int | None, cseq_b: int | None, atom_a: str, atom_b: str) -> str:
    """Why atoms a, b of different clusters were not together (R1 refused by the legalizer, R2 queued and not
    taken, R3 never proposed, R0 no census record). C = the earlier cluster; u = the atom in the later one."""
    if not cseq_a or not cseq_b:
        return "R0"
    early, late, u = (cseq_a, cseq_b, atom_b) if cseq_a < cseq_b else (cseq_b, cseq_a, atom_a)
    root = cen.root_of.get(u)
    if root is None:
        return "R0"
    if cen.failed.get(early, {}).get(root, set()) & {1, 2}:
        return "R1"
    if root in cen.queued.get(early, set()):
        return "R2"
    return "R3"


def analyse(design: str, pack: str, arm: str, nlist: "rc.Netlist") -> dict | None:
    run = nl.runs_dir(design, "r4", f"{pack}.analytic.s1")
    cdir = rc.census_dir(design, arm)
    if not (run / "paths.json.gz").is_file() or not (cdir / "census.tsv").is_file():
        return None
    rm, cm = nl.read_json(run / "metrics.json"), nl.read_json(cdir / "metrics.json")
    differs = bool(rm.get("net_sha256") and cm.get("net_sha256") and rm["net_sha256"] != cm["net_sha256"])
    paths = load_paths(design, pack)
    cen = rc.Census(cdir / "census.tsv")
    atoms_of_clb, cls = r3lib.clb_atoms_of(run / "final.flat_place")
    clb_of = {a: c for c, atoms in atoms_of_clb.items() if cls.get(c) == "logic" for a in atoms}
    groups = {c: sorted(a for a in atoms_of_clb[c] if a in nlist.kind) for c, k in cls.items() if k == "logic"}
    groups = {c: a for c, a in groups.items() if a}
    # clb -> census cluster (plurality of its members)
    cseq_of_clb = {}
    for c, atoms in groups.items():
        cnt = collections.Counter(cen.cseq_of.get(a) for a in atoms if cen.cseq_of.get(a))
        cseq_of_clb[c] = cnt.most_common(1)[0][0] if cnt else None
    a1 = paths[0]["arrival"]
    rho: dict[str, float] = {}
    for p in paths:
        r = p["arrival"] / a1 if a1 else 0.0
        for n in p["nodes"]:
            if r > rho.get(n[0], 0.0):
                rho[n[0]] = r
    out: dict = {"design": design, "pack": pack, "arm": arm, "packing_differs": differs, "paths_in_report": len(paths),
                 "cpd_arrival_ns": a1, "margins": {}}
    # crossing rate of all member-member net edges (local nets, driver to sink, both in logic CLBs)
    edges = cross = 0
    for (d, s) in nlist.series:
        cd, cs = clb_of.get(d), clb_of.get(s)
        if cd is not None and cs is not None:
            edges += 1
            cross += 1 if cd != cs else 0
    out["edge_crossing"] = {"edges": edges, "crossings": cross, "rate": cross / edges if edges else None}
    for m in MARGINS:
        near = [p for p in paths if p["arrival"] >= (1 - m) * a1]
        hops = crossings = split = 0
        reasons: collections.Counter = collections.Counter()
        for p in near:
            nodes = p["nodes"]
            ncross = 0
            for x, y in zip(nodes, nodes[1:], strict=False):
                if x[1] in MEMBER_TYPES and y[1] in MEMBER_TYPES:
                    cx, cy = clb_of.get(x[0]), clb_of.get(y[0])
                    if cx is None or cy is None:
                        continue
                    hops += 1
                    if cx != cy:
                        ncross += 1
                        reasons[reason(cen, cseq_of_clb.get(cx), cseq_of_clb.get(cy), x[0], y[0])] += 1
            crossings += ncross
            split += 1 if ncross else 0
        out["margins"][f"{m:g}"] = {"k": len(near), "capped": bool(len(paths) >= NPATHS and len(near) == len(paths)),
                                    "split": split, "hops": hops, "crossings": crossings,
                                    "hop_crossing_rate": crossings / hops if hops else None,
                                    "reasons": {r: reasons[r] for r in ("R1", "R2", "R3", "R0")}}
    # post-route weighted shares (w2): pair weight = min(rho_a, rho_b)
    crit = cen.pin_crit
    w2: collections.Counter = collections.Counter()
    tot = 0.0
    for atoms in groups.values():
        for i in range(len(atoms)):
            for j in range(i + 1, len(atoms)):
                a, b = atoms[i], atoms[j]
                w = min(rho.get(a, 0.0), rho.get(b, 0.0))
                if w:
                    w2[rc.classify(nlist, crit, a, b)] += w
                    tot += w
    out["share_w2"] = rc.shares(w2, tot)
    out["w2_total"] = tot
    out["atoms_on_reported_paths"] = len(rho)
    return out


def run(designs: list[str]) -> int:
    for design in designs:
        nlist = rc.Netlist(design)
        res: dict = {"design": design, "arms": {}}
        for pack, arm in PAIRS:
            r = analyse(design, pack, arm, nlist)
            if r:
                res["arms"][pack] = r
                m = r["margins"]["0.1"]
                print(f"{design} {pack}: k10={m['k']} split={m['split']} rate={m['hop_crossing_rate']} "
                      f"edge_rate={r['edge_crossing']['rate']} differs={r['packing_differs']}", flush=True)
        nl.write_json(nl.DATA / design / "r4near.json", res)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or list(nl.DESIGN_ORDER)))
