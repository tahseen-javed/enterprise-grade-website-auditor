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
#  If macOS says it is from an unidentified developer, right-click this file
#  once and choose Open, then Open again. That is an Apple security rule for
#  any unsigned script and cannot be avoided from inside the file.
# ===========================================================================

# A double-clicked .command starts in the user's HOME folder, not here, so the
# project directory must come from this script's own location. Quoted
# everywhere so paths containing spaces and apostrophes work.
cd "$(dirname "$0")" || exit 1
PROJECT="$(pwd)"

# Keep the window readable if anything goes wrong.
pause_exit() {
  echo ""
  # `read` fails instantly when there is no terminal (e.g. launched by a
  # script); the || true stops that turning into a silent hang or error.
  read -r -p "  Press Return to close this window..." _ 2>/dev/null || true
  exit "${1:-1}"
}

echo ""
echo "  ============================================"
echo "    ADVANCED WEBSITE AUDITOR"
echo "  ============================================"
echo ""
echo "  Starting up. The first run takes a few minutes"
echo "  while it installs what it needs. Later runs are"
echo "  much faster. Your browser will open by itself."
echo ""

# --- self-healing: permissions and Gatekeeper quarantine --------------------
# If this file ran at all it is already executable, but its sibling scripts
# may not be (some unzip tools drop the executable bit). Fix them here so the
# user never has to open Terminal to run chmod.
chmod +x "$PROJECT"/*.command "$PROJECT"/*.sh "$PROJECT"/scripts/launcher.py 2>/dev/null

# Downloaded files carry com.apple.quarantine, which makes macOS re-prompt for
# every script. Clearing it on our own folder removes those repeat prompts.
xattr -dr com.apple.quarantine "$PROJECT" 2>/dev/null

# --- find a Python that ACTUALLY RUNS ---------------------------------------
#
# Existence is not enough. A fresh macOS ships /usr/bin/python3 as a stub that
# only triggers the Command Line Tools installer: `command -v python3`
# succeeds, but running it fails. Checking existence alone is exactly why an
# earlier version of this launcher appeared to do nothing on a real Mac.
# Every candidate is therefore executed and must report its version.

py_usable() {           # $1 = interpreter, $2 = minimum minor version of 3.x
  [ -n "$1" ] || return 1
  "$1" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $2) else 1)" \
    >/dev/null 2>&1
}

# Never probe /usr/bin/python3 when the Command Line Tools are absent: that is
# the stub, and running it pops a system dialog rather than failing quietly.
CLT_PRESENT=0
xcode-select -p >/dev/null 2>&1 && CLT_PRESENT=1

CANDIDATES="/opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
/usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3 \
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
$(command -v python3 2>/dev/null)"
[ "$CLT_PRESENT" = "1" ] && CANDIDATES="$CANDIDATES /usr/bin/python3"

# Prefer 3.10+ (what the app needs). Otherwise accept any working 3.8+, which
# is enough to run launcher.py so it can install a newer one and explain itself.
PY=""
for c in $CANDIDATES; do
  if py_usable "$c" 10; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  for c in $CANDIDATES; do
    if py_usable "$c" 8; then PY="$c"; break; fi
  done
fi

# --- install Python automatically if we genuinely have none -----------------
if [ -z "$PY" ]; then
  BREW=""
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && BREW="$b" && break
  done
  command -v brew >/dev/null 2>&1 && [ -z "$BREW" ] && BREW="$(command -v brew)"

  if [ -n "$BREW" ]; then
    echo "  Python is missing. Installing it with Homebrew..."
    echo "  (this is a one-time step and needs no password)"
    echo ""
    "$BREW" install python
    for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 $(command -v python3 2>/dev/null); do
      if py_usable "$c" 10; then PY="$c"; break; fi
    done
  fi
fi

if [ -z "$PY" ]; then
  echo "  ============================================"
  echo "    ONE THING IS NEEDED FIRST"
  echo "  ============================================"
  echo ""
  echo "  This Mac does not have Python installed, and there is"
  echo "  no automatic installer available on it."
  echo ""
  echo "  I have opened the official Python download page in your"
  echo "  browser. It is a normal Mac installer - no Terminal:"
  echo ""
  echo "    1. Click the big yellow 'Download Python' button."
  echo "    2. Open the downloaded .pkg file."
  echo "    3. Click Continue / Agree / Install, and enter your"
  echo "       Mac password when it asks."
  echo "    4. Come back and double-click START.command again."
  echo ""
  echo "  (Page: https://www.python.org/downloads/macos/)"
  echo ""
  open "https://www.python.org/downloads/macos/" 2>/dev/null
  pause_exit 1
fi

echo "  Using Python: $PY"
echo ""

"$PY" "$PROJECT/scripts/launcher.py" start
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
  pause_exit $CODE
fi

echo ""
echo "  The app keeps running after this window closes."
echo "    stop.sh     stop the app"
echo "    status.sh   check it is healthy"
echo ""
sleep 5
exit 0
