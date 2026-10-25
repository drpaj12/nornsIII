"""RQ-N17 packing census, part 1 (docs/plan/round4.md): read the packer census of a pack-and-place run
(`--norns_pack_census`), classify every logic-CLB member pair, weight, and write
data/<d>/r4census.json.

  python scripts/r4census.py [design ...]       needs runs/<d>/r4/census-<arm>/ (scripts/round4.py census)

Census records (tab separated, written by the Norns packer, log-only):
  M cseq idx kind source natoms qgain norns_bonus attr_gain base_gain dom_group root   a molecule added
  A cseq idx atom sharing connection timing gain                                       its atoms, gain terms
  P cseq atom net crit                                                                 pack-time criticality per input pin
  Q cseq root source gain                                                              a molecule queued as a candidate
  F cseq root source status                                                            a candidate the legalizer refused
  K cseq n_added n_proposed queue_left                                                 the cluster closed
Pair classes (first rule that applies): SC series-critical, SN series-noncritical, SI shared-input,
OR orthogonal, FL filler; definitions with numbers in docs/plan/round4.md.
"""

from __future__ import annotations

import collections
import random
import re
import statistics
import sys
from pathlib import Path

import affinity as af
import nornlib as nl
import r3lib

ARMS = ("stock", "r3", "r4")
CLASSES = ("SC", "SN", "SI", "OR", "FL")
FANOUT_LOCAL = 32
THETA_C = 0.5
NULL_SAMPLES = 50
SOURCES = {0: "seed", 1: "connectivity_timing", 2: "affinity_group", 3: "transitive", 4: "high_fanout",
           5: "attraction_group", 6: "ram", 7: "unrelated", -1: "unknown"}
STATUS = {0: "passed", 1: "feasible", 2: "route", 3: "floorplan", 4: "noc_group"}
MEMBER_KINDS = ("lut", "latch", "adder")


def census_dir(design: str, arm: str) -> Path:
    return nl.runs_dir(design, "r4", f"census-{arm}")


# ---------------------------------------------------------------------------------------
# census file

