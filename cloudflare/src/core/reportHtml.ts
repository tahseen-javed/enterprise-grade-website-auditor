// Premium, printable HTML audit report. Ported from
// backend/app/core/report_html.py. The Python original renders through
// Jinja2 with autoescaping on "so nothing scraped from a third-party site
// can inject markup into the report" — this hand-built template has no
// templating engine to do that for it, so every dynamic string is passed
// through esc() explicitly. Only the four generated inline-SVG strings
// (this module's own output, never third-party text) skip escaping.
import type { Finding } from "../types";
import {
  AUDIT_CATEGORIES, AUDIT_CATEGORY_LABELS, AUDIT_CATEGORY_WHY, auditCategoryOf, priorityFor,
  Scorecard, PriorityRow, ExecutiveSummary,
} from "./scoring";

const SEVERITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };
const SEVERITY_LABEL: Record<string, string> = { high: "Critical", medium: "High priority", low: "Warning" };
const SEVERITY_BADGE: Record<string, string> = { high: "CRITICAL", medium: "HIGH", low: "MEDIUM" };
const BADGE_CLASS: Record<string, string> = { high: "critical", medium: "high", low: "medium" };

const CATEGORY_ICON: Record<string, string> = {
  technical: "⚙", onpage: "✎", local_seo: "◎", offpage: "⬈",
  performance: "⚡", accessibility: "☺", security: "🛡", ux_conversion: "◈",
};

function esc(v: unknown): string {
  if (v === null || v === undefined) return "";
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ============================================================================
// Bands, grades and formatting
// ============================================================================

interface Band { key: string; label: string; fg: string; g1: string; g2: string; soft: string; edge: string }

const BANDS: Record<string, Band> = {
  green: { key: "green", label: "Good", fg: "#34d399", g1: "#34d399", g2: "#22d3ee", soft: "rgba(52,211,153,.12)", edge: "rgba(52,211,153,.38)" },
  yellow: { key: "yellow", label: "Needs Improvement", fg: "#fbbf24", g1: "#f59e0b", g2: "#fbbf24", soft: "rgba(251,191,36,.13)", edge: "rgba(251,191,36,.40)" },
  orange: { key: "orange", label: "Important Issue", fg: "#fb923c", g1: "#f97316", g2: "#fbbf24", soft: "rgba(251,146,60,.13)", edge: "rgba(251,146,60,.42)" },
  red: { key: "red", label: "Critical Issue", fg: "#fb5b6f", g1: "#fb5b6f", g2: "#fb923c", soft: "rgba(251,91,111,.14)", edge: "rgba(251,91,111,.42)" },
  gray: { key: "gray", label: "Not Verified", fg: "#7f8bad", g1: "#3a4463", g2: "#55607d", soft: "rgba(148,178,255,.07)", edge: "rgba(148,178,255,.20)" },
};

function band(score: number | null | undefined, applicable = true): Band {
  if (!applicable) return { ...BANDS.gray, label: "Not Applicable" };
  if (score === null || score === undefined) return { ...BANDS.gray };
  if (score >= 85) return { ...BANDS.green };
  if (score >= 70) return { ...BANDS.yellow };
  if (score >= 50) return { ...BANDS.orange };
  return { ...BANDS.red };
}

function grade(score: number | null | undefined): string {
  if (score === null || score === undefined) return "";
  const table: [number, string][] = [
    [95, "A+"], [90, "A"], [85, "A−"], [80, "B+"], [75, "B"], [70, "B−"],
    [65, "C+"], [60, "C"], [55, "C−"], [50, "D+"], [40, "D"], [0, "F"],
  ];
  for (const [floor, letter] of table) if (score >= floor) return letter;
  return "F";
}

function fmtBool(v: unknown, yes = "Yes", no = "No", unknown_ = "Not measured"): string {
  if (v === true) return yes;
  if (v === false) return no;
  return unknown_;
}

interface EvidenceRow { k: string; v: string }

function evidenceRows(ev: Record<string, unknown> | undefined, limit = 6): EvidenceRow[] {
  const out: EvidenceRow[] = [];
  if (!ev || typeof ev !== "object") return out;
  for (const [key, val] of Object.entries(ev)) {
    if (val === null || val === undefined || val === "" || (Array.isArray(val) && !val.length)) continue;
    if (val && typeof val === "object" && !Array.isArray(val) && !Object.keys(val).length) continue;
    const label = key.replace(/_/g, " ");
    let value: string;
    if (Array.isArray(val)) {
      const items = val.slice(0, 4).map((v) => {
        if (v && typeof v === "object") return (v as any).url || (v as any).title || JSON.stringify(v);
        return String(v);
      });
      value = items.map((i) => String(i).slice(0, 110)).join(", ");
      if (val.length > 4) value += ` (+${val.length - 4} more)`;
    } else if (val && typeof val === "object") {
      continue;
    } else if (typeof val === "boolean") {
      value = val ? "Yes" : "No";
    } else {
      value = String(val).slice(0, 240);
    }
    out.push({ k: label, v: value });
    if (out.length >= limit) break;
  }
  return out;
}

function slugify(text: string, fallback: string): string {
  const s = (text || "").replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase();
  return s.slice(0, 60) || fallback;
}

interface FindingRow {
  code: string; category: string; category_label: string; severity: string; severity_label: string;
  severity_badge: string; badge_class: string; title: string; detail: string; evidence_rows: EvidenceRow[];
  recommendation: string; why_it_matters: string; priority: string; deduction: number;
}

function findingRow(fnd: Finding): FindingRow {
  const cat = auditCategoryOf(fnd);
  const sev = fnd.severity in SEVERITY_ORDER ? fnd.severity : "low";
  return {
    code: fnd.code, category: cat, category_label: AUDIT_CATEGORY_LABELS[cat] ?? cat,
    severity: sev, severity_label: SEVERITY_LABEL[sev] ?? "Note", severity_badge: SEVERITY_BADGE[sev] ?? "LOW",
    badge_class: BADGE_CLASS[sev] ?? "low", title: fnd.title, detail: fnd.detail, evidence_rows: evidenceRows(fnd.evidence),
    recommendation: fnd.recommendation, why_it_matters: WHY_BY_CODE[fnd.code] || AUDIT_CATEGORY_WHY[cat] || "",
    priority: priorityFor(fnd), deduction: fnd.deduction,
  };
}

function buildFindingsContext(legacy: Finding[], extra: Finding[]) {
  const rows = [...legacy, ...extra].map(findingRow);
  rows.sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 2) - (SEVERITY_ORDER[b.severity] ?? 2) || b.deduction - a.deduction);
  return { all: rows, critical: rows.filter((r) => r.severity === "high"), high: rows.filter((r) => r.severity === "medium"), warnings: rows.filter((r) => r.severity === "low") };
}

// ============================================================================
// Verified-signal panels
// ============================================================================

interface Signal { label: string; value: string; na: boolean; why: string }

function sig(label: string, value: unknown, opts: { why?: string; naText?: string } = {}): Signal {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) {
    return { label, value: opts.naText ?? "Not Available", na: true, why: opts.why || "" };
  }
  return { label, value: String(value), na: false, why: opts.why || "" };
}

function headlineSignals(tech: any, perf: any, extra: any): Signal[] {
  const sec = extra.security || {};
  const onp = extra.onpage || {};
  const out: Signal[] = [];
  out.push(sig("HTTP status", tech.http_status));
  out.push(sig("HTTPS", fmtBool(tech.is_https, "Enabled", "Not enabled", "Not measured")));
  out.push(sig("Homepage response time", tech.response_ms !== null && tech.response_ms !== undefined ? `${tech.response_ms} ms` : null, {
    why: "Single server-side measurement from the machine that ran this audit — not a full performance profile.",
  }));
  out.push(sig("Pages crawled", tech.pages_crawled));
  out.push(sig("Indexable", !(String(tech.meta_robots || "").toLowerCase().includes("noindex")) ? "Yes" : "No — noindex present"));
  out.push(sig("XML sitemap", fmtBool(tech.sitemap_found, "Found", "Not found", "Not measured")));
  out.push(sig("robots.txt", fmtBool(tech.robots_txt_found, "Found", "Not found", "Not measured")));
  out.push(sig("Internal links checked", tech.links_checked ? `${tech.links_checked} · ${(tech.broken_links || []).length} broken` : null));
  if (tech.alt_coverage !== null && tech.alt_coverage !== undefined) {
    out.push(sig("Image alt coverage", `${Math.floor(tech.alt_coverage * 100)}% of ${tech.images_total || 0} images`));
  } else {
    out.push(sig("Image alt coverage", null, { why: "No images were found on the crawled pages." }));
  }
  const schemaTypes = onp.schema_types_found || [];
  out.push(sig("Structured data types", schemaTypes.join(", ") || null, { why: !schemaTypes.length ? "No JSON-LD schema types were found on the crawled pages." : "" }));
  out.push(sig("Security headers measured", fmtBool(sec.headers_measured, "Yes", "No", "Not measured")));
  out.push(sig("Page HTML size", tech.page_bytes ? `${Math.round(tech.page_bytes / 1024)} KB` : null));

  if (perf?.measured) {
    out.push(sig("Google PageSpeed score", `${perf.performance_score}/100 (${perf.strategy})`));
    out.push(sig("Largest Contentful Paint", perf.lcp_s !== null && perf.lcp_s !== undefined ? `${perf.lcp_s} s` : null));
  } else {
    out.push(sig("Core Web Vitals (LCP / CLS / INP)", null, {
      naText: "Not Verified",
      why: "Requires a Google PageSpeed Insights API key, which is not configured for this audit. These values are never estimated.",
    }));
  }
  out.push(sig("Backlinks / referring domains / domain authority", null, {
    naText: "Not Verified", why: "Requires a paid third-party index (Ahrefs, Moz, Majestic, SEMrush). Never estimated or fabricated.",
  }));
  out.push(sig("Organic traffic / keyword rankings", null, {
    naText: "Not Verified", why: "Requires Search Console access or a paid rank-tracking source. Never estimated or fabricated.",
  }));
  return out;
}

