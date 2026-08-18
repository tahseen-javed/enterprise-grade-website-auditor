// Opportunity scoring + the premium audit scorecard. Ported from
// backend/app/core/scoring.py — math, thresholds and category tables
// unchanged.
import { CATEGORIES } from "./auditChecks";
import type { Finding } from "../types";

export const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2, "": 3 };

export const CATEGORY_LABELS: Record<string, string> = {
  technical: "Technical health", mobile: "Mobile experience", conversion: "Conversion readiness",
  trust: "Trust & proof", contact: "Contact accessibility", content: "Content clarity", performance: "Performance",
};

export const STRONG_SIGNALS = new Set([
  "no_primary_cta_above_fold", "no_phone_cta", "no_contact_form", "no_booking_cta",
  "missing_viewport", "viewport_not_responsive", "no_mobile_tap_to_call",
  "no_phone_on_site", "contact_hard_to_find", "broken_internal_links",
  "slow_response", "pagespeed_low", "no_testimonials", "very_thin_homepage",
  "services_not_clear", "no_https", "noindex", "fixed_width_layout",
  "no_website_detected", "social_profile_only", "no_email_on_site",
]);

export interface ScoreExplanationRow {
  category: string;
  label: string;
  weight: number;
  health: number;
  opportunity: number;
  contribution: number;
  findings: number;
  deductions: number;
}

export interface ScoreResult {
  score: number;
  overall_health: number;
  health: Record<string, number>;
  opportunity: Record<string, number>;
  subscores: Record<string, number>;
  weights: Record<string, number>;
  explanation: ScoreExplanationRow[];
}

export function computeScore(
  findings: Finding[],
  weights: Record<string, number>,
  opts: { categories?: string[]; categoryOf?: (f: Finding) => string; labels?: Record<string, string> } = {},
): ScoreResult {
  const cats = opts.categories ?? CATEGORIES;
  const getCat = opts.categoryOf ?? ((f: Finding) => f.category);
  const lbls = opts.labels ?? CATEGORY_LABELS;

  const ded: Record<string, number> = {};
  const perCat: Record<string, Finding[]> = {};
  for (const c of cats) { ded[c] = 0; perCat[c] = []; }

  for (const f of findings) {
    const c = getCat(f);
    if (!(c in ded)) continue;
    ded[c] += Math.max(0, f.deduction);
    perCat[c].push(f);
  }

  const health: Record<string, number> = {};
  const opportunity: Record<string, number> = {};
  for (const c of cats) {
    health[c] = Math.max(0, 100 - ded[c]);
    opportunity[c] = 100 - health[c];
  }

  const totalW = cats.reduce((n, c) => n + Math.max(0, Math.floor(weights[c] ?? 0)), 0) || 1;
  const weighted = cats.reduce((n, c) => n + opportunity[c] * Math.max(0, Math.floor(weights[c] ?? 0)), 0);
  let score = Math.round(weighted / totalW);
  score = Math.max(0, Math.min(100, score));
  const overallHealth = Math.max(0, Math.min(100, 100 - score));

  const explanation: ScoreExplanationRow[] = cats.map((c) => {
    const w = Math.max(0, Math.floor(weights[c] ?? 0));
    return {
      category: c, label: lbls[c] ?? c, weight: w, health: health[c], opportunity: opportunity[c],
      contribution: round1(opportunity[c] * w / totalW), findings: perCat[c].length, deductions: ded[c],
    };
  });
  explanation.sort((a, b) => b.contribution - a.contribution);

  const weightsOut: Record<string, number> = {};
  for (const c of cats) weightsOut[c] = Math.max(0, Math.floor(weights[c] ?? 0));

  return { score, overall_health: overallHealth, health, opportunity, subscores: { ...opportunity }, weights: weightsOut, explanation };
}

export function tierForScore(score: number, tiers: { name: string; min: number; key: string }[]): [string, string] {
  const sorted = [...tiers].sort((a, b) => b.min - a.min);
  for (const t of sorted) if (score >= (t.min ?? 0)) return [t.name || "Low", t.key || "low"];
  return ["Low", "low"];
}

