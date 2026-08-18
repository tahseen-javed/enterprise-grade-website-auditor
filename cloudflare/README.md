# Website Auditor — Cloudflare deployment

A separate, self-contained deployment target for the same product. It does
**not** modify `backend/`, `frontend/`, `Dockerfile`, `render.yaml` or any of
the launcher scripts — those still work exactly as before for local/Docker/
Render use. This directory adds a second way to run the app, on Cloudflare's
free-tier-friendly stack.

## Architecture

```
GitHub → Cloudflare Workers (Hono API + static dashboard)
           ├── Cloudflare D1        audit history, job/lead state, settings
           ├── Cloudflare R2        generated HTML reports + CSV/XLSX exports
           └── Cloudflare Workflows the crawl → audit → score → report pipeline
```

The React dashboard (`../frontend`) is built unmodified and served as static
assets by the same Worker, on the same origin as the API — exactly like the
existing FastAPI backend serves it today. `wrangler.toml`'s
`not_found_handling = "single-page-application"` makes deep links like
`/audits` work on a hard refresh, and `run_worker_first = ["/api/*"]` makes
sure `/api/*` always reaches the Worker instead of the SPA fallback.

Each audit (one business) is one Workflow instance, checkpointed at each
step — the same "resume where it stopped" guarantee the original got from
per-lead stage checkpointing in `pipeline.py`, just implemented on
Cloudflare's durable-execution primitive instead of an in-process asyncio
worker pool.

## What was intentionally not ported

Two things exist in the original Python backend but are **not** reachable
from this app's actual UI (verified by reading `frontend/src/App.jsx` and
every page/component that calls the API — not by assumption):

- **CSV bulk-import.** `Upload.jsx` only has a single "audit this URL" form;
  there is no file input anywhere in the shipped frontend, even though the
  backend has `POST /api/uploads` and CSV-based job creation.
- **WhatsApp/email/LinkedIn outreach drafting.** The pipeline can write
  these drafts, and `Settings → Your identity` still saves a sender profile,
  but no screen anywhere displays a draft, a channel, or a "mark as sent"
  button — the lead drawer only has Overview / Scorecard / Problems /
  Evidence tabs.

Porting both faithfully (including `outreach.py`'s message templates and the
CSV column-mapping UI) would have roughly doubled the size of this port for
functionality nobody using this app today can see or click. If you want
either of these back, they're addable later — nothing about the D1 schema or
Workflow design precludes it (the `settings` and `contact_emails` tables
already carry what a future outreach feature would need).

**Rendered-mobile audits (Playwright)** were already optional and
off-by-default upstream; they are not available on Cloudflare Workers at
all (no headless browser), so that toggle in Settings is now inert — mobile
findings always come from HTML/CSS analysis, exactly as they do upstream
when Playwright isn't installed.

## Free-plan CPU limit — read this before assuming "it just works"

The Workers **Free** plan hard-caps CPU time at **10ms per Workflow
instance, cumulative across every step** (not reset per step — confirmed
against Cloudflare's current docs, not assumed). Parsing several real HTML
pages, running ~90 checks and building a multi-KB report is real CPU work
that can plausibly exceed that on non-trivial sites. The Workers **Paid**
plan ($5/mo flat) raises this to 30s (configurable to 5 minutes) and is what
we'd actually recommend for reliability — see the deployment report for
which plan this was actually tested and deployed on, and what happened.

D1 and R2 usage should stay inside their own free tiers regardless of which
Workers plan is active (5GB D1 storage / 5M reads-100k writes per day; 10GB
R2 storage / 1M-10M ops per month) — a handful of personal audits a day
comes nowhere near either.

## Local development

```
cd cloudflare
npm install
npm run dev          # builds frontend/, then wrangler dev (local D1 + R2 + Workflows)
```

## Deploy

```
npm run deploy
```

Requires `wrangler login` once, and the D1 database / R2 bucket / Workflow
to already exist (see the deployment report for the exact commands used and
the resulting resource names/IDs — `wrangler.toml`'s `database_id` must
match the real D1 database before this will deploy).
