// D1 data access. Column names/shapes mirror backend/app/models.py closely
// enough that API responses keep the same JSON shape the frontend expects.
import type { Finding } from "../types";

function nowIso(): string {
  return new Date().toISOString();
}
function j(v: unknown): string {
  return JSON.stringify(v ?? null);
}
function parseJ<T>(s: string | null | undefined, fallback: T): T {
  if (!s) return fallback;
  try {
    return JSON.parse(s) as T;
  } catch {
    return fallback;
  }
}

// ---------------------------------------------------------------------------
// jobs
// ---------------------------------------------------------------------------

export interface JobRow {
  id: number; name: string; source_filename: string; stored_path: string; source_kind: string;
  original_columns: string; column_mapping: string; engine_snapshot: string; status: string;
  total: number; created_at: string; started_at: string | null; finished_at: string | null;
  last_error: string; workflow_instance_id: string; live_progress: string;
}

export async function createJob(db: D1Database, opts: {
  name: string; sourceKind: string; total: number; engineSnapshot: unknown;
}): Promise<number> {
  const res = await db
    .prepare(`INSERT INTO jobs (name, source_kind, total, engine_snapshot, status, created_at) VALUES (?, ?, ?, ?, 'queued', ?)`)
    .bind(opts.name.slice(0, 255), opts.sourceKind, opts.total, j(opts.engineSnapshot), nowIso())
    .run();
  return res.meta.last_row_id as number;
}

export async function setJobWorkflowInstance(db: D1Database, jobId: number, instanceId: string): Promise<void> {
  await db.prepare(`UPDATE jobs SET workflow_instance_id = ? WHERE id = ?`).bind(instanceId, jobId).run();
}

export async function setJobStatus(db: D1Database, jobId: number, status: string, opts: { startedAt?: boolean; finishedAt?: boolean; lastError?: string } = {}): Promise<void> {
  const sets = ["status = ?"];
  const args: unknown[] = [status];
  if (opts.startedAt) sets.push("started_at = COALESCE(started_at, ?)"), args.push(nowIso());
  if (opts.finishedAt) sets.push("finished_at = ?"), args.push(nowIso());
  if (opts.lastError !== undefined) sets.push("last_error = ?"), args.push(opts.lastError.slice(0, 2000));
  args.push(jobId);
  await db.prepare(`UPDATE jobs SET ${sets.join(", ")} WHERE id = ?`).bind(...args).run();
}

export async function setJobLiveProgress(db: D1Database, jobId: number, progress: unknown): Promise<void> {
  await db.prepare(`UPDATE jobs SET live_progress = ? WHERE id = ?`).bind(j(progress), jobId).run();
}

export async function getJob(db: D1Database, jobId: number): Promise<JobRow | null> {
  return db.prepare(`SELECT * FROM jobs WHERE id = ?`).bind(jobId).first<JobRow>();
}

export async function listJobs(db: D1Database, limit = 50): Promise<JobRow[]> {
  const res = await db.prepare(`SELECT * FROM jobs ORDER BY id DESC LIMIT ?`).bind(Math.max(1, Math.min(200, limit))).all<JobRow>();
  return res.results ?? [];
}

export async function deleteJob(db: D1Database, jobId: number): Promise<void> {
  await db.batch([
    db.prepare(`DELETE FROM events WHERE job_id = ?`).bind(jobId),
    db.prepare(`DELETE FROM audit_errors WHERE job_id = ?`).bind(jobId),
    db.prepare(`DELETE FROM job_items WHERE job_id = ?`).bind(jobId),
    db.prepare(`DELETE FROM contact_emails WHERE business_id IN (SELECT id FROM businesses WHERE job_id = ?)`).bind(jobId),
    db.prepare(`DELETE FROM website_audits WHERE business_id IN (SELECT id FROM businesses WHERE job_id = ?)`).bind(jobId),
    db.prepare(`DELETE FROM businesses WHERE job_id = ?`).bind(jobId),
    db.prepare(`DELETE FROM jobs WHERE id = ?`).bind(jobId),
  ]);
}

export interface JobCounts {
  pending: number; running: number; completed: number; failed: number; skipped: number;
}

