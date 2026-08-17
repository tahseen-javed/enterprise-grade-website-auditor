#!/usr/bin/env python3
"""
Cross-platform one-click launcher (macOS, Linux, and Windows as a fallback).

Windows already has a proven PowerShell launcher (START.bat -> scripts\\*.ps1)
and that path is unchanged. This file is the equivalent for macOS and Linux,
written in the standard library only so it can run on a bare Python 3 with
nothing installed yet.

It does the same job as bootstrap.ps1 + start.ps1:
  detect OS -> find/install Python and Node -> create backend/.venv ->
  install backend packages -> install and build the dashboard ->
  initialise the database -> pick a free port -> start the backend ->
  wait for /api/health -> open the browser.

Like the Windows path it is INCREMENTAL (dependency installs and the dashboard
build are fingerprinted and skipped when nothing changed) and NON-DESTRUCTIVE
(it only ever creates what is missing; an existing database is opened, never
reset).

Usage:  python3 scripts/launcher.py [start|stop|status] [--no-browser] [--force]
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# --------------------------------------------------------------------------
# Paths - everything is derived from this file's location, so the project can
# live anywhere, on any drive, under any user name, including paths with spaces.
# --------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
DATA = ROOT / "data"
RUN_DIR = DATA / "run"
LOG_DIR = DATA / "logs"
VENV = BACKEND / ".venv"
DIST_INDEX = FRONTEND / "dist" / "index.html"

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"

DEFAULT_PORT = 8021
DEFAULT_HOST = "127.0.0.1"
MIN_PY = (3, 10)
MIN_NODE = 18

# Kept separate from the PowerShell launcher's setup.stamp.json: the two use
# different hashing schemes, and sharing one file would make each invalidate
# the other's fingerprints on every alternate run.
STAMP = RUN_DIR / "setup.stamp.py.json"


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
_COLOR = sys.stdout.isatty() and not IS_WINDOWS


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def head(t: str) -> None:
    print(f"\n  {_c('36', t)}\n  {_c('90', '-' * len(t))}")


def ok(t: str) -> None:
    print(f"  {_c('32', '[ OK ]')}   {t}")


def warn(t: str) -> None:
    print(f"  {_c('33', '[WARN]')}   {t}")


def err(t: str) -> None:
    print(f"  {_c('31', '[FAIL]')}   {t}")


def info(t: str) -> None:
    print(f"           {t}")


def die(title: str, *lines: str) -> "NoReturn":  # type: ignore[valid-type]
    print()
    err(title)
    for l in lines:
        info(l)
    print()
    sys.exit(1)


# --------------------------------------------------------------------------
# venv layout
# --------------------------------------------------------------------------
def venv_bin() -> Path:
    return VENV / ("Scripts" if IS_WINDOWS else "bin")


def venv_python() -> Path:
    return venv_bin() / ("python.exe" if IS_WINDOWS else "python")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def ensure_env_file() -> bool:
    """.env is git-ignored, so a fresh clone has none. Create it from the
    example. Never overwrites an existing file."""
    envf = ROOT / ".env"
    if envf.exists():
        return False
    example = ROOT / ".env.example"
    if example.exists():
        shutil.copyfile(example, envf)
    else:
        envf.write_text(
            "WAE_BACKEND_PORT=8021\nWAE_BACKEND_HOST=127.0.0.1\n", encoding="utf-8"
        )
    return True


def read_config() -> dict:
    cfg = {"port": DEFAULT_PORT, "host": DEFAULT_HOST}
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "WAE_BACKEND_PORT" and v.isdigit():
                cfg["port"] = int(v)
            elif k == "WAE_BACKEND_HOST" and v:
                cfg["host"] = v
    # Environment wins, so a one-off override needs no file edit.
    if os.environ.get("WAE_BACKEND_PORT", "").isdigit():
        cfg["port"] = int(os.environ["WAE_BACKEND_PORT"])
    if os.environ.get("WAE_BACKEND_HOST"):
        cfg["host"] = os.environ["WAE_BACKEND_HOST"]
    return cfg


# --------------------------------------------------------------------------
# Fingerprints, so a second launch does no work
# --------------------------------------------------------------------------
def read_stamp() -> dict:
    try:
        return json.loads(STAMP.read_text(encoding="utf-8"))
    except Exception:
        # A corrupt fingerprint must only cost time, never correctness.
        return {}


def save_stamp(d: dict) -> None:
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        warn("Could not save the setup fingerprint; the next launch may redo setup.")


def hash_paths(paths) -> str:
    h = hashlib.sha256()
    for p in sorted(paths, key=str):
        p = Path(p)
        if not p.exists():
            continue
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if not f.is_file():
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            h.update(str(f.relative_to(ROOT)).encode())
            h.update(f"{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()


# --------------------------------------------------------------------------
# Runtime discovery / installation
# --------------------------------------------------------------------------
def _probe_version(exe: str, args, pattern_index: int):
    try:
        out = subprocess.run(
            [exe] + args, capture_output=True, text=True, timeout=20
        ).stdout.strip()
        return out
    except Exception:
        return ""


def find_python() -> str | None:
    """A Python 3.10+ interpreter. The one running this script counts."""
    if sys.version_info >= MIN_PY:
        return sys.executable
    for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python"):
        exe = shutil.which(name)
        if not exe:
            continue
        out = _probe_version(exe, ["--version"], 0)
        parts = out.replace("Python", "").strip().split(".")
        try:
            if (int(parts[0]), int(parts[1])) >= MIN_PY:
                return exe
        except (ValueError, IndexError):
            continue
    return None


def find_node() -> tuple[str, str] | None:
    """(node, npm) if Node 18+ is available."""
    node = shutil.which("node")
    if not node:
        # Homebrew on Apple Silicon is not always on a GUI-launched PATH.
        for cand in ("/opt/homebrew/bin/node", "/usr/local/bin/node"):
            if Path(cand).exists():
                node = cand
                break
    if not node:
        return None
    out = _probe_version(node, ["--version"], 0).lstrip("v")
    try:
        if int(out.split(".")[0]) < MIN_NODE:
            return None
    except (ValueError, IndexError):
        return None
    npm = shutil.which("npm") or str(Path(node).parent / "npm")
    if not Path(npm).exists():
        return None
    return node, npm


def try_install(pkg_brew: str, pkg_apt: str, label: str) -> bool:
    """Install a runtime using the platform's own package manager, from its
    official repositories. Nothing is ever downloaded from an ad-hoc URL.

    On Linux this needs root; `sudo -n` is used so it succeeds silently when
    already authorised and fails immediately rather than hanging on a password
    prompt in a double-clicked window.
    """
    if IS_MAC:
        brew = shutil.which("brew") or (
            "/opt/homebrew/bin/brew" if Path("/opt/homebrew/bin/brew").exists() else None
        )
        if not brew:
            return False
        info(f"Installing {label} with Homebrew...")
        return subprocess.run([brew, "install", pkg_brew]).returncode == 0

    if sys.platform.startswith("linux"):
        if shutil.which("apt-get"):
            cmd = ["sudo", "-n", "apt-get", "install", "-y", pkg_apt]
        elif shutil.which("dnf"):
            cmd = ["sudo", "-n", "dnf", "install", "-y", pkg_apt]
        elif shutil.which("pacman"):
            cmd = ["sudo", "-n", "pacman", "-S", "--noconfirm", pkg_apt]
        else:
            return False
        info(f"Installing {label} with the system package manager...")
        return subprocess.run(cmd).returncode == 0

    if IS_WINDOWS and shutil.which("winget"):
        wid = "OpenJS.NodeJS.LTS" if "node" in pkg_brew else "Python.Python.3.12"
        info(f"Installing {label} with winget...")
        return subprocess.run(
            ["winget", "install", "--id", wid, "-e", "--source", "winget",
             "--accept-package-agreements", "--accept-source-agreements"]
        ).returncode == 0

    return False


def manual_help(what: str, url: str, why: str) -> "NoReturn":  # type: ignore[valid-type]
    extra = []
    if sys.platform.startswith("linux"):
        extra = ["Or with your package manager, for example:",
                 "  sudo apt install python3 python3-venv nodejs npm"]
    die(
        f"{what} could not be installed automatically.",
        "",
        "  What to do (one time, about 3 minutes):",
        f"    1. Open this page:  {url}",
        "    2. Download and run the installer for your system.",
        "    3. Start this launcher again - it carries on from here.",
        *[f"  {e}" for e in extra],
        "",
        f"  Why this is needed: {why}",
    )


# --------------------------------------------------------------------------
# Ports / health
# --------------------------------------------------------------------------
def port_busy(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def find_free_port(preferred: int, span: int = 40) -> int | None:
    for p in range(preferred, preferred + span):
        if not port_busy(p):
            return p
    return None


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def wait_health(url: str, seconds: int = 60) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if http_ok(url, 2):
            return True
        time.sleep(0.7)
    return False


# --------------------------------------------------------------------------
# PID tracking (same file names the Windows launcher uses)
# --------------------------------------------------------------------------
def pid_file() -> Path:
    return RUN_DIR / "backend.pid"


def port_file() -> Path:
    return RUN_DIR / "backend.port"


def read_int(p: Path):
    try:
        return int(p.read_text().strip())
    except Exception:
        return None


def process_is_ours(pid: int) -> bool:
    """Only ever act on a process that verifiably belongs to THIS project copy,
    so another app - or another checkout of this one - is never touched."""
    if pid is None:
        return False
    try:
        if IS_WINDOWS:
            # wmic is deprecated and absent on current Windows 11 builds, so
            # ask CIM through PowerShell instead - available on every
            # supported Windows.
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')."
                 f"CommandLine"],
                capture_output=True, text=True, timeout=20,
            ).stdout
        else:
            out = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=10,
            ).stdout
    except Exception:
        return False
    return str(ROOT) in out


def running_pid():
    pid = read_int(pid_file())
    return pid if (pid and process_is_ours(pid)) else None


# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------
def bootstrap(force: bool = False) -> None:
    head("System")
    ok(f"{platform.system()} {platform.release()} ({platform.machine()}), Python {platform.python_version()}")

    head("Project files")
    for d in (DATA, RUN_DIR, LOG_DIR, DATA / "config", DATA / "uploads",
              DATA / "exports", DATA / "reports"):
        d.mkdir(parents=True, exist_ok=True)
    ok("Data folders ready (existing data left untouched).")
    ok("Created .env from .env.example." if ensure_env_file() else "Configuration file .env found.")

    cfg = read_config()
    if not (1 <= cfg["port"] <= 65535):
        die(f"WAE_BACKEND_PORT is '{cfg['port']}', which is not a valid port.",
            f"Edit: {ROOT / '.env'}")
    ok(f"Configuration valid (port {cfg['port']}, host {cfg['host']}).")

    # ---- Python + venv ----
    head("Python")
    py = find_python()
    if not py:
        if try_install("python@3.12", "python3", "Python 3.12"):
            py = find_python()
    if not py:
        manual_help("Python 3.10 or newer", "https://www.python.org/downloads/",
                    "the audit engine, the web API and the report generator all run on Python.")
    ok(f"Python at {py}")

    if not venv_python().exists():
        info("Creating the private Python environment (backend/.venv)...")
        r = subprocess.run([py, "-m", "venv", str(VENV)], capture_output=True, text=True)
        if not venv_python().exists():
            hint = ("On Debian/Ubuntu install the venv module first:  "
                    "sudo apt install python3-venv") if sys.platform.startswith("linux") else \
                   "Reinstall Python from python.org and try again."
            die("The Python virtual environment could not be created.",
                (r.stderr or "").strip()[:400], hint)
        ok("Private Python environment created.")
    else:
        ok("Private Python environment already exists.")

    stamp = read_stamp()
    req = BACKEND / "requirements.txt"
    req_hash = hash_paths([req])

    healthy = subprocess.run(
        [str(venv_python()), "-c", "import fastapi, uvicorn, sqlalchemy, jinja2"],
        capture_output=True,
    ).returncode == 0

    if force or not healthy or stamp.get("requirements") != req_hash:
        info("Installing backend packages..." if not healthy else "requirements.txt changed - updating backend packages...")
        subprocess.run([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
                       capture_output=True)
        r = subprocess.run([str(venv_python()), "-m", "pip", "install", "-r", str(req), "--quiet"])
        if r.returncode != 0 or subprocess.run(
            [str(venv_python()), "-c", "import fastapi, uvicorn, sqlalchemy, jinja2"],
            capture_output=True,
        ).returncode != 0:
            die("Installing the Python packages failed.",
                "This is almost always no internet connection, or a firewall blocking",
                "pypi.org. Connect to the internet and run this launcher again.")
        stamp["requirements"] = req_hash
        save_stamp(stamp)
        ok("Backend packages installed.")
    else:
        ok("Backend packages already up to date.")

    # ---- Dashboard ----
    head("Dashboard")
    src = [FRONTEND / "src", FRONTEND / "index.html",
           FRONTEND / "vite.config.js", FRONTEND / "package.json"]
    src_hash = hash_paths(src)
    lock_hash = hash_paths([FRONTEND / "package-lock.json", FRONTEND / "package.json"])
    vite_bin = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"

    need_build = force or not DIST_INDEX.exists() or stamp.get("frontend_src") != src_hash
    if not need_build:
        ok("Dashboard already built and up to date.")
    else:
        # Node is needed ONLY to build the dashboard. Once dist exists the
        # backend serves it directly and Node is never used again.
        found = find_node()
        if not found:
            if try_install("node", "nodejs", "Node.js"):
                found = find_node()
        if not found:
            manual_help("Node.js 18 or newer", "https://nodejs.org/en/download",
                        "it compiles the dashboard once. After that it is never used again.")
        node, npm = found
        ok(f"Node at {node}")

        if force or not vite_bin.exists() or stamp.get("frontend_lock") != lock_hash:
            info("Installing dashboard build tools (one time, a few minutes)...")
            r = subprocess.run([npm, "install", "--no-fund", "--no-audit", "--loglevel=error"],
                               cwd=str(FRONTEND))
            if r.returncode != 0 or not vite_bin.exists():
                die("Installing the dashboard build tools failed.",
                    "Usually no internet, or a firewall blocking registry.npmjs.org.")
            stamp["frontend_lock"] = lock_hash
            save_stamp(stamp)
            ok("Dashboard build tools installed.")

        info("Building the dashboard...")
        r = subprocess.run([npm, "run", "build"], cwd=str(FRONTEND))
        if r.returncode != 0 or not DIST_INDEX.exists():
            die("Building the dashboard failed.", f"Expected to produce: {DIST_INDEX}")
        stamp["frontend_src"] = hash_paths(src)
        save_stamp(stamp)
        ok("Dashboard built.")

    # ---- Database ----
    head("Database")
    db = DATA / "app.db"
    existed = db.exists()
    r = subprocess.run([str(venv_python()), "-c", "from app.db import init_db; init_db()"],
                       cwd=str(BACKEND), capture_output=True, text=True)
    if r.returncode != 0:
        die("The database could not be prepared.", f"Location: {db}",
            (r.stderr or "").strip()[:400])
    if existed:
        ok(f"Existing database opened and preserved ({db.stat().st_size // 1024} KB) - no data was reset.")
    else:
        ok("New empty database created.")


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_start(no_browser: bool, force: bool) -> int:
    print(f"\n  Advanced Website Auditor\n  {ROOT}")

    existing = running_pid()
    if existing:
        p = read_int(port_file()) or read_config()["port"]
        head("Already running")
        ok(f"The app is already running for this project (PID {existing}).")
        info(f"Open it at: http://localhost:{p}")
        if not no_browser:
            webbrowser.open(f"http://localhost:{p}")
        return 0

    bootstrap(force=force)

    cfg = read_config()
    head("Port")
    port = cfg["port"]
    if port_busy(port):
        warn(f"Port {port} is already in use by another program.")
        found = find_free_port(port + 1)
        if not found:
            die(f"No free port found near {port}.",
                "Close whatever is using it, or set WAE_BACKEND_PORT in .env.")
        info(f"  using port {found} for this run instead.")
        info("  to make that permanent, set WAE_BACKEND_PORT in .env.")
        port = found
    else:
        ok(f"Port {port} is free.")

    head("Starting the app")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out_log = open(LOG_DIR / "backend.out.log", "ab")
    err_log = open(LOG_DIR / "backend.err.log", "ab")

    env = dict(os.environ, WAE_BACKEND_PORT=str(port), WAE_BACKEND_HOST=cfg["host"])
    cmd = [str(venv_python()), "-m", "uvicorn", "app.main:app",
           "--host", cfg["host"], "--port", str(port),
           "--app-dir", str(BACKEND), "--log-level", "info"]

    # Detach so the app survives this window closing, on every platform.
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, cwd=str(BACKEND), stdout=out_log, stderr=err_log,
                            env=env, **kwargs)

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    pid_file().write_text(str(proc.pid))
    port_file().write_text(str(port))
    info(f"App launched (PID {proc.pid}), waiting for it to answer...")

    url = f"http://127.0.0.1:{port}"
    if not wait_health(f"{url}/api/health", 60):
        err("The app did not become healthy in 60 seconds.")
        info(f"Check the log: {LOG_DIR / 'backend.err.log'}")
        try:
            tail = (LOG_DIR / "backend.err.log").read_text(errors="replace").splitlines()[-20:]
            for line in tail:
                print(f"           {line}")
        except OSError:
            pass
        return 1

    ok(f"Healthy on {url}")
    head("Ready")
    print(f"  Open the dashboard:  {_c('36', f'http://localhost:{port}')}")
    if port != cfg["port"]:
        info(f"(preferred port {cfg['port']} was busy - this run uses {port})")
    info(f"API documentation:   {url}/api/docs")
    info(f"Logs:                {LOG_DIR}")
    print()
    info("The app keeps running after this window closes.")
    info(f"Stop it with:  {'stop.bat' if IS_WINDOWS else './stop.sh'}")
    print()

    if not no_browser:
        time.sleep(0.4)
        webbrowser.open(f"http://localhost:{port}")
    return 0


def cmd_stop() -> int:
    head("Stopping this project")
    pid = read_int(pid_file())
    if not pid:
        info("The app was not running (no PID recorded).")
        return 0
    if not process_is_ours(pid):
        info("The app had already stopped.")
        pid_file().unlink(missing_ok=True)
        port_file().unlink(missing_ok=True)
        return 0

    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
            for _ in range(40):
                if not process_is_ours(pid):
                    break
                time.sleep(0.25)
            if process_is_ours(pid):
                os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as e:
        err(f"Could not stop PID {pid}: {e}")
        return 1

    pid_file().unlink(missing_ok=True)
    port_file().unlink(missing_ok=True)
    ok(f"App stopped (PID {pid}).")
    print()
    return 0


def cmd_status() -> int:
    print(f"\n  Advanced Website Auditor - status\n  {ROOT}")
    head("App")
    pid = running_pid()
    port = read_int(port_file()) or read_config()["port"]
    if pid:
        ok(f"App : running (PID {pid}).")
    else:
        info("App : not running.")
    info(f"  port {port} {'listening' if port_busy(port) else 'not listening'}.")
    url = f"http://127.0.0.1:{port}"
    info(f"  {'responding' if http_ok(f'{url}/api/health', 4) else 'no HTTP response'}: {url}/api/health")

    if not DIST_INDEX.exists():
        warn("frontend/dist is missing - the launcher will build it on next start.")
    head("Links")
    info(f"Dashboard : http://localhost:{port}")
    info(f"Logs      : {LOG_DIR}")
    print()
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:]]
    action = "start"
    for a in list(args):
        if a in ("start", "stop", "status", "restart", "setup"):
            action = a
            args.remove(a)
    no_browser = "--no-browser" in args
    force = "--force" in args

    if sys.version_info < (3, 8):
        print("This launcher needs Python 3.8+ to run, and the app needs 3.10+.")
        return 1

    if action == "stop":
        return cmd_stop()
    if action == "status":
        return cmd_status()
    if action == "setup":
        bootstrap(force=force)
        head("Ready")
        ok("Setup finished. Start the app with the launcher for your system.")
        return 0
    if action == "restart":
        cmd_stop()
        time.sleep(1.5)
        return cmd_start(no_browser, force)
    return cmd_start(no_browser, force)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
