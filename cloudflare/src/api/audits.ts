// Direct website audits — POST /api/audits/quick. Ported from
// backend/app/api/audits.py. This is the only job-creation path the live
// frontend actually uses (see frontend/src/pages/Upload.jsx).
import { Hono } from "hono";
import type { Env } from "../types";
import { isNonWebsiteHost, normalizeUrl, registrableDomain } from "../core/urls";
import { getEngine } from "../lib/settings";
import * as q from "../db/queries";

export const audits = new Hono<{ Bindings: Env }>();

audits.post("/audits/quick", async (c) => {
  const body = await c.req.json().catch(() => ({}));
  const raw = String(body?.url || "").trim();
  const norm = normalizeUrl(raw);
  if (!norm) {
    return c.json({ detail: "That does not look like a valid website URL. Include the domain, e.g. example.com or https://example.com." }, 400);
  }
  const { isProfile, kind } = isNonWebsiteHost(norm);
  if (isProfile) {
    return c.json({ detail: `That URL is a ${kind.replace(/_/g, " ")}, not a standalone website, so it cannot be crawled and audited the same way.` }, 400);
  }

  const domain = registrableDomain(norm);
  const label = String(body?.name || "").trim() || domain || norm;
  const db = c.env.DB;
  const engine = await getEngine(db);

  const jobId = await q.createJob(db, { name: `Website audit — ${label}`.slice(0, 255), sourceKind: "url", total: 1, engineSnapshot: engine });
  const nameNormalized = label.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const businessId = await q.createBusiness(db, {
    jobId, rowIndex: 0, raw: { url: raw }, name: label.slice(0, 512), nameNormalized,
    websiteOriginal: norm, dedupKey: domain ? `site:${domain}` : "",
  });
  await q.createJobItem(db, jobId, businessId);
  await q.addEvent(db, { jobId, message: `Direct audit started: ${norm}`, stage: "job" });

  const startImmediately = body?.start_immediately !== false;
  let started = false;
  if (startImmediately) {
    const instance = await c.env.AUDIT_WORKFLOW.create({ id: `job-${jobId}-biz-${businessId}`, params: { jobId, businessId } });
    await q.setJobWorkflowInstance(db, jobId, instance.id);
    started = true;
  }

  return c.json({ job_id: jobId, business_id: businessId, url: norm, started });
});