export async function jobItemCounts(db: D1Database, jobId: number): Promise<JobCounts> {
  const res = await db.prepare(`SELECT status, COUNT(*) as n FROM job_items WHERE job_id = ? GROUP BY status`).bind(jobId).all<{ status: string; n: number }>();
  const out: JobCounts = { pending: 0, running: 0, completed: 0, failed: 0, skipped: 0 };
  for (const r of res.results ?? []) if (r.status in out) (out as any)[r.status] = r.n;
  return out;
}

export async function jobErrorCount(db: D1Database, jobId: number): Promise<number> {
  const r = await db.prepare(`SELECT COUNT(*) as n FROM audit_errors WHERE job_id = ?`).bind(jobId).first<{ n: number }>();
  return r?.n ?? 0;
}

// ---------------------------------------------------------------------------
// businesses / job_items
// ---------------------------------------------------------------------------

export interface BusinessRow {
  id: number; job_id: number; row_index: number; raw: string; name: string; name_normalized: string;
  category: string; address: string; city: string; state: string; country: string; country_code: string;
  postal_code: string; rating: number | null; review_count: number | null; place_id: string; maps_url: string;
  phone_raw: string; website_original: string; dedup_key: string; is_duplicate_of: number | null;
  website_final: string; website_status: string; website_identity_confidence: number | null; website_source: string;
  score: number | null; opportunity_tier: string; lead_tier: string; audit_kind: string;
  best_channel: string; channel_reason: string; linkedin_url: string; linkedin_status: string; processed_at: string | null;
}

