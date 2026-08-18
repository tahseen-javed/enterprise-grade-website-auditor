# Advanced Website Auditor

A dedicated, premium website-audit tool: point it at a URL and get a full,
evidence-backed audit — technical SEO, on-page SEO, off-page/authority
signals, performance, accessibility, security, UX and conversion — with a
9-part scorecard, severity-graded findings, and a professional HTML report.

This project shares its audit engine with a sister project (a local-business
outreach tool) but runs as a **completely independent app**: its own process,
its own port, its own database, its own config, and its own launcher scripts.
Nothing here reads or writes the other project's data, and starting, stopping
or restarting this app never touches the other one.

---

## Quick start

**Double-click the launcher for your system. That is the whole procedure.**

| Your computer | Double-click this |
|---|---|
| **Windows** | `START.bat` |
| **macOS** | `START.command` |
| **Linux** | `start.sh` (or `./start.sh` in a terminal) |

There is no separate setup step. The first run prepares everything it needs - the
private Python environment, all packages, the dashboard build and the database -
then starts the app and opens your browser. That takes a few minutes and happens
once. Every later run starts in a couple of seconds, because each step is
fingerprinted and skipped when nothing has changed.

You never need to know Python, npm, virtualenv, Vite, FastAPI or any command.
VS Code is not required, and neither is a terminal.

| Windows | macOS / Linux | What it does |
|---|---|---|
| **`START.bat`** | **`START.command`** / **`start.sh`** | **The one file you need.** Sets up anything missing, starts the app, waits until it is healthy, opens the browser |
| `stop.bat` | `./stop.sh` | Stops **only this project's** processes |
| `restart.bat` | `./restart.sh` | Stop, then start |
| `status.bat` | `./status.sh` | What's running, on which port, and whether it answers |
| `setup.bat` | `python3 scripts/launcher.py setup` | Optional. Prepares without starting (`-Force` / `--force` to redo) |
| `scripts\install-autostart.ps1` | — | Optional: start at Windows log-on (asks first) |

Windows runs through PowerShell (`scripts\*.ps1`) and additionally keeps a
crash-recovery watchdog running. macOS and Linux run through
`scripts/launcher.py`, a standard-library-only Python program that performs the
same setup and startup sequence. Both write the same `data/run/backend.pid`, so
either platform's tooling reports the same state.

### Giving this to someone else

Copy or ZIP the project folder, send it, and tell them to double-click the
launcher for their system (`START.bat`, `START.command`, or `start.sh`). It works
from any folder, on any drive, under any account, including paths containing
spaces. Nothing is hardcoded to a machine, username, drive or path - every
location is resolved relative to wherever the launcher is sitting.

**macOS - the one unavoidable step.** The very first time, macOS may refuse to
open `START.command` because it is not from an identified developer. This is an
Apple security rule for every unsigned script and cannot be bypassed from inside
the file. Do this once:

> **Right-click** (or Control-click) `START.command` -> choose **Open** ->
> click **Open** in the dialog.

That is it. Every launch after that is a normal double-click. The launcher then
fixes its own permissions and clears the download quarantine on the rest of the
project, so no Terminal command is ever needed.

If this Mac has no Python, the launcher installs it with Homebrew when Homebrew
is present, and otherwise opens the official python.org download page in the
browser with step-by-step instructions - a normal Mac installer, no Terminal.

**Linux note:** if double-clicking does nothing, run `chmod +x start.sh` then
`./start.sh`. Debian/Ubuntu also needs `python3-venv` (`sudo apt install
python3-venv`) - the launcher says so if it is missing.

The only genuine prerequisite is **Python 3.10+**, and **Node.js 18+** if the
dashboard has not already been built. If either is missing the launcher installs
it automatically using the platform's own package manager and its official
repositories - `winget` on Windows, Homebrew on macOS, `apt`/`dnf`/`pacman` on
Linux. No installer is ever fetched from an ad-hoc URL.

Where that is not possible (no package manager, or a Linux install that would
need a password the launcher deliberately will not prompt for), it prints the
official download page and exactly what to click, then carries on from where it
left off next time.

### What the first run does, in order

