// Rule-based website audit. Every check reports an observable fact with the
// evidence that produced it — nothing here infers anything that was not
// measured. Ported from backend/app/core/audit_checks.py; codes, categories,
// severities and deduction points are unchanged (scoring.ts and
// reportHtml.ts key off these exact strings).
import type { CrawlResult } from "./crawler";
import { homepage as crawlHomepage, typesFound } from "./crawler";
import type { ExtractionResult } from "./extract";
import type { ParsedPage } from "./page";
import { jsonldOfType } from "./page";
import { registrableDomain } from "./urls";
import type { Finding } from "../types";
import type { PageSpeedResult } from "./pagespeed";

function f(kw: Finding): Finding {
  return kw;
}

export const CATEGORIES = ["technical", "mobile", "conversion", "trust", "contact", "content"];

// -- vocabulary ---------------------------------------------------------------

const BOOKING_WORDS = [
  "book now", "book online", "book a", "book an", "make a booking", "booking",
  "appointment", "make an appointment", "schedule", "reserve", "reservation",
  "request a visit", "arrange a visit",
];
const QUOTE_WORDS = [
  "get a quote", "free quote", "request a quote", "get quote", "free estimate",
  "request an estimate", "get pricing", "request pricing", "instant quote",
];
const CONSULT_WORDS = ["consultation", "free consultation", "book a consultation", "talk to us", "speak to us", "discovery call", "free assessment"];
const CONTACT_WORDS = ["contact us", "contact", "get in touch", "reach us", "enquire", "enquiry", "inquire", "inquiry", "send us a message", "message us", "email us", "call us"];
const GENERIC_CTA = new Set(["submit", "send", "click here", "read more", "learn more", "more", "go", "ok"]);

const BOOKING_PLATFORMS = [
  "calendly.com", "acuityscheduling.com", "squareup.com/appointments", "booksy.com",
  "fresha.com", "treatwell", "setmore.com", "simplybook.me", "mindbodyonline.com",
  "opentable.com", "resy.com", "sevenrooms.com", "timely.com", "vagaro.com",
  "square.site", "schedulicity.com", "appointy.com", "10to8.com", "youcanbook.me",
  "cal.com", "housecallpro.com", "jobber.com", "servicetitan.com", "zocdoc.com",
];

const TESTIMONIAL_WORDS = [
  "testimonial", "testimonials", "what our clients say", "what our customers say",
  "client stories", "customer stories", "reviews", "review", "rated", "5 star",
  "five star", "happy clients", "happy customers", "kind words", "success stories",
];
const CREDENTIAL_WORDS = [
  "licensed", "licence", "license", "insured", "certified", "certification",
  "accredited", "accreditation", "qualified", "member of", "registered",
  "award", "awards", "award-winning", "gas safe", "niceic", "checkatrade",
  "city & guilds", "bbb accredited", "iso 900", "years of experience",
  "years experience", "established in", "since 19", "since 20", "guarantee",
  "warranty", "dbs checked", "fully insured",
];
const PORTFOLIO_WORDS = ["portfolio", "our work", "case study", "case studies", "gallery", "projects", "before and after", "before & after", "recent work", "past work"];
const HOURS_WORDS = [
  "opening hours", "open hours", "business hours", "hours of operation", "we are open",
  "mon-fri", "mon - fri", "monday to friday", "monday - friday", "monday-friday",
  "open today", "opening times",
];
const SERVICE_AREA_WORDS = ["areas we serve", "service area", "service areas", "areas covered", "we cover", "serving", "we serve", "coverage area", "locations we serve", "surrounding areas"];

