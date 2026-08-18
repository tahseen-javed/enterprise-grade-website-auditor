// Runtime configuration, backed by the D1 `settings` table (one JSON blob
// per namespace) instead of data/config/*.json. Ported from
// backend/app/settings.py — same defaults, same masking behaviour for
// secret keys.
import { ENGINE_DEFAULTS, PROFILE_DEFAULTS, WEIGHTS_DEFAULTS, EngineConfig, ProfileConfig, WeightsConfig } from "../types";

const SECRET_KEYS = new Set(["pagespeed_api_key", "llm_api_key", "google_places_api_key"]);
const TONES = ["professional", "friendly", "consultant", "founder"];
export { TONES };

async function readSetting<T extends object>(db: D1Database, key: string, defaults: T): Promise<T> {
  const row = await db.prepare(`SELECT value FROM settings WHERE key = ?`).bind(key).first<{ value: string }>();
  if (!row) return { ...defaults };
  try {
    const parsed = JSON.parse(row.value);
    if (parsed && typeof parsed === "object") return { ...defaults, ...parsed };
  } catch {
    /* corrupt row — fall back to defaults, matching the Python behaviour */
  }
  return { ...defaults };
}

async function writeSetting(db: D1Database, key: string, value: unknown): Promise<void> {
  await db
    .prepare(`INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`)
    .bind(key, JSON.stringify(value), new Date().toISOString())
    .run();
}

export async function getProfile(db: D1Database): Promise<ProfileConfig> {
  return readSetting(db, "profile", PROFILE_DEFAULTS);
}

export async function saveProfile(db: D1Database, patch: Partial<ProfileConfig>): Promise<ProfileConfig> {
  const current = await getProfile(db);
  for (const k of Object.keys(PROFILE_DEFAULTS) as (keyof ProfileConfig)[]) {
    if (k in patch && patch[k] !== undefined) (current as any)[k] = patch[k];
  }
  if (!TONES.includes(current.tone)) current.tone = "professional";
  await writeSetting(db, "profile", current);
  return current;
}

export function profileStatus(p: ProfileConfig) {
  const required = ["full_name", "company_name", "service_name"] as const;
  const missing = (keys: readonly string[]) => keys.filter((k) => !String((p as any)[k] || "").trim());
  const coreMissing = missing(required);
  return {
    configured: coreMissing.length === 0,
    missing_core: coreMissing,
    missing_for_whatsapp: missing(["whatsapp_number"]),
    missing_for_email: missing(["email"]),
  };
}

export async function getWeights(db: D1Database): Promise<WeightsConfig> {
  return readSetting(db, "weights", WEIGHTS_DEFAULTS);
}

export async function saveWeights(db: D1Database, patch: Partial<WeightsConfig>): Promise<WeightsConfig> {
  const current = await getWeights(db);
  if (patch.weights && typeof patch.weights === "object") {
    const w = { ...current.weights };
    for (const [k, v] of Object.entries(patch.weights)) {
      if (k in WEIGHTS_DEFAULTS.weights) {
        const n = Number(v);
        if (Number.isFinite(n)) w[k] = Math.max(0, Math.floor(n));
      }
    }
    current.weights = w;
  }
  for (const key of ["max_problems", "min_problems_for_outreach"] as const) {
    if (patch[key] !== undefined) {
      const n = Number(patch[key]);
      if (Number.isFinite(n)) current[key] = Math.max(1, Math.floor(n));
    }
  }
  await writeSetting(db, "weights", current);
  return current;
}

export async function getEngine(db: D1Database): Promise<EngineConfig> {
  const e = await readSetting(db, "engine", ENGINE_DEFAULTS);
  e.workers = Math.max(1, Math.min(20, Math.floor(Number(e.workers) || 5)));
  return e;
}

export async function saveEngine(db: D1Database, patch: Partial<EngineConfig>): Promise<EngineConfig> {
  const current = await getEngine(db);
  for (const [k, v] of Object.entries(patch)) {
    if (!(k in ENGINE_DEFAULTS)) continue;
    if (SECRET_KEYS.has(k) && typeof v === "string" && v.trim() && [...v.trim()].every((c) => c === "*")) continue;
    (current as any)[k] = v;
  }
  current.workers = Math.max(1, Math.min(20, Math.floor(Number(current.workers) || 5)));
  await writeSetting(db, "engine", current);
  return current;
}

export async function enginePublic(db: D1Database): Promise<Record<string, unknown>> {
  const e = await getEngine(db);
  const out: Record<string, unknown> = { ...e };
  for (const k of SECRET_KEYS) {
    const val = String((e as any)[k] || "");
    out[k] = val ? "********" : "";
    out[`${k}_set`] = Boolean(val);
  }
  return out;
}