function categorySignals(key: string, tech: any, mob: any, conv: any, extra: any): Signal[] {
  const sec = extra.security || {};
  const a11y = extra.accessibility || {};
  const onp = extra.onpage || {};
  const offp = extra.offpage || {};
  const pex = extra.performance_extra || {};
  const loc = extra.local_seo || {};

  if (key === "technical") {
    return [
      sig("Final URL", tech.final_url),
      sig("Redirect hops", tech.redirect_count),
      sig("Canonical URL", tech.canonical, { why: !tech.canonical ? "No canonical link element was found." : "" }),
      sig("Meta robots", tech.meta_robots, { why: !tech.meta_robots ? "No meta robots directive was present (default: index, follow)." : "" }),
      sig("Sitemap URL", tech.sitemap_url),
      sig("Broken internal links", tech.links_checked ? (tech.broken_links || []).length : null),
    ];
  }
  if (key === "onpage") {
    return [
      sig("Title", tech.title, { why: tech.title ? `${tech.title_length || 0} characters` : "No <title> element was found." }),
      sig("Meta description", tech.meta_description, { why: tech.meta_description ? `${tech.meta_description_length || 0} characters` : "No meta description was found." }),
      sig("H1", (tech.h1 || []).join(", ") || null, { why: `${tech.h1_count || 0} H1 element(s) on the homepage` }),
      sig("Open Graph tags", (onp.open_graph_tags || []).join(", ") || null),
      sig("Twitter/X card tags", (onp.twitter_card_tags || []).join(", ") || null),
      sig("Declared language", tech.lang),
    ];
  }
  if (key === "local_seo") {
    if (!loc || !Object.keys(loc).length) return [];
    return [
      sig("LocalBusiness/Organization schema", fmtBool(loc.local_business_schema, "Present", "Not found")),
      sig("Schema contains a postal address", fmtBool(loc.schema_has_address, "Yes", "No")),
      sig("Address published on site", fmtBool(loc.address_signal, "Yes", "Not found")),
      sig("Map embed or Google Business Profile link", fmtBool(loc.map_or_gbp_link, "Present", "Not found")),
      sig("Service-area content", fmtBool(loc.service_area_signal, "Present", "Not found")),
      sig("Opening hours", fmtBool(loc.opening_hours_signal, "Published", "Not found")),
    ];
  }
  if (key === "offpage") {
    return [
      sig("Social profiles linked from the site", (offp.social_profiles_linked || []).join(", ") || null),
      sig("sameAs entries in structured data", (offp.structured_data_sameas || []).join(", ") || null),
      sig("External domains referenced", offp.external_domains_referenced_count),
      sig("Backlink count", null, { naText: "Not Verified", why: offp.backlinks?.reason || "" }),
      sig("Referring domains", null, { naText: "Not Verified", why: offp.referring_domains?.reason || "" }),
      sig("Domain authority", null, { naText: "Not Verified", why: offp.domain_authority?.reason || "" }),
    ];
  }
  if (key === "performance") {
    return [
      sig("Response time", tech.response_ms !== null && tech.response_ms !== undefined ? `${tech.response_ms} ms` : null),
      sig("HTML size", tech.page_bytes ? `${Math.round(tech.page_bytes / 1024)} KB` : null),
      sig("Scripts on homepage", tech.script_count),
      sig("Render-blocking scripts", pex.render_blocking_scripts),
      sig("Stylesheets", pex.stylesheet_count),
      sig("Content-Encoding", pex.content_encoding, { why: !pex.content_encoding ? "No compression header was returned." : "" }),
      sig("Cache-Control", pex.cache_control),
    ];
  }
  if (key === "accessibility") {
    return [
      sig("Language declared", fmtBool(a11y.lang_declared, "Yes", "No")),
      sig("<main> landmark", fmtBool(a11y.has_main_landmark, "Present", "Missing")),
      sig("<nav> landmark", fmtBool(a11y.has_nav_landmark, "Present", "Missing")),
      sig("Skip link", fmtBool(a11y.has_skip_link, "Present", "Missing")),
      sig("Unlabelled form inputs", a11y.form_inputs_checked ? `${a11y.unlabelled_form_inputs} of ${a11y.form_inputs_checked}` : null),
      sig("Links with no accessible text", a11y.empty_links),
      sig("Colour contrast", null, { naText: "Not Verified", why: a11y.contrast_note || "" }),
    ];
  }
  if (key === "security") {
    return [
      sig("HTTPS", fmtBool(sec.is_https, "Enabled", "Not enabled")),
      sig("Strict-Transport-Security", fmtBool(sec.hsts_present, "Present", "Missing")),
      sig("Content-Security-Policy", fmtBool(sec.csp_present, "Present", "Missing")),
      sig("X-Content-Type-Options", sec.x_content_type_options),
      sig("X-Frame-Options", sec.x_frame_options),
      sig("Referrer-Policy", fmtBool(sec.referrer_policy_present, "Present", "Missing")),
      sig("Permissions-Policy", fmtBool(sec.permissions_policy_present, "Present", "Missing")),
      sig("Mixed content items", tech.mixed_content_count),
    ];
  }
  if (key === "ux_conversion") {
    return [
      sig("Mobile viewport", mob.viewport, { why: !mob.viewport ? "No viewport meta tag was found." : "" }),
      sig("Tap-to-call on homepage", fmtBool(mob.tap_to_call_on_homepage, "Present", "Not found")),
      sig("Mobile navigation pattern", fmtBool(mob.mobile_menu_detected, "Detected", "Not detected")),
      sig("Contact form", fmtBool(conv.has_contact_form, "Present", "Not found")),
      sig("Booking CTA", fmtBool(conv.has_booking_cta, "Present", "Not found")),
      sig("Strong CTAs counted", conv.strong_cta_count),
    ];
  }
  return [];
}

