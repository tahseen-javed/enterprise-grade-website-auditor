// Job listing, control and statistics. Ported from backend/app/api/jobs.py.
// "Job" here always wraps exactly one business (the quick-audit flow is the
// only job-creation path this deployment's UI uses), so job control maps
// directly onto one Workflow instance's lifecycle.
import { Hono } from "hono";
import type { Env } from "../types";
import * as q from "../db/queries";
import { deleteJobReports } from "../lib/r2";

export const jobs = new Hono<{ Bindings: Env }>();

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued", normalize: "Normalizing business data", discovery: "Website discovery",
  crawl: "Website crawl", "extract-and-validate": "Contact extraction & validation",
  "audit-checks": "Website audit", "score-and-report": "Opportunity scoring & report", done: "Complete",
  workflow: "Unexpected error",
};

async function jobDto(db: D1Database, job: q.JobRow) {
  const counts = await q.jobItemCounts(db, job.id);
  const errorCount = await q.jobErrorCount(db, job.id);
  const total = job.total || Object.values(counts).reduce((a, b) => a + b, 0);
  const done = counts.completed + counts.skipped;
  const isRunning = job.status === "running";
  let live: any = null;
  if (isRunning || job.status === "paused") {
    const item = await db.prepare(`SELECT stage, status FROM job_items WHERE job_id = ? LIMIT 1`).bind(job.id).first<{ stage: string; status: string }>();
    if (item) live = { job_id: job.id, stage: item.stage, stage_label: STAGE_LABELS[item.stage] || item.stage, status: item.status };
  }
  return {
    id: job.id, name: job.name, status: job.status, source_kind: job.source_kind || "url", is_running: isRunning,
    total, counts, processed: done, percent: total ? Math.round((1000 * done) / total) / 10 : 0,
    error_count: errorCount, source_filename: job.source_filename,
    original_columns: q.fromJson(job.original_columns, []), column_mapping: q.fromJson(job.column_mapping, {}),
    created_at: job.created_at, started_at: job.started_at, finished_at: job.finished_at,
    last_error: job.last_error, live,
  };
}

jobs.get("/jobs", async (c) => {
  const limit = Number(c.req.query("limit") ?? 50);
  const list = await q.listJobs(c.env.DB, limit);
  return c.json({ jobs: await Promise.all(list.map((j) => jobDto(c.env.DB, j))) });
});

jobs.get("/jobs/:id", async (c) => {
  const id = Number(c.req.param("id"));
  const job = await q.getJob(c.env.DB, id);
  if (!job) return c.json({ detail: "Job not found." }, 404);
  return c.json(await jobDto(c.env.DB, job));
});

jobs.get("/jobs/:id/progress", async (c) => {
  const id = Number(c.req.param("id"));
  const job = await q.getJob(c.env.DB, id);
  if (!job) return c.json({ detail: "Job not found." }, 404);
  const dto = await jobDto(c.env.DB, job);
  return c.json({ job: dto, live: dto.live, stage_labels: STAGE_LABELS });
});

jobs.post("/jobs/:id/start", async (c) => {
  const id = Number(c.req.param("id"));
  const job = await q.getJob(c.env.DB, id);
  if (!job) return c.json({ detail: "Job not found." }, 404);
  if (job.status === "running") return c.json({ detail: "This job is already running." }, 409);

  const business = await c.env.DB.prepare(`SELECT id FROM businesses WHERE job_id = ? LIMIT 1`).bind(id).first<{ id: number }>();
  if (!business) return c.json({ detail: "This job has no business to audit." }, 409);
  const instance = await c.env.AUDIT_WORKFLOW.create({ id: `job-${id}-biz-${business.id}-${Date.now()}`, params: { jobId: id, businessId: business.id } });
  await q.setJobWorkflowInstance(c.env.DB, id, instance.id);
  return c.json({ status: "running", job_id: id });
});

jobs.post("/jobs/:id/pause", async (c) => {
  const id = Number(c.req.param("id"));
  const job = await q.getJob(c.env.DB, id);
  if (!job || job.status !== "running" || !job.workflow_instance_id) return c.json({ detail: "That job is not currently running." }, 409);
  try {
    const instance = await c.env.AUDIT_WORKFLOW.get(job.workflow_instance_id);
    await instance.pause();
  } catch (exc: any) {
    return c.json({ detail: `Could not pause: ${exc?.message || exc}` }, 409);
  }
  await q.setJobStatus(c.env.DB, id, "paused");
  await q.addEvent(c.env.DB, { jobId: id, message: "Job paused", stage: "job" });
  return c.json({ status: "paused", job_id: id });
});

