-- Website Auditor — D1 schema.
-- Mirrors backend/app/models.py (SQLAlchemy) closely enough that the API
-- responses the frontend already expects stay the same shape. JSON-typed
-- columns in the original (SQLite JSON type) are stored as TEXT here and
-- JSON.parse/stringify'd in application code, which is the standard D1
-- pattern since D1 has no native JSON column type.

CREATE TABLE jobs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  name              TEXT NOT NULL DEFAULT '',
  source_filename   TEXT NOT NULL DEFAULT '',
  stored_path       TEXT NOT NULL DEFAULT '',
  source_kind       TEXT NOT NULL DEFAULT 'url',   -- 'url' (quick audit) | 'csv' (reserved, not wired to any UI today)
  original_columns  TEXT NOT NULL DEFAULT '[]',    -- JSON array
  column_mapping    TEXT NOT NULL DEFAULT '{}',    -- JSON object
  engine_snapshot   TEXT NOT NULL DEFAULT '{}',    -- JSON object: engine config at job creation time
  status            TEXT NOT NULL DEFAULT 'queued', -- queued|running|paused|completed|failed|cancelled
  total             INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL,
  started_at        TEXT,
  finished_at       TEXT,
  last_error        TEXT NOT NULL DEFAULT '',
  workflow_instance_id TEXT NOT NULL DEFAULT '',
  live_progress     TEXT NOT NULL DEFAULT '{}'      -- JSON object, updated by the Workflow as it runs
);
CREATE INDEX ix_jobs_status ON jobs(status);

CREATE TABLE businesses (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id                INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  row_index             INTEGER NOT NULL DEFAULT 0,
  raw                   TEXT NOT NULL DEFAULT '{}',
  name                  TEXT NOT NULL DEFAULT '',
  name_normalized       TEXT NOT NULL DEFAULT '',
  category              TEXT NOT NULL DEFAULT '',
  address               TEXT NOT NULL DEFAULT '',
  city                  TEXT NOT NULL DEFAULT '',
  state                 TEXT NOT NULL DEFAULT '',
  country               TEXT NOT NULL DEFAULT '',
  country_code          TEXT NOT NULL DEFAULT '',
  postal_code           TEXT NOT NULL DEFAULT '',
  rating                REAL,
  review_count          INTEGER,
  place_id              TEXT NOT NULL DEFAULT '',
  maps_url              TEXT NOT NULL DEFAULT '',
  phone_raw             TEXT NOT NULL DEFAULT '',
  website_original      TEXT NOT NULL DEFAULT '',
  dedup_key             TEXT NOT NULL DEFAULT '',
  is_duplicate_of       INTEGER,
  website_final         TEXT NOT NULL DEFAULT '',
  website_status        TEXT NOT NULL DEFAULT 'not_checked',
  website_identity_confidence REAL,
  website_source        TEXT NOT NULL DEFAULT '',
  score                 INTEGER,
  opportunity_tier      TEXT NOT NULL DEFAULT '',
  lead_tier             TEXT NOT NULL DEFAULT '',
  audit_kind            TEXT NOT NULL DEFAULT '',
  best_channel          TEXT NOT NULL DEFAULT '',
  channel_reason        TEXT NOT NULL DEFAULT '',
  linkedin_url          TEXT NOT NULL DEFAULT '',
  linkedin_status       TEXT NOT NULL DEFAULT 'not_checked',
  processed_at          TEXT
);
CREATE INDEX ix_business_job ON businesses(job_id);
CREATE INDEX ix_business_name_norm ON businesses(name_normalized);
CREATE INDEX ix_business_dedup ON businesses(dedup_key);
CREATE INDEX ix_business_score ON businesses(score);
CREATE INDEX ix_business_website_status ON businesses(website_status);