export interface ProblemRow {
  rank: number;
  code: string;
  category: string;
  category_label: string;
  severity: string;
  title: string;
  detail: string;
  evidence: Record<string, any>;
  impact_points: number;
  is_strong_signal: boolean;
}

export function selectProblems(findings: Finding[], maxProblems = 7): ProblemRow[] {
  const scored = findings
    .filter((f) => f.deduction > 0 || STRONG_SIGNALS.has(f.code))
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3) || b.deduction - a.deduction);
  if (!scored.length) return [];

  const chosen: Finding[] = [];
  const seenCat = new Set<string>();
  for (const f of scored) {
    if (!seenCat.has(f.display_category)) {
      chosen.push(f);
      seenCat.add(f.display_category);
    }
    if (chosen.length >= maxProblems) break;
  }
  for (const f of scored) {
    if (chosen.length >= maxProblems) break;
    if (!chosen.includes(f)) chosen.push(f);
  }

  chosen.sort((a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3) || b.deduction - a.deduction);
  return chosen.slice(0, maxProblems).map((f, i) => ({
    rank: i + 1, code: f.code, category: f.display_category,
    category_label: CATEGORY_LABELS[f.display_category] ?? f.display_category, severity: f.severity,
    title: f.title, detail: f.detail, evidence: f.evidence, impact_points: f.deduction,
    is_strong_signal: STRONG_SIGNALS.has(f.code),
  }));
}

export interface RecommendationRow {
  rank: number;
  problem_code: string;
  problem: string;
  recommendation: string;
  category: string;
  severity: string;
}

export function buildRecommendations(problems: ProblemRow[], findings: Finding[]): RecommendationRow[] {
  const byCode = new Map(findings.map((f) => [f.code, f]));
  const out: RecommendationRow[] = [];
  for (const p of problems) {
    const f = byCode.get(p.code);
    if (f?.recommendation) {
      out.push({ rank: p.rank, problem_code: p.code, problem: p.title, recommendation: f.recommendation, category: p.category, severity: p.severity });
    }
  }
  return out;
}

// -- lead tiering (kept for API-shape completeness; a URL-only quick audit's
// lead_tier is informational only, since outreach routing is not part of
// this deployment's live UI) --------------------------------------------

export function leadTier(opts: {
  score: number | null;
  websiteStatus: string;
  hasUsableContact: boolean;
  strongProblemCount: number;
  problemCount: number;
  auditKind: string;
  reviewCount?: number | null;
  rating?: number | null;
}): { tier: string; reasons: string[] } {
  const reasons: string[] = [];
  if (opts.score === null) return { tier: "D", reasons: ["The website could not be audited, so there is no measured opportunity."] };

  const websiteOk = ["valid", "redirected"].includes(opts.websiteStatus);
  const noWebsite = opts.auditKind === "no_website";

  let active: boolean | null = null;
  if (opts.reviewCount !== null && opts.reviewCount !== undefined) {
    active = opts.reviewCount >= 5;
    if (active) reasons.push(`${opts.reviewCount} reviews on the source listing suggest an active business.`);
  }

  if (noWebsite) {
    let tier: string;
    if (opts.hasUsableContact) {
      tier = active !== false ? "B" : "C";
      reasons.push("No website was found, which is an opportunity, but there is no site to reference.");
    } else {
      tier = "D";
      reasons.push("No website and no usable contact channel.");
    }
    return { tier, reasons };
  }

  if (!websiteOk) {
    reasons.push(`The website status is '${opts.websiteStatus}', so the audit is not reliable.`);
    return { tier: "D", reasons };
  }

  const score = opts.score;
  let tier: string;
  if (score >= 75 && opts.hasUsableContact && opts.strongProblemCount >= 2) {
    tier = "A+";
    reasons.push(`Measured opportunity ${score}/100 with ${opts.strongProblemCount} strong, specific problems and a usable contact channel.`);
  } else if (score >= 60 && opts.hasUsableContact && opts.strongProblemCount >= 1) {
    tier = "A";
    reasons.push(`Measured opportunity ${score}/100 with a usable contact channel and at least one strong problem to open with.`);
  } else if (score >= 60 && !opts.hasUsableContact) {
    tier = "B";
    reasons.push(`Measured opportunity ${score}/100, but no usable contact channel was found.`);
  } else if (score >= 40) {
    tier = opts.hasUsableContact ? "B" : "C";
    reasons.push(`Moderate measured opportunity (${score}/100).`);
  } else if (opts.problemCount === 0) {
    tier = "D";
    reasons.push("No meaningful problems were detected on this website.");
  } else {
    tier = "C";
    reasons.push(`Low measured opportunity (${score}/100); the site is in reasonable shape.`);
  }

  if (!opts.hasUsableContact && (tier === "A+" || tier === "A")) {
    tier = "B";
    reasons.push("Downgraded: no usable contact channel.");
  }

  return { tier, reasons };
}