class Census:
    """The parsed census of one run."""

    def __init__(self, path: Path):
        self.mol: dict[tuple[int, int], dict] = {}
        self.atoms_of: dict[tuple[int, int], list[str]] = collections.defaultdict(list)
        self.pin_crit: dict[str, dict[str, float]] = collections.defaultdict(dict)  # atom -> net -> crit
        self.queued: dict[int, set[str]] = collections.defaultdict(set)
        self.failed: dict[int, dict[str, set[int]]] = collections.defaultdict(lambda: collections.defaultdict(set))
        self.failed_n: dict[int, int] = collections.defaultdict(int)
        self.closed: dict[int, dict] = {}
        self.fail_status = collections.Counter()
        self.pin_latest: dict[str, int] = {}
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                t = f[0]
                if t == "M":
                    key = (int(f[1]), int(f[2]))
                    self.mol[key] = {"kind": f[3], "source": int(f[4]), "natoms": int(f[5]), "qgain": float(f[6]),
                                     "bonus": float(f[7]), "attr": float(f[8]), "base": float(f[9]),
                                     "dom": int(f[10]), "root": f[11]}
                elif t == "A":
                    key = (int(f[1]), int(f[2]))
                    self.atoms_of[key].append(f[3])
                    self.mol[key].setdefault("terms", []).append((float(f[4]), float(f[5]), float(f[6]), float(f[7])))
                elif t == "P":
                    cseq, atom, net, crit = int(f[1]), f[2], f[3], float(f[4])
                    if self.pin_latest.get(atom, 0) <= cseq:
                        if self.pin_latest.get(atom) != cseq:
                            self.pin_crit[atom] = {}
                        self.pin_latest[atom] = cseq
                        self.pin_crit[atom][net] = max(crit, self.pin_crit[atom].get(net, 0.0))
                elif t == "Q":
                    self.queued[int(f[1])].add(f[2])
                elif t == "F":
                    cseq = int(f[1])
                    self.failed[cseq][f[2]].add(int(f[4]))
                    self.failed_n[cseq] += 1
                    self.fail_status[int(f[4])] += 1
                elif t == "K":
                    self.closed[int(f[1])] = {"added": int(f[2]), "proposed": int(f[3]), "queue_left": int(f[4])}
        # final cluster of an atom: the latest closed cluster that added it (a destroyed cluster has no K)
        self.cseq_of: dict[str, int] = {}
        self.root_of: dict[str, str] = {}
        for (cseq, idx) in sorted(self.mol):
            if cseq in self.closed:
                for a in self.atoms_of[(cseq, idx)]:
                    self.cseq_of[a] = cseq
                    self.root_of[a] = self.mol[(cseq, idx)]["root"]

    def sources(self, only: set[int]) -> dict:
        """Per source: molecules added to the clusters `only` (the logic CLBs), mean queue-time gain and terms."""
        out: dict[str, dict] = {}
        for (cseq, idx), m in self.mol.items():
            if cseq not in only:
                continue
            name = SOURCES.get(m["source"], "unknown")
            row = out.setdefault(name, {"molecules": 0, "atoms": 0, "qgain": 0.0, "sharing": 0.0, "connection": 0.0,
                                        "timing": 0.0, "bonus_pos": 0, "attr_pos": 0, "natom_terms": 0})
            row["molecules"] += 1
            row["atoms"] += m["natoms"]
            row["qgain"] += m["qgain"]
            row["bonus_pos"] += 1 if m["bonus"] > 0 else 0
            row["attr_pos"] += 1 if m["attr"] > 0 else 0
            for sh, co, ti, _g in m.get("terms", []):
                row["sharing"] += sh
                row["connection"] += co
                row["timing"] += ti
                row["natom_terms"] += 1
        res = {}
        for name, r in out.items():
            n = max(r["molecules"], 1)
            k = max(r["natom_terms"], 1)
            res[name] = {"molecules": r["molecules"], "atoms": r["atoms"], "mean_queue_gain": r["qgain"] / n,
                         "mean_sharing": r["sharing"] / k, "mean_connection": r["connection"] / k,
                         "mean_timing": r["timing"] / k, "affinity_bonus_share": r["bonus_pos"] / n,
                         "attraction_share": r["attr_pos"] / n}
        return res


# ---------------------------------------------------------------------------------------
# netlist relations

