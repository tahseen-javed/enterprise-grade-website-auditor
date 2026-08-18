// Worker entry point. Ported from backend/app/main.py: the /api/* routers
// are mounted first, static assets (the built dashboard) are handled by the
// [assets] binding per wrangler.toml's run_worker_first = ["/api/*"], so an
// /api/* request always reaches this router and everything else falls
// through to the SPA (with the single-page-application 404 fallback making
// deep links like /audits work).
import { Hono } from "hono";
import type { Env } from "./types";
import { health } from "./api/health";
import { settings } from "./api/settings";
import { audits } from "./api/audits";
import { jobs } from "./api/jobs";
import { leads } from "./api/leads";
import { exportsRoute } from "./api/exports";
import { events } from "./api/events";

const app = new Hono<{ Bindings: Env }>();

app.onError((err, c) => {
  console.error(`Unhandled error on ${c.req.method} ${c.req.path}:`, err);
  return c.json({ error: "internal_error", message: `${err.name}: ${err.message}`, path: c.req.path }, 500);
});

const api = new Hono<{ Bindings: Env }>();
api.route("/", health);
api.route("/", settings);
api.route("/", audits);
api.route("/", jobs);
api.route("/", leads);
api.route("/", exportsRoute);
api.route("/", events);

app.route("/api", api);

// Everything else (the built dashboard, including SPA deep links like
// /audits, which [assets].not_found_handling = "single-page-application"
// resolves to index.html) — run_worker_first = true means every request
// reaches this Worker, so anything not under /api/* is handed to the
// static-assets binding explicitly.
//
// Hono's app.route("/api", api) only intercepts paths that match one of
// api's own registered routes; an unmatched /api/* path (e.g. a typo, or a
// route intentionally not implemented in this deployment) falls through to
// here rather than triggering api's own 404 — so this must explicitly catch
// and reject /api/* itself, exactly like the original FastAPI app's
// spa_fallback does ("if full_path.startswith('api/'): raise 404"), or an
// unmatched API call would silently return the SPA's index.html instead of
// a 404.
app.all("*", (c) => {
  if (c.req.path.startsWith("/api/") || c.req.path === "/api") {
    return c.json({ detail: "Not found." }, 404);
  }
  return c.env.ASSETS.fetch(c.req.raw);
});

export default app;
export { AuditWorkflow } from "./workflows/audit-workflow";