// --------------------------------------------------------------------------
// Premium audit scorecard
// --------------------------------------------------------------------------

export const AUDIT_CATEGORIES = ["technical", "onpage", "local_seo", "offpage", "performance", "accessibility", "security", "ux_conversion"];

export const AUDIT_CATEGORY_LABELS: Record<string, string> = {
  technical: "Technical SEO", onpage: "On-Page SEO", local_seo: "Local SEO", offpage: "Off-Page & Authority",
  performance: "Performance", accessibility: "Accessibility", security: "Security", ux_conversion: "UX & Conversion",
};

export const AUDIT_CATEGORY_WHY: Record<string, string> = {
  technical: "Search engines must be able to crawl and index a site before anything else about it can affect organic visibility.",
  onpage: "Titles, descriptions, headings and social tags are what search engines and shared links show first, driving click-through before a visitor ever reaches the page.",
  local_seo: "For a business that serves customers in a physical area, showing up in local search and map results depends on address, service-area and business details that search engines can find and verify - separate from general organic SEO.",
  offpage: "External signals - citations, linked social presence, structured entity data - are part of how search engines and visitors judge a business's credibility beyond its own site.",
  performance: "Slower, heavier pages lose visitors before they see the content, and are penalised by search engines' page-experience signals.",
  accessibility: "Inaccessible pages exclude real visitors - screen reader users, keyboard-only users, low-vision users - and carry legal risk in many jurisdictions.",
  security: "Missing security headers and unencrypted connections expose visitors to real risk and are flagged by browsers, which damages trust.",
  ux_conversion: "A site that is hard to use, unclear about what it offers, or gives visitors no obvious way to make contact loses real enquiries, regardless of how much traffic it gets.",
};

export const AUDIT_WEIGHTS_DEFAULTS: Record<string, number> = {
  technical: 13, onpage: 13, local_seo: 10, offpage: 5, performance: 13, accessibility: 9, security: 13, ux_conversion: 24,
};

export const LEGACY_CODE_TO_AUDIT_CATEGORY: Record<string, string> = {
  noindex: "technical", missing_sitemap: "technical", missing_robots: "technical", broken_internal_links: "technical", long_redirect_chain: "technical",
  no_https: "security", mixed_content: "security",
  missing_title: "onpage", title_too_short: "onpage", title_too_long: "onpage", missing_meta_description: "onpage",
  meta_description_short: "onpage", missing_h1: "onpage", multiple_h1: "onpage", missing_canonical: "onpage",
  generic_value_proposition: "onpage", no_heading_structure: "onpage", very_thin_homepage: "onpage", thin_homepage: "onpage",
  services_not_clear: "onpage", no_service_area: "onpage",
  missing_lang: "accessibility", low_alt_coverage: "accessibility",
  slow_response: "performance", heavy_page: "performance", many_scripts: "performance", pagespeed_low: "performance",
  missing_viewport: "ux_conversion", viewport_not_responsive: "ux_conversion", zoom_disabled: "ux_conversion",
  fixed_width_layout: "ux_conversion", small_mobile_text: "ux_conversion", no_mobile_tap_to_call: "ux_conversion",
  legacy_plugin_content: "ux_conversion", no_mobile_menu: "ux_conversion", minimal_navigation: "ux_conversion",
  no_primary_cta_above_fold: "ux_conversion", no_phone_cta: "ux_conversion", no_contact_form: "ux_conversion",
  no_booking_cta: "ux_conversion", no_quote_cta: "ux_conversion", no_email_cta: "ux_conversion", no_contact_page: "ux_conversion",
  weak_cta_language: "ux_conversion", no_testimonials: "ux_conversion", reviews_not_structured: "ux_conversion",
  no_credentials: "ux_conversion", no_portfolio: "ux_conversion", no_about_page: "ux_conversion", no_phone_on_site: "ux_conversion",
  phone_not_on_homepage: "ux_conversion", no_email_on_site: "ux_conversion", no_address: "ux_conversion", no_opening_hours: "ux_conversion",
  contact_hard_to_find: "ux_conversion", no_website_detected: "ux_conversion", social_profile_only: "ux_conversion",
  no_social_presence_linked: "offpage",
};