// Why each finding matters — direct port of WHY_BY_CODE from report_html.py.
const WHY_BY_CODE: Record<string, string> = {
  noindex: "A noindex directive tells search engines to drop the page from their index entirely. While it is present, the page cannot rank for anything, no matter how good it is.",
  missing_sitemap: "An XML sitemap is how a site tells search engines which URLs exist and are worth crawling. Without one, discovery relies purely on internal links, so newer or deeply nested pages can be found late or missed.",
  missing_robots: "robots.txt is the first file a crawler requests. Without it, crawlers get no guidance on which areas to skip, and the conventional place to point at the sitemap is missing.",
  broken_internal_links: "Broken internal links send visitors and crawlers to dead ends, waste crawl budget, and break the flow of link equity between pages.",
  long_redirect_chain: "Each redirect hop adds latency for the visitor and dilutes the signal passed to the final URL. Long chains are also a common source of redirect loops.",
  missing_title: "The title tag is the headline of the search result and the browser tab. With none, search engines invent one from page content, and the site loses its single strongest on-page relevance signal.",
  title_too_short: "A very short title wastes the most valuable text a search result can show and usually omits the service and location a searcher typed.",
  title_too_long: "Titles beyond roughly 60 characters get truncated in search results, so the end of the message - often the brand or location - is cut off.",
  missing_meta_description: "Without a meta description, search engines assemble a snippet from whatever text they find, which often reads awkwardly and rarely makes the case for clicking.",
  meta_description_short: "A very short description leaves most of the available snippet space unused, giving searchers less reason to choose this result.",
  missing_h1: "The H1 is the page's main heading. Without one, both search engines and screen reader users lack a clear statement of what the page is about.",
  multiple_h1: "Several H1s give no single clear subject for the page and make the heading outline ambiguous for assistive technology.",
  missing_canonical: "Without a canonical URL, the same content reachable at several addresses (with/without a trailing slash, with tracking parameters) can be treated as duplicates, splitting ranking signals between them.",
  onpage_missing_open_graph: "Open Graph tags control the title, description and image shown when the page is shared on social platforms or messaging apps. Without them the preview is assembled at random, or is blank.",
  onpage_missing_twitter_card: "Without a card tag, links shared on X/Twitter render as a plain URL rather than a rich preview.",
  onpage_duplicate_titles: "Pages sharing a title look interchangeable to search engines, which makes it harder for the right page to be selected for a given query.",
  onpage_duplicate_meta_description: "Duplicate descriptions produce identical-looking search results, so nothing distinguishes one page from another.",
  generic_value_proposition: "A heading like “Welcome” or “Home” tells neither a visitor nor a search engine what the business actually does.",
  no_heading_structure: "Headings are the outline of the page. With none below the top level, the content has no machine-readable structure and is harder to scan.",
  very_thin_homepage: "A homepage with very little text gives search engines almost nothing to understand the business by, and gives visitors little reason to stay.",
  thin_homepage: "There is limited content for search engines to assess relevance from, and limited information for a visitor deciding whether to enquire.",
  services_not_clear: "If the services offered are not stated in plain text, the site cannot match the searches people actually type.",
  no_service_area: "Without a stated service area, both visitors and search engines have to guess where the business operates.",
  local_no_business_schema: "LocalBusiness/Organization JSON-LD is how a search engine confirms a business's name, address and category as structured facts rather than inferring them from page text. It underpins map and local results.",
  local_no_address_signal: "A published address is a core local ranking and trust signal, and is what directories and search engines match against.",
  local_address_not_structured: "An address that appears only as visible text has to be parsed out of prose. In structured data it is unambiguous.",
  local_no_map_or_gbp_link: "A map embed or Google Business Profile link connects the website to the business's map listing, which is where local searchers usually arrive.",
  local_no_service_area_content: "Without pages or sections naming the areas served, there is nothing for location-specific searches to match.",
  local_no_opening_hours: "Opening hours are among the first things a local searcher looks for, and are shown directly in map results when published.",
  local_no_reviews_or_testimonials: "Social proof is a decisive factor for local purchases, and review content is a visible trust signal on the page itself.",
  local_reviews_not_structured: "Reviews marked up as Review/AggregateRating can qualify for star-rating rich results; as plain text they cannot.",
  local_name_mismatch: "When the business name in structured data differs from the name on the page, search engines get conflicting information about which entity this is.",
  offpage_no_social_profiles: "Linked social profiles are one of the few verifiable off-site signals a website can publish about itself, and they give visitors another way to check the business is real and active.",
  offpage_sameas_not_structured: "Declaring profile URLs as sameAs in structured data is what lets a search engine tie those accounts to this business as one entity, rather than treating them as unrelated links.",
  no_social_presence_linked: "With no social presence linked from the site, visitors have no secondary way to verify the business is active.",
  slow_response: "Server response time sits in front of everything else: nothing can render until the first byte arrives, so it sets the floor for every other speed metric.",
  heavy_page: "A large HTML document takes longer to download and parse, which delays the point at which a visitor sees anything - most noticeably on mobile connections.",
  many_scripts: "Every script must be fetched, parsed and executed, competing with rendering for the main thread and delaying interactivity.",
  perf_render_blocking_scripts: "Scripts in the head without defer or async stop the page rendering until they finish loading, leaving the visitor on a blank screen.",
  perf_no_compression: "Serving uncompressed text means sending several times more bytes than necessary for the same page.",
  perf_no_cache_headers: "Without cache headers, returning visitors re-download assets that have not changed, making repeat visits slower than they need to be.",
  pagespeed_low: "This is Google's own measurement of the page experience, and page experience is an input to how the page is ranked as well as to whether visitors stay.",
  missing_lang: "Without a declared language, screen readers may use the wrong pronunciation rules, making the page hard or impossible to follow by ear.",
  low_alt_coverage: "Images without alt text are invisible to screen reader users and give search engines nothing to index them by.",
  a11y_no_main_landmark: "A <main> landmark is what lets keyboard and screen reader users jump straight to the content instead of tabbing through the whole header.",
  a11y_unlabelled_form_inputs: "An input with no label is announced as an unnamed field, so a screen reader user cannot tell what to type into it.",
  a11y_empty_links: "A link with no accessible text is announced only as “link”, giving no indication of where it goes.",
  a11y_heading_order_skipped: "Skipped heading levels break the document outline that assistive technology uses to navigate a page.",
  no_https: "Without HTTPS, everything sent between visitor and site - including anything typed into a form - travels in the clear, and browsers actively mark the site as Not Secure.",
  mixed_content: "Loading HTTP resources on an HTTPS page undermines the encryption and causes browsers to block those resources or warn the visitor.",
  security_hsts_missing: "Without HSTS, a visitor's first request can still be made over plain HTTP and intercepted before the redirect to HTTPS happens.",
  security_csp_missing: "A Content-Security-Policy is the strongest browser-level defence against cross-site scripting and unauthorised resource loading.",
  security_frame_protection_missing: "Without frame protection, the site can be embedded invisibly in another page and used to trick visitors into clicking things they cannot see.",
  security_xcto_missing: "Without nosniff, a browser may guess a file's type and execute something that was never meant to run as script.",
  security_referrer_policy_missing: "Without a referrer policy, full URLs - which can contain private identifiers - are sent to every third-party resource the page loads.",
  security_server_header_discloses_version: "Publishing exact software versions tells an attacker precisely which known vulnerabilities to try first.",
  missing_viewport: "Without a viewport tag, mobile browsers render the desktop layout zoomed out, so text is tiny and buttons are hard to hit.",
  viewport_not_responsive: "A viewport that is not set to the device width prevents the layout from adapting to the screen it is being viewed on.",
  zoom_disabled: "Blocking pinch-to-zoom removes the main way low-vision visitors make text readable.",
  fixed_width_layout: "Fixed widths wider than a phone screen force horizontal scrolling, which makes the page awkward to read and use on mobile.",
  small_mobile_text: "Text below roughly 12px is difficult to read on a phone without zooming.",
  no_mobile_tap_to_call: "On a phone, a number that is not a tel: link has to be memorised or copied by hand instead of tapped, and most people will not bother.",
  legacy_plugin_content: "Plugin-based content does not run in any modern browser, so that part of the page is simply blank for every visitor.",
  no_mobile_menu: "Without a mobile navigation pattern, the menu is often unusable at phone widths, cutting visitors off from the rest of the site.",
  minimal_navigation: "With very few navigation links, visitors have no obvious route from the homepage to the information they came for.",
  no_primary_cta_above_fold: "If there is no clear action near the top of the page, the visitors who are ready to act have to hunt for how to do it.",
  no_phone_cta: "A phone number that is not a clickable link adds friction at exactly the moment someone has decided to get in touch.",
  no_phone_on_site: "With no phone number anywhere on the site, an entire category of enquiry - the person who wants to speak to someone now - has nowhere to go.",
  phone_not_on_homepage: "A number only reachable via a subpage is missed by visitors who never leave the homepage.",
  no_contact_form: "A form captures enquiries from people who will not phone and do not want to open an email client - typically the majority of web visitors.",
  no_contact_page: "A contact page is the page visitors look for by default when they want to get in touch, and the one search engines expect to find.",
  no_booking_cta: "Without a booking option, every appointment has to be arranged by a back-and-forth the visitor has to start.",
  no_quote_cta: "A quote request is the natural next step for a service business, and its absence leaves interested visitors with no defined action.",
  no_email_cta: "Without a visible email option, visitors who prefer writing have no route to make contact.",
  no_email_on_site: "No published email address means one of the standard ways to reach a business is unavailable.",
  weak_cta_language: "Vague prompts like “click here” or “submit” do not tell a visitor what will happen, and convert less well than explicit actions.",
  no_testimonials: "Social proof from previous customers is one of the strongest influences on whether a new visitor decides to make contact.",
  reviews_not_structured: "Reviews marked up as structured data can appear as star ratings in search results; as plain text they cannot.",
  no_credentials: "Licences, insurance, accreditations and guarantees are what reassure a visitor that the business is legitimate and accountable.",
  no_portfolio: "Examples of previous work let a visitor judge quality for themselves rather than taking the site's word for it.",
  no_about_page: "An about page is where a visitor checks who they would actually be dealing with.",
  no_address: "A published address is a basic trust signal - its absence makes a business look harder to hold accountable.",
  no_opening_hours: "Without opening hours, a visitor cannot tell whether contacting the business now is worthwhile.",
  contact_hard_to_find: "If contact details are buried, interested visitors give up before finding them.",
  no_website_detected: "With no website, the business is invisible to everyone who searches before they buy, and has no page of its own to send anyone to.",
  social_profile_only: "A social profile is rented space: its layout, reach and continued existence are controlled by the platform, not by the business.",
};

const CATEGORY_DISCLOSURE: Record<string, string> = {
  offpage: "backlink count, referring domains and domain-authority-style scores require a paid third-party index (e.g. Ahrefs, Moz, Majestic, SEMrush). None is configured for this audit, so none of that is estimated or fabricated here.",
  accessibility: "colour contrast requires a rendered page with computed styles and cannot be measured reliably from static HTML/CSS, so it is reported as not verified rather than guessed.",
  performance: "Core Web Vitals (LCP, CLS, INP) come from the Google PageSpeed Insights API. Without an API key configured, only a single server-side response-time measurement is available and no lab or field vitals are shown.",
  ux_conversion: "mobile findings are derived from the page's own markup and inline CSS, not from a rendered phone browser; external stylesheets were not downloaded.",
};

// ============================================================================
// Inline-SVG chart helpers
// ============================================================================

function svgRing(score: number | null, size = 188, stroke = 15, g1 = "#22d3ee", g2 = "#3b82f6", uid = "ring"): string {
  const r = size / 2 - stroke - 4;
  const cx = size / 2;
  const cy = size / 2;
  const circ = 2 * Math.PI * r;
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score));
  const dash = (circ * pct) / 100;
  const label = score === null ? "—" : String(score);
  return (
    `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="Overall score ${label} out of 100">` +
    `<defs><linearGradient id="${uid}" x1="0%" y1="0%" x2="100%" y2="100%">` +
    `<stop offset="0%" stop-color="${g1}"/><stop offset="100%" stop-color="${g2}"/></linearGradient></defs>` +
    `<circle cx="${cx}" cy="${cy}" r="${r.toFixed(1)}" fill="none" stroke="rgba(148,178,255,.10)" stroke-width="${stroke}"/>` +
    `<circle cx="${cx}" cy="${cy}" r="${r.toFixed(1)}" fill="none" stroke="url(#${uid})" stroke-width="${stroke}" ` +
    `stroke-dasharray="${dash.toFixed(2)} ${circ.toFixed(2)}" stroke-linecap="round" transform="rotate(-90 ${cx} ${cy})"/>` +
    `<text x="${cx}" y="${cy + 4}" text-anchor="middle" fill="${g2}" font-family="Space Grotesk,Segoe UI,sans-serif" font-weight="700" font-size="${Math.round(size * 0.28)}">${label}</text>` +
    `<text x="${cx}" y="${cy + Math.round(size * 0.19)}" text-anchor="middle" fill="#6b7593" font-family="JetBrains Mono,monospace" font-size="${Math.round(size * 0.068)}">/ 100</text>` +
    `</svg>`
  );
}

function svgDonut(segments: { value: number; color: string }[], size = 148, stroke = 19, centerLabel = "", centerSub = ""): string {
  const total = segments.reduce((n, s) => n + Math.max(0, Math.floor(s.value || 0)), 0);
  const r = size / 2 - stroke / 2 - 3;
  const cx = size / 2;
  const cy = size / 2;
  const circ = 2 * Math.PI * r;
  let head =
    `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${esc(centerSub || "distribution")} chart">` +
    `<circle cx="${cx}" cy="${cy}" r="${r.toFixed(1)}" fill="none" stroke="rgba(148,178,255,.09)" stroke-width="${stroke}"/>`;
  let body = "";
  if (total > 0) {
    let offset = 0;
    for (const s of segments) {
      const v = Math.max(0, Math.floor(s.value || 0));
      if (!v) continue;
      const dash = circ * (v / total);
      body += `<circle cx="${cx}" cy="${cy}" r="${r.toFixed(1)}" fill="none" stroke="${s.color}" stroke-width="${stroke}" stroke-dasharray="${dash.toFixed(2)} ${circ.toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"/>`;
      offset += dash;
    }
  }
  const label = centerLabel !== "" ? centerLabel : String(total);
  let text = `<text x="${cx}" y="${cy - 1}" text-anchor="middle" fill="#f4f7ff" font-family="Space Grotesk,Segoe UI,sans-serif" font-weight="700" font-size="${Math.round(size * 0.185)}">${esc(label)}</text>`;
  if (centerSub) {
    text += `<text x="${cx}" y="${cy + Math.round(size * 0.13)}" text-anchor="middle" fill="#6b7593" font-family="JetBrains Mono,monospace" font-size="${Math.round(size * 0.068)}">${esc(centerSub)}</text>`;
  }
  return head + body + text + "</svg>";
}

