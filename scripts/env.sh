#!/bin/sh
# Environment of the Norns III experiment (source me from the Norns checkout:
# `. scripts/env.sh`). Every path can be overridden; the defaults assume the Yggdrasil III
# workspace layout, one directory ($WS_ROOT) holding odin3/, loki/ and external/.
export WS_ROOT=${WS_ROOT:-$HOME/odin3-ws}
export ODIN3_ROOT=${ODIN3_ROOT:-$WS_ROOT/odin3}
export ODIN3_LIB=$ODIN3_ROOT/build/release/libodin3.so
export VTR_ROOT=${VTR_ROOT:-$WS_ROOT/external/vtr-verilog-to-routing}
export LOKI_HOME=${LOKI_HOME:-$WS_ROOT/loki}
# One VPR run at a time takes this lock (shared with other heavy jobs on the machine).
export NORNS_LOCK=${NORNS_LOCK:-/tmp/claude-1000/odin3-heavy.lock}
mkdir -p "$(dirname "$NORNS_LOCK")"
# Loki analysis venv (numpy, scipy, scikit-learn, networkx, cffi), built per loki CLAUDE.md;
# Loki itself is imported from LOKI_HOME, never installed into or edited in its checkout.
NR_PY=${NR_PY:-/tmp/claude-1000/nr-loki-venv/bin/python}
# The Norns checkout: the current directory when sourced from it, or set NORN explicitly.
NORN=${NORN:-$(pwd)}
[ -f "$NORN/scripts/nornlib.py" ] || echo "env.sh: NORN=$NORN is not a Norns checkout; source from it or set NORN" >&2
export PYTHONPATH="$NORN/scripts:$LOKI_HOME:$ODIN3_ROOT/plugins/python"
# The Norns packer (packer/): a private VTR build with the provenance-affinity packer overlay.
export NORNS_VTR=${NORNS_VTR:-$WS_ROOT/work/norns-vtr}
export NORNS_VPR=${NORNS_VPR:-$NORNS_VTR/build/vpr/vpr}
