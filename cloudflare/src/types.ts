// Shared types used across the audit engine. Field names deliberately match
// the Python dataclasses/models they were ported from so the API responses
// stay compatible with the existing frontend.

export interface Env {
  DB: D1Database;
  REPORTS: R2Bucket;
  ASSETS: Fetcher;
  AUDIT_WORKFLOW: Workflow;
  APP_NAME: string;
  APP_VERSION: string;
}

export interface AuditWorkflowParams {
  jobId: number;
  businessId: number;
}

export interface Finding {
  code: string;
  category: string;
  display_category: string;
  severity: "high" | "medium" | "low" | "";
  title: string;
  detail: string;
  deduction: number;
  // `any`, not `unknown`: this flows through Workflow step.do() return
  // values, which must satisfy Cloudflare's `Serializable<T>` type — an
  // index signature typed `unknown` fails that check even though the
  // runtime value (plain JSON-safe data) is fine.
  evidence: Record<string, any>;
  recommendation: string;
}

export interface EngineConfig {
  workers: number;
  per_domain_concurrency: number;
  per_domain_delay_ms: number;
  max_pages_per_site: number;
  max_crawl_depth: number;
  request_timeout_s: number;
  total_site_budget_s: number;
  max_retries: number;
  backoff_base_s: number;
  max_page_bytes: number;
  respect_robots: boolean;
  user_agent: string;
  verify_ssl: boolean;
  enable_website_discovery: boolean;
  min_identity_confidence: number;
  full_contact_discovery: boolean;
  enable_mx_lookup: boolean;
  dns_timeout_s: number;
  pagespeed_enabled: boolean;
  pagespeed_api_key: string;
  pagespeed_strategy: "mobile" | "desktop";
  llm_polish_enabled: boolean;
  llm_api_key: string;
  llm_model: string;
  playwright_enabled: boolean;
  google_places_enabled: boolean;
  google_places_api_key: string;
  // Cloudflare-specific safety ceilings, not present in the original engine
  // config, applied on top of the user-set values above so a single audit
  // instance can never exceed the Workers Free plan's 50-external-subrequest
  // budget for the whole Workflow run. See core/limits.ts.
}

export const ENGINE_DEFAULTS: EngineConfig = {
  workers: 5,
  per_domain_concurrency: 2,
  per_domain_delay_ms: 750,
  max_pages_per_site: 10,
  max_crawl_depth: 2,
  request_timeout_s: 20,
  total_site_budget_s: 60,
  max_retries: 1,
  backoff_base_s: 1.5,
  max_page_bytes: 3 * 1024 * 1024,
  respect_robots: true,
  user_agent:
    "Mozilla/5.0 (compatible; WebsiteAuditBot/1.0; local business website audit; +contact via site owner)",
  verify_ssl: true,
  enable_website_discovery: true,
  min_identity_confidence: 0.55,
  full_contact_discovery: false,
  enable_mx_lookup: true,
  dns_timeout_s: 4,
  pagespeed_enabled: false,
  pagespeed_api_key: "",
  pagespeed_strategy: "mobile",
  llm_polish_enabled: false,
  llm_api_key: "",
  llm_model: "claude-sonnet-5",
  playwright_enabled: false,
  google_places_enabled: false,
  google_places_api_key: "",
};

export interface ProfileConfig {
  full_name: string;
  company_name: string;
  whatsapp_number: string;
  email: string;
  website_url: string;
  service_name: string;
  target_service: string;
  booking_url: string;
  email_signature: string;
  tone: string;
  target_countries: string[];
  target_industries: string[];
}

export const PROFILE_DEFAULTS: ProfileConfig = {
  full_name: "",
  company_name: "",
  whatsapp_number: "",
  email: "",
  website_url: "",
  service_name: "",
  target_service: "",
  booking_url: "",
  email_signature: "",
  tone: "professional",
  target_countries: [],
  target_industries: [],
};

export interface WeightsConfig {
  weights: Record<string, number>;
  tiers: { name: string; min: number; key: string }[];
  max_problems: number;
  min_problems_for_outreach: number;
}

export const WEIGHTS_DEFAULTS: WeightsConfig = {
  weights: { technical: 20, mobile: 20, conversion: 25, trust: 15, contact: 10, content: 10 },
  tiers: [
    { name: "Very High", min: 90, key: "very_high" },
    { name: "High", min: 75, key: "high" },
    { name: "Good", min: 60, key: "good" },
    { name: "Moderate", min: 40, key: "moderate" },
    { name: "Low", min: 0, key: "low" },
  ],
  max_problems: 7,
  min_problems_for_outreach: 1,
};