// ============================================================================
// Render
// ============================================================================

export interface ReportContext {
  business: { name: string; location: string; category: string };
  audit: {
    website: string;
    score: number | null;
    opportunity_tier: string;
    technical: any; mobile: any; conversion: any;
  };
  problems: any[];
  recommendations: { problem_code: string; recommendation: string }[];
  contacts: { label: string; value: string; status: string; pill: string }[];
  pages: { type: string; url: string; status: string | number }[];
  generator: string;
  scorecard?: Scorecard;
  legacyFindings: Finding[];
  extraFindings: Finding[];
  extraFacts: Record<string, any>;
  priorities: PriorityRow[];
  executiveSummary?: ExecutiveSummary;
}

export function renderReport(ctx: ReportContext): string {
  const recByCode = new Map(ctx.recommendations.map((r) => [r.problem_code, r.recommendation]));
  const enriched = ctx.problems.map((p) => {
    const sev = p.severity in SEVERITY_ORDER ? p.severity : "low";
    return {
      ...p, severity: sev, severity_badge: SEVERITY_BADGE[sev] ?? "LOW", badge_class: BADGE_CLASS[sev] ?? "low",
      recommendation: recByCode.get(p.code) || "", evidence_rows: evidenceRows(p.evidence || {}),
    };
  });

  const tech = ctx.audit.technical || {};
  const mob = ctx.audit.mobile || {};
  const conv = ctx.audit.conversion || {};
  const perf = tech.pagespeed || {};
  const extra = ctx.extraFacts || {};

  const measured: { label: string; value: string }[] = [];
  const add = (label: string, value: unknown) => measured.push({ label, value: value === null || value === undefined || value === "" ? "—" : String(value) });
  add("HTTP status", tech.http_status);
  add("Served over HTTPS", fmtBool(tech.is_https));
  add("Homepage response time", tech.response_ms !== null && tech.response_ms !== undefined ? `${tech.response_ms} ms` : null);
  add("Pages crawled", tech.pages_crawled);
  add("Mobile viewport tag", fmtBool(mob.has_viewport, "Present", "Missing"));
  add("Tap-to-call on homepage", fmtBool(mob.tap_to_call_on_homepage, "Present", "Not found"));
  add("Contact form detected", fmtBool(conv.has_contact_form, "Yes", "Not found"));
  add("Booking option detected", fmtBool(conv.has_booking_cta, "Yes", "Not found"));
  add("Page title", tech.title || "Missing");
  add("Meta description", (tech.meta_description || "Missing").slice(0, 160));
  add("H1 headings", tech.h1_count);
  add("XML sitemap", fmtBool(tech.sitemap_found, "Found", "Not found"));
  if (tech.alt_coverage !== null && tech.alt_coverage !== undefined) add("Image alt coverage", `${Math.floor(tech.alt_coverage * 100)}% of ${tech.images_total || 0} images`);
  if (tech.links_checked) add("Internal links checked", `${tech.links_checked} (${(tech.broken_links || []).length} broken)`);
  if (perf.measured) {
    add("Google PageSpeed", `${perf.performance_score}/100 (${perf.strategy})`);
    if (perf.lcp_s !== null && perf.lcp_s !== undefined) add("Largest Contentful Paint", `${perf.lcp_s} s`);
  }

  let methodNote = "Technical and conversion findings come from server-side HTTP requests and HTML parsing. Mobile findings are derived from the page's own markup and inline CSS, not from a rendered phone browser; external stylesheets were not downloaded. ";
  methodNote += perf.measured
    ? "Performance figures come from the Google PageSpeed Insights API."
    : "Response time is a single server-side measurement from the machine that ran this audit, not a full performance profile.";

  const findingsCtx = buildFindingsContext(ctx.legacyFindings, ctx.extraFindings);
  const prioritiesCtx = ctx.priorities.map((p) => {
    const sev = p.severity in SEVERITY_ORDER ? p.severity : "low";
    return { ...p, severity_label: SEVERITY_LABEL[sev] ?? "Note", severity_badge: SEVERITY_BADGE[sev] ?? "LOW", badge_class: BADGE_CLASS[sev] ?? "low" };
  });

  const categorySections: any[] = [];
  const sc = ctx.scorecard;
  let byCat: Record<string, any[]> = {};
  let catRowByKey: Record<string, any> = {};
  if (sc) {
    byCat = Object.fromEntries(AUDIT_CATEGORIES.map((c) => [c, [] as any[]]));
    for (const row of findingsCtx.all) (byCat[row.category] ||= []).push(row);
    const checksByCat: Record<string, any[]> = Object.fromEntries(AUDIT_CATEGORIES.map((c) => [c, [] as any[]]));
    for (const chk of sc.checks.checks) (checksByCat[chk.category] ||= []).push(chk);
    catRowByKey = Object.fromEntries(sc.categories.map((c) => [c.category, c]));

    AUDIT_CATEGORIES.forEach((c, i) => {
      const row = catRowByKey[c] || {};
      const applicable = row.applicable !== false;
      const score = row.score ?? null;
      const checksHere = checksByCat[c] || [];
      const catFindings = byCat[c] || [];
      const worst = catFindings.length ? Math.min(...catFindings.map((fr) => SEVERITY_ORDER[fr.severity] ?? 2)) : 3;
      categorySections.push({
        key: c, number: String(i + 1).padStart(2, "0"), label: AUDIT_CATEGORY_LABELS[c] ?? c,
        icon: CATEGORY_ICON[c] || "•", why_it_matters: AUDIT_CATEGORY_WHY[c] || "",
        applicable, not_applicable_reason: row.not_applicable_reason || "", score, band: band(score, applicable),
        findings: catFindings, count_class: ({ 0: "critical", 1: "high", 2: "medium" } as any)[worst] ?? "pass",
        passed_checks: checksHere.filter((x) => x.status === "pass"),
        not_verified_checks: checksHere.filter((x) => x.status === "not_verified"),
        signals: applicable ? categorySignals(c, tech, mob, conv, extra) : [],
        disclosure: CATEGORY_DISCLOSURE[c] || "",
      });
    });
  }

  let scorecardCtx: any = {};
  let checksCtx: any = { passed_count: 0, warning_count: 0, failed_count: 0, not_verified_count: 0, not_applicable_count: 0, total_checked: 0, total_catalogued: 0 };
  let priorityCounts = { P1: 0, P2: 0, P3: 0 };
  let donutSeverity = "", donutStatus = "", donutPriority = "", ringOverall = "";
  let overallBand = band(null);
  let gradeStr = "";
  let totalIssues = 0;
  let findingsPerCategory: any[] = [];
  let signals: Signal[] = [];
  let checkBar = { total: 0, pass_pct: 0, warn_pct: 0, fail_pct: 0 };

  if (sc) {
    scorecardCtx = { ...sc, categories: sc.categories.map((row) => ({ ...row, band: band(row.score, row.applicable !== false), icon: CATEGORY_ICON[row.category] || "•" })) };
    checksCtx = { ...checksCtx, ...sc.checks };
    overallBand = band(sc.overall_score);
    gradeStr = grade(sc.overall_score);

    for (const fnd of [...ctx.legacyFindings, ...ctx.extraFindings]) {
      if (fnd.deduction > 0) {
        const p = priorityFor(fnd);
        (priorityCounts as any)[p] = ((priorityCounts as any)[p] || 0) + 1;
      }
    }

    const sevCounts = sc.severity_counts;
    totalIssues = sevCounts.high + sevCounts.medium + sevCounts.low;

    ringOverall = svgRing(sc.overall_score, 188, 15, overallBand.g1, overallBand.g2, "overallRing");
    donutSeverity = svgDonut([{ value: sevCounts.high, color: "#fb5b6f" }, { value: sevCounts.medium, color: "#fb923c" }, { value: sevCounts.low, color: "#fbbf24" }], undefined, undefined, "", "ISSUES");
    donutStatus = svgDonut(
      [
        { value: checksCtx.passed_count, color: "#34d399" }, { value: checksCtx.warning_count, color: "#fbbf24" },
        { value: checksCtx.failed_count, color: "#fb5b6f" }, { value: checksCtx.not_verified_count + checksCtx.not_applicable_count, color: "#55607d" },
      ], undefined, undefined, "", "CHECKS",
    );
    donutPriority = svgDonut([{ value: priorityCounts.P1, color: "#fb5b6f" }, { value: priorityCounts.P2, color: "#fb923c" }, { value: priorityCounts.P3, color: "#3b82f6" }], undefined, undefined, "", "ACTIONS");

    const maxCount = Math.max(0, ...AUDIT_CATEGORIES.map((c) => (byCat[c] || []).length));
    for (const c of AUDIT_CATEGORIES) {
      const n = (byCat[c] || []).length;
      const row = catRowByKey[c] || {};
      if (row.applicable === false) continue;
      findingsPerCategory.push({
        label: AUDIT_CATEGORY_LABELS[c] ?? c, count: n, pct: maxCount ? Math.round((100 * n) / maxCount) : 0,
        g1: n && n >= Math.max(1, maxCount * 0.66) ? "#fb5b6f" : n ? "#fb923c" : "#34d399", g2: n ? "#fb923c" : "#22d3ee",
      });
    }

    signals = headlineSignals(tech, perf, extra);

    const evaluated = checksCtx.passed_count + checksCtx.warning_count + checksCtx.failed_count;
    checkBar = {
      total: evaluated,
      pass_pct: evaluated ? Math.round((100 * checksCtx.passed_count) / evaluated * 10) / 10 : 0,
      warn_pct: evaluated ? Math.round((100 * checksCtx.warning_count) / evaluated * 10) / 10 : 0,
      fail_pct: evaluated ? Math.round((100 * checksCtx.failed_count) / evaluated * 10) / 10 : 0,
    };
  }

  const coverMeta: { label: string; value: string }[] = [{ label: "Audit date", value: fmtDate(new Date()) }];
  if (tech.pages_crawled) coverMeta.push({ label: "Pages scanned", value: String(tech.pages_crawled) });
  if (checksCtx.total_catalogued) coverMeta.push({ label: "Checks run", value: String(checksCtx.total_catalogued) });
  if (ctx.business.location) coverMeta.push({ label: "Location", value: ctx.business.location });
  if (ctx.business.category) coverMeta.push({ label: "Category", value: ctx.business.category });
  if (ctx.generator) coverMeta.push({ label: "Prepared by", value: ctx.generator });

  return buildDocument({
    business: ctx.business, audit: ctx.audit, problems: enriched, contacts: ctx.contacts, pages: ctx.pages,
    measured, methodNote, coverMeta, generatedAt: fmtDateTime(new Date()), generator: ctx.generator,
    scorecard: scorecardCtx, checks: checksCtx, checkBar, findings: findingsCtx, findingsPerCategory, signals,
    categorySections, priorities: prioritiesCtx, executiveSummary: ctx.executiveSummary || ({} as ExecutiveSummary),
    overallBand, grade: gradeStr, totalIssues, priorityCounts, ringOverall, donutSeverity, donutStatus, donutPriority,
    hasScorecard: Boolean(sc),
  });
}

