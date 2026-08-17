#!/bin/bash
# Stops then starts the app (macOS / Linux).
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "Python 3 not found."; exit 1; }
exec "$PY" "$(pwd)/scripts/launcher.py" restart "$@"
