#!/bin/bash
# ===========================================================================
#  Advanced Website Auditor - ONE-CLICK LAUNCHER FOR LINUX
#
#  Run:  ./start.sh          (or double-click it, if your file manager is set
#                             to run executable text files)
#
#  The first run sets everything up and takes a few minutes. Later runs take
#  seconds. Your browser opens automatically when it is ready.
#
#  If it will not run:  chmod +x start.sh
# ===========================================================================

cd "$(dirname "$0")" || exit 1

echo ""
echo "  ============================================"
echo "    ADVANCED WEBSITE AUDITOR"
echo "  ============================================"
echo ""

PY=""
for c in python3 /usr/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  echo "  [PROBLEM] Python 3 was not found."
  echo ""
  echo "  Install it once, for example:"
  echo "    Debian/Ubuntu :  sudo apt install python3 python3-venv"
  echo "    Fedora        :  sudo dnf install python3"
  echo "    Arch          :  sudo pacman -S python"
  echo ""
  echo "  Then run ./start.sh again."
  echo ""
  exit 1
fi

exec "$PY" "$(pwd)/scripts/launcher.py" start "$@"