1. Checks the operating system, shell and free disk space
2. Creates `data\` and its subfolders, and `.env` from `.env.example`
3. Validates the configuration (port range, host)
4. Finds Python 3.10+ (or installs it) and creates `backend\.venv`
5. Installs the backend packages into that venv - never into your system Python
6. Finds Node 18+ (or installs it), installs the build tools, builds `frontend\dist`
7. Creates the database if there isn't one, and **opens an existing one untouched**
8. Starts the app, waits for `/api/health`, opens the browser
9. On Windows, leaves a watchdog running that restarts the app if it ever stops

Steps 5 and 6 are the slow ones, and both are skipped on later runs unless
`requirements.txt`, `package-lock.json` or the dashboard source actually changed.

Setup is **non-destructive**. It only creates what is missing: your database,
audit history, reports, exports, uploads and settings are never reset or
overwritten, so re-running the launcher on a working installation is always safe.

**URL on this machine** (port set in `.env`, see *Ports* below):

- Dashboard + API: http://localhost:8021 (API docs at `/api/docs`)

Node.js is only needed while the dashboard is being built. Once `frontend/dist`
exists, the launcher never launches Node - only the Python backend runs, and it serves
the built dashboard itself.

---

## What happens when you audit a URL

```
Website URL
   ↓
Crawled politely (robots.txt honoured, rate limited)
   ↓
Technical SEO, on-page SEO, off-page/authority, performance, accessibility,
security, UX and conversion are each checked
   ↓
A 9-part scorecard is computed (higher = healthier)
   ↓
Findings are graded Critical / High / Warning, each with evidence and a fix
   ↓
