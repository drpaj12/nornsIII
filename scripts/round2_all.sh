#!/bin/sh
# The rest of round 2, ordered for a contended lock: freeze the best new family on the designs
# whose soft arms are complete, then shuf + hard + xover per design (one lock hold per design,
# smallest first), and the soft arms of the designs still missing last.
set -u
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/env.sh"
"$NR_PY" "$HERE/round2.py" freeze
"$NR_PY" "$HERE/round2.py" chunk stage2 ch_intrinsics stereovision3 diffeq2 diffeq1 mkPktMerge raygentop sha boundtop mkSMAdapter4B or1200 stereovision0 mkDelayWorker32B stereovision1
"$NR_PY" "$HERE/round2.py" chunk soft stereovision2 blob_merge
"$NR_PY" "$HERE/round2.py" chunk stage2 stereovision2 blob_merge
