#!/bin/sh
# Q-N3b arms (docs/plan/q-n3b-2hop-gain.md): stock, w = 0.1, w = 0.25 on the 35 E10 base designs, seeds 1-3, smallest first.
# Usage: NORNS_VPR=<2hop vpr> sh scripts/q3b_run.sh RUN_ROOT   (RUN_ROOT holds netlists/ and order.json of the keep sweep)
# Guards before each design: /mnt/c free space >= 15 GB, weekly usage meter < 100. Resumable; nothing is deleted.
set -u
ROOT=$1
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NORN=$(CDPATH= cd -- "$HERE/.." && pwd)
cd "$NORN" || exit 1
. "$NORN/scripts/env.sh"
for d in $(python3 -c "import json,sys;print(' '.join(x[0] for x in json.load(open(sys.argv[1]))))" "$ROOT/order.json"); do
    free=$(df --output=avail -BG /mnt/c | tail -1 | tr -dc '0-9')
    if [ "$free" -lt 15 ]; then echo "STOP: /mnt/c has ${free}G free"; exit 3; fi
    wk=$(python3 -c "import json;print(json.load(open('$HOME/.claude/usage-state/latest.json'))['week'])")
    if [ "$wk" -ge 100 ]; then echo "STOP: weekly meter $wk"; exit 4; fi
    echo "## $d $(date -u +%FT%TZ) free ${free}G week ${wk}"
    python3 "$HERE/e10_main.py" --root "$ROOT" --stage runs --label q3b --configs base,h1,h25 --designs "$d" --seeds 1,2,3 || echo "design $d: e10_main rc $?"
done
echo "## all designs done $(date -u +%FT%TZ)"