class Netlist:
    """Relations of the logic atoms of the BLIF: local direct nets, shared inputs, broadcast nets, words."""

    def __init__(self, design: str):
        blif = nl.runs_dir(design, "netlist", f"{design}.blif")
        arch = nl.arch_output_ports(nl.ARCH)
        parsed = nl.parse_blif(blif, None, arch)
        self.kind: dict[str, str] = {}
        driver: dict[str, str] = {}
        sinks: dict[str, list[str]] = collections.defaultdict(list)
        clocks = self._clock_nets(blif)
        # buffer LUTs that VPR absorbs are not atoms: the net they drive is the net they read
        absorbed = af.absorbed_buffers(parsed)
        gone = absorbed | af.swept_blocks(parsed, arch, absorbed)
        alias = {str(b["name"]): b["inputs"][0] for b in parsed["blocks"] if str(b["name"]) in absorbed}

        def res(net: str) -> str:
            seen = 0
            while net in alias and seen < 1000:
                net = alias[net]
                seen += 1
            return net

        for b in parsed["blocks"]:
            name = str(b["name"])
            if name in gone:
                continue
            b = dict(b, inputs=[res(n) for n in b["inputs"]],
                     pins={f: res(n) for f, n in b.get("pins", {}).items()} if "pins" in b else None)
            if b["pins"] is None:
                del b["pins"]
            if b["kind"] == "hard":
                outputs = arch.get(b.get("model", ""), set())
                if b.get("model") == "adder":
                    self.kind[name] = "adder"
                for formal, net in b.get("pins", {}).items():
                    if formal.split("[")[0] in outputs:
                        driver[net] = name
                    elif net not in clocks:
                        sinks[net].append(name)
            elif b["kind"] in ("lut", "latch"):
                self.kind[name] = b["kind"]
                driver[name] = name
                for net in b["inputs"]:
                    if net not in clocks:
                        sinks[net].append(name)
        for net in parsed["outputs"]:
            sinks[res(net)].append("<pad>")
        self.fanout = {n: len(s) for n, s in sinks.items()}
        self.driver = driver
        self.sinks = sinks
        # relations among member atoms
        self.series: dict[tuple[str, str], list[str]] = {}  # (driver, sink) -> nets
        self.shared: set[tuple[str, str]] = set()
        self.bcast: dict[str, set[str]] = collections.defaultdict(set)
        for net, ss in sinks.items():
            d = driver.get(net)
            mem = sorted({s for s in ss if s in self.kind})
            if len(ss) <= FANOUT_LOCAL:
                if d in self.kind:
                    for s in mem:
                        if s != d:
                            self.series.setdefault((d, s), []).append(net)
                for i, a in enumerate(mem):
                    for b in mem[i + 1:]:
                        self.shared.add((a, b))
            else:
                for s in mem:
                    self.bcast[s].add(net)
        self.word = self._words(design)

    @staticmethod
    def _clock_nets(blif: Path) -> set[str]:
        clocks: set[str] = set()
        for line in nl.logical_lines(blif):
            tok = line.split()
            if tok and tok[0] == ".latch" and len(tok) >= 5 and tok[3] in ("re", "fe", "ah", "al", "as"):
                clocks.add(tok[4])
            elif tok and tok[0] == ".subckt":
                for item in tok[2:]:
                    if "=" in item:
                        formal, actual = item.split("=", 1)
                        if formal.lower().startswith("clk") or formal.lower() == "clock":
                            clocks.add(actual)
        return clocks

    @staticmethod
    def _words(design: str) -> dict[str, str]:
        members = nl.read_json(nl.runs_dir(design, "words", "members.json"))
        return {a: m["word"] for a, m in members.items() if m.get("word")}


def classify(nlist: Netlist, crit: dict[str, dict[str, float]], a: str, b: str) -> str:
    """Pair class of atoms a, b (a < b not required)."""
    best = None
    for d, s in ((a, b), (b, a)):
        nets = nlist.series.get((d, s))
        if nets:
            c = max(crit.get(s, {}).get(n, 0.0) for n in nets)
            best = c if best is None else max(best, c)
    if best is not None:
        return "SC" if best >= THETA_C else "SN"
    key = (a, b) if a < b else (b, a)
    if key in nlist.shared:
        return "SI"
    wa, wb = nlist.word.get(a), nlist.word.get(b)
    if (wa is not None and wa == wb) or (nlist.bcast.get(a, set()) & nlist.bcast.get(b, set())):
        return "OR"
    return "FL"


def atom_crit(crit: dict[str, dict[str, float]], a: str) -> float:
    d = crit.get(a)
    return max(d.values()) if d else 0.0


def shares(counts: collections.Counter, total: float) -> dict[str, float]:
    return {c: (counts[c] / total if total else 0.0) for c in CLASSES}


def pair_stats(nlist: Netlist, crit: dict, groups: dict[str, list[str]]) -> dict:
    cnt: collections.Counter = collections.Counter()
    w1: collections.Counter = collections.Counter()
    w1_total = 0.0
    n = 0
    for atoms in groups.values():
        k = len(atoms)
        for i in range(k):
            for j in range(i + 1, k):
                a, b = atoms[i], atoms[j]
                c = classify(nlist, crit, a, b)
                w = min(atom_crit(crit, a), atom_crit(crit, b))
                cnt[c] += 1
                w1[c] += w
                w1_total += w
                n += 1
    return {"pairs": n, "counts": {c: cnt[c] for c in CLASSES}, "share": shares(cnt, n),
            "share_w1": shares(w1, w1_total), "w1_total": w1_total}


