#!/bin/bash
# ===========================================================================
#  Advanced Website Auditor - ONE-CLICK LAUNCHER FOR macOS
#
#  Double-click this file in Finder. That is the whole procedure.
#
#  The first run sets everything up (Python environment, packages, dashboard
#  build, database) and takes a few minutes. Later runs take seconds.
#  Your browser opens automatically when it is ready.
#
#  If macOS says it "cannot be opened because it is from an unidentified
#  developer", right-click the file once and choose Open, then Open again.
# ===========================================================================

# A double-clicked .command starts in the user's home folder, NOT here, so the
# project directory has to be resolved from this script's own location. Quoted
# throughout so paths containing spaces work.
cd "$(dirname "$0")" || exit 1

echo ""
echo "  ============================================"
echo "    ADVANCED WEBSITE AUDITOR"
echo "  ============================================"
echo ""
echo "  Starting up. The first run takes a few minutes"
echo "  while it installs what it needs."
echo ""

# Find a Python 3 to run the launcher with. Homebrew locations are checked
# explicitly because a GUI-launched shell does not always inherit the PATH
# a Terminal window would have.
PY=""
for c in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  echo "  [PROBLEM] Python 3 was not found on this Mac."
  echo ""
  echo "  Fix it once, either way:"
  echo "    * Run this in Terminal:  xcode-select --install"
  echo "    * Or download it from:   https://www.python.org/downloads/macos/"
  echo ""
  echo "  Then double-click this file again."
  echo ""
  read -r -p "  Press Return to close..." _
  exit 1
fi

"$PY" "$(pwd)/scripts/launcher.py" start
CODE=$?

if [ $CODE -ne 0 ]; then
  echo ""
  echo "  ============================================"
  echo "    IT COULD NOT START"
  echo "  ============================================"
  echo ""
  echo "  The reason is printed above and usually says"
  echo "  exactly what to do next."
  echo ""
  read -r -p "  Press Return to close..." _
  exit $CODE
fi

echo ""
echo "  The app keeps running after this window closes."
echo "    ./stop.sh     stop the app"
echo "    ./status.sh   check it is healthy"
echo ""
sleep 5
exit 0
