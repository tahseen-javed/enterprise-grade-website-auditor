// Lead listing, detail and audit-report download. Ported from
// backend/app/api/leads.py (regenerate-outreach / mark-sent are not ported —
// see cloudflare/README.md for why).
import { Hono } from "hono";
import type { Env } from "../types";
import * as q from "../db/queries";
import { fromJson } from "../db/queries";
import { getReport } from "../lib/r2";

export const leads = new Hono<{ Bindings: Env }>();

function leadRow(b: q.BusinessRow, emails: { email: string; status: string }[], audit: any, item: any) {
  return {
    id: b.id, job_id: b.job_id, row_index: b.row_index, name: b.name, category: b.category,
    city: b.city, state: b.state, country: b.country, address: b.address, rating: b.rating,
    review_count: b.review_count, maps_url: b.maps_url,
    website_original: b.website_original, website_final: b.website_final, website_status: b.website_status,
    website_identity_confidence: b.website_identity_confidence, website_source: b.website_source,
    score: b.score, opportunity_tier: b.opportunity_tier, lead_tier: b.lead_tier, audit_kind: b.audit_kind,
    best_channel: b.best_channel, channel_reason: b.channel_reason,
    contact_channel: (b.best_channel || "SKIP").toUpperCase(), contact_channel_reason: b.channel_reason,
    linkedin_url: b.linkedin_url, linkedin_status: b.linkedin_status,
    processed_at: b.processed_at, is_duplicate_of: b.is_duplicate_of,
    status: item?.status || "pending", stage: item?.stage || "queued", error_message: item?.error_message || "",
    phone: null,
    emails: emails.map((e) => ({ email: e.email, status: e.status })),
    problem_count: audit ? fromJson<any[]>(audit.problems, []).length : 0,
    problems: audit ? fromJson<any[]>(audit.problems, []).slice(0, 3) : [],
    audit_status: audit?.audit_status || "",
    has_report: Boolean(audit?.report_r2_key),
    premium_score: audit ? fromJson<any>(audit.extra, {})?.scorecard?.overall_score ?? null : null,
    drafts_available: [], draft_preview: "",
  };
}

leads.get("/leads", async (c) => {
  const jobIdParam = c.req.query("job_id");
  const page = Math.max(1, Number(c.req.query("page") ?? 1));
  const pageSize = Math.max(1, Math.min(500, Number(c.req.query("page_size") ?? 50)));
  const result = await q.listLeads(c.env.DB, {
    jobId: jobIdParam ? Number(jobIdParam) : undefined,
    search: c.req.query("search") || undefined,
    minScore: c.req.query("min_score") ? Number(c.req.query("min_score")) : undefined,
    websiteStatus: c.req.query("website_status") || undefined,
    sort: c.req.query("sort") || "score_desc",
    page, pageSize,
  });

  return c.json({
    total: result.total, page, page_size: pageSize, pages: Math.max(1, Math.ceil(result.total / pageSize)),
    leads: result.rows.map((b) => leadRow(b, result.emailsByBiz.get(b.id) || [], result.auditByBiz.get(b.id), result.itemByBiz.get(b.id))),
  });
});

leads.get("/leads/:id", async (c) => {
  const id = Number(c.req.param("id"));
  const detail = await q.getLeadDetail(c.env.DB, id);
  if (!detail) return c.json({ detail: "Lead not found." }, 404);
  const { business: b, audit, emails, item, errors } = detail;

  const base = leadRow(b, emails, audit, item);
  return c.json({
    ...base,
    raw: fromJson(b.raw, {}),
    audit: audit
      ? {
          website: audit.website, audit_kind: audit.audit_kind, http_status: audit.http_status,
          is_https: audit.is_https === null ? null : Boolean(audit.is_https), redirect_chain: fromJson(audit.redirect_chain, []),
          response_ms: audit.response_ms, pages_crawled: audit.pages_crawled, pages: fromJson(audit.pages, []),
          technical: fromJson(audit.technical, {}), conversion: fromJson(audit.conversion, {}), mobile: fromJson(audit.mobile, {}),
          trust: fromJson(audit.trust, {}), content: fromJson(audit.content, {}), performance: fromJson(audit.performance, {}),
          subscores: fromJson(audit.subscores, {}), score: audit.score, opportunity_tier: audit.opportunity_tier,
          score_explanation: fromJson(audit.score_explanation, []), problems: fromJson(audit.problems, []),
          recommendations: fromJson(audit.recommendations, []), audit_status: audit.audit_status, audit_error: audit.audit_error,
          has_report: Boolean(audit.report_r2_key), created_at: audit.created_at, extra: fromJson(audit.extra, {}),
        }
      : null,
    drafts: [],
    errors: errors.map((e: any) => ({ stage: e.stage, code: e.code, message: e.message, retryable: Boolean(e.retryable), url: e.url, created_at: e.created_at })),
  });
});

leads.get("/leads/:id/report", async (c) => {
  const id = Number(c.req.param("id"));
  const key = await q.getReportKey(c.env.DB, id);
  if (!key) return c.json({ detail: "No audit report exists for this lead." }, 404);
  const obj = await getReport(c.env.REPORTS, key);
  if (!obj) return c.json({ detail: "The report file is missing from storage." }, 404);
  return new Response(obj.body, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "private, max-age=60" } });
});
