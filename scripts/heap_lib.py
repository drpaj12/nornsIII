"""Critical-heap lane (docs/plan/critical-heap.md): pure helpers, no database or file access except parse_census.

Terms. A run is one (design, seed) of the keep sweep. rc(atom) = the largest `crit` over the reported (<= 1000) setup paths that
contain the atom: the post-route criticality, a lower bound of the true value (an atom in no reported path has rc <= last_crit).
pc(atom) = the pack-time criticality: the largest `P` record value over the atom's input pins at the moment the atom was packed
(VPR's pre-cluster timing, which is updated as clusters close). The heap at threshold t = the atoms with crit >= t.
"""
from __future__ import annotations

import collections
import random
from pathlib import Path

THRS = (0.90, 0.95, 0.99)


def innermost_kind(structs):
    """structs: iterable of (kind, atoms). Each atom gets the kind of the smallest structure that contains it (ties: kind name order)."""
    best = {}
    for kind, atoms in sorted(structs, key=lambda s: (len(s[1]), s[0])):
        for a in atoms:
            if a not in best:
                best[a] = kind
    return best


def enrichment(near_k, near_tot, base_k, base_tot):
    """(share of the heap in kind k) / (share of all atoms in kind k); None when undefined."""
    if near_tot <= 0 or base_k <= 0 or base_tot <= 0:
        return None
    return (near_k / near_tot) / (base_k / base_tot)


def quantile(sorted_vals, q):
    n = len(sorted_vals)
    if n == 0:
        return None
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def median(vals):
    return quantile(sorted(vals), 0.5)


def boot_median(vals, b=2000, seed=1, level=0.90):
    """(median, lo, hi, n): percentile bootstrap interval of the median, resampling the values (designs) with replacement."""
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if n == 0:
        return (None, None, None, 0)
    rng = random.Random(seed)
    meds = sorted(median([vals[rng.randrange(n)] for _ in range(n)]) for _ in range(b))
    a = (1 - level) / 2
    return (median(vals), quantile(meds, a), quantile(meds, 1 - a), n)


def _ranks(x):
    order = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return r


def spearman(x, y):
    """Spearman rank correlation with tied ranks averaged; None for fewer than 3 points or a constant series."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def crit_bin(c):
    """Bin of a criticality for the transition tables; None (atom in no reported path) is its own bin."""
    if c is None:
        return "unseen"
    if c >= 0.99:
        return ">=0.99"
    if c >= 0.90:
        return "0.90-0.99"
    if c >= 0.50:
        return "0.50-0.90"
    return "<0.50"


BINS = (">=0.99", "0.90-0.99", "0.50-0.90", "<0.50", "unseen")


def parse_census(path, pads=frozenset()):
    """Per atom of the final clustering: {atom: dict(cseq, idx, pc)}. The final cluster of an atom is the latest closed (K) cluster
    that added it; pc is the max P value of that cluster for the atom (None when the atom has no input pin record). Pad atoms
    (names in `pads`) are left out. Records: M cseq idx kind source n qgain bonus attr base dom root; A cseq idx atom ...;
    P cseq atom net crit; K cseq n_added n_proposed queue_left."""
    atoms_at = collections.defaultdict(list)  # (cseq, idx) -> atoms
    pin = {}  # (cseq, atom) -> max crit
    closed = set()
    with Path(path).open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            t = f[0]
            if t == "A":
                atoms_at[(int(f[1]), int(f[2]))].append(f[3])
            elif t == "P":
                k = (int(f[1]), f[2])
                c = float(f[4])
                if c > pin.get(k, -1.0):
                    pin[k] = c
            elif t == "K":
                closed.add(int(f[1]))
    out = {}
    for (cseq, idx) in sorted(atoms_at):
        if cseq not in closed:
            continue
        for a in atoms_at[(cseq, idx)]:
            if a in pads:
                continue
            out[a] = {"cseq": cseq, "idx": idx, "pc": pin.get((cseq, a))}
    return out


def pack_rank(census):
    """Add 'crank' (0..1 rank of the atom's cluster among the logic clusters, by cluster number) and 'seq' (global molecule order)."""
    cs = sorted({v["cseq"] for v in census.values()})
    rk = {c: i / max(len(cs) - 1, 1) for i, c in enumerate(cs)}
    for v in census.values():
        v["crank"] = rk[v["cseq"]]
    order = sorted(census, key=lambda a: (census[a]["cseq"], census[a]["idx"]))
    for i, a in enumerate(order):
        census[a]["seq"] = i / max(len(order) - 1, 1)
    return census


# ---------------------------------------------------------------------------------------
# netlist graph (Q6): combinational depth and fan-in cones, from the BLIF only (no VPR timing)

def parse_blif_graph(text, atoms=None):
    """Netlist of a VTR-dialect BLIF. Returns dict:
      pis (set of net names), pos (list of net names), comb {atom: (kind, [input nets])} for LUTs ('lut') and adders ('adder'),
      seq {atom: input net} (latches), hard {atom} (other subckts), net_atom {net: atom} (driver of every net),
      alias {net: net} (single-input identity LUTs are buffers VPR absorbs: they are not atoms), cin {adder atom: carry-in net}.
    `atoms` (optional set of VPR atom names) names a subckt atom: the one of its pin nets that VPR knows; else its first output pin."""
    atoms = atoms or set()
    lines = []
    cur = ""
    for raw in text.splitlines():
        s = raw.split("#")[0].rstrip()
        if s.endswith("\\"):
            cur += s[:-1] + " "
            continue
        lines.append(cur + s)
        cur = ""
    pis, pos = set(), []
    names = []  # (inputs, out, rows)
    latches, subckts = [], []
    i = 0
    while i < len(lines):
        f = lines[i].split()
        if not f:
            i += 1
            continue
        if f[0] == ".inputs":
            pis.update(f[1:])
        elif f[0] == ".outputs":
            pos.extend(f[1:])
        elif f[0] == ".names":
            rows = []
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].lstrip().startswith("."):
                rows.append(lines[j].split())
                j += 1
            names.append((f[1:-1], f[-1], rows))
            i = j
            continue
        elif f[0] == ".latch":
            latches.append((f[1], f[2]))
        elif f[0] == ".subckt":
            subckts.append((f[1], [tuple(p.split("=", 1)) for p in f[2:] if "=" in p]))
        i += 1
    alias, comb, seq, hard, net_atom, cin = {}, {}, {}, set(), {}, {}
    for ins, out, rows in names:
        if len(ins) == 1 and rows == [["1", "1"]]:
            alias[out] = ins[0]
            continue
        comb[out] = ("lut", list(ins))
        net_atom[out] = out
    for d, q in latches:
        seq[q] = d
        net_atom[q] = q
    for model, pins in subckts:
        outs = [n for f, n in pins if f.split("[")[0] in ("cout", "sumout", "out", "data_out", "q")] or [pins[0][1]]
        nets = [n for _f, n in pins]
        name = next((n for n in outs if n in atoms), None) or next((n for n in nets if n in atoms), None) or outs[0]
        if model == "adder":
            ins = [n for f, n in pins if f.split("[")[0] in ("a", "b", "cin")]
            comb[name] = ("adder", ins)
            c = [n for f, n in pins if f.split("[")[0] == "cin"]
            if c:
                cin[name] = c[0]
        else:
            hard.add(name)
        for n in outs:
            net_atom[n] = name
    return {"pis": pis, "pos": pos, "comb": comb, "seq": seq, "hard": hard, "net_atom": net_atom, "alias": alias, "cin": cin}


