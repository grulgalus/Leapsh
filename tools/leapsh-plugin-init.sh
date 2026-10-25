#!/usr/bin/env sh
# Obal kolem leapsh-plugin-init.py (funguje v Linuxu i Termuxu)
SELF="$0"
command -v readlink >/dev/null 2>&1 && SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
DIR="$(cd "$(dirname "$SELF")" && pwd)"
PY="${LEAPSH_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
exec "$PY" "$DIR/leapsh-plugin-init.py" "$@"
