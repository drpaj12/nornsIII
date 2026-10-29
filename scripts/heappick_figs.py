"""Figures of the heap-picking lane (matplotlib, PNG) from data/analysis/heappick.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def per(S, sec, key, sub=None):
    d = S[sec][key] if sub is None else S[sec][sub][key]
    return d["per_design"]


def make(S, fig_dir):
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    designs = S["designs"]
    x = np.arange(len(designs))

    def vals(d):
        return [np.nan if d.get(k) is None else d[k] for k in designs]

    # P1: share of pack-time heap picks that are not in the post-route heap
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(x - 0.2, vals(per(S, "p1", "seed_picks_leave")), 0.4, label="seed picks", color="#4c78a8")
    ax.bar(x + 0.2, vals(per(S, "p1", "cand_picks_leave")), 0.4, label="candidate picks", color="#f58518")
    ax.set_xticks(x)
    ax.set_xticklabels(designs, rotation=60, ha="right", fontsize=8)
    ax.set_ylabel("share of heap picks that leave the heap")
    ax.set_ylim(0, 1.05)
    ax.set_title("P1: picks made on pack-time crit >= 0.90 whose atoms are not in the post-route heap")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "p1-picks-leaving.png", dpi=130)
    plt.close(fig)

    # P2: clusters touched by a near-critical path against the floor
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(x - 0.27, vals(per(S, "p2", "mean_visits")), 0.27, label="clusters touched", color="#4c78a8")
    ax.bar(x, vals(per(S, "p2", "mean_floor10")), 0.27, label="floor, 10 BLEs per cluster", color="#f58518")
    ax.bar(x + 0.27, vals(per(S, "p2", "mean_floor20")), 0.27, label="floor, 20 BLEs per cluster", color="#54a24b")
    ax.set_xticks(x)
    ax.set_xticklabels(designs, rotation=60, ha="right", fontsize=8)
    ax.set_ylabel("clusters per near-critical path (mean)")
    ax.set_title("P2: clusters touched by the reported crit >= 0.90 paths, against the capacity floor")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "p2-visits-vs-floor.png", dpi=130)
    plt.close(fig)

    # P4: tie rates
    fig, ax = plt.subplots(figsize=(9, 4))
    for j, (e, c) in enumerate((("e0.0", "#4c78a8"), ("e0.01", "#f58518"), ("e0.05", "#54a24b"))):
        ax.bar(x + (j - 1) * 0.27, vals(S["p4"][e]["tie_rate"]["per_design"]), 0.27, label={"e0.0": "exact", "e0.01": "within 1%", "e0.05": "within 5%"}[e], color=c)
    ax.set_xticks(x)
    ax.set_xticklabels(designs, rotation=60, ha="right", fontsize=8)
    ax.set_ylabel("share of candidate picks")
    ax.set_ylim(0, 1.05)
    ax.set_title("P4: picks where another queued molecule had (nearly) the same gain")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "p4-ties.png", dpi=130)
    plt.close(fig)

    # P8: tie share of word bits against what the stock packer did
    rows = S["p8_rows"]
    fig, axs = plt.subplots(1, 2, figsize=(9, 4))
    for src, c in (("odin", "#4c78a8"), ("port", "#f58518")):
        rr = [r for r in rows if r["src"] == src]
        axs[0].scatter([r["flow"] for r in rr], [r["co_cluster"] for r in rr], s=14, alpha=0.7, color=c, label=f"{src} words ({len(rr)})")
        axs[1].scatter([r["flow"] for r in rr], [r["spread"] for r in rr], s=14, alpha=0.7, color=c)
    axs[0].set_xlabel("pairs tied by dataflow (share)")
    axs[0].set_ylabel("pairs in one cluster (stock packer)")
    axs[1].set_xlabel("pairs tied by dataflow (share)")
    axs[1].set_ylabel("clusters touched / minimum")
    axs[0].legend(fontsize=8)
    fig.suptitle("P8: words of >= 8 bits: dataflow ties between bits, and the stock packing")
    fig.tight_layout()
    fig.savefig(fig_dir / "p8-word-ties.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    make(json.loads((root / "data/analysis/heappick.json").read_text()), root / "docs/figures/heap-picking")
