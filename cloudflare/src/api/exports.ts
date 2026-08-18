// CSV / XLSX / reports.zip exports. Ported from backend/app/api/exports.py.
import { Hono } from "hono";
import type { Env } from "../types";
import * as q from "../db/queries";
import { fromJson } from "../db/queries";
import { buildExportRows, buildReportsZip, COLUMN_DOCS, ENRICHMENT_COLUMNS, exportCsv, exportFilename, exportXlsx, ExportBusinessRow } from "../core/exporter";
import { getReport } from "../lib/r2";

export const exportsRoute = new Hono<{ Bindings: Env }>();

// The download itself never depends on R2 — only the "keep a copy for
// Reports > Previously generated files" convenience does. If storage is
// temporarily unavailable, the export still succeeds; it just won't show
// up in history until storage is back.
async function saveExportCopy(bucket: R2Bucket | undefined, key: string, body: string | ArrayBuffer, contentType: string): Promise<void> {
  try {
    if (!bucket) return;
    await bucket.put(key, body, { httpMetadata: { contentType } });
  } catch {
    /* best effort */
  }
}

exportsRoute.get("/exports/columns", (c) =>
  c.json({
    columns: ENRICHMENT_COLUMNS, documentation: COLUMN_DOCS,
    note: "These are appended after every original column from your CSV. Original columns and row order are preserved exactly, and one input business remains one output row.",
  }),
);

async function loadExportRows(db: D1Database, jobId: number): Promise<{ job: q.JobRow; rows: ExportBusinessRow[] } | null> {
  const job = await q.getJob(db, jobId);
  if (!job) return null;
  const businessesRes = await db.prepare(`SELECT * FROM businesses WHERE job_id = ? ORDER BY row_index`).bind(jobId).all<q.BusinessRow>();
  const businesses = businessesRes.results ?? [];
  const ids = businesses.map((b) => b.id);

  const auditByBiz = new Map<number, any>();
  const emailsByBiz = new Map<number, any[]>();
  if (ids.length) {
    const placeholders = ids.map(() => "?").join(",");
    const auditsRes = await db.prepare(`SELECT * FROM website_audits WHERE business_id IN (${placeholders})`).bind(...ids).all<any>();
    for (const a of auditsRes.results ?? []) auditByBiz.set(a.business_id, a);
    const emailsRes = await db.prepare(`SELECT * FROM contact_emails WHERE business_id IN (${placeholders}) ORDER BY rank`).bind(...ids).all<any>();
    for (const e of emailsRes.results ?? []) {
      if (!emailsByBiz.has(e.business_id)) emailsByBiz.set(e.business_id, []);
      emailsByBiz.get(e.business_id)!.push(e);
    }
  }

  const rows: ExportBusinessRow[] = businesses.map((b) => {
    const audit = auditByBiz.get(b.id);
    return {
      raw: fromJson(b.raw, {}), website_status: b.website_status, website_final: b.website_final,
      website_identity_confidence: b.website_identity_confidence, website_source: b.website_source,
      score: b.score, opportunity_tier: b.opportunity_tier, lead_tier: b.lead_tier,
      best_channel: b.best_channel, channel_reason: b.channel_reason,
      linkedin_url: b.linkedin_url, linkedin_status: b.linkedin_status, processed_at: b.processed_at,
      audit: audit
        ? {
            problems: fromJson(audit.problems, []), recommendations: fromJson(audit.recommendations, []),
            priorities: fromJson<any>(audit.extra, {})?.priorities || [], report_r2_key: audit.report_r2_key,
            audit_status: audit.audit_status, audit_error: audit.audit_error,
          }
        : null,
      emails: (emailsByBiz.get(b.id) || []).map((e) => ({ email: e.email, source_url: e.source_url, status: e.status })),
    };
  });

  return { job, rows };
}

exportsRoute.get("/exports/:jobId/csv", async (c) => {
  const jobId = Number(c.req.param("jobId"));
  const loaded = await loadExportRows(c.env.DB, jobId);
  if (!loaded) return c.json({ detail: "Job not found." }, 404);

  const { headers, rows } = buildExportRows(fromJson(loaded.job.original_columns, []), loaded.rows);
  const csv = exportCsv(headers, rows);
  const filename = exportFilename(jobId, loaded.job.name, "csv");
  await saveExportCopy(c.env.REPORTS, `exports/${filename}`, csv, "text/csv; charset=utf-8");

  return new Response(csv, { headers: { "content-type": "text/csv; charset=utf-8", "content-disposition": `attachment; filename="${filename}"` } });
});

exportsRoute.get("/exports/:jobId/xlsx", async (c) => {
  const jobId = Number(c.req.param("jobId"));
  const loaded = await loadExportRows(c.env.DB, jobId);
  if (!loaded) return c.json({ detail: "Job not found." }, 404);

  const { headers, rows } = buildExportRows(fromJson(loaded.job.original_columns, []), loaded.rows);
  const originalCount = fromJson<string[]>(loaded.job.original_columns, []).length;
  const buf = await exportXlsx(headers, rows, originalCount);
  const filename = exportFilename(jobId, loaded.job.name, "xlsx");
  await saveExportCopy(c.env.REPORTS, `exports/${filename}`, buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");

  return new Response(buf, { headers: { "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "content-disposition": `attachment; filename="${filename}"` } });
});

exportsRoute.get("/exports/:jobId/reports.zip", async (c) => {
  const jobId = Number(c.req.param("jobId"));
  const job = await q.getJob(c.env.DB, jobId);
  if (!job) return c.json({ detail: "Job not found." }, 404);

  const rows = await c.env.DB
    .prepare(`SELECT wa.report_r2_key as key, b.name as name FROM website_audits wa JOIN businesses b ON b.id = wa.business_id WHERE b.job_id = ? AND wa.report_r2_key != ''`)
    .bind(jobId)
    .all<{ key: string; name: string }>();

  const files: { name: string; content: string }[] = [];
  for (const r of rows.results ?? []) {
    try {
      const obj = c.env.REPORTS ? await getReport(c.env.REPORTS, r.key) : null;
      if (obj) files.push({ name: r.key.split("/").pop() || `${r.name}.html`, content: await obj.text() });
    } catch {
      /* skip a report that can't currently be read; the rest of the zip still builds */
    }
  }
  if (!files.length) return c.json({ detail: "No audit reports have been generated yet." }, 404);

  const zip = buildReportsZip(files);
  return new Response(zip, { headers: { "content-type": "application/zip", "content-disposition": `attachment; filename="job${jobId}-audit-reports.zip"` } });
});

exportsRoute.get("/exports/history", async (c) => {
  const limit = Math.max(1, Math.min(200, Number(c.req.query("limit") ?? 30)));
  if (!c.env.REPORTS) return c.json({ files: [], folder: "Cloudflare R2 (exports/)" });
  const listing = await c.env.REPORTS.list({ prefix: "exports/", limit: 1000 });
  const files = listing.objects
    .sort((a, b) => (b.uploaded?.getTime() ?? 0) - (a.uploaded?.getTime() ?? 0))
    .slice(0, limit)
    .map((o) => ({
      name: o.key.replace(/^exports\//, ""), size_bytes: o.size, modified: (o.uploaded?.getTime() ?? 0) / 1000,
      kind: o.key.split(".").pop() || "",
    }));
  return c.json({ files, folder: "Cloudflare R2 (exports/)" });
});