def _resolve(net, alias):
    n = 0
    while net in alias and n < 10000:
        net = alias[net]
        n += 1
    return net


def comb_levels(g):
    """LUT levels from the nearest register / primary input / hard block: {comb atom: level}. A LUT is one level above its deepest
    input; an adder whose carry-in comes from another adder adds no level for that input (a carry chain counts once)."""
    comb, na, al = g["comb"], g["net_atom"], g["alias"]
    deps, users = {}, collections.defaultdict(list)
    for a, (_k, ins) in comb.items():
        d = {na.get(_resolve(n, al)) for n in ins}
        d = {x for x in d if x in comb and x != a}
        deps[a] = d
        for x in d:
            users[x].append(a)
    indeg = {a: len(d) for a, d in deps.items()}
    ready = [a for a, n in indeg.items() if n == 0]
    lv = {}
    while ready:
        a = ready.pop()
        kind, ins = comb[a]
        cn = g["cin"].get(a)
        best = 0
        for n in ins:
            d = na.get(_resolve(n, al))
            base = lv.get(d, 0) if d in comb else 0
            add = 1
            if kind == "adder" and n == cn and d in comb and comb[d][0] == "adder":
                add = 0
            best = max(best, base + add)
        lv[a] = max(best, 1)
        for u in users[a]:
            indeg[u] -= 1
            if indeg[u] == 0:
                ready.append(u)
    return lv


def assign_cones(g, lv):
    """One group per register bit (latch) or primary output: the fan-in cone back to registers / PIs / hard blocks. Each combinational
    atom goes to the cone of its highest-hint endpoint (hint = combinational depth of the endpoint's driver, ties by name); the DFS
    from an endpoint stops at atoms already assigned (their whole cone is assigned too). Returns ({atom: endpoint key}, {key: size}).
    Endpoint keys: the latch atom name, or 'out:'+net for a primary output."""
    comb, na, al = g["comb"], g["net_atom"], g["alias"]
    eps = [(q, d) for q, d in g["seq"].items()] + [("out:" + n, n) for n in g["pos"]]

    def drv(net):
        return na.get(_resolve(net, al))

    def hint(e):
        d = drv(e[1])
        return (-(lv.get(d, 0) if d in comb else 0), e[0])

    group, size = {}, {}
    for key, net in sorted(eps, key=hint):
        top = drv(net)
        if top not in comb or top in group:
            size.setdefault(key, 0)
            continue
        stack = [top]
        group[top] = key
        n = 1
        while stack:
            a = stack.pop()
            for inn in comb[a][1]:
                d = drv(inn)
                if d in comb and d not in group:
                    group[d] = key
                    n += 1
                    stack.append(d)
        size[key] = n
    return group, size


def adder_chains(g):
    """{adder atom: (position, length)} along its carry chain (position 0 = the head, whose carry-in is not driven by an adder)."""
    comb, na, al, cin = g["comb"], g["net_atom"], g["alias"], g["cin"]
    nxt, heads = {}, []
    for a, (k, _ins) in comb.items():
        if k != "adder":
            continue
        d = na.get(_resolve(cin[a], al)) if a in cin else None
        if d in comb and comb[d][0] == "adder" and d != a:
            nxt.setdefault(d, []).append(a)
        else:
            heads.append(a)
    out = {}
    for h in heads:
        chain, cur, seen = [h], h, {h}
        while cur in nxt and nxt[cur]:
            cur = sorted(nxt[cur])[0]
            if cur in seen:
                break
            seen.add(cur)
            chain.append(cur)
        for i, a in enumerate(chain):
            out[a] = (i, len(chain))
    return out
