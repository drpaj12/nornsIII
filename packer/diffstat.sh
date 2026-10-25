#!/bin/sh
# Diff summary of packer/vpr against the pinned VTR commit (read-only use of $VTR_ROOT): writes DIFFSTAT.txt
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/../scripts/env.sh"
PIN=$(cat "$HERE/VTR_COMMIT")
cd "$HERE/vpr"
for f in $(find . -type f | sort); do
    f=${f#./}
    if git -C "$VTR_ROOT" cat-file -e "$PIN:vpr/$f" 2>/dev/null; then
        add=$(git -C "$VTR_ROOT" show "$PIN:vpr/$f" | diff - "$f" | grep -c '^>' || true)
        del=$(git -C "$VTR_ROOT" show "$PIN:vpr/$f" | diff - "$f" | grep -c '^<' || true)
        echo "modified $f +$add -$del"
    else
        echo "new $f +$(wc -l < "$f") -0"
    fi
done > "$HERE/DIFFSTAT.txt"
cat "$HERE/DIFFSTAT.txt"