export function auditCategoryOf(finding: Finding): string {
  const mapped = LEGACY_CODE_TO_AUDIT_CATEGORY[finding.code];
  if (mapped) return mapped;
  if (AUDIT_CATEGORIES.includes(finding.category)) return finding.category;
  return AUDIT_CATEGORIES.includes(finding.display_category) ? finding.display_category : finding.category;
}

export function priorityFor(finding: Finding): "P1" | "P2" | "P3" {
  if (finding.severity === "high" || finding.deduction >= 20) return "P1";
  if (finding.severity === "medium" || finding.deduction >= 10) return "P2";
  return "P3";
}

interface CheckCatalogItem { id: string; category: string; label: string; fail_codes: string[] }

export const CHECK_CATALOG: CheckCatalogItem[] = [
  { id: "https", category: "security", label: "Site is served over HTTPS", fail_codes: ["no_https"] },
  { id: "mixed_content", category: "security", label: "No mixed HTTP content on an HTTPS page", fail_codes: ["mixed_content"] },
  { id: "hsts", category: "security", label: "Strict-Transport-Security header present", fail_codes: ["security_hsts_missing"] },
  { id: "csp", category: "security", label: "Content-Security-Policy header present", fail_codes: ["security_csp_missing"] },
  { id: "frame_protection", category: "security", label: "Clickjacking protection header present", fail_codes: ["security_frame_protection_missing"] },
  { id: "xcto", category: "security", label: "X-Content-Type-Options header present", fail_codes: ["security_xcto_missing"] },
  { id: "referrer_policy", category: "security", label: "Referrer-Policy header present", fail_codes: ["security_referrer_policy_missing"] },
  { id: "indexable", category: "technical", label: "Homepage is indexable (no noindex)", fail_codes: ["noindex"] },
  { id: "sitemap", category: "technical", label: "XML sitemap found", fail_codes: ["missing_sitemap"] },
  { id: "robots_txt", category: "technical", label: "robots.txt found", fail_codes: ["missing_robots"] },
  { id: "broken_links", category: "technical", label: "No broken internal links detected", fail_codes: ["broken_internal_links"] },
  { id: "redirects", category: "technical", label: "No excessive redirect chain", fail_codes: ["long_redirect_chain"] },
  { id: "title", category: "onpage", label: "Title tag present and well-sized", fail_codes: ["missing_title", "title_too_short", "title_too_long"] },
  { id: "meta_description", category: "onpage", label: "Meta description present and well-sized", fail_codes: ["missing_meta_description", "meta_description_short"] },
  { id: "h1", category: "onpage", label: "Homepage has exactly one H1", fail_codes: ["missing_h1", "multiple_h1"] },
  { id: "canonical", category: "onpage", label: "Canonical URL declared", fail_codes: ["missing_canonical"] },
  { id: "open_graph", category: "onpage", label: "Open Graph tags present", fail_codes: ["onpage_missing_open_graph"] },
  { id: "twitter_card", category: "onpage", label: "Twitter/X card tag present", fail_codes: ["onpage_missing_twitter_card"] },
  { id: "duplicate_titles", category: "onpage", label: "No duplicate titles across crawled pages", fail_codes: ["onpage_duplicate_titles"] },
  { id: "viewport", category: "ux_conversion", label: "Mobile viewport configured correctly", fail_codes: ["missing_viewport", "viewport_not_responsive"] },
  { id: "tap_to_call", category: "ux_conversion", label: "Tap-to-call link present on the homepage", fail_codes: ["no_mobile_tap_to_call"] },
  { id: "fixed_width", category: "ux_conversion", label: "No fixed-width layout wider than a phone screen", fail_codes: ["fixed_width_layout"] },
  { id: "mobile_menu", category: "ux_conversion", label: "Mobile navigation pattern detected", fail_codes: ["no_mobile_menu"] },
  { id: "alt_text", category: "accessibility", label: "Good image alt-text coverage", fail_codes: ["low_alt_coverage"] },
  { id: "lang", category: "accessibility", label: "Page language declared", fail_codes: ["missing_lang"] },
  { id: "main_landmark", category: "accessibility", label: "<main> landmark present", fail_codes: ["a11y_no_main_landmark"] },
  { id: "form_labels", category: "accessibility", label: "Form fields have associated labels", fail_codes: ["a11y_unlabelled_form_inputs"] },
  { id: "link_text", category: "accessibility", label: "Links have accessible text", fail_codes: ["a11y_empty_links"] },
  { id: "response_time", category: "performance", label: "Homepage responded quickly", fail_codes: ["slow_response"] },
  { id: "page_weight", category: "performance", label: "Homepage HTML is a reasonable size", fail_codes: ["heavy_page"] },
  { id: "compression", category: "performance", label: "Response is compressed", fail_codes: ["perf_no_compression"] },
  { id: "render_blocking", category: "performance", label: "No excessive render-blocking scripts", fail_codes: ["perf_render_blocking_scripts"] },
  { id: "phone_cta", category: "ux_conversion", label: "Clickable phone link present", fail_codes: ["no_phone_cta"] },
  { id: "contact_form", category: "ux_conversion", label: "Contact/enquiry form present", fail_codes: ["no_contact_form"] },
  { id: "contact_page", category: "ux_conversion", label: "Contact page present", fail_codes: ["no_contact_page"] },
  { id: "testimonials", category: "ux_conversion", label: "Testimonials/reviews present", fail_codes: ["no_testimonials"] },
  { id: "credentials", category: "ux_conversion", label: "Trust signals (licences/insurance/guarantees) present", fail_codes: ["no_credentials"] },
  { id: "address", category: "ux_conversion", label: "Business address published", fail_codes: ["no_address"] },
  { id: "social_profiles", category: "offpage", label: "Social profiles linked from the site", fail_codes: ["offpage_no_social_profiles"] },
  { id: "local_business_schema", category: "local_seo", label: "LocalBusiness/Organization structured data present", fail_codes: ["local_no_business_schema"] },
  { id: "local_address", category: "local_seo", label: "Business address published", fail_codes: ["local_no_address_signal"] },
  { id: "local_map_or_gbp", category: "local_seo", label: "Map embed or Google Business Profile link present", fail_codes: ["local_no_map_or_gbp_link"] },
  { id: "local_service_area", category: "local_seo", label: "Service-area or local landing-page content present", fail_codes: ["local_no_service_area_content"] },
  { id: "local_hours", category: "local_seo", label: "Opening hours published", fail_codes: ["local_no_opening_hours"] },
  { id: "local_reviews", category: "local_seo", label: "Reviews or testimonials present", fail_codes: ["local_no_reviews_or_testimonials"] },
  { id: "local_reviews_structured", category: "local_seo", label: "Reviews marked up as structured data (Review/AggregateRating)", fail_codes: ["local_reviews_not_structured"] },
  { id: "local_name_consistency", category: "local_seo", label: "Business name consistent between structured data and page content", fail_codes: ["local_name_mismatch"] },
];

