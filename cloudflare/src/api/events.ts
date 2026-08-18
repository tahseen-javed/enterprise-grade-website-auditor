// Live activity stream (SSE) and global statistics. Ported from
// backend/app/api/events_api.py.
//
// The original's SSE bus also broadcasts ephemeral `progress`/`job` events
// that are never persisted (only `activity` events are — see events.py's
// `_persist`, which only fires for type=="activity"). This Worker can't hold
// an in-process subscriber registry across requests, so it polls D1 instead:
// activity events come from the `events` table, and `job` transition events
// are synthesised by diffing `jobs.status` between polls. The frontend
// already auto-reconnects on stream drop (frontend/src/lib/store.jsx), so a
// self-imposed connection lifetime here is transparent to the user.
import { Hono } from "hono";
import { streamSSE } from "hono/streaming";
import type { Env } from "../types";
import * as q from "../db/queries";

export const events = new Hono<{ Bindings: Env }>();

function sseEvent(evt: any) {
  return {
    id: evt.id, job_id: evt.job_id, business_id: evt.business_id, business_name: evt.business_name,
    level: evt.level, stage: evt.stage, message: evt.message, ts: evt.created_at,
    type: "activity",
  };
}

events.get("/events/recent", async (c) => {
  const jobId = c.req.query("job_id");
  const limit = Number(c.req.query("limit") ?? 120);
  const rows = await q.recentEvents(c.env.DB, { jobId: jobId ? Number(jobId) : undefined, limit });
  return c.json({
    events: rows.map((e) => ({ id: e.id, job_id: e.job_id, business_id: e.business_id, business_name: e.business_name, level: e.level, stage: e.stage, message: e.message, ts: e.created_at })),
  });
});

events.get("/stats", async (c) => {
  const jobId = c.req.query("job_id");
  const stats = await q.statsFor(c.env.DB, jobId ? Number(jobId) : undefined);
  const running = await c.env.DB.prepare(`SELECT id FROM jobs WHERE status IN ('running','paused')`).all<{ id: number }>();
  return c.json({ ...stats, running_jobs: (running.results ?? []).map((r) => r.id), live: {} });
});

const STREAM_LIFETIME_MS = 100_000;
const POLL_INTERVAL_MS = 2000;

events.get("/events/stream", async (c) => {
  const db = c.env.DB;
  return streamSSE(c, async (stream) => {
    const recent = await q.recentEvents(db, { limit: 60 });
    const runningRes = await db.prepare(`SELECT id, status FROM jobs WHERE status IN ('running','paused')`).all<{ id: number; status: string }>();
    let knownRunning = new Map((runningRes.results ?? []).map((r) => [r.id, r.status]));

    await stream.writeSSE({
      event: "hello",
      data: JSON.stringify({ connected: true, recent: recent.map(sseEvent), running_jobs: [...knownRunning.keys()], progress: {} }),
    });

    let lastEventId = recent.length ? Math.max(...recent.map((e) => e.id)) : 0;
    const deadline = Date.now() + STREAM_LIFETIME_MS;

    while (Date.now() < deadline) {
      await stream.sleep(POLL_INTERVAL_MS);

      const fresh = await q.recentEvents(db, { sinceId: lastEventId, limit: 50 });
      for (const evt of [...fresh].reverse()) {
        lastEventId = Math.max(lastEventId, evt.id);
        await stream.writeSSE({ event: "activity", data: JSON.stringify(sseEvent(evt)) });
      }

      const nowRunningRes = await db.prepare(`SELECT id, status FROM jobs WHERE status IN ('running','paused')`).all<{ id: number; status: string }>();
      const nowRunning = new Map((nowRunningRes.results ?? []).map((r) => [r.id, r.status]));

      for (const [id, status] of nowRunning) {
        if (!knownRunning.has(id)) await stream.writeSSE({ event: "job", data: JSON.stringify({ job_id: id, data: { status } }) });
      }
      for (const [id] of knownRunning) {
        if (!nowRunning.has(id)) {
          const job = await q.getJob(db, id);
          await stream.writeSSE({ event: "job", data: JSON.stringify({ job_id: id, data: { status: job?.status || "completed" } }) });
        }
      }
      knownRunning = nowRunning;
    }
  });
});
