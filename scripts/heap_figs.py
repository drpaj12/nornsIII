"""Figures of the critical-heap lane (matplotlib, PNG)."""
from __future__ import annotations

import collections
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import heap_lib as hl  # noqa: E402


def make(fig_dir, runs, q1, pts, q3, q4, q6):
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    # Q1: enrichment by kind, operator view, three thresholds
    fig, ax = plt.subplots(figsize=(7, 4))
    kinds = [k for k in ("adder", "multiplier", "mux", "relational", "equality", "none") if k in q1["op@0.9"]]
    for j, thr in enumerate(hl.THRS):
        rows = q1[f"op@{thr}"]
        y = np.arange(len(kinds)) + (j - 1) * 0.25
        med = [rows.get(k, {}).get("atoms", {}).get("median") or 0 for k in kinds]
        lo = [med[i] - (rows.get(k, {}).get("atoms", {}).get("lo90") or 0) for i, k in enumerate(kinds)]
        hi = [(rows.get(k, {}).get("atoms", {}).get("hi90") or 0) - med[i] for i, k in enumerate(kinds)]
        ax.barh(y, med, height=0.22, xerr=[np.maximum(lo, 0), np.maximum(hi, 0)], label=f"crit >= {thr}", capsize=2)
    ax.axvline(1.0, color="k", lw=0.8)
    ax.set_yticks(range(len(kinds)))
    ax.set_yticklabels(kinds)
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlabel("heap share / atom share (median over designs, 90% bootstrap)")
    ax.set_title("Q1: enrichment of operator-level constructs in the heap")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "q1-enrichment.png", dpi=130)
    plt.close(fig)
    # Q2: crit vs relative bit position
    fig, ax = plt.subplots(figsize=(7, 4))
    for k, v in sorted(pts.items()):
        if len(v) < 50:
            continue
        a = np.array(v)
        bins = np.linspace(0, 1, 9)
        idx = np.clip(np.digitize(a[:, 0], bins) - 1, 0, 7)
        m = [a[idx == i, 1].mean() for i in range(8)]
        ax.plot((bins[:-1] + bins[1:]) / 2, m, marker="o", label=f"{k} ({len(v)})")
    ax.set_xlabel("relative bit position (word bit or carry-chain position)")
    ax.set_ylabel("mean post-route crit of atoms in reported paths")
    ax.set_title("Q2: criticality against bit position")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(fig_dir / "q2-bit-position.png", dpi=130)
    plt.close(fig)
    # Q3: wall
    fig, ax = plt.subplots(figsize=(7, 4))
    for r in runs:
        if r["seed"] != 1:
            continue
        c = np.sort([p["crit"] or 0.0 for p in r["paths"].values()])[::-1]
        ax.plot(np.arange(1, len(c) + 1), c, lw=1, label=r["design"])
    ax.axhline(0.9, color="k", lw=0.6, ls="--")
    ax.set_xscale("log")
    ax.set_xlabel("path rank")
    ax.set_ylabel("crit")
    ax.set_title("Q3: criticality of the reported paths (seed 1)")
    ax.legend(fontsize=5, ncol=3)
    fig.tight_layout()
    fig.savefig(fig_dir / "q3-wall.png", dpi=130)
    plt.close(fig)
    # Q4: pack-time against post-route crit, aggregated matrix; pack order against pack-time crit
    rowsb = ("<0.50", "0.50-0.90", "0.90-0.99", ">=0.99")
    mat = collections.Counter()
    for p in q4:
        for k, c in p["matrix"].items():
            a, b = k.split("|")
            mat[(a, b)] += c
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    M = np.array([[mat[(a, b)] for b in hl.BINS] for a in rowsb], dtype=float)
    M = M / M.sum(1, keepdims=True)
    im = axs[0].imshow(M, cmap="viridis", vmin=0, vmax=1)
    axs[0].set_xticks(range(len(hl.BINS)))
    axs[0].set_xticklabels(hl.BINS, fontsize=7)
    axs[0].set_yticks(range(len(rowsb)))
    axs[0].set_yticklabels(rowsb)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            axs[0].text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", color="w", fontsize=8)
    axs[0].set_xlabel("post-route crit (unseen = in no reported path)")
    axs[0].set_ylabel("pack-time crit")
    axs[0].set_title("row-normalised, all 45 runs pooled")
    for r in runs:
        if r["seed"] != 1:
            continue
        la = [v for v in r["atoms"].values() if v["pc"] is not None]
        x = np.array([v["crank"] for v in la])
        y = np.array([v["pc"] for v in la])
        bins = np.linspace(0, 1, 11)
        idx = np.clip(np.digitize(x, bins) - 1, 0, 9)
        axs[1].plot((bins[:-1] + bins[1:]) / 2, [y[idx == i].mean() if (idx == i).any() else np.nan for i in range(10)], lw=1)
    axs[1].set_xlabel("cluster rank in pack order")
    axs[1].set_ylabel("mean pack-time crit of the cluster's atoms")
    axs[1].set_title("pack order against pack-time crit (one line per design, seed 1)")
    fig.tight_layout()
    fig.savefig(fig_dir / "q4-dynamics.png", dpi=130)
    plt.close(fig)
    # Q6: AUC by model set
    fig, ax = plt.subplots(figsize=(7, 4))
    names = ["kind", "kind+ops", "kind+ops+netlist", "netlist only"]
    x = np.arange(len(names))
    for j, tgt in enumerate(("route", "pack")):
        med = [q6["model_sets"][f"{tgt}:{n}"]["auc_median"] for n in names]
        lo = [m - q6["model_sets"][f"{tgt}:{n}"]["auc_lo90"] for m, n in zip(med, names)]
        hi = [q6["model_sets"][f"{tgt}:{n}"]["auc_hi90"] - m for m, n in zip(med, names)]
        ax.bar(x + (j - 0.5) * 0.35, med, width=0.33, yerr=[lo, hi], capsize=3, label=f"target: {tgt} heap")
    ax.axhline(0.5, color="k", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylim(0.3, 0.9)
    ax.set_ylabel("AUC, leave-one-design-out (median, 90% bootstrap)")
    ax.set_title("Q6: HDL and netlist hints against heap membership")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "q6-auc.png", dpi=130)
    plt.close(fig)