export const NOT_VERIFIED_CATALOG = [
  { id: "color_contrast", category: "accessibility", label: "Colour contrast meets WCAG guidelines", detail: "Requires a rendered page with computed styles; not measurable from static HTML/CSS." },
  { id: "backlink_profile", category: "offpage", label: "Backlink count and referring domains", detail: "Requires a paid third-party index (e.g. Ahrefs, Moz, Majestic, SEMrush); never estimated." },
  { id: "domain_authority", category: "offpage", label: "Domain authority / DR-style score", detail: "Proprietary to each vendor; never approximated." },
];

export const STATUS_PASS = "pass";
export const STATUS_WARNING = "warning";
export const STATUS_FAIL = "fail";
export const STATUS_NOT_VERIFIED = "not_verified";
export const STATUS_NOT_APPLICABLE = "not_applicable";

interface CheckResultRow { id: string; category: string; label: string; status: string; detail: string }

export interface CheckResults {
  checks: CheckResultRow[];
  passed: CheckResultRow[];
  warnings: CheckResultRow[];
  failed: CheckResultRow[];
  not_verified: CheckResultRow[];
  not_applicable: CheckResultRow[];
  passed_count: number;
  warning_count: number;
  failed_count: number;
  not_verified_count: number;
  not_applicable_count: number;
  total_checked: number;
  total_catalogued: number;
}

