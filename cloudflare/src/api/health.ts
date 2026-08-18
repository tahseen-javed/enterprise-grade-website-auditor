// Health and System Health endpoints. Ported from backend/app/api/health.py,
// adapted to what a Worker can actually introspect about itself.
import { Hono } from "hono";
import type { Env } from "../types";
import { enginePublic, getEngine } from "../lib/settings";
import { checkAvailability } from "../core/pagespeed";

export const health = new Hono<{ Bindings: Env }>();

health.get("/health", (c) => c.json({ status: "ok", app: c.env.APP_NAME, version: c.env.APP_VERSION }));

health.get("/system/health", async (c) => {
  const engine = await getEngine(c.env.DB);

  const outbound = await (async () => {
    try {
      const controller = new AbortController();
      const t = setTimeout(() => controller.abort(), 8000);
      const r = await fetch("https://example.com", { signal: controller.signal });
      clearTimeout(t);
      return r.status < 400
        ? { status: "healthy", detail: `Outbound HTTPS works (example.com → ${r.status}).` }
        : { status: "warning", detail: `Outbound request returned HTTP ${r.status}.` };
    } catch (exc: any) {
      return { status: "error", detail: `Outbound HTTPS failed (${exc?.message || exc}). The crawler cannot reach websites.` };
    }
  })();

  const dns = await (async () => {
    try {
      const controller = new AbortController();
      const t = setTimeout(() => controller.abort(), 5000);
      const r = await fetch("https://cloudflare-dns.com/dns-query?name=google.com&type=A", { headers: { accept: "application/dns-json" }, signal: controller.signal });
      clearTimeout(t);
      const data = (await r.json()) as any;
      return data.Status === 0
        ? { status: "healthy", detail: "DNS-over-HTTPS resolution is working." }
        : { status: "warning", detail: `DNS-over-HTTPS returned status ${data.Status}.` };
    } catch (exc: any) {
      return { status: "error", detail: `DNS lookups are failing (${exc?.message || exc}). Email MX validation will report 'unknown'.` };
    }
  })();

  let database: { status: string; detail: string };
  try {
    await c.env.DB.prepare("SELECT 1").first();
    database = { status: "healthy", detail: "D1 is reachable and responding." };
  } catch (exc: any) {
    database = { status: "error", detail: `D1 error: ${exc?.message || exc}` };
  }

  let r2Status: { status: string; detail: string };
  if (!c.env.REPORTS) {
    r2Status = { status: "error", detail: "The R2 REPORTS binding is not configured in this deployment — reports and export history are unavailable until it's added back and redeployed." };
  } else {
    try {
      await c.env.REPORTS.head("__healthcheck__");
      r2Status = { status: "healthy", detail: "R2 bucket is reachable." };
    } catch (exc: any) {
      r2Status = { status: "error", detail: `R2 error: ${exc?.message || exc}` };
    }
  }

  const pagespeed = engine.pagespeed_enabled
    ? engine.pagespeed_api_key
      ? await checkAvailability(engine.pagespeed_api_key)
      : { status: "warning", detail: "PageSpeed is enabled but no API key is set, so no performance score will be recorded." }
    : { status: "disabled", detail: "Optional. Not configured, so no PageSpeed score is claimed." };

  const components: Record<string, { status: string; detail: string }> = {
    backend: { status: "healthy", detail: `Cloudflare Worker, ${c.env.APP_VERSION}. Audits run as Cloudflare Workflow instances.` },
    database, storage: r2Status,
    crawler: { status: "healthy", detail: `HTML parser loaded. Politeness delay ${engine.per_domain_delay_ms}ms, robots ${engine.respect_robots ? "respected" : "IGNORED"}.` },
    dns, outbound_http: outbound,
    email_validator: { status: "healthy", detail: "Syntax + DNS-over-HTTPS MX validation ready." },
    browser_engine: { status: "disabled", detail: "Rendered-browser mobile audits (Playwright) are not available on Cloudflare Workers; mobile findings come from HTML and inline CSS and are labelled as such." },
    pagespeed,
    export_engine: { status: "healthy", detail: "CSV, XLSX and HTML export engines ready." },
    event_stream: { status: "healthy", detail: "Live activity stream via Server-Sent Events, backed by D1." },
  };

  const ranks: Record<string, number> = { error: 3, warning: 2, healthy: 1, disabled: 0 };
  const worst = Math.max(...Object.values(components).map((cmp) => ranks[cmp.status] ?? 1));
  const overall = ({ 3: "error", 2: "warning", 1: "healthy", 0: "healthy" } as Record<number, string>)[worst];

  return c.json({
    overall, components, engine: await enginePublic(c.env.DB),
    ports: { backend: 443, frontend: 443 },
    paths: { data: "Cloudflare D1", uploads: "not used in this deployment", exports: "Cloudflare R2 (exports/)", reports: "Cloudflare R2 (reports/)" },
  });
});