jobs.post("/jobs/:id/resume", async (c) => {
  const id = Number(c.req.param("id"));
  const job = await q.getJob(c.env.DB, id);
  if (!job) return c.json({ detail: "Job not found." }, 404);

  if (job.status === "paused" && job.workflow_instance_id) {
    try {
      const instance = await c.env.AUDIT_WORKFLOW.get(job.workflow_instance_id);
      await instance.resume();
      await q.setJobStatus(c.env.DB, id, "running");
      await q.addEvent(c.env.DB, { jobId: id, message: "Job resumed", stage: "job" });
      return c.json({ status: "running", job_id: id, mode: "unpaused" });
    } catch (exc: any) {
      return c.json({ detail: `Could not resume: ${exc?.message || exc}` }, 409);
    }
  }

  const counts = await q.jobItemCounts(c.env.DB, id);
  const remaining = counts.pending + counts.running + counts.failed;
  if (remaining === 0) return c.json({ detail: "Every lead in this job is already processed." }, 409);

  const business = await c.env.DB.prepare(`SELECT id FROM businesses WHERE job_id = ? LIMIT 1`).bind(id).first<{ id: number }>();
  if (!business) return c.json({ detail: "This job has no business to audit." }, 409);
  const instance = await c.env.AUDIT_WORKFLOW.create({ id: `job-${id}-biz-${business.id}-${Date.now()}`, params: { jobId: id, businessId: business.id } });
  await q.setJobWorkflowInstance(c.env.DB, id, instance.id);
  await q.addEvent(c.env.DB, { jobId: id, message: `Job resumed — ${remaining} lead(s) still to process`, stage: "job" });
  return c.json({ status: "running", job_id: id, mode: "resumed", remaining });
});

jobs.post("/jobs/:id/cancel", async (c) => {
  const id = Number(c.req.param("id"));
  const job = await q.getJob(c.env.DB, id);
  if (!job || !["running", "paused"].includes(job.status) || !job.workflow_instance_id) return c.json({ detail: "That job is not currently running." }, 409);
  try {
    const instance = await c.env.AUDIT_WORKFLOW.get(job.workflow_instance_id);
    await instance.terminate();
  } catch {
    /* instance may already be finished */
  }
  await q.setJobStatus(c.env.DB, id, "cancelled", { finishedAt: true });
  await q.addEvent(c.env.DB, { jobId: id, message: "Job cancelled", stage: "job", level: "warn" });
  return c.json({ status: "cancelling", job_id: id });
});

jobs.post("/jobs/:id/retry-failed", async (c) => {
  const id = Number(c.req.param("id"));
  const counts = await q.jobItemCounts(c.env.DB, id);
  if (counts.failed === 0) return c.json({ detail: "There are no failed leads to retry." }, 409);

  await c.env.DB.prepare(`UPDATE job_items SET status = 'pending', stage = 'queued', error_message = '', error_stage = '' WHERE job_id = ? AND status = 'failed'`).bind(id).run();
  const business = await c.env.DB.prepare(`SELECT id FROM businesses WHERE job_id = ? LIMIT 1`).bind(id).first<{ id: number }>();
  if (business) {
    const instance = await c.env.AUDIT_WORKFLOW.create({ id: `job-${id}-biz-${business.id}-retry-${Date.now()}`, params: { jobId: id, businessId: business.id } });
    await q.setJobWorkflowInstance(c.env.DB, id, instance.id);
  }
  await q.addEvent(c.env.DB, { jobId: id, message: `Retrying ${counts.failed} failed lead(s)`, stage: "job" });
  return c.json({ requeued: counts.failed, job_id: id });
});

jobs.delete("/jobs/:id", async (c) => {
  const id = Number(c.req.param("id"));
  const job = await q.getJob(c.env.DB, id);
  if (!job) return c.json({ detail: "Job not found." }, 404);
  if (job.status === "running") return c.json({ detail: "Stop the job before deleting it." }, 409);

  const removedReports = await deleteJobReports(c.env.REPORTS, id);
  await q.deleteJob(c.env.DB, id);
  return c.json({ deleted: id, files_removed: { reports: removedReports, upload: false } });
});

jobs.get("/jobs/:id/stats", async (c) => {
  const id = Number(c.req.param("id"));
  const job = await q.getJob(c.env.DB, id);
  if (!job) return c.json({ detail: "Job not found." }, 404);
  return c.json(await q.statsFor(c.env.DB, id));
});

jobs.get("/jobs/:id/errors", async (c) => {
  const id = Number(c.req.param("id"));
  const limit = Number(c.req.query("limit") ?? 200);
  const rows = await q.listErrors(c.env.DB, id, limit);
  return c.json({
    errors: rows.map((e) => ({
      id: e.id, business_id: e.business_id, business: e.business_name || "", stage: e.stage, code: e.code,
      message: e.message, retryable: Boolean(e.retryable), url: e.url, created_at: e.created_at,
    })),
  });
});

export { jobDto, STAGE_LABELS };