export function buildCheckResults(
  findings: Finding[],
  opts: { categoryApplicability?: Record<string, boolean>; applicabilityReason?: Record<string, string>; pagespeedMeasured?: boolean } = {},
): CheckResults {
  const applicability = opts.categoryApplicability ?? {};
  const reasons = opts.applicabilityReason ?? {};
  const present = new Map<string, Finding>();
  for (const f of findings) if (!present.has(f.code)) present.set(f.code, f);

  const results: CheckResultRow[] = [];

  for (const chk of CHECK_CATALOG) {
    const cat = chk.category;
    if (applicability[cat] === false) {
      results.push({ id: chk.id, category: cat, label: chk.label, status: STATUS_NOT_APPLICABLE, detail: reasons[cat] || "Not applicable to this website." });
      continue;
    }
    const hit = chk.fail_codes.find((c) => present.has(c));
    if (!hit) {
      results.push({ id: chk.id, category: cat, label: chk.label, status: STATUS_PASS, detail: "" });
    } else {
      const fnd = present.get(hit)!;
      results.push({ id: chk.id, category: cat, label: chk.label, status: fnd.severity === "high" ? STATUS_FAIL : STATUS_WARNING, detail: fnd.title });
    }
  }

  for (const chk of NOT_VERIFIED_CATALOG) {
    const cat = chk.category;
    if (applicability[cat] === false) {
      results.push({ id: chk.id, category: cat, label: chk.label, status: STATUS_NOT_APPLICABLE, detail: reasons[cat] || "Not applicable to this website." });
    } else {
      results.push({ id: chk.id, category: cat, label: chk.label, status: STATUS_NOT_VERIFIED, detail: chk.detail });
    }
  }

  let cwvStatus: string;
  let cwvDetail: string;
  if (applicability.performance === false) {
    cwvStatus = STATUS_NOT_APPLICABLE;
    cwvDetail = reasons.performance || "Not applicable to this website.";
  } else if (opts.pagespeedMeasured) {
    const hit = present.get("pagespeed_low");
    if (hit) {
      cwvStatus = hit.severity === "high" ? STATUS_FAIL : STATUS_WARNING;
      cwvDetail = hit.title;
    } else {
      cwvStatus = STATUS_PASS;
      cwvDetail = "";
    }
  } else {
    cwvStatus = STATUS_NOT_VERIFIED;
    cwvDetail = "Configure a Google PageSpeed Insights API key in Settings to measure Core Web Vitals.";
  }
  results.push({ id: "core_web_vitals", category: "performance", label: "Core Web Vitals / PageSpeed performance score", status: cwvStatus, detail: cwvDetail });

  const counts: Record<string, number> = { [STATUS_PASS]: 0, [STATUS_WARNING]: 0, [STATUS_FAIL]: 0, [STATUS_NOT_VERIFIED]: 0, [STATUS_NOT_APPLICABLE]: 0 };
  for (const r of results) counts[r.status] += 1;
  const evaluated = counts[STATUS_PASS] + counts[STATUS_WARNING] + counts[STATUS_FAIL];

  return {
    checks: results,
    passed: results.filter((r) => r.status === STATUS_PASS),
    warnings: results.filter((r) => r.status === STATUS_WARNING),
    failed: results.filter((r) => r.status === STATUS_FAIL),
    not_verified: results.filter((r) => r.status === STATUS_NOT_VERIFIED),
    not_applicable: results.filter((r) => r.status === STATUS_NOT_APPLICABLE),
    passed_count: counts[STATUS_PASS], warning_count: counts[STATUS_WARNING], failed_count: counts[STATUS_FAIL],
    not_verified_count: counts[STATUS_NOT_VERIFIED], not_applicable_count: counts[STATUS_NOT_APPLICABLE],
    total_checked: evaluated, total_catalogued: results.length,
  };
}