export async function createBusiness(db: D1Database, opts: {
  jobId: number; rowIndex: number; raw: unknown; name: string; nameNormalized: string;
  websiteOriginal: string; dedupKey: string;
}): Promise<number> {
  const res = await db
    .prepare(
      `INSERT INTO businesses (job_id, row_index, raw, name, name_normalized, website_original, dedup_key)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(opts.jobId, opts.rowIndex, j(opts.raw), opts.name.slice(0, 512), opts.nameNormalized.slice(0, 512), opts.websiteOriginal, opts.dedupKey)
    .run();
  return res.meta.last_row_id as number;
}

export async function createJobItem(db: D1Database, jobId: number, businessId: number): Promise<void> {
  await db.prepare(`INSERT INTO job_items (job_id, business_id, status, stage, updated_at) VALUES (?, ?, 'pending', 'queued', ?)`).bind(jobId, businessId, nowIso()).run();
}

export async function startJobItem(db: D1Database, businessId: number): Promise<void> {
  await db
    .prepare(
      `UPDATE job_items SET status = 'running', stage = 'normalize', attempts = attempts + 1,
       started_at = COALESCE(started_at, ?), error_message = '', error_stage = '', updated_at = ? WHERE business_id = ?`,
    )
    .bind(nowIso(), nowIso(), businessId)
    .run();
}

export async function markStage(db: D1Database, businessId: number, stage: string): Promise<void> {
  await db.prepare(`UPDATE job_items SET stage = ?, updated_at = ? WHERE business_id = ?`).bind(stage, nowIso(), businessId).run();
}

export async function completeJobItem(db: D1Database, businessId: number): Promise<void> {
  await db.prepare(`UPDATE job_items SET status = 'completed', stage = 'done', finished_at = ?, updated_at = ? WHERE business_id = ?`).bind(nowIso(), nowIso(), businessId).run();
}

export async function failJobItem(db: D1Database, businessId: number, stage: string, message: string, retryable: boolean): Promise<void> {
  await db
    .prepare(
      `UPDATE job_items SET status = 'failed', error_message = ?, error_stage = ?, retryable = ?, finished_at = ?, updated_at = ? WHERE business_id = ?`,
    )
    .bind(message.slice(0, 2000), stage, retryable ? 1 : 0, nowIso(), nowIso(), businessId)
    .run();
}

export async function skipNoWebsite(db: D1Database, businessId: number, disc: { website_original: string; website_final: string; status: string; identity_confidence: number | null; source: string }): Promise<void> {
  await db.batch([
    db
      .prepare(
        `UPDATE businesses SET website_original = ?, website_final = ?, website_status = ?, website_identity_confidence = ?,
         website_source = ?, best_channel = 'none', channel_reason = ?, processed_at = ? WHERE id = ?`,
      )
      .bind(
        disc.website_original, disc.website_final, disc.status, disc.identity_confidence, disc.source,
        `No valid website could be confirmed for this business (status: ${disc.status}), so it was excluded from audit, scoring and outreach.`.slice(0, 500),
        nowIso(), businessId,
      ),
    db
      .prepare(
        `UPDATE job_items SET status = 'skipped', stage = 'no_website',
         error_message = ?, error_stage = 'discovery', finished_at = ?, updated_at = ? WHERE business_id = ?`,
      )
      .bind(
        `Skipped — no valid website (status: ${disc.status}). Leads without a confirmed website are not audited, scored or drafted.`,
        nowIso(), nowIso(), businessId,
      ),
  ]);
}

export async function getBusiness(db: D1Database, id: number): Promise<BusinessRow | null> {
  return db.prepare(`SELECT * FROM businesses WHERE id = ?`).bind(id).first<BusinessRow>();
}

export async function getJobItemForBusiness(db: D1Database, businessId: number) {
  return db.prepare(`SELECT * FROM job_items WHERE business_id = ?`).bind(businessId).first<any>();
}

// ---------------------------------------------------------------------------
// website_audits + contact_emails (persisted after a completed audit)
// ---------------------------------------------------------------------------

export interface AuditPersistPayload {
  businessId: number;
  website: string; auditKind: string; httpStatus: number | null; isHttps: boolean | null;
  redirectChain: string[]; responseMs: number | null; pagesCrawled: number; pages: unknown[];
  technical: unknown; conversion: unknown; mobile: unknown; performance: unknown; trust: unknown; content: unknown;
  subscores: unknown; score: number | null; opportunityTier: string; scoreExplanation: unknown[];
  problems: unknown[]; recommendations: unknown[]; extra: unknown; reportR2Key: string; auditStatus: string; auditError: string;
  websiteFinal: string; websiteStatus: string; websiteIdentityConfidence: number | null; websiteSource: string;
  leadTier: string; bestChannel: string; channelReason: string; linkedinUrl: string; linkedinStatus: string;
  emails: { email: string; sourceUrl: string; sourceType: string; pageType: string; status: string; confidence: number; isRole: boolean; isDisposable: boolean; domainMatchesSite: boolean; mxRecords: string[]; notes: string[] }[];
}

export async function persistAuditResult(db: D1Database, p: AuditPersistPayload): Promise<void> {
  const stmts = [
    db
      .prepare(
        `UPDATE businesses SET website_original = website_original, website_final = ?, website_status = ?,
         website_identity_confidence = ?, website_source = ?, score = ?, opportunity_tier = ?, lead_tier = ?,
         audit_kind = ?, best_channel = ?, channel_reason = ?, linkedin_url = ?, linkedin_status = ?, processed_at = ?
         WHERE id = ?`,
      )
      .bind(
        p.websiteFinal, p.websiteStatus, p.websiteIdentityConfidence, p.websiteSource, p.score, p.opportunityTier,
        p.leadTier, p.auditKind, p.bestChannel, p.channelReason.slice(0, 500), p.linkedinUrl, p.linkedinStatus,
        nowIso(), p.businessId,
      ),
    db.prepare(`DELETE FROM website_audits WHERE business_id = ?`).bind(p.businessId),
    db
      .prepare(
        `INSERT INTO website_audits
         (business_id, website, audit_kind, http_status, is_https, redirect_chain, response_ms, pages_crawled, pages,
          technical, conversion, mobile, performance, trust, content, subscores, score, opportunity_tier,
          score_explanation, problems, recommendations, extra, report_r2_key, audit_status, audit_error, created_at)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
      )
      .bind(
        p.businessId, p.website, p.auditKind, p.httpStatus, p.isHttps === null ? null : p.isHttps ? 1 : 0,
        j(p.redirectChain), p.responseMs, p.pagesCrawled, j(p.pages), j(p.technical), j(p.conversion), j(p.mobile),
        j(p.performance), j(p.trust), j(p.content), j(p.subscores), p.score, p.opportunityTier, j(p.scoreExplanation),
        j(p.problems), j(p.recommendations), j(p.extra), p.reportR2Key, p.auditStatus, p.auditError, nowIso(),
      ),
    db.prepare(`DELETE FROM contact_emails WHERE business_id = ?`).bind(p.businessId),
  ];
  for (const [i, e] of p.emails.entries()) {
    stmts.push(
      db
        .prepare(
          `INSERT INTO contact_emails (business_id, email, source_url, source_type, page_type, status, confidence,
           is_role, is_disposable, domain_matches_site, mx_records, validation_notes, rank) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,
        )
        .bind(p.businessId, e.email, e.sourceUrl, e.sourceType, e.pageType, e.status, e.confidence, e.isRole ? 1 : 0, e.isDisposable ? 1 : 0, e.domainMatchesSite ? 1 : 0, j(e.mxRecords), j(e.notes), i),
    );
  }
  await db.batch(stmts);
}

// ---------------------------------------------------------------------------
// audit_errors / events
// ---------------------------------------------------------------------------

export async function recordError(db: D1Database, opts: { jobId: number; businessId?: number | null; stage: string; code: string; message: string; retryable?: boolean; url?: string }): Promise<void> {
  await db
    .prepare(`INSERT INTO audit_errors (job_id, business_id, stage, code, message, retryable, url, created_at) VALUES (?,?,?,?,?,?,?,?)`)
    .bind(opts.jobId, opts.businessId ?? null, opts.stage, opts.code, (opts.message || "").slice(0, 2000), opts.retryable ? 1 : 0, (opts.url || "").slice(0, 1000), nowIso())
    .run();
}

export async function listErrors(db: D1Database, jobId: number, limit = 200) {
  const res = await db
    .prepare(
      `SELECT e.*, b.name as business_name FROM audit_errors e LEFT JOIN businesses b ON b.id = e.business_id
       WHERE e.job_id = ? ORDER BY e.id DESC LIMIT ?`,
    )
    .bind(jobId, Math.max(1, Math.min(1000, limit)))
    .all<any>();
  return res.results ?? [];
}

export async function addEvent(db: D1Database, opts: { jobId: number; businessId?: number | null; businessName?: string; level?: string; stage?: string; message: string }): Promise<void> {
  await db
    .prepare(`INSERT INTO events (job_id, business_id, business_name, level, stage, message, created_at) VALUES (?,?,?,?,?,?,?)`)
    .bind(opts.jobId, opts.businessId ?? null, (opts.businessName || "").slice(0, 500), opts.level || "info", opts.stage || "", (opts.message || "").slice(0, 2000), nowIso())
    .run();
}

export async function recentEvents(db: D1Database, opts: { jobId?: number; sinceId?: number; limit?: number }) {
  const limit = Math.max(1, Math.min(1000, opts.limit ?? 120));
  let sql = `SELECT * FROM events`;
  const args: unknown[] = [];
  const conds: string[] = [];
  if (opts.jobId !== undefined) {
    conds.push("job_id = ?");
    args.push(opts.jobId);
  }
  if (opts.sinceId !== undefined) {
    conds.push("id > ?");
    args.push(opts.sinceId);
  }
  if (conds.length) sql += ` WHERE ${conds.join(" AND ")}`;
  sql += ` ORDER BY id DESC LIMIT ?`;
  args.push(limit);
  const res = await db.prepare(sql).bind(...args).all<any>();
  return res.results ?? [];
}

// ---------------------------------------------------------------------------
// leads listing / detail
// ---------------------------------------------------------------------------

export async function listLeads(db: D1Database, opts: {
  jobId?: number; search?: string; minScore?: number; websiteStatus?: string; sort?: string; page: number; pageSize: number;
}) {
  const conds: string[] = [];
  const args: unknown[] = [];
  if (opts.jobId !== undefined) { conds.push("job_id = ?"); args.push(opts.jobId); }
  if (opts.websiteStatus) { conds.push("website_status = ?"); args.push(opts.websiteStatus); }
  if (opts.minScore !== undefined) { conds.push("score >= ?"); args.push(opts.minScore); }
  if (opts.search) {
    conds.push("(name LIKE ? OR city LIKE ? OR category LIKE ? OR website_final LIKE ?)");
    const like = `%${opts.search}%`;
    args.push(like, like, like, like);
  }
  const where = conds.length ? `WHERE ${conds.join(" AND ")}` : "";

  const totalRow = await db.prepare(`SELECT COUNT(*) as n FROM businesses ${where}`).bind(...args).first<{ n: number }>();
  const total = totalRow?.n ?? 0;

  const orderMap: Record<string, string> = {
    score_desc: "score IS NULL, score DESC, id ASC", score_asc: "score IS NULL, score ASC, id ASC",
    name_asc: "name ASC", name_desc: "name DESC", row_asc: "row_index ASC", recent: "processed_at IS NULL, processed_at DESC, id DESC",
  };
  const order = orderMap[opts.sort || "score_desc"] || orderMap.score_desc;
  const offset = (opts.page - 1) * opts.pageSize;

  const rowsRes = await db.prepare(`SELECT * FROM businesses ${where} ORDER BY ${order} LIMIT ? OFFSET ?`).bind(...args, opts.pageSize, offset).all<BusinessRow>();
  const rows = rowsRes.results ?? [];
  const ids = rows.map((r) => r.id);

  const emailsByBiz = new Map<number, { email: string; status: string }[]>();
  const auditByBiz = new Map<number, any>();
  const itemByBiz = new Map<number, any>();
  if (ids.length) {
    const placeholders = ids.map(() => "?").join(",");
    const emailsRes = await db.prepare(`SELECT * FROM contact_emails WHERE business_id IN (${placeholders}) ORDER BY rank`).bind(...ids).all<any>();
    for (const e of emailsRes.results ?? []) {
      if (!emailsByBiz.has(e.business_id)) emailsByBiz.set(e.business_id, []);
      emailsByBiz.get(e.business_id)!.push({ email: e.email, status: e.status });
    }
    const auditsRes = await db.prepare(`SELECT * FROM website_audits WHERE business_id IN (${placeholders})`).bind(...ids).all<any>();
    for (const a of auditsRes.results ?? []) auditByBiz.set(a.business_id, a);
    const itemsRes = await db.prepare(`SELECT * FROM job_items WHERE business_id IN (${placeholders})`).bind(...ids).all<any>();
    for (const it of itemsRes.results ?? []) itemByBiz.set(it.business_id, it);
  }

  return { total, rows, emailsByBiz, auditByBiz, itemByBiz };
}

export async function getLeadDetail(db: D1Database, id: number) {
  const business = await getBusiness(db, id);
  if (!business) return null;
  const audit = await db.prepare(`SELECT * FROM website_audits WHERE business_id = ?`).bind(id).first<any>();
  const emailsRes = await db.prepare(`SELECT * FROM contact_emails WHERE business_id = ? ORDER BY rank`).bind(id).all<any>();
  const item = await getJobItemForBusiness(db, id);
  const errorsRes = await db.prepare(`SELECT * FROM audit_errors WHERE business_id = ? ORDER BY id DESC LIMIT 30`).bind(id).all<any>();
  return { business, audit, emails: emailsRes.results ?? [], item, errors: errorsRes.results ?? [] };
}

export async function getReportKey(db: D1Database, leadId: number): Promise<string | null> {
  const row = await db.prepare(`SELECT report_r2_key FROM website_audits WHERE business_id = ?`).bind(leadId).first<{ report_r2_key: string }>();
  return row?.report_r2_key || null;
}

// ---------------------------------------------------------------------------
// stats
// ---------------------------------------------------------------------------

export async function statsFor(db: D1Database, jobId?: number) {
  const where = jobId !== undefined ? "WHERE job_id = ?" : "";
  const args = jobId !== undefined ? [jobId] : [];

  const total = (await db.prepare(`SELECT COUNT(*) as n FROM businesses ${where}`).bind(...args).first<{ n: number }>())?.n ?? 0;
  const processed = (await db.prepare(`SELECT COUNT(*) as n FROM businesses ${where}${where ? " AND" : "WHERE"} processed_at IS NOT NULL`).bind(...args).first<{ n: number }>())?.n ?? 0;
  const highOpportunity = (await db.prepare(`SELECT COUNT(*) as n FROM businesses ${where}${where ? " AND" : "WHERE"} score >= 75`).bind(...args).first<{ n: number }>())?.n ?? 0;
  const avgRow = await db.prepare(`SELECT AVG(score) as avg FROM businesses ${where}${where ? " AND" : "WHERE"} score IS NOT NULL`).bind(...args).first<{ avg: number | null }>();

  const itemWhere = jobId !== undefined ? "WHERE job_id = ?" : "";
  const itemCountsRes = await db.prepare(`SELECT status, COUNT(*) as n FROM job_items ${itemWhere} GROUP BY status`).bind(...args).all<{ status: string; n: number }>();
  const itemCounts: Record<string, number> = {};
  for (const r of itemCountsRes.results ?? []) itemCounts[r.status] = r.n;

  const tiersRes = await db.prepare(`SELECT lead_tier, COUNT(*) as n FROM businesses ${where} GROUP BY lead_tier`).bind(...args).all<{ lead_tier: string; n: number }>();
  const oppRes = await db.prepare(`SELECT opportunity_tier, COUNT(*) as n FROM businesses ${where} GROUP BY opportunity_tier`).bind(...args).all<{ opportunity_tier: string; n: number }>();
  const wsRes = await db.prepare(`SELECT website_status, COUNT(*) as n FROM businesses ${where} GROUP BY website_status`).bind(...args).all<{ website_status: string; n: number }>();

  const errWhere = jobId !== undefined ? "WHERE job_id = ?" : "";
  const errCodesRes = await db
    .prepare(`SELECT code, COUNT(*) as n FROM audit_errors ${errWhere} GROUP BY code ORDER BY n DESC LIMIT 12`)
    .bind(...args)
    .all<{ code: string; n: number }>();
  const errTotal = (await db.prepare(`SELECT COUNT(*) as n FROM audit_errors ${errWhere}`).bind(...args).first<{ n: number }>())?.n ?? 0;

  const noClearJoin = jobId !== undefined ? "JOIN businesses b ON b.id = wa.business_id WHERE wa.audit_status = 'no_clear_opportunity' AND b.job_id = ?" : "WHERE wa.audit_status = 'no_clear_opportunity'";
  const noClear = (await db.prepare(`SELECT COUNT(*) as n FROM website_audits wa ${noClearJoin}`).bind(...args).first<{ n: number }>())?.n ?? 0;

  const errorCodes: Record<string, number> = {};
  for (const r of errCodesRes.results ?? []) errorCodes[r.code] = r.n;
  const tiers: Record<string, number> = {};
  for (const r of tiersRes.results ?? []) tiers[r.lead_tier || "unprocessed"] = r.n;
  const opp: Record<string, number> = {};
  for (const r of oppRes.results ?? []) opp[r.opportunity_tier || "unscored"] = r.n;
  const ws: Record<string, number> = {};
  for (const r of wsRes.results ?? []) ws[r.website_status || "not_checked"] = r.n;

  return {
    job_id: jobId ?? null, total, processed,
    in_progress: itemCounts.running || 0, queued: itemCounts.pending || 0,
    successful: itemCounts.completed || 0, failed: itemCounts.failed || 0, skipped: itemCounts.skipped || 0,
    high_opportunity: highOpportunity, average_score: avgRow?.avg !== null && avgRow?.avg !== undefined ? Math.round(avgRow.avg * 10) / 10 : null,
    no_clear_opportunity: noClear,
    channels: { whatsapp: 0, email: 0, linkedin: 0, phone: 0, website_contact: 0, none: 0 },
    drafts: { whatsapp: 0, email: 0, linkedin: 0, call: 0 },
    lead_tiers: tiers, opportunity_tiers: opp, website_status: ws,
    contacts: { with_public_email: 0, with_whatsapp_path: 0 },
    error_codes: errorCodes, error_total: errTotal,
  };
}

export { j as toJson, parseJ as fromJson };
