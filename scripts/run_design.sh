#!/bin/sh
# One design end to end: front end, baseline, Loki graph/clusters, seeds, full matrix.
# Usage: scripts/run_design.sh <design> [more designs ...]
set -u
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/env.sh"
for design in "$@"; do
    echo "== $design: frontend"
    "$NR_PY" "$HERE/frontend.py" "$design" || exit 1
    echo "== $design: baseline"
    "$NR_PY" "$HERE/matrix.py" baseline "$design" || exit 1
    echo "== $design: clusters"
    "$NR_PY" "$HERE/build_graph_clusters.py" "$design" || exit 1
    echo "== $design: seeds"
    "$NR_PY" "$HERE/build_seeds.py" "$design" || exit 1
    echo "== $design: matrix"
    "$NR_PY" "$HERE/matrix.py" all "$design" | grep -v "already done"
done