A full HTML report is generated: executive summary, scorecards, severity
breakdown, passed checks, prioritized action plan
```

Open the result from **Website Audits** once the job finishes — usually well under a
minute for a typical site.

---

## What the app will not do

These are enforced in code and covered by tests, not just documented:

- **No invented findings.** Every issue traces back to a check that actually failed
  against the live page. Backlink and domain-authority data are explicitly labelled
  "not available" rather than fabricated — there is no free, legitimate source for them.
- **No performance claims that were not measured.** Response time is a single
  server-side measurement and is labelled as such. A PageSpeed score appears only if you
  configured your own API key.
- **No rendered-mobile claims.** Mobile findings come from the page's HTML and inline
  CSS and say so. External stylesheets are not downloaded. Playwright is optional.
- **No CAPTCHA or anti-bot circumvention.** A block is recorded as a block.

---

## The scorecard

Nine parts, each scored independently and then weighted into an overall figure —
**higher is better** (this is a health score, unlike opportunity-style scoring):

Overall · Technical SEO · On-Page SEO · Off-Page/Authority · Performance ·
Accessibility · Security · UX · Conversion

Every finding is Critical, High or Warning, with the evidence that triggered it and a
concrete fix. Passed checks are listed too, so a clean site's report isn't just a wall
of problems.

---

## Ports

This project defaults to **8021**, kept deliberately apart from the sister outreach
project (which runs on its own port on this machine). Both can run at the same time —
they do not share a process, a port, a database, or config.

`START.bat` checks the port first. If your preferred port is held by something outside
this project, it does not just fail: it automatically uses the next free port **for that
run** and tells you plainly which URL is actually live. Your `.env` preference is never
overwritten by that fallback - to make a different port permanent, set
`WAE_BACKEND_PORT` yourself.

### Process safety

The service is never matched by a generic name like `python.exe` or `uvicorn`.
`START.bat` records the real PID it launched, and before stopping anything `stop.bat`
confirms the live process's executable path or command line contains **this project's
directory**. A PID that fails that check is reported and left running - so the sister
project's Python process on a nearby port is never touched, and vice versa.

---

## Resume

Every audit is checkpointed. If the app closes mid-run, `START.bat` then **Jobs → Resume**
picks up only the unfinished work.

---

## Optional integrations

All off until you supply your own key, in Settings → Integrations. Keys are stored
server-side in `data/config/engine.json` and are never sent to the browser.

- **Google PageSpeed Insights** — real performance measurement. Adds 10–30s per site and
  is rate limited; best used sparingly.
- **Playwright** — rendered mobile audit. Needs
  `pip install playwright && playwright install chromium` (~300 MB) inside `backend\.venv`.

---

## Tests

```
cd backend
.venv\Scripts\python.exe -m pytest
```

387 tests, ~1 minute, no internet required — crawler and audit tests run against a
small local HTTP server started by the fixtures.

```
cd frontend
npx vite build
```

---

## Layout

```
backend/
  app/
    main.py          FastAPI app
    settings.py      config (data/config/*.json)
    models.py        SQLAlchemy models
    db.py            SQLite (WAL, serialized writes)
    events.py        SSE event bus
    api/             health, settings, uploads, jobs, leads, audits, exports, events
    core/
      urls.py          normalization + identity matching
      fetcher.py       polite HTTP (robots, throttling, retries)
      crawler.py       budgeted priority crawl
      page.py          HTML parsing
      extract.py       public contact discovery (used as audit evidence)
      audit_checks.py  every measurable check, including the premium categories
      scoring.py       weighted opportunity score + the 9-part premium scorecard
      observations.py  human phrasing for each finding
      report_html.py   the premium HTML report
      exporter.py      CSV / XLSX
      pipeline.py      orchestrator, checkpointing, resume
  tests/
frontend/
  src/
    pages/           Audits (results + drawer), Upload (new audit), Reports, Jobs,
                     Settings, System Health
    components/      UI primitives, charts, audit drawer, activity log
  dist/              production build (created by START.bat; gitignored - not committed)
scripts/             bootstrap / start / stop / restart / status / watchdog (lib.ps1 shared)
data/                database, uploads, exports, reports, logs, config
sample_data/         labelled synthetic CSV for testing only
```

**Note on shared history:** this project began as a fork of a local-business outreach
app's codebase, which is why some backend modules (job/pipeline orchestration, contact
extraction) are shared plumbing rather than audit-specific. The frontend has been
trimmed to only the audit-relevant screens; the CSV bulk-import and outreach-channel
(WhatsApp/Email/LinkedIn/Calls) UI from the original project were removed here since
this app's job is auditing websites, not managing leads.

---

## Deploying it publicly

See **[DEPLOY.md](DEPLOY.md)** — the repository already contains a production
`Dockerfile`, a Render blueprint (`render.yaml`) with a persistent disk, and a
GitHub Actions CI workflow. The backend serves the dashboard, so it deploys as
a single service on one HTTPS URL.

---

## Troubleshooting

**Port already in use** — `START.bat` names the program holding it, then automatically
falls back to the next free port for that run. To pin a specific port instead, set it
in `.env`.

**Backend won't start** — check `data\logs\backend.err.log`.

**Dashboard loads but shows no data** — run `status.bat`; if the backend is not
responding the dashboard shows a reconnecting indicator rather than blank panels.

**"Python could not be installed automatically"** — the machine has no `winget`.
Install Python from the link `START.bat` prints (python.org), tick *Add to PATH*,
then double-click `START.bat` again. It resumes from where it stopped.

**First run fails part-way through** — almost always no internet, or a firewall
blocking `pypi.org` / `registry.npmjs.org`. The message says which one. Reconnect
and run `START.bat` again: completed steps are remembered and not repeated.

**The app keeps restarting by itself** — that is the crash-recovery watchdog doing
its job because the app is exiting. `data\logs\watchdog.log` records each attempt
and the reason; `backend.err.log` has the underlying error. After 5 restarts in
10 minutes it stops trying and says so, rather than looping forever.

**Setup seems to repeat work every launch** — delete `data\run\setup.stamp.json`
and run `START.bat` once; a corrupt fingerprint file makes it re-verify. This
costs time only, never data.

**Force a full reinstall** — `setup.bat -Force`. This rebuilds the environment and
dashboard but still never touches your database, reports or settings.

---

## Limitations

Stated plainly, because the alternative is overselling:

- True backlink/referring-domain and domain-authority data would require a paid
  third-party index; this app labels that data "not available" rather than guessing.
- Mobile findings are DOM/CSS-derived unless you enable Playwright.
- Sites behind Cloudflare challenges or aggressive bot protection are recorded as
  `blocked`. That is not worked around.