function fmtDate(d: Date): string {
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}
function fmtDateTime(d: Date): string {
  return `${fmtDate(d)} at ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}

function buildDocument(c: any): string {
  const scorecardBlock = c.hasScorecard ? buildScorecardBlocks(c) : "";
  const categoryBlock = c.categorySections.length ? buildCategoryBlocks(c) : "";
  const fallbackBlock = !c.hasScorecard ? buildFallbackBlock(c) : "";

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Website Audit — ${esc(c.business.name)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>${REPORT_CSS(c.business.name)}</style>
</head>
<body>
<div class="doc">

  <div class="page">
    <header class="card cover">
      <div class="cover-left">
        <div class="eyebrow"><span class="dot"></span> Website Intelligence Report</div>
        <div class="biz-name">${esc(c.business.name)}</div>
        ${c.audit.website
          ? `<a class="biz-url" href="${esc(c.audit.website)}" rel="noopener nofollow">${esc(c.audit.website)}</a>`
          : `<div class="biz-url" style="color:var(--slate)">No website was available to audit</div>`}
        <div class="meta-row">
          ${c.coverMeta.map((m: any) => `<div class="meta-item"><div class="meta-label">${esc(m.label)}</div><div class="meta-val">${esc(m.value)}</div></div>`).join("")}
        </div>
      </div>
      <div class="cover-right">
        <div class="ring-wrap">${c.ringOverall}</div>
        <div class="verdict">
          <h3>Overall Website Health</h3>
          <p>${esc(c.executiveSummary.headline || "This website could not be fully audited.")}</p>
          ${c.grade ? `<span class="grade-pill" style="background:${c.overallBand.soft};border:1px solid ${c.overallBand.edge};color:${c.overallBand.fg}">GRADE ${esc(c.grade)} · ${esc(c.overallBand.label.toUpperCase())}</span>` : ""}
        </div>
      </div>
    </header>
    ${scorecardBlock}
  </div>

  ${categoryBlock}
  ${fallbackBlock}

  <div class="page">
    <div class="section-head">
      <div class="section-title"><span class="bar"></span>Appendix</div>
      <div class="section-sub">Method, raw measurements and scope</div>
    </div>
    <section class="card">
      <div class="flabel" style="margin-bottom:12px">What was measured</div>
      <div class="table-wrap"><table><tbody>
        ${c.measured.map((row: any) => `<tr><th style="width:40%">${esc(row.label)}</th><td>${esc(row.value)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="note" style="margin-top:14px">${esc(c.methodNote)}</p>
    </section>
    ${c.contacts.length ? `
    <section class="card">
      <div class="flabel" style="margin-bottom:12px">Contact options found on the site</div>
      <div class="sig-grid">
        ${c.contacts.map((ct: any) => `<div class="sig"><div class="k">${esc(ct.label)}</div><div class="v">${esc(ct.value)}${ct.status ? ` <span class="badge b-neutral">${esc(ct.status)}</span>` : ""}</div></div>`).join("")}
      </div>
      <p class="note" style="margin-top:12px">Listed here only if found publicly on the business's own website or supplied in the source data. Nothing was guessed or constructed.</p>
    </section>` : ""}
    ${c.pages.length ? `
    <section class="card">
      <div class="flabel" style="margin-bottom:12px">Pages reviewed — ${c.pages.length}</div>
      <div class="table-wrap"><table>
        <thead><tr><th>Type</th><th>URL</th><th style="width:78px">Status</th></tr></thead>
        <tbody>${c.pages.map((pg: any) => `<tr><td>${esc(pg.type)}</td><td><code>${esc(pg.url)}</code></td><td>${esc(pg.status)}</td></tr>`).join("")}</tbody>
      </table></div>
    </section>` : ""}
    <footer class="doc-footer">
      Audit generated ${esc(c.generatedAt)}${c.generator ? ` by ${esc(c.generator)}` : ""}.<br>
      Findings are limited to what could be observed from publicly accessible pages at that time.
      No performance, ranking, backlink, traffic, review-count or revenue claims are made beyond the
      measurements shown in this report. Checks that could not be measured are labelled
      “Not verified”; categories that do not apply to this site are labelled “Not Applicable” —
      neither is ever scored as if it had passed or failed.
    </footer>
  </div>

</div>
</body>
</html>`;
}

function buildScorecardBlocks(c: any): string {
  return `
    <div class="kpi-row">
      <div class="kpi"><div class="n" style="color:var(--red)">${c.scorecard.severity_counts.high}</div><div class="l">Critical issues</div><div class="h">Fix first — actively costing visibility or trust</div></div>
      <div class="kpi"><div class="n" style="color:var(--orange)">${c.scorecard.severity_counts.medium}</div><div class="l">High priority</div><div class="h">Material impact, should be scheduled now</div></div>
      <div class="kpi"><div class="n" style="color:var(--amber)">${c.scorecard.severity_counts.low}</div><div class="l">Warnings</div><div class="h">Smaller gaps worth tidying up</div></div>
      <div class="kpi"><div class="n" style="color:var(--green)">${c.checks.passed_count}</div><div class="l">Checks passed</div><div class="h">Of ${c.checks.total_checked} checks that could be evaluated</div></div>
      <div class="kpi"><div class="n" style="color:var(--slate)">${c.checks.not_verified_count}</div><div class="l">Not verified</div><div class="h">Needs a paid data source or a rendered browser</div></div>
      <div class="kpi"><div class="n" style="color:var(--slate)">${c.checks.not_applicable_count}</div><div class="l">Not applicable</div><div class="h">Does not apply to this type of website</div></div>
    </div>

    <div class="section-head"><div class="section-title"><span class="bar"></span>Visual Scorecard</div><div class="section-sub">${c.scorecard.categories.length} categories · weighted model · higher is better</div></div>
    <div class="scorecard-grid">
      ${c.scorecard.categories.map((cat: any) => `
      <div class="score-card">
        <div class="sc-top">
          <div class="sc-icon">${cat.icon}</div>
          ${cat.applicable && cat.score !== null ? `<div class="sc-value" style="color:${cat.band.fg}">${cat.score}<small>/100</small></div>` : `<div class="sc-value" style="color:var(--slate);font-size:19px">N/A</div>`}
        </div>
        <div class="sc-name">${esc(cat.label)}</div>
        <div class="track">${cat.applicable && cat.score !== null
          ? `<span class="fill" style="width:${cat.score}%;background:linear-gradient(90deg,${cat.band.g1},${cat.band.g2})"></span>`
          : `<span class="fill" style="width:100%;background:rgba(148,178,255,.10)"></span>`}</div>
        <span class="tag" style="background:${cat.band.soft};color:${cat.band.fg}">${esc(cat.band.label)}</span>
      </div>`).join("")}
    </div>

    <div class="section-head"><div class="section-title"><span class="bar"></span>Executive summary</div><div class="section-sub">What this means for the business</div></div>
    <div class="lower-row">
      <section class="card stack">
        <div><div class="flabel">Business impact</div><p style="font-size:14px;color:var(--mid);line-height:1.65">${esc(c.executiveSummary.business_impact)}</p></div>
        <div class="check-grid">
          <div><div class="flabel">✓ What is working</div>
            ${c.executiveSummary.whats_working?.length
              ? `<ul style="margin:0;padding-left:17px;font-size:13px;color:var(--mid);line-height:1.8">${c.executiveSummary.whats_working.map((w: string) => `<li>${esc(w)}</li>`).join("")}</ul>`
              : `<p class="empty">No category currently scores in the “Good” range (85+).</p>`}
          </div>
          <div><div class="flabel">↑ Biggest opportunities</div>
            ${c.executiveSummary.biggest_opportunities?.length
              ? `<ul style="margin:0;padding-left:17px;font-size:13px;color:var(--mid);line-height:1.8">${c.executiveSummary.biggest_opportunities.map((o: string) => `<li>${esc(o)}</li>`).join("")}</ul>`
              : `<p class="empty">No applicable category scores below 70.</p>`}
          </div>
        </div>
        <div class="spacer"></div>
        <div>
          <div class="flabel">Checks evaluated — passed vs warning vs failed</div>
          <div class="stackbar">${c.checkBar.total ? `
            <span style="width:${c.checkBar.pass_pct}%;background:linear-gradient(90deg,#34d399,#22d3ee)"></span>
            <span style="width:${c.checkBar.warn_pct}%;background:linear-gradient(90deg,#f59e0b,#fbbf24)"></span>
            <span style="width:${c.checkBar.fail_pct}%;background:linear-gradient(90deg,#fb5b6f,#fb923c)"></span>` : ""}</div>
          <div class="stackbar-legend">
            <span><i style="background:#34d399"></i>Passed <b>${c.checks.passed_count}</b></span>
            <span><i style="background:#fbbf24"></i>Warning <b>${c.checks.warning_count}</b></span>
            <span><i style="background:#fb5b6f"></i>Failed <b>${c.checks.failed_count}</b></span>
            <span><i style="background:#55607d"></i>Not verified / not applicable <b>${c.checks.not_verified_count + c.checks.not_applicable_count}</b></span>
          </div>
        </div>
      </section>
      <section class="card">
        <div class="flabel" style="margin-bottom:11px">→ Recommended next steps</div>
        ${c.executiveSummary.next_steps?.length
          ? `<div class="prio-list">${c.executiveSummary.next_steps.map((n: string, i: number) => `<div class="prio-item" style="padding:11px 13px"><div class="prio-num">${i + 1}</div><div class="prio-detail" style="color:var(--hi);padding-top:3px">${esc(n)}</div></div>`).join("")}</div>`
          : `<p class="empty">No outstanding actions were produced by this audit.</p>`}
      </section>
    </div>

    <div class="section-head"><div class="section-title"><span class="bar"></span>Top 5 priorities</div><div class="section-sub">Ranked by measured severity and impact</div></div>
    <section class="card">
      ${c.priorities.length ? `<div class="prio-list">${c.priorities.map((p: any) => `
        <div class="prio-item">
          <div class="prio-num">${p.rank}</div>
          <div>
            <div class="prio-head">
              <span class="badge b-${p.badge_class}">${p.severity_badge}</span>
              <span class="badge b-neutral">${esc(p.priority)}</span>
              <span class="badge b-cat">${esc(p.category_label)}</span>
            </div>
            <div class="prio-title">${esc(p.title)}</div>
            <div class="prio-detail">${esc(p.detail)}</div>
            ${p.recommendation ? `<div class="prio-action"><b>Recommended action:</b> ${esc(p.recommendation)}</div>` : ""}
          </div>
        </div>`).join("")}</div>` : `<p class="empty">No priority issues were detected within the checks this audit performs. No issues have been invented to fill this section.</p>`}
    </section>
  </div>

  <div class="page">
    <div class="section-head"><div class="section-title"><span class="bar"></span>Visual analytics</div><div class="section-sub">${c.checks.total_catalogued} checks evaluated · ${c.findings.all.length} findings</div></div>
    <div class="charts-row">
      <div class="chart-card">
        <div class="chart-title">Category scores<span>Weighted 0–100 · higher is better</span></div>
        <div class="bar-chart">${c.scorecard.categories.map((cat: any) => `
          <div class="bar-row">
            <div class="lbl">${esc(cat.label)}</div>
            <div class="track">${cat.applicable && cat.score !== null
              ? `<span class="fill" style="width:${cat.score}%;background:linear-gradient(90deg,${cat.band.g1},${cat.band.g2})"></span>`
              : `<span class="fill" style="width:100%;background:rgba(148,178,255,.09)"></span>`}</div>
            ${cat.applicable && cat.score !== null ? `<div class="val">${cat.score}</div>` : `<div class="val na">N/A</div>`}
          </div>`).join("")}</div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Issues by severity<span>${c.totalIssues} finding(s) with a measured impact</span></div>
        <div class="donut-wrap">${c.donutSeverity}
          <div class="donut-legend">
            <div class="legend-item"><span class="legend-dot" style="background:#fb5b6f"></span>Critical<b>${c.scorecard.severity_counts.high}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fb923c"></span>High<b>${c.scorecard.severity_counts.medium}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fbbf24"></span>Medium<b>${c.scorecard.severity_counts.low}</b></div>
          </div>
        </div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Checks by status<span>Passed vs warning vs failed</span></div>
        <div class="donut-wrap">${c.donutStatus}
          <div class="donut-legend">
            <div class="legend-item"><span class="legend-dot" style="background:#34d399"></span>Passed<b>${c.checks.passed_count}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fbbf24"></span>Warning<b>${c.checks.warning_count}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fb5b6f"></span>Failed<b>${c.checks.failed_count}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#55607d"></span>N/V or N/A<b>${c.checks.not_verified_count + c.checks.not_applicable_count}</b></div>
          </div>
        </div>
      </div>
    </div>
    <div class="charts-row two">
      <div class="chart-card">
        <div class="chart-title">Priority distribution<span>P1 fix now · P2 next · P3 backlog</span></div>
        <div class="donut-wrap">${c.donutPriority}
          <div class="donut-legend">
            <div class="legend-item"><span class="legend-dot" style="background:#fb5b6f"></span>P1 — fix now<b>${c.priorityCounts.P1}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#fb923c"></span>P2 — next<b>${c.priorityCounts.P2}</b></div>
            <div class="legend-item"><span class="legend-dot" style="background:#3b82f6"></span>P3 — backlog<b>${c.priorityCounts.P3}</b></div>
          </div>
        </div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Findings per category<span>Where the measured problems actually are</span></div>
        <div class="bar-chart">${c.findingsPerCategory.map((row: any) => `
          <div class="bar-row"><div class="lbl">${esc(row.label)}</div><div class="track"><span class="fill" style="width:${row.pct}%;background:linear-gradient(90deg,${row.g1},${row.g2})"></span></div><div class="val">${row.count}</div></div>`).join("")}</div>
      </div>
    </div>

    <div class="section-head"><div class="section-title"><span class="bar"></span>Verified signals</div><div class="section-sub">Measured directly from this website — nothing estimated</div></div>
    <section class="card">
      <div class="sig-grid">${c.signals.map((s: Signal) => `<div class="sig"><div class="k">${esc(s.label)}</div><div class="v ${s.na ? "na" : ""}">${esc(s.value)}</div>${s.why ? `<div class="why">${esc(s.why)}</div>` : ""}</div>`).join("")}</div>
      <div class="disclosure" style="margin-top:14px"><b>Not Verified — external verification unavailable.</b>
        Backlinks, referring domains, domain-authority-style scores, organic traffic, keyword rankings
        and search volume all require a paid third-party index. None is configured for this audit, so
        none of those figures appear anywhere in this report — they are not estimated, modelled or guessed.
      </div>
    </section>
  </div>`;
}

function buildCategoryBlocks(c: any): string {
  const index = `
  <div class="page">
    <div class="section-head"><div class="section-title"><span class="bar"></span>Issues &amp; Recommendations</div><div class="section-sub">Every detected issue · what · why · how · evidence · priority</div></div>
    <section class="card">
      <div class="note" style="color:var(--mid)">
        Each of the ${c.categorySections.length} sections that follow covers one audit category. Every
        finding lists <b style="color:var(--hi)">What we found</b>, <b style="color:var(--hi)">Why it matters</b>,
        <b style="color:var(--hi)">How to fix</b> it, the <b style="color:var(--hi)">Evidence</b> that
        triggered it, and a <b style="color:var(--hi)">Priority</b>. Checks that passed are listed too, so a
        clean category is visibly clean rather than simply absent. Anything the engine could not measure is
        labelled <b style="color:var(--hi)">Not verified</b> with the reason, and anything that does not apply
        to this website is labelled <b style="color:var(--hi)">Not Applicable</b> with the reason.
      </div>
      <div class="cat-index">${c.categorySections.map((cat: any) => `
        <div class="check-row"><span class="badge b-neutral">${cat.number}</span><span class="label">${esc(cat.label)}</span>
          ${cat.applicable ? `<span class="badge b-${cat.count_class}">${cat.findings.length}</span>` : `<span class="badge b-neutral">N/A</span>`}</div>`).join("")}</div>
    </section>
  </div>`;

  const sections = c.categorySections.map((cat: any) => `
  <div class="page" id="cat-${cat.key}">
    <section class="card stack">
      <div class="cat-header">
        <div class="sec-num">${cat.number}</div>
        <h2>${esc(cat.label)}</h2>
        <div class="cat-score">${cat.applicable && cat.score !== null
          ? `<span class="n" style="color:${cat.band.fg}">${cat.score}<small style="font-size:13px;color:var(--low)">/100</small></span><span class="tag" style="background:${cat.band.soft};color:${cat.band.fg}">${esc(cat.band.label)}</span>`
          : `<span class="tag" style="background:rgba(148,178,255,.07);color:var(--slate)">Not Applicable</span>`}</div>
      </div>
      <p class="cat-why">${esc(cat.why_it_matters)}</p>
      ${!cat.applicable ? `<div class="banner na"><b>Not applicable to this website.</b><br>${esc(cat.not_applicable_reason)}</div>` : `
      ${cat.findings.length ? `
      <div>
        <div class="flabel">What needs improvement — ${cat.findings.length} finding${cat.findings.length !== 1 ? "s" : ""}</div>
        <div class="findings-list">${cat.findings.map((p: any) => `
          <article class="finding ${p.severity}">
            <div class="finding-head">
              <span class="badge b-${p.badge_class}">${p.severity_badge}</span>
              <span class="badge b-neutral">${esc(p.priority)}</span>
              <span class="badge b-code">${esc(p.code)}</span>
              ${p.deduction ? `<span class="badge b-neutral">−${p.deduction} pts</span>` : ""}
              <div class="finding-title">${esc(p.title)}</div>
            </div>
            <div class="field"><div class="flabel">What we found</div><p>${esc(p.detail)}</p></div>
            ${p.why_it_matters ? `<div class="field"><div class="flabel">Why it matters</div><p>${esc(p.why_it_matters)}</p></div>` : ""}
            ${p.recommendation ? `<div class="field fix"><div class="flabel">How to fix</div><p>${esc(p.recommendation)}</p></div>` : ""}
            ${p.evidence_rows.length ? `<div class="field"><div class="flabel">Evidence — measured on this site</div><div class="ev-list">${p.evidence_rows.map((e: EvidenceRow) => `<div class="ev-row"><span class="k">${esc(e.k)}</span><span class="v">${esc(e.v)}</span></div>`).join("")}</div></div>` : ""}
          </article>`).join("")}</div>
      </div>` : `<div class="banner"><b>No evidence-backed issues were detected in this category.</b><br>Nothing has been invented to fill this section.</div>`}
      ${cat.passed_checks.length ? `
      <div><div class="flabel">Passed — ${cat.passed_checks.length} check${cat.passed_checks.length !== 1 ? "s" : ""}</div>
        <div class="check-grid">${cat.passed_checks.map((chk: any) => `<div class="check-row"><span class="icon" style="background:var(--green)">✓</span><span class="label">${esc(chk.label)}</span><span class="badge b-pass">PASS</span></div>`).join("")}</div>
      </div>` : ""}
      ${cat.not_verified_checks.length ? `
      <div><div class="flabel">Not verified — could not be measured by this engine</div>
        <div class="check-grid one">${cat.not_verified_checks.map((chk: any) => `<div class="check-row"><span class="icon" style="background:var(--slate)">?</span><span class="label">${esc(chk.label)} <span class="why">— ${esc(chk.detail)}</span></span><span class="badge b-neutral">NOT VERIFIED</span></div>`).join("")}</div>
      </div>` : ""}
      ${cat.signals.length ? `
      <div><div class="flabel">Technical context for this category</div>
        <div class="sig-grid">${cat.signals.map((s: Signal) => `<div class="sig"><div class="k">${esc(s.label)}</div><div class="v ${s.na ? "na" : ""}">${esc(s.value)}</div>${s.why ? `<div class="why">${esc(s.why)}</div>` : ""}</div>`).join("")}</div>
      </div>` : ""}
      ${cat.disclosure ? `<div class="disclosure"><b>Not verified:</b> ${esc(cat.disclosure)}</div>` : ""}
      `}
    </section>
  </div>`).join("");

  return index + sections;
}

function buildFallbackBlock(c: any): string {
  return `
  <div class="page">
    <section class="card">
      <div class="flabel">Audit status</div>
      <p style="font-size:14px;color:var(--mid);line-height:1.65;margin-top:6px">${esc(c.audit.audit_error || "This website could not be fully audited. What was checked is listed below.")}</p>
    </section>
    <section class="card">
      <div class="section-title" style="font-size:17px;margin-bottom:14px"><span class="bar"></span>Detected problems${c.problems.length ? ` — ${c.problems.length}` : ""}</div>
      ${c.problems.length ? `<div class="findings-list">${c.problems.map((p: any) => `
        <article class="finding ${p.severity}">
          <div class="finding-head"><span class="badge b-${p.badge_class}">${p.severity_badge}</span><div class="finding-title">${esc(p.title)}</div></div>
          <div class="field"><div class="flabel">What we found</div><p>${esc(p.detail)}</p></div>
          ${p.recommendation ? `<div class="field fix"><div class="flabel">How to fix</div><p>${esc(p.recommendation)}</p></div>` : ""}
          ${p.evidence_rows?.length ? `<div class="field"><div class="flabel">Evidence</div><div class="ev-list">${p.evidence_rows.map((e: EvidenceRow) => `<div class="ev-row"><span class="k">${esc(e.k)}</span><span class="v">${esc(e.v)}</span></div>`).join("")}</div></div>` : ""}
        </article>`).join("")}</div>` : `<p class="empty">No evidence-backed problems were detected within the checks this audit performs. No issues have been invented to fill this section.</p>`}
    </section>
  </div>`;
}

function REPORT_CSS(businessName: string): string {
  return `
  :root{
    --void:#05070d; --navy:#0a0f1e; --card:#0e1526; --card-2:#111a30; --raise:rgba(255,255,255,.022);
    --line:rgba(148,178,255,.12); --line-bright:rgba(148,178,255,.26);
    --blue:#3b82f6; --cyan:#22d3ee; --violet:#8b5cf6;
    --green:#34d399; --amber:#fbbf24; --orange:#fb923c; --red:#fb5b6f; --slate:#7f8bad;
    --hi:#f4f7ff; --mid:#a9b4d0; --low:#6b7593;
    --font-display:'Space Grotesk','Segoe UI',system-ui,sans-serif;
    --font-body:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
    --font-mono:'JetBrains Mono','SF Mono',ui-monospace,Consolas,'Courier New',monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{-webkit-text-size-adjust:100%}
  body{
    background:
      radial-gradient(1200px 620px at 10% -12%, rgba(59,130,246,.16), transparent 60%),
      radial-gradient(1000px 520px at 100% 0%, rgba(34,211,238,.10), transparent 55%),
      radial-gradient(900px 560px at 50% 108%, rgba(139,92,246,.10), transparent 60%),
      var(--void);
    background-attachment:fixed;
    color:var(--hi); font-family:var(--font-body); font-size:15px; line-height:1.6;
    -webkit-font-smoothing:antialiased; padding:26px 20px 56px;
  }
  .doc{max-width:1320px;margin:0 auto;display:flex;flex-direction:column;gap:16px}
  .mono{font-family:var(--font-mono)}
  .display{font-family:var(--font-display)}
  a{color:var(--cyan)}
  .card{background:linear-gradient(160deg, var(--card) 0%, var(--navy) 100%);border:1px solid var(--line); border-radius:18px; padding:24px 26px;}
  .page{break-before:page}
  .page:first-child{break-before:auto}
  .page{display:flex;flex-direction:column;gap:16px}
  .section-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;margin:12px 4px 0;flex-wrap:wrap}
  .section-title{font-family:var(--font-display);font-weight:700;font-size:20px;letter-spacing:-.01em;display:flex;align-items:center;gap:11px}
  .section-title .bar{width:4px;height:19px;border-radius:3px;background:linear-gradient(180deg,var(--cyan),var(--blue));flex:0 0 auto}
  .section-sub{font-family:var(--font-mono);font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--low)}
  .eyebrow{display:inline-flex;align-items:center;gap:8px;font-family:var(--font-mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--cyan);width:fit-content;background:rgba(34,211,238,.08);border:1px solid rgba(34,211,238,.28);padding:5px 12px;border-radius:100px}
  .eyebrow .dot{width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan)}
  .cover{display:grid;grid-template-columns:1.45fr 1fr;gap:22px;position:relative;overflow:hidden;border-radius:20px;padding:30px 34px}
  .cover::before{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(520px 280px at 92% 8%, rgba(34,211,238,.14), transparent 70%)}
  .cover-left{display:flex;flex-direction:column;justify-content:center;gap:11px;position:relative;z-index:1}
  .biz-name{font-family:var(--font-display);font-weight:700;font-size:36px;letter-spacing:-.02em;line-height:1.06;word-break:break-word}
  .biz-url{font-family:var(--font-mono);font-size:14.5px;color:var(--cyan);word-break:break-all}
  .meta-row{display:flex;gap:26px;flex-wrap:wrap;margin-top:8px}
  .meta-item{display:flex;flex-direction:column;gap:3px}
  .meta-label{font-family:var(--font-mono);font-size:10px;letter-spacing:.11em;text-transform:uppercase;color:var(--low)}
  .meta-val{font-size:14px;font-weight:600;color:var(--hi)}
  .cover-right{display:flex;align-items:center;justify-content:center;gap:22px;position:relative;z-index:1;flex-wrap:wrap}
  .ring-wrap{position:relative;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
  .ring-wrap svg{filter:drop-shadow(0 0 20px rgba(59,130,246,.42))}
  .verdict{display:flex;flex-direction:column;gap:9px;max-width:230px}
  .verdict h3{font-family:var(--font-display);font-size:15px;font-weight:600}
  .verdict p{font-size:13px;color:var(--mid);line-height:1.55}
  .grade-pill{display:inline-flex;align-items:center;gap:7px;width:fit-content;padding:4px 11px;border-radius:100px;font-family:var(--font-mono);font-size:12px;font-weight:700}
  .kpi-row{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}
  .kpi{background:linear-gradient(160deg,var(--card) 0%,var(--navy) 100%);border:1px solid var(--line);border-radius:14px;padding:15px 16px;display:flex;flex-direction:column;gap:5px}
  .kpi .n{font-family:var(--font-display);font-weight:700;font-size:30px;line-height:1;letter-spacing:-.02em}
  .kpi .l{font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--low)}
  .kpi .h{font-size:11.5px;color:var(--mid);line-height:1.4}
  .scorecard-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:13px}
  .score-card{background:linear-gradient(160deg,var(--card) 0%,var(--navy) 100%);border:1px solid var(--line);border-radius:16px;padding:17px 18px 15px;display:flex;flex-direction:column;gap:10px}
  .sc-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
  .sc-icon{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px;background:rgba(59,130,246,.10);border:1px solid rgba(59,130,246,.25);flex:0 0 auto}
  .sc-value{font-family:var(--font-display);font-weight:700;font-size:27px;letter-spacing:-.02em;line-height:1}
  .sc-value small{font-size:12px;font-weight:500;color:var(--low);letter-spacing:0}
  .sc-name{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--mid)}
  .track{width:100%;height:6px;border-radius:6px;background:rgba(255,255,255,.06);overflow:hidden}
  .track .fill{height:100%;border-radius:6px;display:block}
  .tag{font-family:var(--font-mono);font-size:10.5px;font-weight:500;padding:3px 9px;border-radius:100px;width:fit-content;letter-spacing:.03em}
  .charts-row{display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:13px}
  .charts-row.two{grid-template-columns:1fr 1.25fr}
  .chart-card{background:linear-gradient(160deg,var(--card) 0%,var(--navy) 100%);border:1px solid var(--line);border-radius:16px;padding:19px 21px;display:flex;flex-direction:column;gap:13px}
  .chart-title{font-family:var(--font-display);font-size:14.5px;font-weight:700}
  .chart-title span{display:block;margin-top:3px;font-family:var(--font-mono);font-size:11px;font-weight:400;color:var(--low);letter-spacing:.02em}
  .bar-chart{display:flex;flex-direction:column;gap:9px}
  .bar-row{display:grid;grid-template-columns:118px 1fr 38px;align-items:center;gap:11px}
  .bar-row .lbl{font-size:11.5px;font-weight:600;color:var(--mid)}
  .bar-row .val{font-family:var(--font-mono);font-size:12px;color:var(--hi);text-align:right}
  .bar-row .val.na{color:var(--low);font-size:10.5px}
  .donut-wrap{display:flex;align-items:center;gap:16px;flex:1;flex-wrap:wrap}
  .donut-legend{display:flex;flex-direction:column;gap:8px;min-width:130px;flex:1}
  .legend-item{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--mid)}
  .legend-dot{width:9px;height:9px;border-radius:3px;flex:0 0 auto}
  .legend-item b{margin-left:auto;padding-left:12px;color:var(--hi);font-family:var(--font-mono);font-weight:500}
  .prio-list{display:flex;flex-direction:column;gap:11px}
  .prio-item{display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:start;background:var(--raise);border:1px solid var(--line);border-radius:13px;padding:14px 16px}
  .prio-num{flex-shrink:0;width:28px;height:28px;border-radius:9px;background:linear-gradient(135deg,var(--blue),var(--cyan));display:flex;align-items:center;justify-content:center;font-family:var(--font-mono);font-weight:700;font-size:12.5px;color:#04101f;box-shadow:0 0 14px rgba(59,130,246,.35)}
  .prio-head{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-bottom:6px}
  .prio-title{font-weight:700;font-size:14px;color:var(--hi)}
  .prio-detail{font-size:12.5px;color:var(--mid);line-height:1.55}
  .prio-action{font-size:12.5px;color:var(--hi);line-height:1.55;margin-top:7px;background:rgba(34,211,238,.06);border-left:2px solid var(--cyan);border-radius:0 8px 8px 0;padding:8px 12px}
  .prio-action b{color:var(--cyan)}
  .badge{font-family:var(--font-mono);font-size:10px;font-weight:700;letter-spacing:.07em;padding:3px 8px;border-radius:6px;white-space:nowrap;text-transform:uppercase}
  .b-critical{background:rgba(251,91,111,.14);color:var(--red);border:1px solid rgba(251,91,111,.42)}
  .b-high{background:rgba(251,146,60,.13);color:var(--orange);border:1px solid rgba(251,146,60,.42)}
  .b-medium{background:rgba(251,191,36,.13);color:var(--amber);border:1px solid rgba(251,191,36,.40)}
  .b-low{background:rgba(59,130,246,.13);color:#7fb0ff;border:1px solid rgba(59,130,246,.40)}
  .b-pass{background:rgba(52,211,153,.12);color:var(--green);border:1px solid rgba(52,211,153,.38)}
  .b-neutral{background:rgba(148,178,255,.07);color:var(--slate);border:1px solid var(--line)}
  .b-cat{background:rgba(139,92,246,.12);color:#b79dff;border:1px solid rgba(139,92,246,.34);text-transform:none;letter-spacing:.02em}
  .b-code{background:rgba(255,255,255,.03);color:var(--low);border:1px solid var(--line);text-transform:none;letter-spacing:0;font-weight:500;white-space:normal;word-break:break-all}
  .cat-header{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  .sec-num{width:38px;height:38px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-family:var(--font-mono);font-weight:700;font-size:14px;color:#04101f;flex:0 0 auto;background:linear-gradient(135deg,var(--cyan),var(--blue));box-shadow:0 0 16px rgba(59,130,246,.3)}
  .cat-header h2{font-family:var(--font-display);font-size:21px;font-weight:700;letter-spacing:-.01em}
  .cat-score{margin-left:auto;display:flex;align-items:center;gap:10px}
  .cat-score .n{font-family:var(--font-display);font-weight:700;font-size:26px;letter-spacing:-.02em}
  .cat-why{font-size:13px;color:var(--mid);line-height:1.6;margin-top:2px}
  .flabel{font-family:var(--font-mono);font-size:10px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--low);margin-bottom:5px}
  .finding{background:var(--raise);border:1px solid var(--line);border-left-width:3px;border-radius:13px;padding:17px 19px;display:flex;flex-direction:column;gap:12px}
  .finding.high{border-left-color:var(--red)}
  .finding.medium{border-left-color:var(--orange)}
  .finding.low{border-left-color:var(--amber)}
  .finding-head{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .finding-title{font-family:var(--font-display);font-size:15.5px;font-weight:600;letter-spacing:-.01em;width:100%;line-height:1.35}
  .field p{font-size:13.5px;color:var(--mid);line-height:1.62}
  .field.fix{background:rgba(34,211,238,.05);border:1px solid rgba(34,211,238,.18);border-radius:10px;padding:12px 14px}
  .field.fix p{color:#cfeaf6}
  .field.fix .flabel{color:var(--cyan)}
  .ev-list{display:flex;flex-direction:column;gap:5px;background:rgba(0,0,0,.24);border:1px solid var(--line);border-radius:10px;padding:11px 13px}
  .ev-row{display:grid;grid-template-columns:minmax(110px,auto) 1fr;gap:12px;font-family:var(--font-mono);font-size:11.5px;line-height:1.5}
  .ev-row .k{color:var(--low);text-transform:uppercase;letter-spacing:.06em;font-size:10.5px;padding-top:1px}
  .ev-row .v{color:#c9d6f5;word-break:break-word}
  .findings-list{display:flex;flex-direction:column;gap:12px}
  .check-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
  .check-grid.one{grid-template-columns:1fr}
  .cat-index{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}
  .check-row{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:10px;background:var(--raise);border:1px solid var(--line);font-size:12.5px}
  .check-row .icon{width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#04101f;flex:0 0 auto}
  .check-row .label{color:var(--mid);flex:1}
  .check-row .why{color:var(--low);font-size:11.5px}
  .sig-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:10px}
  .sig{background:var(--raise);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:4px}
  .sig .k{font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--low)}
  .sig .v{font-size:13.5px;font-weight:600;color:var(--hi);word-break:break-word;line-height:1.45}
  .sig .v.na{color:var(--slate);font-weight:500}
  .sig .why{font-size:11.5px;color:var(--low);line-height:1.45}
  .doc > *, .page > *, .lower-row > *, .charts-row > *, .scorecard-grid > *, .kpi-row > *, .check-grid > *, .cat-index > *, .sig-grid > *, .bar-row > *, .donut-wrap > *, .prio-item > *, .finding > *{min-width:0}
  .table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  table{width:100%;min-width:420px;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:9px 11px;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-family:var(--font-mono);color:var(--low);font-weight:500;font-size:10.5px;text-transform:uppercase;letter-spacing:.1em}
  td{color:var(--mid)}
  td code,code{font-family:var(--font-mono);font-size:12px;color:#c9d6f5;background:rgba(0,0,0,.28);padding:2px 6px;border-radius:5px;word-break:break-all}
  .note{font-size:12.5px;color:var(--low);line-height:1.65}
  .banner{border:1px dashed var(--line-bright);background:rgba(148,178,255,.03);border-radius:13px;padding:18px 20px;font-size:13px;color:var(--mid);line-height:1.65}
  .banner b{color:var(--hi)}
  .banner.na{text-align:center}
  .disclosure{background:rgba(148,178,255,.03);border:1px dashed var(--line-bright);border-radius:11px;padding:12px 14px;font-size:12.5px;color:var(--low);line-height:1.6}
  .disclosure b{color:var(--mid)}
  .empty{font-size:13px;color:var(--low)}
  .stack{display:flex;flex-direction:column;gap:14px}
  .stack .spacer{flex:1;min-height:0}
  .stackbar{display:flex;width:100%;height:13px;border-radius:7px;overflow:hidden;background:rgba(255,255,255,.06)}
  .stackbar span{height:100%;display:block}
  .stackbar-legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:9px;font-size:12px;color:var(--mid)}
  .stackbar-legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px}
  .stackbar-legend b{color:var(--hi);font-family:var(--font-mono);font-weight:500}
  .lower-row{display:grid;grid-template-columns:1.4fr 1fr;gap:13px;align-items:stretch}
  footer.doc-footer{text-align:center;color:var(--low);font-size:11.5px;line-height:1.85;padding:22px 0 4px;border-top:1px solid var(--line);font-family:var(--font-mono);letter-spacing:.02em}
  @media (max-width:1100px){
    .cover{grid-template-columns:1fr} .cover-right{justify-content:flex-start} .scorecard-grid{grid-template-columns:repeat(2,1fr)}
    .charts-row{grid-template-columns:1fr} .lower-row{grid-template-columns:1fr} .charts-row.two{grid-template-columns:1fr}
    .kpi-row{grid-template-columns:repeat(3,1fr)} .check-grid{grid-template-columns:1fr} .cat-index{grid-template-columns:repeat(2,1fr)}
  }
  @media (max-width:640px){
    body{padding:16px 12px 40px} .card{padding:19px 17px} .cover{padding:22px 20px} .biz-name{font-size:27px}
    .scorecard-grid{grid-template-columns:1fr} .kpi-row{grid-template-columns:repeat(2,1fr)} .cat-index{grid-template-columns:1fr}
    .bar-row{grid-template-columns:96px 1fr 34px} .ev-row{grid-template-columns:1fr;gap:1px}
  }
  @media print{
    :root{
      --void:#fff; --navy:#fff; --card:#fff; --card-2:#f7f8fc; --raise:#fbfcff; --line:#dfe3ee; --line-bright:#c8cfe0;
      --hi:#0f1424; --mid:#3a4257; --low:#69718a; --slate:#69718a; --green:#1c7a52; --amber:#8a6a05; --orange:#a3560a; --red:#b32a3d;
      --blue:#2b5fd0; --cyan:#0e7f97;
    }
    body{background:#fff !important;padding:0;font-size:11.5pt}
    .doc{max-width:none;gap:10px}
    .card,.kpi,.score-card,.chart-card{background:#fff !important;border:1px solid #dfe3ee !important;box-shadow:none !important;break-inside:avoid}
    .cover::before{display:none}
    .ring-wrap svg{filter:none}
    .prio-num,.sec-num{box-shadow:none;color:#fff;background:#2b5fd0}
    .finding,.prio-item,.check-row,.sig{background:#fbfcff !important;break-inside:avoid}
    .ev-list{background:#f4f6fb !important}
    .field.fix{background:#f0f8fb !important}
    code,td code{background:#f1f3f9;color:#25304a}
    a{color:#2b5fd0}
    .table-wrap{overflow:visible}
    table{min-width:0}
  }
  @page{
    margin:14mm 12mm 16mm;
    @bottom-center{ content:"Page " counter(page) " of " counter(pages); font-size:8.5pt; color:#8a90a3; }
    @top-right{ content:"${esc(businessName)} — Website Audit"; font-size:8pt; color:#a3a8b8; }
  }
  `;
}
