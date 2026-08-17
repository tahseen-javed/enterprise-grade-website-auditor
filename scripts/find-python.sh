#!/bin/bash
# Shared Python discovery for the macOS/Linux launchers.
#
# Existence is NOT enough. A fresh macOS ships /usr/bin/python3 as a stub that
# only triggers the Command Line Tools installer: `command -v python3` succeeds
# but running it fails. Every candidate here is therefore actually executed and
# must report a usable version. Sets PY, or leaves it empty.

py_usable() {           # $1 = interpreter, $2 = minimum minor version of 3.x
  [ -n "$1" ] || return 1
  "$1" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $2) else 1)" \
    >/dev/null 2>&1
}

find_python() {
  # Skip the macOS stub entirely when the Command Line Tools are absent -
  # running it pops a system dialog instead of failing quietly.
  local clt=0
  xcode-select -p >/dev/null 2>&1 && clt=1

  local cands="/opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
/usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3 \
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
$(command -v python3 2>/dev/null) $(command -v python3.12 2>/dev/null) $(command -v python3.11 2>/dev/null)"
  if [ "$(uname -s)" != "Darwin" ] || [ "$clt" = "1" ]; then
    cands="$cands /usr/bin/python3"
  fi

  PY=""
  local c
  for c in $cands; do if py_usable "$c" 10; then PY="$c"; return 0; fi; done
  for c in $cands; do if py_usable "$c" 8;  then PY="$c"; return 0; fi; done
  return 1
}