const RE_PX = /(?:^|[;{\s])(?:min-)?width\s*:\s*(\d{3,5})px/gi;
const RE_FONT_PX = /font-size\s*:\s*(\d{1,2}(?:\.\d+)?)px/gi;
const RE_ADDRESS = /\b\d{1,5}\s+[A-Za-z][A-Za-z.\- ]{3,40}\s+(street|st|road|rd|avenue|ave|lane|ln|drive|dr|way|court|ct|boulevard|blvd|place|pl|parade|terrace)\b/i;

function blob(pages: ParsedPage[], limit = 60000): string {
  return pages.map((p) => p.text).join(" ").slice(0, limit).toLowerCase();
}

function anyWord(text: string, words: string[]): string | null {
  for (const w of words) if (text.includes(w)) return w;
  return null;
}

function ctaTexts(pages: ParsedPage[]): string[] {
  const out: string[] = [];
  for (const p of pages) {
    for (const b of p.buttons) if (b.trim()) out.push(b.toLowerCase().trim());
    for (const link of p.links) {
      const t = link.text.toLowerCase().trim();
      if (t.length >= 2 && t.length <= 60) out.push(t);
    }
  }
  return out;
}

type Facts = Record<string, any>;

// ==========================================================================
// TECHNICAL
// ==========================================================================

export function checkTechnical(crawl: CrawlResult, perf?: PageSpeedResult | null): [Facts, Finding[]] {
  const home = crawlHomepage(crawl);
  const findings: Finding[] = [];
  const facts: Facts = {};
  if (!home) return [facts, findings];

  facts.final_url = crawl.final_url;
  facts.http_status = crawl.home_status;
  facts.is_https = crawl.is_https;
  facts.response_ms = crawl.home_response_ms;
  facts.redirect_chain = crawl.redirect_chain;
  facts.redirect_count = Math.max(0, crawl.redirect_chain.length - 1);
  facts.title = home.title;
  facts.title_length = home.title.length;
  facts.meta_description = home.meta_description;
  facts.meta_description_length = home.meta_description.length;
  facts.h1_count = home.h1.length;
  facts.h1 = home.h1.slice(0, 3);
  facts.canonical = home.canonical;
  facts.meta_robots = home.meta_robots;
  facts.lang = home.lang;
  facts.robots_txt_found = crawl.robots_txt_found;
  facts.sitemap_found = crawl.sitemap_found;
  facts.sitemap_url = crawl.sitemap_url;
  facts.pages_crawled = crawl.pages.length;
  facts.broken_links = crawl.broken_links;
  facts.links_checked = crawl.links_checked;
  facts.mixed_content_count = home.mixed_content.length;
  facts.page_bytes = home.bytes_len;
  facts.script_count = home.scripts.length;

  const imagesTotal = crawl.pages.reduce((n, p) => n + p.images_total, 0);
  const imagesAlt = crawl.pages.reduce((n, p) => n + p.images_with_alt, 0);
  facts.images_total = imagesTotal;
  facts.images_with_alt = imagesAlt;
  facts.alt_coverage = imagesTotal ? Math.round((imagesAlt / imagesTotal) * 1000) / 1000 : null;

  if (crawl.is_https === false) {
    findings.push(f({
      code: "no_https", category: "technical", display_category: "technical", severity: "high",
      title: "The site does not load over HTTPS",
      detail: `The homepage resolved to ${crawl.final_url}, which is not a secure connection.`,
      deduction: 30, evidence: { final_url: crawl.final_url },
      recommendation: "Install an SSL certificate and force all traffic to https:// with a 301 redirect.",
    }));
  }
  if (home.mixed_content.length) {
    findings.push(f({
      code: "mixed_content", category: "technical", display_category: "technical", severity: "medium",
      title: "The secure page loads some assets over plain HTTP",
      detail: `${home.mixed_content.length} asset(s) on the homepage are requested over http://, which browsers flag or block.`,
      deduction: 12, evidence: { examples: home.mixed_content.slice(0, 5) },
      recommendation: "Update those asset URLs to https:// so the padlock is not broken.",
    }));
  }

  if ((home.meta_robots || "").includes("noindex")) {
    findings.push(f({
      code: "noindex", category: "technical", display_category: "technical", severity: "high",
      title: "The homepage is set to noindex",
      detail: `The homepage carries <meta name="robots" content="${home.meta_robots}">, which asks search engines not to index it.`,
      deduction: 40, evidence: { meta_robots: home.meta_robots },
      recommendation: "Remove the noindex directive so the homepage can appear in search results.",
    }));
  }

  if (!home.title.trim()) {
    findings.push(f({
      code: "missing_title", category: "technical", display_category: "technical", severity: "high",
      title: "The homepage has no title tag", detail: "No <title> element was found on the homepage.",
      deduction: 18, evidence: {}, recommendation: "Add a title of roughly 50-60 characters naming the service and the location.",
    }));
  } else if (home.title.length < 15) {
    findings.push(f({
      code: "title_too_short", category: "technical", display_category: "technical", severity: "low",
      title: "The homepage title is very short", detail: `The title is ${home.title.length} characters: "${home.title}".`,
      deduction: 6, evidence: { title: home.title },
      recommendation: "Expand the title to around 50-60 characters including the main service and location.",
    }));
  } else if (home.title.length > 70) {
    findings.push(f({
      code: "title_too_long", category: "technical", display_category: "technical", severity: "low",
      title: "The homepage title is longer than search results display",
      detail: `The title is ${home.title.length} characters; search results typically show about 60.`,
      deduction: 3, evidence: { title: home.title.slice(0, 120) },
      recommendation: "Trim the title so the important words are not cut off in search results.",
    }));
  }

  if (!home.meta_description.trim()) {
    findings.push(f({
      code: "missing_meta_description", category: "technical", display_category: "technical", severity: "medium",
      title: "The homepage has no meta description",
      detail: "No meta description was found, so search engines generate the snippet themselves.",
      deduction: 14, evidence: {},
      recommendation: "Write a 140-160 character description covering the service, area and one reason to choose them.",
    }));
  } else if (home.meta_description.length < 50) {
    findings.push(f({
      code: "meta_description_short", category: "technical", display_category: "technical", severity: "low",
      title: "The homepage meta description is very short",
      detail: `The description is ${home.meta_description.length} characters.`,
      deduction: 5, evidence: { meta_description: home.meta_description },
      recommendation: "Expand it to 140-160 characters to use the full search snippet.",
    }));
  }

  if (!home.h1.length) {
    findings.push(f({
      code: "missing_h1", category: "technical", display_category: "technical", severity: "medium",
      title: "The homepage has no H1 heading", detail: "No <h1> element was found on the homepage.",
      deduction: 14, evidence: {}, recommendation: "Add a single H1 that states what the business does and where.",
    }));
  } else if (home.h1.length > 1) {
    findings.push(f({
      code: "multiple_h1", category: "technical", display_category: "technical", severity: "low",
      title: "The homepage has more than one H1",
      detail: `${home.h1.length} H1 headings were found: ${home.h1.slice(0, 3).join("; ")}`,
      deduction: 4, evidence: { h1: home.h1.slice(0, 5) },
      recommendation: "Keep one H1 as the page's main heading and demote the others to H2.",
    }));
  }

  if (!home.canonical) {
    findings.push(f({
      code: "missing_canonical", category: "technical", display_category: "technical", severity: "low",
      title: "No canonical URL is declared on the homepage", detail: 'No <link rel="canonical"> was found.',
      deduction: 4, evidence: {}, recommendation: "Add a canonical link so duplicate URLs consolidate onto one address.",
    }));
  }
  if (!home.lang) {
    findings.push(f({
      code: "missing_lang", category: "technical", display_category: "technical", severity: "low",
      title: "The page does not declare a language",
      detail: "The <html> element has no lang attribute, which screen readers rely on.",
      deduction: 3, evidence: {}, recommendation: 'Add lang="en" (or the correct language) to the <html> element.',
    }));
  }

  if (crawl.sitemap_found === false) {
    findings.push(f({
      code: "missing_sitemap", category: "technical", display_category: "technical", severity: "low",
      title: "No XML sitemap was found", detail: "Neither robots.txt nor /sitemap.xml pointed to a sitemap.",
      deduction: 6, evidence: {}, recommendation: "Publish an XML sitemap and reference it from robots.txt.",
    }));
  }
  if (crawl.robots_txt_found === false) {
    findings.push(f({
      code: "missing_robots", category: "technical", display_category: "technical", severity: "low",
      title: "No robots.txt file was found", detail: "A request to /robots.txt did not return a file.",
      deduction: 3, evidence: {}, recommendation: "Add a robots.txt that allows crawling and links the sitemap.",
    }));
  }

  if (crawl.broken_links.length) {
    const n = crawl.broken_links.length;
    findings.push(f({
      code: "broken_internal_links", category: "technical", display_category: "technical",
      severity: n >= 3 ? "high" : "medium",
      title: `${n} broken internal link${n !== 1 ? "s" : ""} were found`,
      detail: `Of ${crawl.links_checked} internal links checked, ${n} returned an error.`,
      deduction: Math.min(20, 8 + 4 * n),
      evidence: { broken: crawl.broken_links.slice(0, 6), checked: crawl.links_checked },
      recommendation: "Fix or remove the broken links so visitors do not hit dead ends.",
    }));
  }

  if (imagesTotal >= 5 && facts.alt_coverage !== null && facts.alt_coverage < 0.5) {
    findings.push(f({
      code: "low_alt_coverage", category: "technical", display_category: "technical", severity: "medium",
      title: "Most images have no alt text",
      detail: `${imagesAlt} of ${imagesTotal} images across ${crawl.pages.length} crawled pages have alt text (${Math.floor(facts.alt_coverage * 100)}%).`,
      deduction: 8, evidence: { examples: home.images_missing_alt_examples.slice(0, 4) },
      recommendation: "Add descriptive alt text to meaningful images for accessibility and image search.",
    }));
  }

  if (facts.redirect_count > 2) {
    findings.push(f({
      code: "long_redirect_chain", category: "technical", display_category: "technical", severity: "low",
      title: "The homepage goes through several redirects",
      detail: `${facts.redirect_count} redirects were followed before the page loaded.`,
      deduction: 4, evidence: { chain: crawl.redirect_chain.slice(0, 6) },
      recommendation: "Point the entry URL straight at the final address to remove the extra hops.",
    }));
  }

  const rt = crawl.home_response_ms;
  if (rt !== null) {
    let sev: Finding["severity"] = "";
    let ded = 0;
    if (rt > 4000) { sev = "high"; ded = 20; }
    else if (rt > 2500) { sev = "medium"; ded = 14; }
    else if (rt > 1500) { sev = "low"; ded = 7; }
    if (ded) {
      findings.push(f({
        code: "slow_response", category: "technical", display_category: "performance", severity: sev,
        title: "The homepage was slow to respond",
        detail: `The homepage took ${rt} ms to return from this machine (single measured request, not a full performance profile).`,
        deduction: ded, evidence: { response_ms: rt, method: "single server-side HTTP request" },
        recommendation: "Investigate server response time, caching and hosting; a sub-1s response is a reasonable target.",
      }));
    }
  }

  if (home.bytes_len > 2_500_000) {
    findings.push(f({
      code: "heavy_page", category: "technical", display_category: "performance", severity: "medium",
      title: "The homepage HTML download is large",
      detail: `The homepage document alone was ${(home.bytes_len / 1_000_000).toFixed(1)} MB (images and scripts not included).`,
      deduction: 10, evidence: { bytes: home.bytes_len },
      recommendation: "Reduce the page weight - compress, lazy-load and remove unused markup.",
    }));
  }
  if (home.scripts.length > 25) {
    findings.push(f({
      code: "many_scripts", category: "technical", display_category: "performance", severity: "low",
      title: "The homepage loads a large number of scripts",
      detail: `${home.scripts.length} external scripts were referenced on the homepage.`,
      deduction: 6, evidence: { script_count: home.scripts.length },
      recommendation: "Audit third-party scripts and remove or defer the ones that are not needed on load.",
    }));
  }

  if (perf?.measured) {
    facts.pagespeed = perf;
    const score = perf.performance_score;
    if (typeof score === "number") {
      let sev: Finding["severity"] = "";
      let ded = 0;
      if (score < 40) { sev = "high"; ded = 18; }
      else if (score < 60) { sev = "medium"; ded = 12; }
      else if (score < 80) { sev = "low"; ded = 6; }
      if (ded) {
        findings.push(f({
          code: "pagespeed_low", category: "technical", display_category: "performance", severity: sev,
          title: `Google PageSpeed scored the ${perf.strategy || "mobile"} page ${Math.floor(score)}/100`,
          detail: pagespeedDetail(perf), deduction: ded, evidence: perf as any,
          recommendation: "Work through the PageSpeed opportunities, starting with the largest contentful paint.",
        }));
      }
    }
  } else if (perf?.error) {
    facts.pagespeed = perf;
  }

  return [facts, findings];
}

function pagespeedDetail(perf: PageSpeedResult): string {
  const bits = [`Google PageSpeed Insights returned ${perf.performance_score}/100 for the ${perf.strategy} strategy.`];
  const rows: [keyof PageSpeedResult, string, string][] = [
    ["lcp_s", "Largest Contentful Paint", " s"], ["cls", "Cumulative Layout Shift", ""],
    ["tbt_ms", "Total Blocking Time", " ms"], ["fcp_s", "First Contentful Paint", " s"],
  ];
  for (const [key, label, unit] of rows) {
    const v = perf[key];
    if (v !== null && v !== undefined) bits.push(`${label}: ${v}${unit}.`);
  }
  return bits.join(" ");
}

// ==========================================================================
// MOBILE
// ==========================================================================

export function checkMobile(crawl: CrawlResult): [Facts, Finding[]] {
  const home = crawlHomepage(crawl);
  const findings: Finding[] = [];
  const facts: Facts = { method: "static_dom_css_analysis" };
  if (!home) return [facts, findings];

  const vp = (home.viewport || "").trim();
  facts.viewport = vp;
  facts.has_viewport = Boolean(vp);

  if (!vp) {
    findings.push(f({
      code: "missing_viewport", category: "mobile", display_category: "mobile", severity: "high",
      title: "The page has no mobile viewport tag",
      detail: 'No <meta name="viewport"> was found, so mobile browsers render the page at desktop width and the visitor has to pinch and zoom.',
      deduction: 45, evidence: {},
      recommendation: 'Add <meta name="viewport" content="width=device-width, initial-scale=1"> and confirm the layout reflows on a phone.',
    }));
  } else {
    const responsive = vp.includes("width=device-width");
    facts.viewport_responsive = responsive;
    const blocksZoom = vp.replace(/\s+/g, "").includes("user-scalable=no") || /maximum-scale\s*=\s*1(\.0)?\b/.test(vp);
    facts.viewport_blocks_zoom = blocksZoom;

    if (!responsive) {
      findings.push(f({
        code: "viewport_not_responsive", category: "mobile", display_category: "mobile", severity: "high",
        title: "The viewport tag is not set to the device width",
        detail: `The viewport is "${vp}", which does not use width=device-width, so the layout will not adapt to phone screens.`,
        deduction: 25, evidence: { viewport: vp },
        recommendation: 'Set the viewport to "width=device-width, initial-scale=1".',
      }));
    }
    if (blocksZoom) {
      findings.push(f({
        code: "zoom_disabled", category: "mobile", display_category: "mobile", severity: "medium",
        title: "Pinch-to-zoom is disabled on mobile",
        detail: `The viewport "${vp}" prevents visitors from zooming, which is an accessibility problem for anyone with low vision.`,
        deduction: 10, evidence: { viewport: vp },
        recommendation: "Remove user-scalable=no / maximum-scale=1 so visitors can zoom.",
      }));
    }
  }

  const css = home.inline_style_blocks.join(" ").slice(0, 120000);
  const htmlSlice = (home.raw_html || "").slice(0, 200000);
  const widths = [...css.matchAll(RE_PX)].map((m) => parseInt(m[1], 10));
  const attrWidths = [...htmlSlice.matchAll(/<(?:table|div|img)[^>]+width\s*=\s*"?(\d{3,5})/gi)].map((m) => parseInt(m[1], 10));
  const big = [...widths, ...attrWidths].filter((w) => w > 600);
  facts.fixed_width_declarations = big.length;
  facts.largest_fixed_width_px = big.length ? Math.max(...big) : null;

  if (big.length >= 3) {
    findings.push(f({
      code: "fixed_width_layout", category: "mobile", display_category: "mobile", severity: "medium",
      title: "The layout uses fixed pixel widths wider than a phone screen",
      detail: `${big.length} declarations set a fixed width above 600px (largest ${Math.max(...big)}px) in the page's own markup and inline CSS. Fixed widths above roughly 400px commonly cause sideways scrolling on phones.`,
      deduction: 15, evidence: { count: big.length, largest_px: Math.max(...big), samples: [...new Set(big)].sort((a, b) => a - b).slice(-5) },
      recommendation: "Replace fixed pixel widths with max-width plus percentage/flex layout.",
    }));
  }

  const fonts = [...css.matchAll(RE_FONT_PX)].map((m) => parseFloat(m[1]));
  const smallFonts = fonts.filter((n) => n < 12);
  facts.small_font_declarations = smallFonts.length;
  if (smallFonts.length >= 3) {
    findings.push(f({
      code: "small_mobile_text", category: "mobile", display_category: "mobile", severity: "low",
      title: "Several text styles are set below 12px",
      detail: `${smallFonts.length} font-size declarations under 12px were found in the page's inline CSS, which is hard to read on a phone without zooming.`,
      deduction: 8, evidence: { count: smallFonts.length, smallest_px: Math.min(...smallFonts) },
      recommendation: "Use a base body size of at least 16px on mobile.",
    }));
  }

  const hasTelHome = Boolean(home.tel.length);
  facts.tap_to_call_on_homepage = hasTelHome;
  facts.tap_to_call_anywhere = crawl.pages.some((p) => p.tel.length);

  if (!hasTelHome) {
    const anywhere = facts.tap_to_call_anywhere;
    findings.push(f({
      code: "no_mobile_tap_to_call", category: "mobile", display_category: "mobile", severity: anywhere ? "medium" : "high",
      title: "The homepage has no tap-to-call phone link",
      detail: `No <a href="tel:"> link was found on the homepage, so a phone visitor cannot tap the number to call. ${
        anywhere ? "A tap-to-call link does exist on another page." : "No tap-to-call link was found on any crawled page."
      }`,
      deduction: anywhere ? 12 : 20, evidence: { pages_checked: crawl.pages.length, found_elsewhere: anywhere },
      recommendation: "Make the phone number a tel: link and place it in the mobile header so it is tappable without scrolling.",
    }));
  }

  if (/<(object|embed|applet)\b/i.test(htmlSlice)) {
    findings.push(f({
      code: "legacy_plugin_content", category: "mobile", display_category: "mobile", severity: "low",
      title: "The page embeds legacy plugin content",
      detail: "An <object>, <embed> or <applet> element was found; this content typically does not run on mobile browsers.",
      deduction: 6, evidence: {}, recommendation: "Replace legacy embeds with HTML5 equivalents.",
    }));
  }

  const navLinks = home.links.filter((l) => l.internal).length;
  facts.internal_link_count_home = navLinks;
  const hasMobileMenu = /(hamburger|mobile-menu|menu-toggle|navbar-toggle|nav-toggle|burger)/i.test(htmlSlice);
  facts.mobile_menu_detected = hasMobileMenu;
  if (navLinks > 25 && !hasMobileMenu) {
    findings.push(f({
      code: "no_mobile_menu", category: "mobile", display_category: "mobile", severity: "medium",
      title: "A large navigation with no mobile menu pattern detected",
      detail: `The homepage has ${navLinks} internal links and no recognisable mobile menu markup (hamburger/toggle), so navigation may be unusable on a phone.`,
      deduction: 10, evidence: { internal_links: navLinks },
      recommendation: "Add a collapsible mobile menu that exposes the main services and contact link.",
    }));
  }

  facts.note = "Mobile findings are derived from the page's HTML and inline CSS, not from a rendered phone browser. External stylesheets were not downloaded.";
  return [facts, findings];
}

// ==========================================================================
// CONVERSION
// ==========================================================================

export function checkConversion(crawl: CrawlResult): [Facts, Finding[]] {
  const findings: Finding[] = [];
  const facts: Facts = {};
  const home = crawlHomepage(crawl);
  if (!home) return [facts, findings];

  const pages = crawl.pages;
  const textAll = blob(pages);
  const ctas = ctaTexts(pages);
  const ctaBlob = ctas.join(" | ");
  const types = typesFound(crawl);
  const htmlAll = pages.map((p) => p.raw_html || "").join(" ").slice(0, 200000).toLowerCase();

  const hasTel = pages.some((p) => p.tel.length);
  const hasMailto = pages.some((p) => p.mailto.length);
  const realForms = pages.flatMap((p) => p.forms).filter(
    (fm) => !fm.is_search && !fm.is_newsletter && (fm.has_email_field || fm.has_message_field || fm.has_phone_field),
  );
  const hasForm = realForms.length > 0;

  const bookingWord = anyWord(ctaBlob, BOOKING_WORDS) || anyWord(textAll, BOOKING_WORDS);
  const bookingPlatform = BOOKING_PLATFORMS.find((p) => htmlAll.includes(p));
  const hasBooking = Boolean(bookingWord || bookingPlatform || types.has("booking"));

  const quoteWord = anyWord(ctaBlob, QUOTE_WORDS) || anyWord(textAll, QUOTE_WORDS);
  const consultWord = anyWord(ctaBlob, CONSULT_WORDS) || anyWord(textAll, CONSULT_WORDS);

  const hasWhatsapp = pages.some((p) => p.whatsapp_links.length);

  facts.has_phone_cta = hasTel;
  facts.has_email_cta = hasMailto;
  facts.has_contact_form = hasForm;
  facts.contact_form_count = realForms.length;
  facts.has_booking_cta = hasBooking;
  facts.booking_evidence = bookingPlatform || bookingWord || (types.has("booking") ? "booking page" : "");
  facts.has_quote_cta = Boolean(quoteWord);
  facts.has_consultation_cta = Boolean(consultWord);
  facts.has_whatsapp_cta = hasWhatsapp;
  facts.has_contact_page = types.has("contact");
  facts.cta_samples = ctas.slice(0, 15);

  const af = (home.above_fold_html || "").toLowerCase();
  const afText = (home.above_fold_text || "").toLowerCase();
  const afSignals: string[] = [];
  if (af.includes('href="tel:') || af.includes("href='tel:")) afSignals.push("tap-to-call link");
  if (af.includes("mailto:")) afSignals.push("email link");
  for (const w of [...BOOKING_WORDS, ...QUOTE_WORDS, ...CONSULT_WORDS, ...CONTACT_WORDS]) {
    if (afText.includes(w)) {
      afSignals.push(`"${w}"`);
      break;
    }
  }
  facts.above_fold_cta_signals = afSignals;
  facts.above_fold_method = "header markup plus the first ~18KB of body HTML (approximation)";

  if (!afSignals.length) {
    findings.push(f({
      code: "no_primary_cta_above_fold", category: "conversion", display_category: "conversion", severity: "high",
      title: "No clear call to action was found near the top of the homepage",
      detail: "The header and the opening section of the homepage contain no phone link, email link, or booking/quote/contact wording. (Measured from the page markup, which approximates what appears before scrolling.)",
      deduction: 22, evidence: { checked: facts.above_fold_method },
      recommendation: "Put one primary action - call, book, or request a quote - in the header and repeat it in the opening section.",
    }));
  }

  if (!hasTel) {
    findings.push(f({
      code: "no_phone_cta", category: "conversion", display_category: "conversion", severity: "high",
      title: "No clickable phone link was found anywhere on the site",
      detail: `No tel: link was found across ${pages.length} crawled pages.`,
      deduction: 22, evidence: { pages_crawled: pages.length },
      recommendation: "Add the phone number as a tel: link in the header, footer and contact page.",
    }));
  }

  if (!hasForm) {
    findings.push(f({
      code: "no_contact_form", category: "conversion", display_category: "conversion", severity: !hasTel && !hasMailto ? "high" : "medium",
      title: "No contact or enquiry form was detected",
      detail: `No form with a name/email/message field was found on the ${pages.length} pages crawled (search and newsletter forms were excluded).`,
      deduction: 15, evidence: { pages_crawled: pages.length },
      recommendation: "Add a short enquiry form - name, contact detail and message - on the contact page and after the main service section.",
    }));
  }

  if (!hasBooking) {
    findings.push(f({
      code: "no_booking_cta", category: "conversion", display_category: "conversion", severity: "medium",
      title: "No booking or appointment option was detected",
      detail: "No booking wording, booking page or recognised scheduling platform was found on the crawled pages.",
      deduction: 16, evidence: { platforms_checked: BOOKING_PLATFORMS.length },
      recommendation: "If the business takes appointments, add an online booking option; otherwise make 'request a callback' the equivalent primary action.",
    }));
  }

  if (!quoteWord && !consultWord) {
    findings.push(f({
      code: "no_quote_cta", category: "conversion", display_category: "conversion", severity: "low",
      title: "No quote or consultation offer was found",
      detail: "The site does not invite visitors to request a quote, estimate or consultation.",
      deduction: 8, evidence: {},
      recommendation: "Add a 'Request a free quote' or 'Book a consultation' action for visitors who are not ready to call.",
    }));
  }

  if (!hasMailto && !hasForm) {
    findings.push(f({
      code: "no_email_cta", category: "conversion", display_category: "conversion", severity: "medium",
      title: "There is no way to make contact in writing",
      detail: "Neither an email link nor a contact form was found on the crawled pages.",
      deduction: 10, evidence: {},
      recommendation: "Publish an email address or add a form so visitors can enquire outside opening hours.",
    }));
  }

  if (!types.has("contact")) {
    findings.push(f({
      code: "no_contact_page", category: "conversion", display_category: "conversion", severity: "medium",
      title: "No contact page was found",
      detail: `No page identifiable as a contact page was reachable from the homepage within ${pages.length} crawled pages.`,
      deduction: 12, evidence: { pages_found: [...types].sort() },
      recommendation: "Add a clearly linked Contact page with phone, email, address and a form.",
    }));
  }

  const generic = ctas.filter((c) => GENERIC_CTA.has(c));
  const strong = ctas.filter((c) => [...BOOKING_WORDS, ...QUOTE_WORDS, ...CONSULT_WORDS, "call", "contact"].some((w) => c.includes(w)));
  facts.generic_cta_count = generic.length;
  facts.strong_cta_count = strong.length;
  if (generic.length && !strong.length) {
    findings.push(f({
      code: "weak_cta_language", category: "conversion", display_category: "conversion", severity: "low",
      title: "The calls to action use generic wording",
      detail: `Buttons and links use wording like ${[...new Set(generic)].slice(0, 4).map((g) => `"${g}"`).join(", ")} with no action-specific alternative found.`,
      deduction: 6, evidence: { generic: [...new Set(generic)].slice(0, 6) },
      recommendation: "Name the outcome in the button - 'Get a free quote', 'Book an appointment' - rather than 'Submit' or 'Learn more'.",
    }));
  }

  if (!hasWhatsapp) facts.whatsapp_cta_note = "No WhatsApp link found on the site.";

  return [facts, findings];
}

// ==========================================================================
// TRUST / PROOF
// ==========================================================================

export function checkTrust(crawl: CrawlResult): [Facts, Finding[]] {
  const findings: Finding[] = [];
  const facts: Facts = {};
  const pages = crawl.pages;
  if (!pages.length) return [facts, findings];

  const textAll = blob(pages);
  const types = typesFound(crawl);

  const testimonialHit = anyWord(textAll, TESTIMONIAL_WORDS);
  const credentialHit = anyWord(textAll, CREDENTIAL_WORDS);
  const portfolioHit = anyWord(textAll, PORTFOLIO_WORDS);
  const reviewSchema = pages.some((p) => jsonldOfType(p, "Review", "AggregateRating").length);
  const social = [...new Set(pages.flatMap((p) => p.social_links))].sort();

  facts.testimonials_detected = Boolean(testimonialHit) || types.has("testimonials");
  facts.testimonial_evidence = testimonialHit || (types.has("testimonials") ? "testimonials page" : "");
  facts.credentials_detected = Boolean(credentialHit);
  facts.credential_evidence = credentialHit || "";
  facts.portfolio_detected = Boolean(portfolioHit);
  facts.portfolio_evidence = portfolioHit || "";
  facts.review_structured_data = reviewSchema;
  facts.about_page = types.has("about");
  facts.team_page = types.has("team");
  facts.social_links = social.slice(0, 10);

  if (!facts.testimonials_detected) {
    findings.push(f({
      code: "no_testimonials", category: "trust", display_category: "trust", severity: "high",
      title: "No testimonials or customer reviews were found on the site",
      detail: `None of the ${pages.length} crawled pages mention testimonials, reviews or customer feedback.`,
      deduction: 24, evidence: { pages_crawled: pages.length },
      recommendation: "Add three to five short customer quotes with a name and location near the main call to action.",
    }));
  } else if (!reviewSchema) {
    findings.push(f({
      code: "reviews_not_structured", category: "trust", display_category: "trust", severity: "low",
      title: "Reviews are shown but not marked up as structured data",
      detail: "Review wording appears on the site but no Review/AggregateRating structured data was found, so ratings cannot show in search results.",
      deduction: 5, evidence: {},
      recommendation: "Add Review/AggregateRating schema so star ratings can appear in search listings.",
    }));
  }

  if (!credentialHit) {
    findings.push(f({
      code: "no_credentials", category: "trust", display_category: "trust", severity: "medium",
      title: "No licences, insurance, certifications or guarantees are mentioned",
      detail: "No wording about being licensed, insured, certified, accredited, guaranteed or award-winning was found on the crawled pages.",
      deduction: 14, evidence: {},
      recommendation: "State the licences, insurance, accreditations or guarantee near the top of the homepage - it is one of the cheapest trust wins available.",
    }));
  }

  if (!portfolioHit) {
    findings.push(f({
      code: "no_portfolio", category: "trust", display_category: "trust", severity: "medium",
      title: "No portfolio, gallery or case studies were found",
      detail: "No 'our work', gallery, project or case-study content was detected.",
      deduction: 12, evidence: {}, recommendation: "Publish photos of recent work or a few short case studies with the outcome.",
    }));
  }

  if (!types.has("about")) {
    findings.push(f({
      code: "no_about_page", category: "trust", display_category: "trust", severity: "low",
      title: "No About page was found",
      detail: "No page describing the business or its people was reachable from the homepage.",
      deduction: 10, evidence: { pages_found: [...types].sort() },
      recommendation: "Add a short About page covering who runs the business and how long they have traded.",
    }));
  }

  if (!social.length) {
    findings.push(f({
      code: "no_social_presence_linked", category: "trust", display_category: "trust", severity: "low",
      title: "No social media profiles are linked from the site",
      detail: "No links to Facebook, Instagram, LinkedIn or similar were found.",
      deduction: 6, evidence: {}, recommendation: "Link the active social profiles so visitors can see recent activity.",
    }));
  }

  return [facts, findings];
}

// ==========================================================================
// CONTACT ACCESSIBILITY
// ==========================================================================

export function checkContact(crawl: CrawlResult, extracted?: ExtractionResult | null): [Facts, Finding[]] {
  const findings: Finding[] = [];
  const facts: Facts = {};
  const pages = crawl.pages;
  const home = crawlHomepage(crawl);
  if (!home) return [facts, findings];

  const textAll = blob(pages);
  const types = typesFound(crawl);

  const telAnywhere = pages.some((p) => p.tel.length);
  const telHome = Boolean(home.tel.length);
  const mailAnywhere = pages.some((p) => p.mailto.length);
  const emailsFound = extracted?.emails?.length ?? 0;

  const addrSchema = pages.some((p) => jsonldOfType(p, "LocalBusiness", "Organization", "PostalAddress").length);
  const hoursHit = anyWord(textAll, HOURS_WORDS);
  const hoursSchema = pages.some((p) => p.jsonld.some((b) => Object.keys(b).some((k) => k.toLowerCase().includes("openinghours"))));
  const addrPattern = RE_ADDRESS.test(textAll);

  const footerHasContact = pages.some((p) => (p.footer_html || "").toLowerCase().includes("tel:") || (p.footer_html || "").toLowerCase().includes("mailto:"));
  const headerHasContact = pages.some((p) => (p.header_html || "").toLowerCase().includes("tel:") || (p.header_html || "").toLowerCase().includes("mailto:"));

  facts.phone_on_site = telAnywhere;
  facts.phone_on_homepage = telHome;
  facts.email_on_site = mailAnywhere;
  facts.public_emails_found = emailsFound;
  facts.address_detected = addrPattern || addrSchema;
  facts.address_structured_data = addrSchema;
  facts.opening_hours_detected = Boolean(hoursHit) || hoursSchema;
  facts.contact_page = types.has("contact");
  facts.contact_in_header = headerHasContact;
  facts.contact_in_footer = footerHasContact;

  if (!telAnywhere) {
    findings.push(f({
      code: "no_phone_on_site", category: "contact", display_category: "contact", severity: "high",
      title: "No phone number is published as a link on the website",
      detail: `No tel: link was found on any of the ${pages.length} crawled pages.`,
      deduction: 30, evidence: { pages_crawled: pages.length },
      recommendation: "Publish the phone number as a tel: link in the header and footer of every page.",
    }));
  } else if (!telHome) {
    findings.push(f({
      code: "phone_not_on_homepage", category: "contact", display_category: "contact", severity: "medium",
      title: "The phone number is not linked on the homepage",
      detail: "A tap-to-call link exists elsewhere on the site but not on the homepage, so most visitors have to navigate before they can call.",
      deduction: 15, evidence: {}, recommendation: "Move the phone number into the homepage header where it is visible immediately.",
    }));
  }

  if (!mailAnywhere && emailsFound === 0) {
    findings.push(f({
      code: "no_email_on_site", category: "contact", display_category: "contact", severity: "medium",
      title: "No email address is published on the website",
      detail: `No mailto: link or visible email address was found across ${pages.length} pages.`,
      deduction: 15, evidence: {}, recommendation: "Publish a monitored business email address on the contact page.",
    }));
  }

  if (!facts.address_detected) {
    findings.push(f({
      code: "no_address", category: "contact", display_category: "contact", severity: "medium",
      title: "No business address was found on the site",
      detail: "No street address text or address structured data was detected on the crawled pages.",
      deduction: 12, evidence: {}, recommendation: "Publish the trading address (or service area) plus LocalBusiness structured data.",
    }));
  }

  if (!facts.opening_hours_detected) {
    findings.push(f({
      code: "no_opening_hours", category: "contact", display_category: "contact", severity: "low",
      title: "No opening hours were found on the site",
      detail: "No opening-hours wording or openingHours structured data was detected.",
      deduction: 10, evidence: {}, recommendation: "Publish opening hours on the contact page and in structured data.",
    }));
  }

  if (!(headerHasContact || footerHasContact) && !types.has("contact")) {
    findings.push(f({
      code: "contact_hard_to_find", category: "contact", display_category: "contact", severity: "high",
      title: "Contact details are not reachable from the header, footer or a contact page",
      detail: "No contact link was found in the site header or footer, and no contact page was reachable from the homepage.",
      deduction: 20, evidence: {},
      recommendation: "Put the phone number in the header, repeat contact details in the footer, and link a dedicated contact page from the main navigation.",
    }));
  }

  return [facts, findings];
}

// ==========================================================================
// CONTENT CLARITY
// ==========================================================================

export function checkContent(crawl: CrawlResult, _categoryHint = ""): [Facts, Finding[]] {
  const findings: Finding[] = [];
  const facts: Facts = {};
  const home = crawlHomepage(crawl);
  if (!home) return [facts, findings];

  const pages = crawl.pages;
  const types = typesFound(crawl);
  const textAll = blob(pages);

  facts.homepage_word_count = home.word_count;
  facts.h2_count = home.h2.length;
  facts.pages_found = [...types].sort();
  facts.services_page = types.has("services");
  facts.nav_link_count = new Set(home.links.filter((l) => l.internal).map((l) => l.href)).size;

  if (home.word_count < 120) {
    findings.push(f({
      code: "very_thin_homepage", category: "content", display_category: "content", severity: "high",
      title: "The homepage has very little text",
      detail: `The homepage contains about ${home.word_count} words of readable text, which is not enough to explain the service or rank in search.`,
      deduction: 28, evidence: { word_count: home.word_count },
      recommendation: "Expand the homepage to clearly cover the services, the area served and why someone should choose this business.",
    }));
  } else if (home.word_count < 300) {
    findings.push(f({
      code: "thin_homepage", category: "content", display_category: "content", severity: "medium",
      title: "The homepage content is thin", detail: `The homepage contains about ${home.word_count} words of readable text.`,
      deduction: 14, evidence: { word_count: home.word_count },
      recommendation: "Add a section per main service with a short description and a call to action.",
    }));
  }

  const serviceWords = ["service", "services", "we offer", "we provide", "what we do", "our work", "specialis", "specializ", "treatments", "products"];
  const hasServices = types.has("services") || serviceWords.some((w) => textAll.includes(w));
  facts.services_described = hasServices;
  if (!hasServices) {
    findings.push(f({
      code: "services_not_clear", category: "content", display_category: "content", severity: "high",
      title: "The services offered are not clearly presented",
      detail: "No services page and no service wording was found on the crawled pages.",
      deduction: 22, evidence: { pages_found: [...types].sort() },
      recommendation: "List the main services on the homepage, each with its own short section or page.",
    }));
  }

  if (!home.h1.length) {
    facts.value_proposition = "";
  } else {
    facts.value_proposition = home.h1[0];
    const genericH1 = ["home", "welcome", "welcome to our website", "homepage", "untitled"].includes(home.h1[0].trim().toLowerCase());
    if (genericH1) {
      findings.push(f({
        code: "generic_value_proposition", category: "content", display_category: "content", severity: "medium",
        title: "The main heading does not say what the business does",
        detail: `The homepage H1 is "${home.h1[0]}", which does not state the service or the area.`,
        deduction: 12, evidence: { h1: home.h1[0] },
        recommendation: 'Rewrite the H1 as service + area, for example "Emergency plumbing in <city>, 24/7".',
      }));
    }
  }

  const areaHit = anyWord(textAll, SERVICE_AREA_WORDS);
  facts.service_area_detected = Boolean(areaHit) || types.has("locations");
  if (!facts.service_area_detected) {
    findings.push(f({
      code: "no_service_area", category: "content", display_category: "content", severity: "low",
      title: "The service area is not stated", detail: "No 'areas we serve' wording or locations page was found.",
      deduction: 10, evidence: {}, recommendation: "State the towns or radius covered - it helps both visitors and local search.",
    }));
  }

  if (home.h2.length === 0 && home.word_count > 200) {
    findings.push(f({
      code: "no_heading_structure", category: "content", display_category: "content", severity: "low",
      title: "The homepage has no subheadings",
      detail: `The homepage has ${home.word_count} words but no H2 headings, so the content is one undifferentiated block.`,
      deduction: 8, evidence: { word_count: home.word_count },
      recommendation: "Break the page into sections with descriptive H2 subheadings.",
    }));
  }

  const nav = facts.nav_link_count;
  if (nav < 3) {
    findings.push(f({
      code: "minimal_navigation", category: "content", display_category: "content", severity: "medium",
      title: "The site has almost no internal navigation",
      detail: `Only ${nav} distinct internal link(s) were found on the homepage.`,
      deduction: 12, evidence: { internal_links: nav }, recommendation: "Add a navigation menu covering services, about and contact.",
    }));
  }

  return [facts, findings];
}

// ==========================================================================
// NO-WEBSITE case
// ==========================================================================

export function noWebsiteFindings(reason: string, socialUrl = ""): Finding[] {
  if (socialUrl) {
    return [f({
      code: "social_profile_only", category: "conversion", display_category: "conversion", severity: "high",
      title: "The business appears to rely on a social or directory profile instead of a website",
      detail: `The listed web address is ${socialUrl}, which is a third-party profile rather than a site the business controls.`,
      deduction: 0, evidence: { profile_url: socialUrl, checked: reason },
      recommendation: "A small owned website would let them rank in search, publish services and prices, and capture enquiries directly.",
    })];
  }
  return [f({
    code: "no_website_detected", category: "conversion", display_category: "conversion", severity: "high",
    title: "No website could be found for this business", detail: reason,
    deduction: 0, evidence: { checked: reason },
    recommendation: "A simple website covering services, area, proof and one clear contact action would give them a presence they own.",
  })];
}

// ==========================================================================
// SECURITY
// ==========================================================================

const SERVER_VERSION_RE = /[/ ]\d+\.\d+/;

export function checkSecurity(crawl: CrawlResult): [Facts, Finding[]] {
  const home = crawlHomepage(crawl);
  const findings: Finding[] = [];
  const facts: Facts = {};
  if (!home) return [facts, findings];

  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(crawl.home_headers || {})) headers[k.toLowerCase()] = v;
  facts.is_https = crawl.is_https;
  facts.headers_measured = Object.keys(headers).length > 0;
  facts.hsts_present = "strict-transport-security" in headers;
  facts.csp_present = "content-security-policy" in headers;
  facts.x_content_type_options = headers["x-content-type-options"] || "";
  facts.x_frame_options = headers["x-frame-options"] || "";
  facts.referrer_policy_present = "referrer-policy" in headers;
  facts.permissions_policy_present = "permissions-policy" in headers;
  facts.server_header = headers["server"] || "";

  if (!Object.keys(headers).length) {
    facts.note = "Response headers were not available for this fetch, so header-based security checks could not run.";
    return [facts, findings];
  }

  if (crawl.is_https && !facts.hsts_present) {
    findings.push(f({
      code: "security_hsts_missing", category: "security", display_category: "security", severity: "medium",
      title: "No HTTP Strict-Transport-Security header",
      detail: "The homepage is served over HTTPS but did not send a Strict-Transport-Security header, so browsers are not told to always use HTTPS for this site.",
      deduction: 12, evidence: { checked_header: "Strict-Transport-Security" },
      recommendation: "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains' once HTTPS is confirmed working on every subdomain.",
    }));
  }

  const frameProtected = Boolean(facts.x_frame_options) || (headers["content-security-policy"] || "").toLowerCase().includes("frame-ancestors");
  if (!frameProtected) {
    findings.push(f({
      code: "security_frame_protection_missing", category: "security", display_category: "security", severity: "medium",
      title: "No clickjacking protection header",
      detail: "Neither an X-Frame-Options header nor a Content-Security-Policy with frame-ancestors was found, so the page could potentially be embedded in a hidden frame on another site.",
      deduction: 10, evidence: { checked_headers: ["X-Frame-Options", "Content-Security-Policy: frame-ancestors"] },
      recommendation: "Add 'X-Frame-Options: SAMEORIGIN' or a CSP frame-ancestors directive.",
    }));
  }

  if (!facts.csp_present) {
    findings.push(f({
      code: "security_csp_missing", category: "security", display_category: "security", severity: "low",
      title: "No Content-Security-Policy header",
      detail: "No Content-Security-Policy header was found. CSP is the strongest available browser-level defence against cross-site scripting and unauthorised resource loading.",
      deduction: 6, evidence: {}, recommendation: "Introduce a Content-Security-Policy, starting in report-only mode if needed.",
    }));
  }

  if ((facts.x_content_type_options as string).toLowerCase() !== "nosniff") {
    findings.push(f({
      code: "security_xcto_missing", category: "security", display_category: "security", severity: "low",
      title: "No X-Content-Type-Options header",
      detail: "The response did not send 'X-Content-Type-Options: nosniff', so some browsers may try to guess ('sniff') a file's type instead of trusting the declared one.",
      deduction: 5, evidence: {}, recommendation: "Add 'X-Content-Type-Options: nosniff' to every response.",
    }));
  }

  if (!facts.referrer_policy_present) {
    findings.push(f({
      code: "security_referrer_policy_missing", category: "security", display_category: "security", severity: "low",
      title: "No Referrer-Policy header",
      detail: "No Referrer-Policy header was found, so the browser's default behaviour applies, which can leak the full page URL to third-party sites linked from this page.",
      deduction: 4, evidence: {}, recommendation: "Add 'Referrer-Policy: strict-origin-when-cross-origin' (a safe modern default).",
    }));
  }

  const server = facts.server_header as string;
  if (server && SERVER_VERSION_RE.test(server)) {
    findings.push(f({
      code: "security_server_header_discloses_version", category: "security", display_category: "security", severity: "low",
      title: "The server header discloses software version details",
      detail: `The Server response header is "${server}", which names the exact software version in use and can help an attacker target known vulnerabilities.`,
      deduction: 4, evidence: { server_header: server }, recommendation: "Configure the web server to omit or generalise the Server header.",
    }));
  }

  return [facts, findings];
}

// ==========================================================================
// ACCESSIBILITY
// ==========================================================================

export function checkAccessibility(crawl: CrawlResult): [Facts, Finding[]] {
  const home = crawlHomepage(crawl);
  const findings: Finding[] = [];
  const facts: Facts = {};
  if (!home) return [facts, findings];

  facts.has_main_landmark = home.has_main_landmark;
  facts.has_nav_landmark = home.has_nav_landmark;
  facts.has_skip_link = home.has_skip_link;
  facts.lang_declared = Boolean(home.lang);
  facts.contrast = "not_measured";
  facts.contrast_note = "Colour contrast requires a rendered page and computed styles; it cannot be measured reliably from static HTML/CSS, so it is reported as not measured rather than guessed.";

  const totalInputs = crawl.pages.reduce((n, p) => n + p.forms.reduce((m, fm) => m + fm.labelled_inputs + fm.unlabelled_inputs, 0), 0);
  const unlabelled = crawl.pages.reduce((n, p) => n + p.forms.reduce((m, fm) => m + fm.unlabelled_inputs, 0), 0);
  facts.form_inputs_checked = totalInputs;
  facts.unlabelled_form_inputs = unlabelled;

  const emptyLinks = crawl.pages.reduce((n, p) => n + p.empty_link_count, 0);
  facts.empty_links = emptyLinks;

  if (!home.has_main_landmark) {
    findings.push(f({
      code: "a11y_no_main_landmark", category: "accessibility", display_category: "accessibility", severity: "low",
      title: "No <main> landmark on the homepage",
      detail: 'No <main> element or role="main" was found, which screen reader users rely on to jump straight to the primary content.',
      deduction: 6, evidence: {}, recommendation: "Wrap the primary content in a <main> element.",
    }));
  }

  if (totalInputs > 0 && unlabelled > 0) {
    findings.push(f({
      code: "a11y_unlabelled_form_inputs", category: "accessibility", display_category: "accessibility", severity: unlabelled >= 2 ? "medium" : "low",
      title: `${unlabelled} form field${unlabelled !== 1 ? "s" : ""} have no associated label`,
      detail: `Of ${totalInputs} form field(s) checked across ${crawl.pages.length} crawled pages, ${unlabelled} have no <label>, aria-label or aria-labelledby, so screen reader users cannot tell what to enter.`,
      deduction: Math.min(16, 6 + 4 * unlabelled), evidence: { unlabelled, checked: totalInputs },
      recommendation: 'Associate every input with a <label for="..."> (or aria-label) naming the field.',
    }));
  }

  if (emptyLinks > 0) {
    findings.push(f({
      code: "a11y_empty_links", category: "accessibility", display_category: "accessibility", severity: "low",
      title: `${emptyLinks} link${emptyLinks !== 1 ? "s" : ""} with no accessible text`,
      detail: `${emptyLinks} link(s) across ${crawl.pages.length} crawled pages have no visible text, aria-label or alt text on an image inside them, so a screen reader announces them as just "link".`,
      deduction: Math.min(10, 3 * emptyLinks), evidence: { count: emptyLinks },
      recommendation: "Add descriptive link text or an aria-label to every link, especially icon-only links.",
    }));
  }

  if (home.h3.length && !home.h2.length) {
    findings.push(f({
      code: "a11y_heading_order_skipped", category: "accessibility", display_category: "accessibility", severity: "low",
      title: "Heading levels skip from H1 to H3",
      detail: "The homepage uses H3 headings with no H2 in between, which breaks the logical outline screen reader users navigate by.",
      deduction: 5, evidence: { h3_count: home.h3.length }, recommendation: "Use heading levels in order (H1 -> H2 -> H3) without skipping a level.",
    }));
  }

  return [facts, findings];
}

// ==========================================================================
// ON-PAGE SEO EXTRAS
// ==========================================================================

export function checkOnpage(crawl: CrawlResult): [Facts, Finding[]] {
  const home = crawlHomepage(crawl);
  const findings: Finding[] = [];
  const facts: Facts = {};
  if (!home) return [facts, findings];

  facts.open_graph_tags = Object.keys(home.og).sort();
  facts.twitter_card_tags = Object.keys(home.twitter).sort();
  facts.hreflang_count = home.hreflang.length;
  facts.hreflang_languages = [...new Set(home.hreflang.map((h) => h.lang))].sort();
  facts.schema_types_found = [...new Set(crawl.pages.flatMap((p) => p.schema_types))].sort();

  if (!home.og.title && !home.og.description) {
    findings.push(f({
      code: "onpage_missing_open_graph", category: "onpage", display_category: "onpage", severity: "medium",
      title: "No Open Graph tags on the homepage",
      detail: "No og:title or og:description meta tags were found, so links shared on Facebook, LinkedIn and most chat apps will show a blank or generic preview.",
      deduction: 10, evidence: {}, recommendation: "Add og:title, og:description and og:image so shared links preview correctly.",
    }));
  }

  if (!home.twitter.card) {
    findings.push(f({
      code: "onpage_missing_twitter_card", category: "onpage", display_category: "onpage", severity: "low",
      title: "No Twitter/X card meta tag",
      detail: "No twitter:card meta tag was found, so links shared on X/Twitter fall back to a plain link instead of a rich preview.",
      deduction: 4, evidence: {}, recommendation: "Add twitter:card (summary_large_image works well), twitter:title and twitter:image.",
    }));
  }

  const titles = crawl.pages.map((p) => p.title.trim().toLowerCase()).filter(Boolean);
  const dupTitles = new Set(titles.filter((t) => titles.filter((x) => x === t).length > 1));
  if (dupTitles.size) {
    findings.push(f({
      code: "onpage_duplicate_titles", category: "onpage", display_category: "onpage", severity: "medium",
      title: "Multiple crawled pages share the same title tag",
      detail: `${dupTitles.size} title(s) are reused across more than one crawled page, which makes it harder for search engines to tell the pages apart.`,
      deduction: 10, evidence: { examples: [...dupTitles].slice(0, 3) }, recommendation: "Give every page a unique, descriptive title.",
    }));
  }

  const descs = crawl.pages.map((p) => p.meta_description.trim().toLowerCase()).filter(Boolean);
  const dupDescs = new Set(descs.filter((d) => descs.filter((x) => x === d).length > 1));
  if (dupDescs.size) {
    findings.push(f({
      code: "onpage_duplicate_meta_description", category: "onpage", display_category: "onpage", severity: "low",
      title: "Multiple crawled pages share the same meta description",
      detail: `${dupDescs.size} meta description(s) are reused across more than one crawled page.`,
      deduction: 5, evidence: { examples: [...dupDescs].slice(0, 2).map((d) => d.slice(0, 120)) },
      recommendation: "Write a unique meta description for every page.",
    }));
  }

  return [facts, findings];
}

// ==========================================================================
// OFF-PAGE / AUTHORITY
// ==========================================================================

export function checkOffpage(crawl: CrawlResult): [Facts, Finding[]] {
  const findings: Finding[] = [];
  const facts: Facts = {};
  const pages = crawl.pages;
  if (!pages.length) return [facts, findings];

  const social = [...new Set(pages.flatMap((p) => p.social_links))].sort();
  const sameAs: string[] = [];
  for (const p of pages) {
    for (const block of p.jsonld) {
      const sa = block.sameAs;
      if (typeof sa === "string") sameAs.push(sa);
      else if (Array.isArray(sa)) sameAs.push(...sa.filter((x) => typeof x === "string"));
    }
  }
  const sameAsSet = [...new Set(sameAs)].sort().slice(0, 20);

  const externalDomains = [...new Set(pages.flatMap((p) => p.external_links).map((u) => registrableDomain(u)).filter(Boolean))].sort().slice(0, 30);

  facts.social_profiles_linked = social;
  facts.structured_data_sameas = sameAsSet;
  facts.external_domains_referenced = externalDomains;
  facts.external_domains_referenced_count = externalDomains.length;

  facts.backlinks = { measured: false, reason: "No backlink index (e.g. Ahrefs, Moz, Majestic, SEMrush) is configured. Backlink counts are never estimated or fabricated." };
  facts.referring_domains = { measured: false, reason: "Same as backlinks - requires a paid third-party index that is not configured." };
  facts.domain_authority = { measured: false, reason: "Domain authority-style scores (Moz DA, Ahrefs DR, etc.) are proprietary to each vendor and are never approximated here." };

  if (!social.length && !sameAsSet.length) {
    findings.push(f({
      code: "offpage_no_social_profiles", category: "offpage", display_category: "offpage", severity: "low",
      title: "No social media profiles are linked from the site",
      detail: "No links to Facebook, Instagram, LinkedIn, X or similar were found on the crawled pages, and no sameAs structured data points to any.",
      deduction: 8, evidence: { pages_checked: pages.length },
      recommendation: "Link active social profiles from the site and add them as sameAs entries in Organization/LocalBusiness structured data.",
    }));
  } else if (social.length && !sameAsSet.length) {
    findings.push(f({
      code: "offpage_sameas_not_structured", category: "offpage", display_category: "offpage", severity: "low",
      title: "Social profiles are linked but not declared as structured data",
      detail: "Social links were found on the page, but no sameAs entries in Organization/LocalBusiness structured data connect them to the business entity.",
      deduction: 4, evidence: { social_links: social.slice(0, 5) },
      recommendation: 'Add the social profile URLs as "sameAs" in your Organization/LocalBusiness JSON-LD so search engines can connect them to the business.',
    }));
  }

  return [facts, findings];
}

// ==========================================================================
// PERFORMANCE EXTRAS
// ==========================================================================

export function checkPerformanceExtra(crawl: CrawlResult): [Facts, Finding[]] {
  const home = crawlHomepage(crawl);
  const findings: Finding[] = [];
  const facts: Facts = {};
  if (!home) return [facts, findings];

  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(crawl.home_headers || {})) headers[k.toLowerCase()] = v;
  facts.render_blocking_scripts = home.render_blocking_scripts;
  facts.stylesheet_count = home.stylesheets.length;
  facts.content_encoding = headers["content-encoding"] || "";
  facts.cache_control = headers["cache-control"] || "";
  facts.note = "Asset weight here counts requests and response headers only; it does not download every image, script and stylesheet, so it is not a full byte-for-byte page-weight measurement.";

  if (home.render_blocking_scripts > 4) {
    findings.push(f({
      code: "perf_render_blocking_scripts", category: "performance", display_category: "performance", severity: "medium",
      title: "Several render-blocking scripts load before the page can render",
      detail: `${home.render_blocking_scripts} <script> tag(s) with a src attribute and neither async nor defer were found, which can delay when the page becomes visible.`,
      deduction: 10, evidence: { count: home.render_blocking_scripts },
      recommendation: "Add defer (or async, if order does not matter) to non-critical scripts, or move them to the end of the page.",
    }));
  }

  if (Object.keys(headers).length && !facts.content_encoding) {
    findings.push(f({
      code: "perf_no_compression", category: "performance", display_category: "performance", severity: "medium",
      title: "The homepage response is not compressed",
      detail: "No Content-Encoding header (gzip/br) was found on the homepage response, so the page transfers larger than it needs to.",
      deduction: 8, evidence: { headers_checked: "Content-Encoding" }, recommendation: "Enable gzip or Brotli compression on the web server.",
    }));
  }

  if (Object.keys(headers).length && (!facts.cache_control || String(facts.cache_control).toLowerCase().includes("no-store"))) {
    findings.push(f({
      code: "perf_no_cache_headers", category: "performance", display_category: "performance", severity: "low",
      title: "No caching guidance in the response headers",
      detail: "No usable Cache-Control header was found on the homepage response, so repeat visits may re-download content unnecessarily.",
      deduction: 4, evidence: { cache_control: facts.cache_control }, recommendation: "Add Cache-Control headers appropriate to each asset type.",
    }));
  }

  return [facts, findings];
}

// ==========================================================================
// LOCAL SEO
// ==========================================================================

const MAP_LINK_RE = /(google\.com\/maps|maps\.google\.|goo\.gl\/maps|g\.page\/|business\.google\.com)/i;
const LOCAL_SERVICE_AREA_RE = /\b(areas we serve|service area[s]?|areas covered|locations we serve|our service area)\b/i;

export function checkLocalSeo(crawl: CrawlResult): [Facts, Finding[]] {
  const findings: Finding[] = [];
  const facts: Facts = {};
  const pages = crawl.pages;
  const home = crawlHomepage(crawl);
  if (!home || !pages.length) return [facts, findings];

  const textAll = blob(pages);
  const types = typesFound(crawl);

  const localSchemaBlocks = pages.flatMap((p) => jsonldOfType(p, "LocalBusiness", "Organization"));
  const schemaWithAddress = localSchemaBlocks.filter((b) => b.address);
  const schemaName = localSchemaBlocks.find((b) => b.name)?.name || "";

  const addrPattern = RE_ADDRESS.test(textAll);
  const hasAddressSignal = addrPattern || Boolean(schemaWithAddress.length);

  const mapLink = pages.some((p) => p.iframes.some((u) => MAP_LINK_RE.test(u))) || pages.some((p) => p.links.some((l) => l.href && MAP_LINK_RE.test(l.href)));

  const serviceAreaHit = LOCAL_SERVICE_AREA_RE.test(textAll);
  const locationsPage = types.has("locations");
  const hasServiceAreaSignal = serviceAreaHit || locationsPage;

  const hoursHit = anyWord(textAll, HOURS_WORDS);
  const hoursSchema = pages.some((p) => p.jsonld.some((b) => Object.keys(b).some((k) => k.toLowerCase().includes("openinghours"))));
  const hasHoursSignal = Boolean(hoursHit) || hoursSchema;

  const testimonialHit = anyWord(textAll, TESTIMONIAL_WORDS);
  const reviewSchema = pages.some((p) => jsonldOfType(p, "Review", "AggregateRating").length);
  const hasReviewsSignal = Boolean(testimonialHit) || types.has("testimonials") || reviewSchema;

  const coreSignals = [Boolean(schemaWithAddress.length), hasAddressSignal, mapLink, hasServiceAreaSignal];
  const signalCount = coreSignals.filter(Boolean).length;

  facts.local_business_schema = Boolean(localSchemaBlocks.length);
  facts.schema_has_address = Boolean(schemaWithAddress.length);
  facts.address_signal = hasAddressSignal;
  facts.map_or_gbp_link = mapLink;
  facts.service_area_signal = hasServiceAreaSignal;
  facts.opening_hours_signal = hasHoursSignal;
  facts.reviews_signal = hasReviewsSignal;
  facts.reviews_structured = reviewSchema;
  facts.signal_count = signalCount;

  const applicable = Boolean(schemaWithAddress.length) || signalCount >= 2;
  facts.applicable = applicable;
  if (!applicable) {
    facts.reason = "No address, map or Google Business Profile link, service-area content, or LocalBusiness/Organization structured data was found on the crawled pages (or only one weak signal was), so this does not appear to be a physical, location-based business. Local SEO is reported as Not Applicable rather than scored - if this is in fact a local business, publishing this information more clearly would also be the fastest way to improve here.";
    return [facts, findings];
  }

  if (!localSchemaBlocks.length) {
    findings.push(f({
      code: "local_no_business_schema", category: "local_seo", display_category: "local_seo", severity: "high",
      title: "No LocalBusiness or Organization structured data was found",
      detail: "Search engines rely on LocalBusiness/Organization JSON-LD - not just visible text - to confirm a business's name, address and category for local search and map results. None was found on the crawled pages.",
      deduction: 22, evidence: { pages_checked: pages.length },
      recommendation: "Add LocalBusiness JSON-LD structured data with the business name, address, phone number and category.",
    }));
  }

  if (!hasAddressSignal) {
    findings.push(f({
      code: "local_no_address_signal", category: "local_seo", display_category: "local_seo", severity: "high",
      title: "No business address was found on the site",
      detail: `No street address text and no structured-data address field were found across ${pages.length} crawled pages.`,
      deduction: 20, evidence: { pages_checked: pages.length },
      recommendation: "Publish the full trading address on the contact page (and in LocalBusiness structured data).",
    }));
  } else if (localSchemaBlocks.length && !schemaWithAddress.length) {
    findings.push(f({
      code: "local_address_not_structured", category: "local_seo", display_category: "local_seo", severity: "low",
      title: "The business address is published but not in structured data",
      detail: "An address appears on the page, but the LocalBusiness/Organization structured data has no address field, so search engines cannot confirm it as reliably as they could from structured data.",
      deduction: 6, evidence: {},
      recommendation: 'Add the address as a structured "address" field in the LocalBusiness JSON-LD, not just as visible text.',
    }));
  }

  if (!mapLink) {
    findings.push(f({
      code: "local_no_map_or_gbp_link", category: "local_seo", display_category: "local_seo", severity: "medium",
      title: "No map embed or Google Business Profile link was found",
      detail: "No embedded Google Map and no link to a Google Maps or Google Business Profile listing was found, which makes it harder for visitors (and search engines) to confirm the business's exact location.",
      deduction: 12, evidence: {}, recommendation: "Embed a Google Map on the contact page and link the Google Business Profile listing.",
    }));
  }

  if (!hasServiceAreaSignal) {
    findings.push(f({
      code: "local_no_service_area_content", category: "local_seo", display_category: "local_seo", severity: "medium",
      title: "The area(s) served are not clearly stated",
      detail: "No 'areas we serve' wording and no locations page were found, so it is unclear which towns or region the business actually covers.",
      deduction: 12, evidence: {}, recommendation: "Add a short 'areas we serve' section or a locations page naming the towns/region covered.",
    }));
  }

  if (!hasHoursSignal) {
    findings.push(f({
      code: "local_no_opening_hours", category: "local_seo", display_category: "local_seo", severity: "low",
      title: "Opening hours are not published",
      detail: "No opening-hours wording and no openingHours structured data were found.",
      deduction: 8, evidence: {}, recommendation: "Publish opening hours on the contact page and in structured data.",
    }));
  }

  if (!hasReviewsSignal) {
    findings.push(f({
      code: "local_no_reviews_or_testimonials", category: "local_seo", display_category: "local_seo", severity: "medium",
      title: "No reviews or testimonials were found",
      detail: "Reviews are one of the strongest local-search ranking and trust signals; none were found on the crawled pages.",
      deduction: 12, evidence: {}, recommendation: "Display recent customer reviews, and encourage Google Business Profile reviews specifically.",
    }));
  } else if (!reviewSchema) {
    findings.push(f({
      code: "local_reviews_not_structured", category: "local_seo", display_category: "local_seo", severity: "low",
      title: "Reviews are shown but not marked up as structured data",
      detail: "Review or testimonial content appears on the site but no Review/AggregateRating structured data was found, so star ratings cannot show directly in search results.",
      deduction: 5, evidence: {}, recommendation: "Add Review/AggregateRating structured data so ratings can appear in search listings.",
    }));
  }

  if (schemaName) {
    const nameLc = schemaName.trim().toLowerCase();
    const firstWord = nameLc.split(/\s+/)[0] || "";
    const titleLc = (home.title || "").toLowerCase();
    const h1Lc = home.h1.join(" ").toLowerCase();
    if (firstWord && !titleLc.includes(firstWord) && !h1Lc.includes(firstWord)) {
      findings.push(f({
        code: "local_name_mismatch", category: "local_seo", display_category: "local_seo", severity: "low",
        title: "The business name in structured data does not appear on the homepage",
        detail: `Structured data names the business "${schemaName}", but that name was not found in the homepage title or heading, which can make it harder for search engines to match the two together.`,
        deduction: 6, evidence: { schema_name: schemaName },
        recommendation: "Make sure the business name in structured data matches the name shown on the page.",
      }));
    }
  }

  return [facts, findings];
}

// ==========================================================================

export function runExtraChecks(crawl: CrawlResult): [Record<string, Facts>, Finding[]] {
  const facts: Record<string, Facts> = {};
  const findings: Finding[] = [];
  const checks: [string, (c: CrawlResult) => [Facts, Finding[]]][] = [
    ["security", checkSecurity], ["accessibility", checkAccessibility], ["onpage", checkOnpage],
    ["offpage", checkOffpage], ["performance_extra", checkPerformanceExtra], ["local_seo", checkLocalSeo],
  ];
  for (const [name, fn] of checks) {
    try {
      const [fa, fi] = fn(crawl);
      facts[name] = fa;
      findings.push(...fi);
    } catch (exc: any) {
      facts[name] = { error: `${exc?.name || "Error"}: ${exc?.message || exc}` };
    }
  }
  return [facts, findings];
}

export function runAllChecks(
  crawl: CrawlResult,
  opts: { extracted?: ExtractionResult | null; perf?: PageSpeedResult | null; categoryHint?: string } = {},
): [Record<string, Facts>, Finding[]] {
  const facts: Record<string, Facts> = {};
  const findings: Finding[] = [];
  const checks: [string, () => [Facts, Finding[]]][] = [
    ["technical", () => checkTechnical(crawl, opts.perf)],
    ["mobile", () => checkMobile(crawl)],
    ["conversion", () => checkConversion(crawl)],
    ["trust", () => checkTrust(crawl)],
    ["contact", () => checkContact(crawl, opts.extracted)],
    ["content", () => checkContent(crawl, opts.categoryHint)],
  ];
  for (const [name, fn] of checks) {
    try {
      const [fa, fi] = fn();
      facts[name] = fa;
      findings.push(...fi);
    } catch (exc: any) {
      facts[name] = { error: `${exc?.name || "Error"}: ${exc?.message || exc}` };
    }
  }
  return [facts, findings];
}
