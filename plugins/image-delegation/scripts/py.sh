#!/bin/sh
# Portable Python launcher: py.sh [--fail-open] <script.py> [args...]
# Picks a working Python 3.8+ (skips the Windows Store "python3" stub).
# --fail-open: exit 0 when no Python is found (used by hooks so a missing
# interpreter never wedges the session).
here=$(cd "$(dirname "$0")" && pwd)
fail=1
if [ "$1" = "--fail-open" ]; then fail=0; shift; fi
script=$1; shift
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then
    exec "$py" "$here/$script" "$@"
  fi
done
echo "image-delegation: no Python 3.8+ found (needed for $script)" >&2
exit $fail
