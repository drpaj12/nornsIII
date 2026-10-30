"""Q-N2 (docs/plan/q-n2-appack-gap.md): replay the stock pack census of the round 9 designs against the known clustering C and
attribute the CLB gap (and, where the logs allow, extra cut nets and extra near-critical crossings) to five kinds of packing decision.

Read only on the round 9 run roots; no VPR run. Pure functions `analyse_run` (one pack) and `pool` (many) so the tests can feed small data.

Terms (see the plan): molecule = packer unit; c0 = C cluster of a stock cluster's seed; kinds a (seed in a leftover piece), b (wrong add with a
free member of c0 queued), c (wrong add, none queued), d (early close), e (capacity cut); x = tail/other.
"""
from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

import heap_lib as hl
import heappick_lib as hp

CAP = 10
HF = 32
NEAR = 0.90
EPS = 1e-6
KINDS = ("b", "c", "d", "e", "a", "x")


# ---------------------------------------------------------------------------------------------------
def read_c(path):
    c = {}
    for line in Path(path).read_text().splitlines():
        f = line.split("\t")
        if len(f) >= 2:
            c[f[0]] = int(f[1])
    return c


def build_net_index(g, hub=HF):
    """net -> atoms on it (driver and sinks), atom -> nets; nets with more than `hub` sinks go to `hubnets` and are left out of the index."""
    al, na = g["alias"], g["net_atom"]
    sinks = collections.defaultdict(set)
    for a, (_k, ins) in g["comb"].items():
        for n in ins:
            sinks[hl._resolve(n, al)].add(a)
    for q, d in g["seq"].items():
        sinks[hl._resolve(d, al)].add(q)
    net_atoms, atom_nets, hubnets = {}, collections.defaultdict(set), set()
    for r, s in sinks.items():
        members = set(s)
        d = na.get(r)
        if d is not None:
            members.add(d)
        if len(s) > hub:
            hubnets.add(r)
            continue
        net_atoms[r] = members
        for a in members:
            atom_nets[a].add(r)
    hub_of = collections.defaultdict(set)
    for r in hubnets:
        for a in sinks[r] | ({na[r]} if r in na else set()):
            hub_of[a].add(r)
    return net_atoms, atom_nets, hub_of


def connection_class(member_atoms, cl_atoms, net_atoms, atom_nets, hub_of):
    """How a free molecule relates to the open cluster: 'direct' (shares a net of at most HF sinks), 'two_hop', 'hub' (only a net with more
    than HF sinks), 'none'."""
    direct = False
    two = False
    hub = False
    for a in member_atoms:
        for n in atom_nets.get(a, ()):
            if net_atoms[n] & cl_atoms:
                direct = True
                break
        if direct:
            break
    if direct:
        return "direct"
    for a in member_atoms:
        for n in atom_nets.get(a, ()):
            for b in net_atoms[n]:
                for n2 in atom_nets.get(b, ()):
                    if net_atoms[n2] & cl_atoms:
                        two = True
                        break
                if two:
                    break
            if two:
                break
        if two:
            break
    if two:
        return "two_hop"
    for a in member_atoms:
        if hub_of.get(a, set()) and any(hub_of.get(b) and (hub_of[a] & hub_of[b]) for b in cl_atoms):
            hub = True
            break
    return "hub" if hub else "none"


