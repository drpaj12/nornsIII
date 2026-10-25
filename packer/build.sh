#!/bin/sh
# Build the Norns packer: a private VTR tree at the pinned commit, with packer/vpr overlaid, vpr only.
# Usage: sh packer/build.sh            (tree + overlay + incremental build, under the heavy lock)
#        sh packer/build.sh --no-lock  (the caller already holds the lock)
# Result: $NORNS_VTR/build/vpr/vpr (set NORNS_VPR to it, see scripts/env.sh). Never touches $VTR_ROOT
# (read only: it is the clone source of the private tree).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NORN=$(CDPATH= cd -- "$HERE/.." && pwd)
. "$NORN/scripts/env.sh"
PIN=$(cat "$HERE/VTR_COMMIT")
NV=${NORNS_VTR:-$WS_ROOT/work/norns-vtr}
LOCK_CMD="flock -x $NORNS_LOCK"
[ "${1:-}" = "--no-lock" ] && LOCK_CMD=""

if [ ! -d "$NV/.git" ]; then
    git clone -q --no-checkout "$VTR_ROOT" "$NV"      # a local clone, not a worktree of $VTR_ROOT
fi
git -C "$NV" checkout -q "$PIN"
# submodules: from the local checkout of $VTR_ROOT, not the network
git -C "$NV" config -f .gitmodules --get-regexp '^submodule\..*\.path$' | while read -r key path; do
    name=${key#submodule.}; name=${name%.path}
    git -C "$NV" config "submodule.$name.url" "$VTR_ROOT/$path"
done
git -C "$NV" -c protocol.file.allow=always submodule update --init -q
# overlay the Norns files (mirrors the vpr/ tree)
rsync -rc "$HERE/vpr/" "$NV/vpr/"
if [ ! -f "$NV/build/CMakeCache.txt" ]; then
    # the flags of the stock build (release, -O3, LTO, VTR_ASSERT_LEVEL=2); only vpr's inputs
    cmake -S "$NV" -B "$NV/build" -DCMAKE_BUILD_TYPE=release -DVTR_ASSERT_LEVEL=2 \
        -DWITH_PARMYS=OFF -DWITH_MOSAIC=OFF -DWITH_ABC=OFF -DWITH_ODIN=OFF \
        -DSLANG_SYSTEMVERILOG=OFF -DBUILD_TESTING=OFF > "$NV/cmake-configure.log" 2>&1
fi
# `cmake --build` re-globs the new source files (norns_affinity.cpp) on re-configure
cmake -S "$NV" -B "$NV/build" > /dev/null 2>&1
# make -j4: memory stays below 60% of the 23 GB VM
$LOCK_CMD cmake --build "$NV/build" --target vpr -j4
echo "built: $NV/build/vpr/vpr"