CREATE TABLE job_items (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id            INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  business_id       INTEGER NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
  status            TEXT NOT NULL DEFAULT 'pending', -- pending|running|completed|failed|skipped
  stage             TEXT NOT NULL DEFAULT 'queued',
  attempts          INTEGER NOT NULL DEFAULT 0,
  stage_data        TEXT NOT NULL DEFAULT '{}',
  completed_stages  TEXT NOT NULL DEFAULT '[]',
  error_message     TEXT NOT NULL DEFAULT '',
  error_stage       TEXT NOT NULL DEFAULT '',
  retryable         INTEGER NOT NULL DEFAULT 0,
  started_at        TEXT,
  updated_at        TEXT NOT NULL,
  finished_at       TEXT
);
CREATE INDEX ix_jobitem_job_status ON job_items(job_id, status);

CREATE TABLE website_audits (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  business_id           INTEGER NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
  website               TEXT NOT NULL DEFAULT '',
  audit_kind            TEXT NOT NULL DEFAULT 'website',
  http_status           INTEGER,
  is_https              INTEGER,
  redirect_chain        TEXT NOT NULL DEFAULT '[]',
  response_ms           INTEGER,
  pages_crawled         INTEGER NOT NULL DEFAULT 0,
  pages                 TEXT NOT NULL DEFAULT '[]',
  technical             TEXT NOT NULL DEFAULT '{}',
  conversion            TEXT NOT NULL DEFAULT '{}',
  mobile                TEXT NOT NULL DEFAULT '{}',
  performance           TEXT NOT NULL DEFAULT '{}',
  trust                 TEXT NOT NULL DEFAULT '{}',
  content                TEXT NOT NULL DEFAULT '{}',
  subscores              TEXT NOT NULL DEFAULT '{}',
  score                  INTEGER,
  opportunity_tier       TEXT NOT NULL DEFAULT '',
  score_explanation      TEXT NOT NULL DEFAULT '[]',
  problems                TEXT NOT NULL DEFAULT '[]',
  recommendations          TEXT NOT NULL DEFAULT '[]',
  extra                    TEXT NOT NULL DEFAULT '{}',
  report_r2_key            TEXT NOT NULL DEFAULT '',
  audit_status             TEXT NOT NULL DEFAULT '',
  audit_error              TEXT NOT NULL DEFAULT '',
  created_at                TEXT NOT NULL
);

CREATE TABLE contact_emails (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  business_id       INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  email             TEXT NOT NULL DEFAULT '',
  source_url        TEXT NOT NULL DEFAULT '',
  source_type       TEXT NOT NULL DEFAULT '',
  page_type         TEXT NOT NULL DEFAULT '',
  status            TEXT NOT NULL DEFAULT 'unknown',
  confidence        REAL NOT NULL DEFAULT 0,
  is_role           INTEGER NOT NULL DEFAULT 0,
  is_disposable     INTEGER NOT NULL DEFAULT 0,
  domain_matches_site INTEGER NOT NULL DEFAULT 0,
  mx_records        TEXT NOT NULL DEFAULT '[]',
  validation_notes  TEXT NOT NULL DEFAULT '[]',
  rank              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_email_business ON contact_emails(business_id);

CREATE TABLE audit_errors (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id        INTEGER NOT NULL DEFAULT 0,
  business_id   INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
  stage         TEXT NOT NULL DEFAULT '',
  code          TEXT NOT NULL DEFAULT '',
  message       TEXT NOT NULL DEFAULT '',
  retryable     INTEGER NOT NULL DEFAULT 0,
  url           TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL
);
CREATE INDEX ix_error_job ON audit_errors(job_id);
CREATE INDEX ix_error_code ON audit_errors(code);

CREATE TABLE events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id        INTEGER NOT NULL DEFAULT 0,
  business_id   INTEGER,
  business_name TEXT NOT NULL DEFAULT '',
  level         TEXT NOT NULL DEFAULT 'info',
  stage         TEXT NOT NULL DEFAULT '',
  message       TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL
);
CREATE INDEX ix_events_job ON events(job_id);
CREATE INDEX ix_events_created ON events(created_at);

-- Replaces data/config/{profile,weights,engine}.json. One row per config
-- namespace, value stored as a JSON blob, exactly like the original
-- SettingRow "key/value store for anything that outgrows the JSON files".
CREATE TABLE settings (
  key           TEXT PRIMARY KEY,
  value         TEXT NOT NULL DEFAULT '{}',
  updated_at    TEXT NOT NULL
);