export interface ScorecardCategoryRow {
  category: string;
  label: string;
  weight: number;
  health: number | null;
  opportunity: number | null;
  contribution: number;
  findings: number;
  deductions: number;
  score: number | null;
  why_it_matters: string;
  applicable: boolean;
  not_applicable_reason?: string;
}

export interface Scorecard {
  overall_score: number;
  categories: ScorecardCategoryRow[];
  weights: Record<string, number>;
  severity_counts: { high: number; medium: number; low: number };
  checks: CheckResults;
}

export function buildScorecard(
  findings: Finding[],
  weights: Record<string, number> = AUDIT_WEIGHTS_DEFAULTS,
  opts: { categoryApplicability?: Record<string, boolean>; applicabilityReason?: Record<string, string>; pagespeedMeasured?: boolean } = {},
): Scorecard {
  const applicability = opts.categoryApplicability ?? {};
  const reasons = opts.applicabilityReason ?? {};

  const activeCats = AUDIT_CATEGORIES.filter((c) => applicability[c] !== false);
  const activeWeights: Record<string, number> = {};
  for (const c of activeCats) activeWeights[c] = weights[c] ?? 0;

  const result = computeScore(findings, activeWeights, { categories: activeCats, categoryOf: auditCategoryOf, labels: AUDIT_CATEGORY_LABELS });

  const severityCounts = { high: 0, medium: 0, low: 0 };
  for (const f of findings) {
    if (f.deduction > 0 && f.severity in severityCounts) (severityCounts as any)[f.severity] += 1;
  }

  const categories: ScorecardCategoryRow[] = result.explanation.map((row) => ({
    ...row, score: row.health, why_it_matters: AUDIT_CATEGORY_WHY[row.category] || "", applicable: true,
  }));
  for (const c of AUDIT_CATEGORIES) {
    if (applicability[c] === false) {
      categories.push({
        category: c, label: AUDIT_CATEGORY_LABELS[c] ?? titleCase(c), weight: 0, health: null, opportunity: null,
        contribution: 0, findings: 0, deductions: 0, score: null, why_it_matters: AUDIT_CATEGORY_WHY[c] || "",
        applicable: false, not_applicable_reason: reasons[c] || "Not applicable to this website.",
      });
    }
  }
  categories.sort((a, b) => AUDIT_CATEGORIES.indexOf(a.category) - AUDIT_CATEGORIES.indexOf(b.category));

  return {
    overall_score: result.overall_health,
    categories,
    weights: result.weights,
    severity_counts: severityCounts,
    checks: buildCheckResults(findings, { categoryApplicability: applicability, applicabilityReason: reasons, pagespeedMeasured: opts.pagespeedMeasured }),
  };
}

export function hasClearOpportunity(problems: ProblemRow[], score: number | null, minProblems = 1): [boolean, string] {
  if (score === null) return [false, "The website could not be audited."];
  const strong = problems.filter((p) => p.is_strong_signal);
  if (problems.length < minProblems) return [false, "No meaningful, evidence-backed problems were detected on this website."];
  if (!strong.length && score < 40) {
    return [false, "Only minor issues were detected and the overall opportunity score is low; there is no strong, specific observation to open a conversation with."];
  }
  return [true, ""];
}

export interface PriorityRow {
  rank: number;
  code: string;
  category: string;
  category_label: string;
  severity: string;
  priority: string;
  title: string;
  detail: string;
  why_it_matters: string;
  recommendation: string;
  impact_points: number;
}

export function topPriorities(findings: Finding[], n = 5): PriorityRow[] {
  const scored = findings.filter((f) => f.deduction > 0).sort((a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3) || b.deduction - a.deduction);
  if (!scored.length) return [];

  const chosen: Finding[] = [];
  const seenCat = new Set<string>();
  for (const f of scored) {
    const cat = auditCategoryOf(f);
    if (!seenCat.has(cat)) {
      chosen.push(f);
      seenCat.add(cat);
    }
    if (chosen.length >= n) break;
  }
  for (const f of scored) {
    if (chosen.length >= n) break;
    if (!chosen.includes(f)) chosen.push(f);
  }
  chosen.sort((a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3) || b.deduction - a.deduction);

  return chosen.slice(0, n).map((f, i) => {
    const cat = auditCategoryOf(f);
    return {
      rank: i + 1, code: f.code, category: cat, category_label: AUDIT_CATEGORY_LABELS[cat] ?? titleCase(cat),
      severity: f.severity, priority: priorityFor(f), title: f.title, detail: f.detail,
      why_it_matters: AUDIT_CATEGORY_WHY[cat] || "", recommendation: f.recommendation, impact_points: f.deduction,
    };
  });
}