def null_stats(design: str, arm: str, nlist: Netlist, crit: dict, groups: dict[str, list[str]]) -> dict:
    """NULL_SAMPLES packings: the same logic atoms assigned at random to CLBs of the same sizes."""
    sizes = [len(a) for a in groups.values()]
    atoms = sorted(a for g in groups.values() for a in g)
    rows = []
    for k in range(NULL_SAMPLES):
        rng = random.Random(f"{design}-{arm}-null-{k}-20261025")
        order = atoms[:]
        rng.shuffle(order)
        pos = 0
        fake: dict[str, list[str]] = {}
        for i, sz in enumerate(sizes):
            fake[str(i)] = order[pos:pos + sz]
            pos += sz
        rows.append(pair_stats(nlist, crit, fake)["share"])
    mean = {c: statistics.fmean(r[c] for r in rows) for c in CLASSES}
    sd = {c: (statistics.pstdev([r[c] for r in rows]) if len(rows) > 1 else 0.0) for c in CLASSES}
    return {"samples": NULL_SAMPLES, "mean": mean, "sd": sd}


PROP = re.compile(r"Norns proposals: (\d+) calls, (\d+) with 0 queued, (\d+) molecules attempted, (\d+) queued")


def analyse(design: str, arm: str, nlist: Netlist) -> dict | None:
    d = census_dir(design, arm)
    cpath, flat = d / "census.tsv", d / "final.flat_place"
    if not cpath.is_file() or not flat.is_file():
        return None
    cen = Census(cpath)
    atoms_of_clb, cls = r3lib.clb_atoms_of(flat)
    groups = {c: sorted(a for a in atoms_of_clb[c] if a in nlist.kind) for c, k in cls.items() if k == "logic"}
    groups = {c: a for c, a in groups.items() if len(a) >= 1}
    # census / final packing consistency: CLBs whose members all come from one closed census cluster
    same = sum(1 for a in groups.values() if len({cen.cseq_of.get(x) for x in a}) == 1 and cen.cseq_of.get(a[0]))
    ps = pair_stats(nlist, cen.pin_crit, groups)
    nl_stats = null_stats(design, arm, nlist, cen.pin_crit, groups)
    logic_cseqs = {cen.cseq_of[a] for g in groups.values() for a in g if a in cen.cseq_of}
    rej_c: collections.Counter = collections.Counter()
    for cseq in logic_cseqs:
        for statuses in cen.failed.get(cseq, {}).values():
            for st in statuses:
                rej_c[STATUS.get(st, str(st))] += 1
    rej = dict(sorted(rej_c.items()))
    n_closed = max(len(logic_cseqs), 1)
    prop = None
    log = d / "vpr.out"
    if log.is_file():
        m = PROP.search(log.read_text(errors="replace"))
        if m:
            c, z, att, que = (int(x) for x in m.groups())
            prop = {"calls": c, "calls_zero_queued": z, "attempted": att, "queued": que,
                    "hit_rate": que / att if att else None,
                    "zero_share": z / c if c else None}
    return {"arm": arm, "logic_clbs": len(groups), "members": sum(len(a) for a in groups.values()),
            "census_clusters": len(cen.closed), "logic_clusters": len(logic_cseqs),
            "census_destroyed": len({k[0] for k in cen.mol} - set(cen.closed)),
            "clbs_single_census_cluster": same, "pairs": ps, "null": nl_stats, "sources": cen.sources(logic_cseqs),
            "rejections": rej, "rejections_per_cluster": sum(rej.values()) / n_closed,
            "queued_per_cluster": statistics.fmean(len(cen.queued[c]) for c in logic_cseqs) if logic_cseqs else 0.0,
            "proposals": prop}


def run(designs: list[str]) -> int:
    for design in designs:
        nlist = Netlist(design)
        out: dict = {"design": design, "arms": {}}
        for arm in ARMS:
            res = analyse(design, arm, nlist)
            if res:
                out["arms"][arm] = res
                s = res["pairs"]["share"]
                print(f"{design} {arm}: clbs={res['logic_clbs']} pairs={res['pairs']['pairs']} "
                      + " ".join(f"{c}={s[c]:.3f}" for c in CLASSES), flush=True)
        nl.write_json(nl.DATA / design / "r4census.json", out)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or list(nl.DESIGN_ORDER)))
