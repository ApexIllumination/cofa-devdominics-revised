#!/bin/sh
# Optional POSIX hook entry point; no provider registration or baseline writes.
if [ "$#" -ne 1 ]; then
  printf '%s\n' 'Usage: sh hooks/session-start.sh PROJECT_ROOT' >&2
  exit 2
fi
script_dir=$(dirname "$0")
kit_dir=$(CDPATH='' cd "$script_dir/.." && pwd) || exit 2
exec "${COFA_PYTHON:-python3}" "$kit_dir/scripts/cofa.py" --root "$1" check
