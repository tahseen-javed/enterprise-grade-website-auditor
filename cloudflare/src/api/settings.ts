// Settings endpoints. Ported from backend/app/api/settings_api.py.
import { Hono } from "hono";
import type { Env } from "../types";
import { enginePublic, getProfile, getWeights, profileStatus, saveEngine, saveProfile, saveWeights, TONES } from "../lib/settings";

export const settings = new Hono<{ Bindings: Env }>();

settings.get("/settings", async (c) => {
  const db = c.env.DB;
  const profile = await getProfile(db);
  return c.json({ profile, profile_status: profileStatus(profile), engine: await enginePublic(db), scoring: await getWeights(db), tones: TONES });
});

settings.get("/settings/profile", async (c) => {
  const profile = await getProfile(c.env.DB);
  return c.json({ profile, status: profileStatus(profile), tones: TONES });
});

settings.put("/settings/profile", async (c) => {
  const patch = await c.req.json().catch(() => ({}));
  const saved = await saveProfile(c.env.DB, patch);
  return c.json({ profile: saved, status: profileStatus(saved) });
});

settings.get("/settings/engine", async (c) => c.json({ engine: await enginePublic(c.env.DB) }));

settings.put("/settings/engine", async (c) => {
  const patch = await c.req.json().catch(() => ({}));
  await saveEngine(c.env.DB, patch);
  return c.json({ engine: await enginePublic(c.env.DB) });
});

settings.get("/settings/scoring", async (c) => c.json({ scoring: await getWeights(c.env.DB) }));

settings.put("/settings/scoring", async (c) => {
  const patch = await c.req.json().catch(() => ({}));
  const saved = await saveWeights(c.env.DB, patch);
  return c.json({ scoring: saved });
});