# ---------------------------------------------------------------------------------------------------
def analyse_run(census, cmap, atom_loc, clbs, g, want_edges=True, on_pick=None):
    """One pack. census: heappick_lib.parse_census_full; cmap {atom: C cluster}; atom_loc/clbs: heappick_lib.parse_net_clusters;
    g: heap_lib.parse_blif_graph of the shuffled D'. on_pick (Q-N3, log-only): optional callback(kind, info) called for a wrong pick with a
    right atom queued (kind 'b') and for a right pick with another free member of c0 queued (kind 'ok'); it changes no result. Returns a dict (no raw per-cluster dump except the example list)."""
    mols = [m for m in census["mols"] if m["cseq"] in census["closed"]]
    by_cseq = collections.OrderedDict()
    for m in mols:
        by_cseq.setdefault(m["cseq"], []).append(m)
    # molecule records
    root_mol = {}
    for m in mols:
        locs = [atom_loc.get(a) for a in m["atoms"]]
        m["is_clb"] = bool(locs) and all(l is not None for l in locs)
        m["w"] = len({l[1] for l in locs if l}) if m["is_clb"] else 0
        labs = collections.Counter(cmap[a] for a in m["atoms"] if a in cmap)
        m["c"] = labs.most_common(1)[0][0] if labs else None
        m["mixed"] = len(labs) > 1
        root_mol[m["root"]] = m
    logic = [cs for cs, ms in by_cseq.items() if all(x["is_clb"] for x in ms)]
    members = collections.defaultdict(list)
    for cs in logic:
        for m in by_cseq[cs]:
            if m["c"] is not None:
                members[m["c"]].append(m)
    cweight = {c: sum(m["w"] for m in ms) for c, ms in members.items()}
    # events per cluster
    ev = collections.defaultdict(list)
    for e in census["events"]:
        ev[e[2]].append(e)
    net_atoms, atom_nets, hub_of = build_net_index(g)

    clustered = set()  # id(m)
    place_kind = {}  # id(m) -> kind of the decision that placed it
    host_c0 = {}
    frag_cs = set()
    host_close = {}
    host_dev = {}
    host_cseq = {}
    ex = {k: [] for k in KINDS}
    out = {"S": len(logic), "T": 0, "waste": collections.Counter(), "a_sub": collections.Counter(), "events": collections.Counter(),
           "b": collections.Counter(), "c": collections.Counter(), "d": collections.Counter(), "e": collections.Counter(),
           "n_adds": 0, "n_mixed_mol": sum(1 for m in mols if m["mixed"]), "fle_mismatch": 0, "clusters_nonfull": 0}
    pend_log = []
    cluster_rec = {}
    for cs in logic:
        ms = by_cseq[cs]
        seed = ms[0]
        c0 = seed["c"]
        fle = clbs[next(iter({atom_loc[a][0] for a in seed["atoms"]}))]["fles"]
        wsum = sum(m["w"] for m in ms)
        if fle != wsum:
            out["fle_mismatch"] += 1
        out["T"] += fle
        mc = collections.Counter()
        for m in ms:
            mc[m["c"]] += m["w"]
        major = mc.most_common(1)[0][0]
        out["seed_in_major"] = out.get("seed_in_major", 0) + (1 if c0 == major else 0)
        out["pure"] = out.get("pure", 0) + (1 if len(mc) == 1 else 0)
        frag = c0 is not None and any(id(x) in clustered for x in members[c0])
        if frag:
            frag_cs.add(cs)
        # replay
        pending = {}
        qidx = {}
        add_log = []  # atoms of each molecule added so far, in order
        refused = set()
        cl_atoms = set()
        used = 0
        foreign = 0
        first_dev = None
        evs = ev[cs]
        mi = 0
        idx_to_m = {m["idx"]: m for m in ms}
        last_add_pos = None
        for (pos, t, _cs, root, a, gain) in evs:
            if t == "Q":
                pending[root] = gain
                qidx[root] = len(add_log)
            elif t == "F":
                refused.add(root)
                pending.pop(root, None)
            elif t == "M":
                m = root_mol[root]
                snap = dict(pending) if on_pick else None
                pending.pop(root, None)
                if m["idx"] == 0:
                    place_kind[id(m)] = "seed"
                    add_log.append(set(m["atoms"]))
                    cl_atoms.update(m["atoms"])
                    used += m["w"]
                    clustered.add(id(m))
                    last_add_pos = pos
                    continue
                out["n_adds"] += 1
                if c0 is not None and m["c"] != c0:
                    foreign += 1
                    free = [x for x in members[c0] if id(x) not in clustered and x["w"] <= CAP - used]
                    if not free:
                        place_kind[id(m)] = "filler"
                        out["events"]["filler"] += 1
                    else:
                        queued = [x for x in free if x["root"] in pending]
                        if queued:
                            bx = max(queued, key=lambda x: pending[x["root"]])
                            bg = pending[bx["root"]]
                            rank = 1 + sum(1 for r, gg in pending.items() if gg > bg)
                            tie = bg >= m["qgain"] * (1 - EPS) if m["qgain"] > 0 else bg == 0
                            out["b"]["n"] += 1
                            out["b"]["tie" if tie else ("below" if bg < m["qgain"] else "above")] += 1
                            out["b"]["rank1" if rank == 1 else "rank_gt1"] += 1
                            out["b"]["src%d" % m["src"]] += 1
                            if m["qgain"] > 0:
                                out["b"]["ratio_sum_milli"] += int(1000 * bg / m["qgain"])
                                out["b"]["ratio_n"] += 1
                            out["events"]["b"] += 1
                            # why: did the queued member gain connections after it was queued (VPR keeps its queue-time gain)?
                            later = set().union(*add_log[qidx.get(bx["root"], 0):]) if add_log[qidx.get(bx["root"], 0):] else set()
                            sh_m = sum(1 for a in bx["atoms"] for n in atom_nets.get(a, ()) if net_atoms[n] & cl_atoms)
                            sh_p = sum(1 for a in m["atoms"] for n in atom_nets.get(a, ()) if net_atoms[n] & cl_atoms)
                            sh_later = sum(1 for a in bx["atoms"] for n in atom_nets.get(a, ()) if net_atoms[n] & later)
                            out["b"]["member_gained_after_queue" if sh_later else "member_no_gain_after_queue"] += 1
                            out["b"]["member_nets_ge_pick_nets" if sh_m >= sh_p else "member_nets_lt_pick_nets"] += 1
                            if sh_later and sh_m >= sh_p:
                                out["b"]["stale_likely"] += 1
                            na_p, na_m = len(m["atoms"]), len(bx["atoms"])
                            out["b"]["pick_more_atoms" if na_p > na_m else ("pick_fewer_atoms" if na_p < na_m else "same_atoms")] += 1
                            pa = census["atoms"].get(m["root"])
                            if pa:
                                out["b"]["pick_tg_ge_0.9" if pa["tg"] >= 0.9 else "pick_tg_lt_0.9"] += 1
                            if on_pick:
                                on_pick("b", {"cseq": cs, "idx": m["idx"], "pick": m, "right": [x["root"] for x in queued], "snap": snap,
                                              "cl_atoms": set(cl_atoms), "root_mol": root_mol, "clustered": clustered})
                            place_kind[id(m)] = "b"
                            if first_dev is None:
                                first_dev = "b"
                            if len(ex["b"]) < 3 and len(ms) > 3:
                                ex["b"].append({"cseq": cs, "idx": m["idx"], "pick": m["root"], "pick_c": m["c"], "c0": c0, "pick_gain": m["qgain"],
                                                "member": bx["root"], "member_gain": bg, "member_rank": rank, "src": m["src"], "queue": len(pending)})
                        else:
                            cls = collections.Counter()
                            for x in free:
                                if x["root"] in refused:
                                    cls["c4_refused"] += 1
                                    continue
                                k = connection_class(x["atoms"], cl_atoms, net_atoms, atom_nets, hub_of)
                                cls[{"direct": "c3_direct_not_queued", "two_hop": "c5_two_hop", "hub": "c2_hub_only", "none": "c1_no_net"}[k]] += 1
                            order = ["c3_direct_not_queued", "c4_refused", "c5_two_hop", "c2_hub_only", "c1_no_net"]
                            reason = next(r for r in order if cls[r])
                            if m["src"] == 7:
                                reason = "c6_unrelated_pick"
                            out["c"]["n"] += 1
                            out["c"][reason] += 1
                            out["events"]["c"] += 1
                            place_kind[id(m)] = "c"
                            if first_dev is None:
                                first_dev = "c"
                            if len(ex["c"]) < 3 and len(ms) > 3:
                                ex["c"].append({"cseq": cs, "idx": m["idx"], "pick": m["root"], "pick_c": m["c"], "c0": c0, "reason": reason,
                                                "free_members": len(free), "src": m["src"]})
                else:
                    place_kind[id(m)] = "track"
                    if on_pick and c0 is not None and m["idx"] > 0:
                        okq = [x for x in members[c0] if id(x) not in clustered and x["w"] <= CAP - used and x is not m and x["root"] in snap]
                        if okq:
                            on_pick("ok", {"cseq": cs, "idx": m["idx"], "pick": m, "right": [x["root"] for x in okq], "snap": snap,
                                           "cl_atoms": set(cl_atoms), "root_mol": root_mol, "clustered": clustered})
                add_log.append(set(m["atoms"]))
                cl_atoms.update(m["atoms"])
                used += m["w"]
                clustered.add(id(m))
                last_add_pos = pos
        close = census["closed"][cs]
        free_slots = CAP - used
        after_f = [e for e in evs if e[1] == "F" and last_add_pos is not None and e[0] > last_add_pos]
        free_c0 = ([x for x in members[c0] if id(x) not in clustered and x["w"] <= free_slots] if c0 is not None else [])
        left_c0 = ([x for x in members[c0] if id(x) not in clustered] if c0 is not None else [])
        close_kind = None
        if free_slots > 0 and free_c0:
            st = {e[4] for e in after_f}
            reason = ("refused_pins" if st == {1} else "refused_route" if st == {2} else "refused_both" if st else
                      "queue_left" if close["queue_left"] > 0 else "no_candidate")
            queued = [x for x in free_c0 if x["root"] in pending]
            cls = collections.Counter()
            for x in free_c0:
                if x["root"] in pending:
                    cls["queued_at_close"] += 1
                elif x["root"] in refused:
                    cls["refused_earlier"] += 1
                else:
                    cls[connection_class(x["atoms"], cl_atoms, net_atoms, atom_nets, hub_of)] += 1
            top = next((r for r in ("queued_at_close", "refused_earlier", "direct", "two_hop", "hub", "none") if cls[r]), "none")
            out["d"]["n"] += 1
            out["d"]["reason_" + reason] += 1
            out["d"]["member_" + top] += 1
            out["events"]["d"] += 1
            close_kind = "d"
            if len(ex["d"]) < 3 and len(ms) > 2:
                ex["d"].append({"cseq": cs, "fle": fle, "c0": c0, "free_c0": len(free_c0), "reason": reason, "member_state": top,
                                "queue_left": close["queue_left"]})
        elif free_slots == 0 and left_c0 and foreign == 0 and not frag:
            art = cweight.get(c0, 0) > CAP
            out["e"]["n"] += 1
            out["e"]["artefact" if art else "real"] += 1
            out["events"]["e"] += 1
            close_kind = "e"
            if len(ex["e"]) < 3:
                ex["e"].append({"cseq": cs, "c0": c0, "left": len(left_c0), "c0_weight": cweight.get(c0, 0)})
        host_close[cs] = close_kind
        host_dev[cs] = first_dev
        host_c0[cs] = c0
        for m in ms:
            host_cseq[id(m)] = cs
        if frag:
            out["events"]["a"] += 1
        # attribution of the waste of this cluster
        u = CAP - fle
        if u > 0:
            out["clusters_nonfull"] += 1
            if first_dev:
                kind = first_dev
            elif close_kind:
                kind = close_kind
            elif frag:
                kind = "a"
            else:
                kind = "x"
            out["waste"][kind] += u
            cluster_rec[cs] = (kind, u)
            if kind == "a":
                sib = [x for x in members[c0] if id(x) in clustered and host_cseq.get(id(x)) != cs]
                sub = collections.Counter()
                for x in sib:
                    hs = host_cseq[id(x)]
                    pk = place_kind.get(id(x), "track")
                    if pk in ("b", "c", "filler"):
                        sub[pk] += x["w"]
                    else:  # on track, or the seed, of a host cluster: the host's own first deviation, else its close (d/e)
                        sub[host_dev.get(hs) or host_close.get(hs) or "x"] += x["w"]
                tot = sum(sub.values())
                for k2, v in sub.items():
                    out["a_sub"][k2] += u * (v / tot) if tot else 0
                if not tot:
                    out["a_sub"]["none_found"] += u
        if len(ex["a"]) < 3 and frag and u > 0 and len(ms) > 1:
            ex["a"].append({"cseq": cs, "fle": fle, "c0": c0})
    out["examples"] = ex
    out["cluster_rec"] = None
    # ---- extra cut and near-critical crossings
    if want_edges:
        stock_key, atom_kind = {}, {}
        for cs in by_cseq:
            for m in by_cseq[cs]:
                pk = place_kind.get(id(m), "track")
                if pk in ("seed", "track") and cs in frag_cs:
                    pk = "a"  # leftover piece of a split C cluster
                for a in m["atoms"]:
                    stock_key[a] = ("s", cs)
                    atom_kind[a] = pk
        na, al = g["net_atom"], g["alias"]

        def skey(a):
            return stock_key.get(a, ("u", a))

        def ckey(a):
            return ("c", cmap[a]) if a in cmap else ("u", a)
        nets = collections.defaultdict(set)
        sinkpairs = []
        for a, (_k, ins) in g["comb"].items():
            for n in ins:
                r = hl._resolve(n, al)
                nets[r].add(a)
                sinkpairs.append((r, a))
        for q, d in g["seq"].items():
            r = hl._resolve(d, al)
            nets[r].add(q)
            sinkpairs.append((r, q))
        for po in g["pos"]:
            nets[hl._resolve(po, al)].add(("po", po))
        cut_s = cut_c = 0
        extra = collections.Counter()
        for r, sk in nets.items():
            d = na.get(r)
            if d is not None and d in g["comb"] and not g["comb"][d][1] and g["comb"][d][0] == "lut" and r in ("gnd", "vcc", "unconn"):
                continue
            atoms = set(sk)
            atoms.add(d if d is not None else ("pi", r))
            ks = {skey(a) if not isinstance(a, tuple) else ("u", a) for a in atoms}
            kc = {ckey(a) if not isinstance(a, tuple) else ("u", a) for a in atoms}
            cs_, cc_ = len(ks) > 1, len(kc) > 1
            cut_s += cs_
            cut_c += cc_
            if len(ks) > len(kc):
                disp = [a for a in atoms if not isinstance(a, tuple) and atom_kind.get(a, "track") != "track"]
                ex_n = len(ks) - len(kc)
                if disp:
                    for a in disp:
                        extra[atom_kind[a]] += ex_n / len(disp)
                else:
                    extra["track"] += ex_n
        out["cut"] = {"stock": cut_s, "C": cut_c, "extra_by_kind": dict(extra)}
        # near-critical edges
        nc_total = nc_s = nc_c = 0
        seen = set()
        extra_nc = collections.Counter()
        for (cs, atom), lst in census["pins"].items():
            for net, crit in lst:
                if crit < NEAR:
                    continue
                r = hl._resolve(net, al)
                d = na.get(r)
                if d is None or (d, atom) in seen:
                    continue
                seen.add((d, atom))
                nc_total += 1
                x_s = skey(d) != skey(atom)
                x_c = ckey(d) != ckey(atom)
                nc_s += x_s
                nc_c += x_c
                if x_s and not x_c:
                    ks2 = [atom_kind.get(d, "track"), atom_kind.get(atom, "track")]
                    dk = [k for k in ks2 if k != "track"]
                    if dk:
                        for k in dk:
                            extra_nc[k] += 1 / len(dk)
                    else:
                        extra_nc["track"] += 1
        out["near"] = {"edges": nc_total, "cross_stock": nc_s, "cross_C": nc_c, "extra_by_kind": dict(extra_nc)}
    for k in ("waste", "a_sub", "events", "b", "c", "d", "e"):
        out[k] = dict(out[k])
    return out


