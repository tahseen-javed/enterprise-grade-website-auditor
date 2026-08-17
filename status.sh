#!/bin/bash
# Advanced Website Auditor - status (macOS / Linux)
cd "$(dirname "$0")" || exit 1
. "$(pwd)/scripts/find-python.sh"

if ! find_python; then
  echo ""
  echo "  [PROBLEM] No working Python 3 was found."
  echo ""
  if [ "$(uname -s)" = "Darwin" ]; then
    echo "  Double-click START.command instead - it can install Python for you."
  else
    echo "  Install it once, for example:"
    echo "    Debian/Ubuntu :  sudo apt install python3 python3-venv"
    echo "    Fedora        :  sudo dnf install python3"
    echo "    Arch          :  sudo pacman -S python"
  fi
  echo ""
  exit 1
fi

exec "$PY" "$(pwd)/scripts/launcher.py" status "$@"
