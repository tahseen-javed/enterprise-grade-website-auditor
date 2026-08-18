# Deploying the Audit Engine as a public website

Everything in this repository is deployment-ready. What remains needs **your
accounts**, which no automated process can create on your behalf.

Your portfolio at `tahseen-javed.github.io` is **not touched by any of this**.
This is a separate service, on separate hosting, with its own URL.

---

## Architecture (why this is simple)

The backend **serves the dashboard itself**. Frontend and backend are one
process on one port, so:

- there is **no separate frontend host** to configure
- there is **no cross-origin problem** — the browser only ever sees one origin
- there is **one URL**, one TLS certificate, one deploy

```
  Browser ── HTTPS ──> Render (Docker: Python API + built dashboard)
                          └── /data  persistent disk
                                ├── app.db        SQLite (audit history)
                                ├── reports/      generated HTML reports
                                └── exports/      CSV / XLSX
```

---

## Why not the obvious free options

| Option | Verdict |
|---|---|
| GitHub Pages | Static only. Cannot run Python. |
| Vercel / Netlify functions | Serverless: 10–60s timeouts kill audits that take longer, and the filesystem is ephemeral, so audit history disappears. |
| Render **free** | Works, but the disk is ephemeral **and** it sleeps after 15 min idle. Audit history is lost on every restart, and the first request after sleeping can time out mid-audit. |
| **Render Starter + 1 GB disk** | **Recommended.** Persistent history, no sleeping, free HTTPS, free custom domain, deploy-on-push. |
| Fly.io / Railway | Also fine (both support volumes). Comparable cost. |
| Oracle Cloud Always Free ARM VM | Genuinely free forever with a real disk, but you administer the VM yourself. |

This app needs a **persistent filesystem** and **long-running background jobs**.
That is what rules out the free serverless tiers, not preference.

**Cost of the recommendation: about $7/month** (Starter) **+ ~$0.25/month**
(1 GB disk). If you want zero cost and can accept losing audit history on every
restart, set `plan: free` in `render.yaml` and delete the `disk:` block.

---

## Deploy it (about 10 minutes)

### 1. Put this repo on GitHub as its own project

It is currently at `tahseen-javed/enterprise-grade-website-auditor`. That is
already separate from your portfolio repo, so nothing else is needed. (If you
prefer a different name, create the empty repo on GitHub, then:
`git remote set-url origin <new-url> && git push -u origin main`.)

### 2. Create the service on Render

1. Sign in at <https://dashboard.render.com> with your GitHub account.
2. **New → Blueprint**.
3. Select this repository. Render reads `render.yaml` and fills everything in:
   Docker build, the 1 GB disk mounted at `/data`, the health check on
   `/api/health`, and the environment variables.
4. Click **Apply**. The first build takes roughly 5–8 minutes.

You get a live HTTPS URL immediately, of the form:

```
https://website-audit-engine.onrender.com
```

That URL already works worldwide, on any phone or laptop, with no local setup.

### 3. Custom domain (optional)

In Render: **Settings → Custom Domains → Add**. Then at your DNS provider:

| Type | Name | Value |
|---|---|---|
| CNAME | `audit` | `website-audit-engine.onrender.com` |

giving `https://audit.yourdomain.com`. Render issues the TLS certificate
automatically once DNS resolves (usually minutes, up to a few hours).

**This does not affect your portfolio.** A new `audit` subdomain record is
additive — your existing `A`/`CNAME` records for the apex and `www` are
untouched.

If you have no custom domain, the `.onrender.com` URL is production-grade and
already has HTTPS.

---

## Secrets

**No API keys belong in this repository, and none are in it.**

PageSpeed / Claude / Google Places keys are entered in the app's own
**Settings** page and stored server-side under `/data/config/engine.json` on
the persistent disk. They are never sent to the browser and never committed.

If you would rather inject one at the platform level, add it in the Render
dashboard under **Environment** as a secret. Do not put it in `render.yaml`.

---

## What is already configured

- `Dockerfile` — multi-stage: Node builds the dashboard, the runtime image
  contains only Python plus the built files. Runs as a non-root user.
- Binds `0.0.0.0` and honours the platform's injected `$PORT`. Binding
  `127.0.0.1` inside a container is the usual cause of a "deployed but 502".
- `--proxy-headers --forwarded-allow-ips='*'` so the app sees the real client
  scheme and IP behind Render's TLS terminator.
- `WAE_DATA_DIR=/data` so the database, reports and exports live on the disk
  and survive redeploys.
- `healthCheckPath: /api/health` so a broken build never replaces a working one.
- `.github/workflows/ci.yml` — runs the backend tests, builds the dashboard,
  and builds and boots the production image on every push.
- `autoDeploy: true` — every push to `main` redeploys automatically.

---

## Verified before shipping

Run locally against the exact production configuration
(`WAE_BACKEND_HOST=0.0.0.0`, injected `PORT`, external `WAE_DATA_DIR`):

- health endpoint returns 200
- dashboard, hashed assets and SPA deep links (`/audits`) all serve correctly
- `/api/*` 404s correctly instead of falling through to `index.html`
- a real audit of `example.com` completed and produced the premium report
- CSV, XLSX and reports.zip all downloaded successfully
- **the process was killed and restarted against the same volume, and the job
  history and the downloadable report both survived** — this is the check that
  proves the persistent-disk setup actually preserves audit history

---

## Notes for production use

- **Cold start**: on the free plan the first request after 15 minutes of idle
  takes ~30s while the service wakes. Starter does not sleep.
- **Concurrency**: one instance runs audits sequentially through its worker
  pool. That is fine for personal or client-demo use. Heavy public traffic
  would want a queue and more instances.
- **Public exposure**: there is no authentication. Anyone with the URL can run
  audits, which costs you crawl bandwidth. If the URL will be shared widely,
  put Cloudflare Access in front of it or add auth before publishing.
