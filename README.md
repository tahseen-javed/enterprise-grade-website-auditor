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

```
1. setup.bat      (once - creates the Python environment, installs packages, builds the frontend)
2. start.bat      (opens the dashboard in your browser)
3. New audit       a website URL
```

VS Code is not required for any of this. The whole app is **one process**: the backend
serves the built dashboard directly, so there is nothing else to install or keep running.
`start.bat` launches it detached, so it keeps running after the window closes.

The project folder is fully portable - copy it anywhere (a different drive, a different
PC, a different Windows account) and run `setup.bat` there. Nothing here is hardcoded to
a machine, username or path; ports, project location and runtime paths are all detected
at run time.

| Script | What it does |
|---|---|
| `setup.bat` | One-time (or after pulling changes): creates `backend\.venv`, installs Python + Node packages, builds `frontend\dist`, initialises the database |
| `start.bat` | Starts the app detached, waits until it responds, opens the browser |
| `stop.bat` | Stops **only this project's** process |
| `restart.bat` | Stop, then start |
| `status.bat` | What's running, on which port, component health, recent jobs |
| `scripts\install-autostart.ps1` | Optional: start at Windows log-on (asks first) |
| `scripts\uninstall-autostart.ps1` | Removes that scheduled task |

**URL on this machine** (port set in `.env`, see *Ports* below):

- Dashboard + API: http://localhost:8021 (API docs at `/api/docs`)

Node.js is only needed at `setup.bat` time, to build the dashboard. Once `frontend\dist`
exists, `start.bat` never launches Node - only the Python backend runs, and it serves
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

`start.bat` checks the port first. If your preferred port is held by something outside
this project, it does not just fail: it automatically uses the next free port **for that
run** and tells you plainly which URL is actually live. Your `.env` preference is never
overwritten by that fallback - to make a different port permanent, set
`WAE_BACKEND_PORT` yourself.

### Process safety

The service is never matched by a generic name like `python.exe` or `uvicorn`.
`start.bat` records the real PID it launched, and before stopping anything `stop.bat`
confirms the live process's executable path or command line contains **this project's
directory**. A PID that fails that check is reported and left running - so the sister
project's Python process on a nearby port is never touched, and vice versa.

---

## Resume

Every audit is checkpointed. If the app closes mid-run, `start.bat` then **Jobs → Resume**
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
  dist/              production build (created by setup.bat; gitignored - not committed)
scripts/             start / stop / restart / status / setup / autostart (lib.ps1 shared)
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

## Troubleshooting

**Port already in use** — `start.bat` names the program holding it, then automatically
falls back to the next free port for that run. To pin a specific port instead, set it
in `.env`.

**Backend won't start** — check `data\logs\backend.err.log`.

**Dashboard loads but shows no data** — run `status.bat`; if the backend is not
responding the dashboard shows a reconnecting indicator rather than blank panels.

---

## Limitations

Stated plainly, because the alternative is overselling:

- True backlink/referring-domain and domain-authority data would require a paid
  third-party index; this app labels that data "not available" rather than guessing.
- Mobile findings are DOM/CSS-derived unless you enable Playwright.
- Sites behind Cloudflare challenges or aggressive bot protection are recorded as
  `blocked`. That is not worked around.