def kc_of(rows):
    return {(r["design"], r["cons"]): r["Kc"] for r in rows}


def run_one(root, design, cons, sh):
    d = Path(root) / design / cons / sh
    runs = sorted(d.glob("run-*/stock.s1/design.net"))
    if not runs:
        return None
    census = hp.parse_census_full(d / "census.tsv")
    cmap = read_c(d / "affinity.tsv")
    atom_loc, clbs, _others = hp.parse_net_clusters(runs[0])
    g = hl.parse_blif_graph((d / "design.blif").read_text(), set(cmap))
    return analyse_run(census, cmap, atom_loc, clbs, g)


def main(argv):
    root, outdir = argv[0], Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    only = set(argv[2].split(",")) if len(argv) > 2 else None
    designs = sorted(p.name for p in Path(root).iterdir() if p.is_dir() and (p / "own").is_dir())
    for design in designs:
        if only and design not in only:
            continue
        for cons in ("own", "foreign"):
            for sh in ("sh0", "sh1", "sh2", "sh3"):
                dst = outdir / f"{design}.{cons}.{sh}.json"
                if dst.exists():
                    continue
                res = run_one(root, design, cons, sh)
                if res is None:
                    continue
                dst.write_text(json.dumps(res))
                print(design, cons, sh, res["S"], res["T"], res["waste"], flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
