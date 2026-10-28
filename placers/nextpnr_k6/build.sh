#!/bin/sh
# Build nextpnr-generic with the Norns k6 viaduct uarch overlaid. Overlay, not fork:
#   1. git archive of external/nextpnr (read only) -> $SRC (only if $SRC does not exist yet);
#   2. copy placers/nextpnr_k6/{k6.cc,constids.inc} to $SRC/generic/viaduct/k6/;
#   3. apply cmake-register.patch (two source lines in generic/CMakeLists.txt; skipped if already applied);
#   4. cmake + ninja into $BLD, under the heavy lock.
# Needs the Dispatch 2 dependencies in $DEPS (Boost 1.86.0 and Eigen 3.4.0 prefix, docs/plan/placers.md section 8).
# external/nextpnr and the dependency tree are never modified. Nothing is deleted.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
WS_ROOT=${WS_ROOT:-$HOME/odin3-ws}
NORNS_TMP=${NORNS_TMP:-/tmp/claude-1000}
# Persistent default (a VM restart wipes /tmp; 2026-10-28): $WS_ROOT/work. Override with SRC, BLD, DEPS.
SRC=${SRC:-$WS_ROOT/work/nextpnr-k6-src}
BLD=${BLD:-$WS_ROOT/work/nextpnr-k6-build}
DEPS=${DEPS:-$WS_ROOT/work/nextpnr-deps}
JOBS=${JOBS:-4}
if [ ! -e "$SRC/CMakeLists.txt" ]; then
    mkdir -p "$SRC"
    git -C "$WS_ROOT/external/nextpnr" archive HEAD | tar -x -C "$SRC"
fi
mkdir -p "$SRC/generic/viaduct/k6"
cp "$HERE/k6.cc" "$HERE/constids.inc" "$SRC/generic/viaduct/k6/"
if ! grep -q 'viaduct/k6/k6.cc' "$SRC/generic/CMakeLists.txt"; then
    patch -p1 -d "$SRC" < "$HERE/cmake-register.patch"
fi
flock -x "$NORNS_TMP/odin3-heavy.lock" sh -c "
  cmake -S '$SRC' -B '$BLD' -G Ninja -DCMAKE_BUILD_TYPE=Release -DARCH=generic \
    -DBUILD_GUI=OFF -DBUILD_PYTHON=OFF -DBUILD_RUST=OFF -DBUILD_TESTS=OFF \
    -DBOOST_ROOT='$DEPS/prefix' -DBoost_NO_SYSTEM_PATHS=ON -DEigen3_DIR='$DEPS/prefix/share/eigen3/cmake' &&
  cmake --build '$BLD' -j$JOBS"
echo "binary: $BLD/nextpnr-generic (export LD_LIBRARY_PATH=$DEPS/prefix/lib)"