const BUSINESS_IMPACT_BY_CATEGORY: Record<string, string> = {
  technical: "search engines may struggle to fully crawl and index the site",
  onpage: "the site is less likely to appear for the searches that matter, and shared links look unpolished",
  local_seo: "the business is less likely to appear in local search and map results for nearby customers",
  offpage: "the site has less credibility signal to search engines and visitors than it could",
  performance: "visitors on slower connections may leave before the page finishes loading",
  accessibility: "some real visitors cannot use the site properly, which also carries legal risk in many places",
  security: "visitors' browsers may warn them the connection is not fully secure, which damages trust",
  ux_conversion: "interested visitors may leave without ever making contact",
};

export interface ExecutiveSummary {
  headline: string;
  whats_working: string[];
  top_problems: string[];
  biggest_opportunities: string[];
  business_impact: string;
  next_steps: string[];
  checks_summary: { passed: number; warnings: number; critical: number; not_verified: number; not_applicable: number; total: number };
}

export function buildExecutiveSummary(scorecard: Scorecard, findings: Finding[], priorities: PriorityRow[]): ExecutiveSummary {
  const categories = scorecard.categories || [];
  const checks = scorecard.checks;

  const working = categories
    .filter((c) => c.applicable !== false && c.score !== null)
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    .filter((c) => (c.score ?? 0) >= 85)
    .map((c) => c.label)
    .slice(0, 4);

  const topProblems = priorities.slice(0, 3).map((p) => p.title);

  const opportunityCats = categories
    .filter((c) => c.applicable !== false && c.score !== null && (c.score ?? 0) < 70)
    .sort((a, b) => (a.score ?? 0) - (b.score ?? 0));
  const biggestOpportunities = opportunityCats.slice(0, 3).map((c) => `${c.label} (${c.score}/100)`);

  const impactedCats: string[] = [];
  for (const fnd of findings) {
    if (fnd.deduction > 0 && (fnd.severity === "high" || fnd.severity === "medium")) {
      const cat = auditCategoryOf(fnd);
      if (!impactedCats.includes(cat)) impactedCats.push(cat);
    }
  }
  const impactSentences = AUDIT_CATEGORIES.filter((c) => impactedCats.includes(c) && c in BUSINESS_IMPACT_BY_CATEGORY)
    .map((c) => BUSINESS_IMPACT_BY_CATEGORY[c])
    .slice(0, 3);
  const businessImpact = impactSentences.length
    ? `Left unaddressed, ${impactSentences.join("; ")}.`
    : "No high-impact issues were found that are likely to cost the business enquiries.";

  const nextSteps = priorities.filter((p) => p.recommendation).map((p) => p.recommendation).slice(0, 5);

  const overall = scorecard.overall_score;
  let headline: string;
  if (overall === null || overall === undefined) headline = "This site could not be fully audited.";
  else if (overall >= 85) headline = `This site is in strong shape overall, scoring ${overall}/100.`;
  else if (overall >= 70) headline = `This site is in reasonable shape overall, scoring ${overall}/100, with room to improve.`;
  else if (overall >= 50) headline = `This site scores ${overall}/100 overall — several important issues are holding it back.`;
  else headline = `This site scores ${overall}/100 overall — a number of significant issues need attention.`;

  return {
    headline, whats_working: working, top_problems: topProblems, biggest_opportunities: biggestOpportunities,
    business_impact: businessImpact, next_steps: nextSteps,
    checks_summary: {
      passed: checks.passed_count, warnings: checks.warning_count, critical: checks.failed_count,
      not_verified: checks.not_verified_count, not_applicable: checks.not_applicable_count, total: checks.total_checked,
    },
  };
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}
function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
