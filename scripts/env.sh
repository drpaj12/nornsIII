#!/bin/sh
# Environment of the Norns III experiment lane (source me).
export ODIN3_ROOT=${ODIN3_ROOT:-/home/jamiespa/odin3-ws/odin3}
export ODIN3_LIB=$ODIN3_ROOT/build/release/libodin3.so
export VTR_ROOT=${VTR_ROOT:-/home/jamiespa/odin3-ws/external/vtr-verilog-to-routing}
export LOKI_HOME=${LOKI_HOME:-/home/jamiespa/odin3-ws/loki}
# Loki analysis venv (numpy, scipy, scikit-learn, networkx, cffi), built per loki CLAUDE.md;
# Loki itself is imported from LOKI_HOME, never installed into or edited in its checkout.
NR_PY=${NR_PY:-/tmp/claude-1000/nr-loki-venv/bin/python}
NORN=$HOME/odin3-ws/work/norns-exp
export PYTHONPATH="$NORN/scripts:$LOKI_HOME:$ODIN3_ROOT/plugins/python"
