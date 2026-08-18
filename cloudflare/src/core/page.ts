// HTML parsing into a structured page model, plus page-type classification.
// Ported from backend/app/core/page.py. selectolax (Python) -> node-html-parser (JS).
import { parse, HTMLElement } from "node-html-parser";
import { absolutize, sameSite, urlKey } from "./urls";

export interface Link {
  href: string;
  text: string;
  rel: string;
  internal: boolean;
  raw_href: string;
}

export interface FormInfo {
  action: string;
  method: string;
  input_types: string[];
  input_names: string[];
  has_email_field: boolean;
  has_phone_field: boolean;
  has_message_field: boolean;
  submit_text: string;
  is_search: boolean;
  is_newsletter: boolean;
  labelled_inputs: number;
  unlabelled_inputs: number;
}

export interface ParsedPage {
  url: string;
  final_url: string;
  status: number | null;
  page_type: string;
  depth: number;
  elapsed_ms: number;
  bytes_len: number;

  title: string;
  meta_description: string;
  meta_robots: string;
  canonical: string;
  viewport: string;
  lang: string;

  h1: string[];
  h2: string[];
  h3: string[];

  text: string;
  word_count: number;

  links: Link[];
  external_links: string[];

  mailto: string[];
  tel: string[];
  whatsapp_links: string[];
  social_links: string[];

  images_total: number;
  images_with_alt: number;
  images_missing_alt_examples: string[];

  forms: FormInfo[];
  scripts: string[];
  stylesheets: string[];
  inline_style_blocks: string[];

  jsonld: Record<string, any>[];
  raw_html: string;

  header_html: string;
  footer_html: string;
  above_fold_text: string;
  above_fold_html: string;

  buttons: string[];
  iframes: string[];
  mixed_content: string[];

  og: Record<string, string>;
  twitter: Record<string, string>;
  hreflang: { lang: string; href: string }[];
  has_main_landmark: boolean;
  has_nav_landmark: boolean;
  has_skip_link: boolean;
  render_blocking_scripts: number;
  empty_link_count: number;
  schema_types: string[];
}

function emptyPage(url: string, opts: Partial<ParsedPage>): ParsedPage {
  return {
    url, final_url: opts.final_url || url, status: opts.status ?? null, page_type: opts.page_type || "other",
    depth: opts.depth ?? 0, elapsed_ms: opts.elapsed_ms ?? 0, bytes_len: opts.bytes_len ?? 0,
    title: "", meta_description: "", meta_robots: "", canonical: "", viewport: "", lang: "",
    h1: [], h2: [], h3: [], text: "", word_count: 0, links: [], external_links: [],
    mailto: [], tel: [], whatsapp_links: [], social_links: [],
    images_total: 0, images_with_alt: 0, images_missing_alt_examples: [],
    forms: [], scripts: [], stylesheets: [], inline_style_blocks: [], jsonld: [], raw_html: "",
    header_html: "", footer_html: "", above_fold_text: "", above_fold_html: "",
    buttons: [], iframes: [], mixed_content: [],
    og: {}, twitter: {}, hreflang: [], has_main_landmark: false, has_nav_landmark: false,
    has_skip_link: false, render_blocking_scripts: 0, empty_link_count: 0, schema_types: [],
  };
}

// -- page-type classification ------------------------------------------------

const PAGE_TYPE_PATTERNS: [string, string[]][] = [
  ["contact", ["contact", "kontakt", "contacto", "contactez", "get-in-touch", "getintouch", "reach-us", "reachus", "enquiry", "enquire", "inquiry", "contact-us"]],
  ["booking", ["book", "booking", "appointment", "appointments", "schedule", "reserve", "reservation", "book-now", "book-online", "make-appointment", "buchen"]],
  ["about", ["about", "about-us", "aboutus", "who-we-are", "our-story", "company", "ueber-uns", "sobre", "notre-histoire"]],
  ["team", ["team", "our-team", "staff", "people", "meet-the-team", "our-people", "practitioners", "doctors", "stylists", "therapists"]],
  ["services", ["service", "services", "what-we-do", "treatments", "solutions", "offerings", "products", "menu", "our-work", "specialties", "leistungen"]],
  ["pricing", ["pricing", "prices", "price-list", "rates", "packages", "plans", "cost", "fees", "tariff"]],
  ["testimonials", ["testimonial", "testimonials", "reviews", "review", "feedback", "client-stories", "case-studies", "case-study", "portfolio", "gallery", "our-work", "projects"]],
  ["locations", ["location", "locations", "areas-we-serve", "service-area", "service-areas", "find-us", "branches", "stores", "coverage", "where-we-work"]],
  ["quote", ["quote", "get-a-quote", "request-quote", "free-quote", "estimate", "free-estimate", "request-estimate"]],
];

const SKIP_PATTERNS = [
  "privacy", "terms", "cookie", "gdpr", "disclaimer", "sitemap.xml", "/tag/", "/tags/",
  "/author/", "/category/", "/wp-admin", "/wp-login", "/cart", "/checkout", "/account",
  "/login", "/signin", "/register", "/feed", "?add-to-cart", "/wp-json",
];

export const PAGE_PRIORITY: Record<string, number> = {
  homepage: 0, contact: 1, about: 2, services: 3, booking: 4, team: 5,
  testimonials: 6, pricing: 7, locations: 8, quote: 9, other: 20, blog: 20,
};

export function classifyPage(url: string, linkText = "", isHome = false): string {
  if (isHome) return "homepage";
  const haystack = `${url.toLowerCase()} ${linkText.toLowerCase()}`;
  const path = url.toLowerCase().replace(/^https?:\/\/[^/]+/, "");
  if (path === "" || path === "/") return "homepage";
  const pathWords = path.replace(/[/_-]+/g, " ");
  const linkTextL = linkText.toLowerCase();
  for (const [ptype, keys] of PAGE_TYPE_PATTERNS) {
    for (const k of keys) {
      const pat = new RegExp(`\\b${escapeRe(k.replace(/-/g, " "))}\\b`);
      if (pat.test(pathWords) || pat.test(linkTextL)) return ptype;
    }
  }
  if (["blog", "news", "article", "post"].some((k) => haystack.includes(k))) return "blog";
  return "other";
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function shouldSkipUrl(url: string): boolean {
  const low = url.toLowerCase();
  return SKIP_PATTERNS.some((p) => low.includes(p));
}

// -- parsing ------------------------------------------------------------------

const WS = /\s+/g;
const MAILTO_RE = /^mailto:([^?]+)/i;
const TEL_RE = /^(?:tel|callto):(.+)$/i;
const WA_RE = /(wa\.me\/|api\.whatsapp\.com|web\.whatsapp\.com|whatsapp:\/\/)/i;
const SOCIAL_RE = /(facebook\.com|instagram\.com|twitter\.com|x\.com|linkedin\.com|youtube\.com|tiktok\.com|pinterest\.com)/i;
const DROP_TAGS = new Set(["script", "style", "noscript", "template", "svg", "iframe"]);

function cleanText(text: string | undefined | null): string {
  if (!text) return "";
  return text.replace(WS, " ").trim();
}

function hasAttr(el: HTMLElement, name: string): boolean {
  return Object.prototype.hasOwnProperty.call(el.attributes || {}, name);
}

export function parseHtml(
  html: string,
  url: string,
  opts: {
    final_url?: string;
    status?: number | null;
    depth?: number;
    page_type?: string;
    elapsed_ms?: number;
    bytes_len?: number;
    keep_html?: boolean;
  } = {},
): ParsedPage {
  const page = emptyPage(url, opts);
  if (!html) return page;

  const base = page.final_url;
  let tree: HTMLElement;
  try {
    tree = parse(html, { comment: false, blockTextElements: { script: true, noscript: true, style: true, pre: true } });
  } catch {
    return page;
  }

  if (opts.keep_html) page.raw_html = html;

  // -- head ------------------------------------------------------------------
  const head = tree.querySelector("head");
  if (head) {
    const titleEl = head.querySelector("title");
    page.title = cleanText(titleEl?.text).slice(0, 500);
    for (const meta of head.querySelectorAll("meta")) {
      const name = (meta.getAttribute("name") || "").toLowerCase();
      const prop = (meta.getAttribute("property") || "").toLowerCase();
      const content = (meta.getAttribute("content") || "").trim();
      if (name === "description" && !page.meta_description) page.meta_description = content.slice(0, 1000);
      else if (prop === "og:description" && !page.meta_description) page.meta_description = content.slice(0, 1000);
      else if (name === "robots") page.meta_robots = content.toLowerCase();
      else if (name === "viewport") page.viewport = content.toLowerCase();
      if (prop.startsWith("og:") && content) {
        const key = prop.slice(3);
        if (!(key in page.og)) page.og[key] = content.slice(0, 500);
      }
      if (name.startsWith("twitter:") && content) {
        const key = name.slice(8);
        if (!(key in page.twitter)) page.twitter[key] = content.slice(0, 500);
      }
    }
    const canon = head.querySelectorAll("link").find((l) => (l.getAttribute("rel") || "") === "canonical");
    if (canon) page.canonical = (canon.getAttribute("href") || "").trim();
    for (const link of head.querySelectorAll("link")) {
      if ((link.getAttribute("rel") || "") === "stylesheet") {
        const href = link.getAttribute("href");
        if (href) page.stylesheets.push(href);
      }
      if ((link.getAttribute("rel") || "") === "alternate") {
        const hl = (link.getAttribute("hreflang") || "").trim();
        const href = (link.getAttribute("href") || "").trim();
        if (hl && href && page.hreflang.length < 30) page.hreflang.push({ lang: hl, href });
      }
    }
  }

  const htmlNode = tree.querySelector("html");
  if (htmlNode) page.lang = (htmlNode.getAttribute("lang") || "").trim();

  // -- structured data ---------------------------------------------------------
  for (const node of tree.querySelectorAll("script")) {
    if ((node.getAttribute("type") || "").toLowerCase() !== "application/ld+json") continue;
    const raw = (node.rawText || "").trim();
    if (!raw) continue;
    try {
      const data = JSON.parse(raw);
      if (Array.isArray(data)) {
        for (const d of data) if (d && typeof d === "object") page.jsonld.push(d);
      } else if (data && typeof data === "object") {
        if (Array.isArray((data as any)["@graph"])) {
          for (const d of (data as any)["@graph"]) if (d && typeof d === "object") page.jsonld.push(d);
        } else {
          page.jsonld.push(data);
        }
      }
    } catch {
      /* malformed JSON-LD is common in the wild; skip it */
    }
  }
  for (const block of page.jsonld) {
    const t = block["@type"] ?? block["type"];
    const names = Array.isArray(t) ? t : [t];
    for (const name of names) {
      if (name && !page.schema_types.includes(String(name))) page.schema_types.push(String(name));
    }
  }

  // -- scripts / inline styles --------------------------------------------------
  for (const node of tree.querySelectorAll("script")) {
    const src = node.getAttribute("src");
    if (src) {
      page.scripts.push(src);
      const hasAsync = hasAttr(node, "async");
      const hasDefer = hasAttr(node, "defer");
      const scriptType = (node.getAttribute("type") || "").toLowerCase();
      if (!hasAsync && !hasDefer && !["module", "application/json", "application/ld+json"].includes(scriptType)) {
        page.render_blocking_scripts += 1;
      }
    }
  }
  for (const node of tree.querySelectorAll("style")) {
    const block = node.rawText || "";
    if (block) page.inline_style_blocks.push(block.slice(0, 20000));
  }
  for (const node of tree.querySelectorAll("iframe")) {
    const src = node.getAttribute("src") || "";
    if (src) page.iframes.push(src);
  }

  // -- mixed content -------------------------------------------------------------
  if (page.final_url.startsWith("https://")) {
    for (const list of [page.scripts, page.stylesheets, page.iframes]) {
      for (const src of list) if (src.startsWith("http://")) page.mixed_content.push(src);
    }
    for (const img of tree.querySelectorAll("img")) {
      const src = img.getAttribute("src") || "";
      if (src.startsWith("http://")) page.mixed_content.push(src);
    }
    page.mixed_content = page.mixed_content.slice(0, 20);
  }

  // -- headings --------------------------------------------------------------------
  page.h1 = tree.querySelectorAll("h1").map((n) => cleanText(n.text).slice(0, 300)).filter(Boolean);
  page.h2 = tree.querySelectorAll("h2").map((n) => cleanText(n.text).slice(0, 300)).filter(Boolean).slice(0, 40);
  page.h3 = tree.querySelectorAll("h3").map((n) => cleanText(n.text).slice(0, 300)).filter(Boolean).slice(0, 40);

  // -- images --------------------------------------------------------------------
  for (const img of tree.querySelectorAll("img")) {
    page.images_total += 1;
    const alt = img.getAttribute("alt");
    if (alt !== undefined && alt !== null && alt.trim()) {
      page.images_with_alt += 1;
    } else if (page.images_missing_alt_examples.length < 5) {
      const src = img.getAttribute("src") || img.getAttribute("data-src") || "";
      if (src) page.images_missing_alt_examples.push(src.slice(0, 200));
    }
  }

  // -- links -----------------------------------------------------------------------
  const seenLinks = new Set<string>();
  for (const a of tree.querySelectorAll("a")) {
    const rawHref = (a.getAttribute("href") || "").trim();
    if (!rawHref) continue;
    const text = cleanText(a.text).slice(0, 200);
    const rel = (a.getAttribute("rel") || "").toLowerCase();

    if (!text && !a.getAttribute("aria-label") && !a.getAttribute("title")) {
      const hasAltImg = a.querySelectorAll("img").some((img) => (img.getAttribute("alt") || "").trim());
      if (!hasAltImg) page.empty_link_count += 1;
    }

    let m = MAILTO_RE.exec(rawHref);
    if (m) {
      const addr = m[1].trim().replace(/%20/g, "").toLowerCase();
      if (addr && !page.mailto.includes(addr)) page.mailto.push(addr);
      continue;
    }
    m = TEL_RE.exec(rawHref);
    if (m) {
      const num = m[1].trim();
      if (num && !page.tel.includes(num)) page.tel.push(num);
      continue;
    }
    if (WA_RE.test(rawHref)) {
      if (!page.whatsapp_links.includes(rawHref)) page.whatsapp_links.push(rawHref);
      continue;
    }
    if (SOCIAL_RE.test(rawHref)) {
      if (!page.social_links.includes(rawHref) && page.social_links.length < 20) page.social_links.push(rawHref);
    }

    const absUrl = absolutize(base, rawHref);
    if (!absUrl) continue;
    const internal = sameSite(base, absUrl);
    const key = urlKey(absUrl);
    page.links.push({ href: absUrl, text, rel, internal, raw_href: rawHref });
    if (seenLinks.has(key)) continue;
    seenLinks.add(key);
    if (!internal && page.external_links.length < 60) page.external_links.push(absUrl);
  }

  // -- buttons ------------------------------------------------------------------------
  const buttonEls = [
    ...tree.querySelectorAll("button"),
    ...tree.querySelectorAll("input").filter((i) => (i.getAttribute("type") || "").toLowerCase() === "submit"),
    ...tree.querySelectorAll(".btn"),
    ...tree.querySelectorAll(".button"),
  ];
  for (const b of buttonEls) {
    const label = (cleanText(b.text) || b.getAttribute("value") || "").trim();
    if (label && !page.buttons.includes(label) && page.buttons.length < 60) page.buttons.push(label.slice(0, 120));
  }

  // -- forms --------------------------------------------------------------------------
  const labelForIds = new Set(tree.querySelectorAll("label").map((l) => l.getAttribute("for")).filter(Boolean) as string[]);
  for (const form of tree.querySelectorAll("form")) {
    const info: FormInfo = {
      action: (form.getAttribute("action") || "").trim(),
      method: (form.getAttribute("method") || "get").toLowerCase(),
      input_types: [], input_names: [], has_email_field: false, has_phone_field: false,
      has_message_field: false, submit_text: "", is_search: false, is_newsletter: false,
      labelled_inputs: 0, unlabelled_inputs: 0,
    };
    const blob = `${info.action} ${form.getAttribute("id") || ""} ${form.getAttribute("class") || ""}`.toLowerCase();
    const fields = [...form.querySelectorAll("input"), ...form.querySelectorAll("textarea"), ...form.querySelectorAll("select")];
    for (const inp of fields) {
      const tag = inp.tagName.toLowerCase();
      const itype = (inp.getAttribute("type") || tag || "text").toLowerCase();
      if (["hidden", "submit", "button", "image"].includes(itype)) continue;
      const iname = (inp.getAttribute("name") || inp.getAttribute("id") || "").toLowerCase();
      const ph = (inp.getAttribute("placeholder") || "").toLowerCase();
      info.input_types.push(itype);
      if (iname) info.input_names.push(iname);

      const iid = inp.getAttribute("id");
      let hasLabel = Boolean(
        (iid && labelForIds.has(iid)) || inp.getAttribute("aria-label") || inp.getAttribute("aria-labelledby") || inp.getAttribute("title"),
      );
      if (!hasLabel) {
        let anc: HTMLElement | null = inp.parentNode as HTMLElement | null;
        for (let i = 0; i < 3 && anc; i++) {
          if (anc.tagName === "LABEL") {
            hasLabel = true;
            break;
          }
          anc = anc.parentNode as HTMLElement | null;
        }
      }
      if (hasLabel) info.labelled_inputs += 1;
      else info.unlabelled_inputs += 1;

      const probe = `${itype} ${iname} ${ph}`;
      if (itype === "email" || probe.includes("email") || probe.includes("mail")) info.has_email_field = true;
      if (itype === "tel" || ["phone", "tel", "mobile", "number"].some((k) => probe.includes(k))) info.has_phone_field = true;
      if (tag === "textarea" || ["message", "comment", "enquiry", "inquiry", "detail", "describe"].some((k) => probe.includes(k))) {
        info.has_message_field = true;
      }
    }
    const sub = form.querySelector("button") || form.querySelectorAll("input").find((i) => (i.getAttribute("type") || "").toLowerCase() === "submit");
    if (sub) info.submit_text = (cleanText(sub.text) || sub.getAttribute("value") || "").slice(0, 120);
    info.is_search = blob.includes("search") || info.input_names.some((n) => n.includes("search") || n === "q" || n === "s");
    info.is_newsletter = ["newsletter", "subscribe", "mailchimp", "signup-form", "mc4wp"].some((k) =>
      `${blob} ${info.submit_text.toLowerCase()}`.includes(k),
    );
    page.forms.push(info);
  }

  // -- header / footer / above-the-fold -------------------------------------------------
  const header = tree.querySelector("header") || tree.querySelector("#header") || tree.querySelector(".header");
  if (header) page.header_html = (header.innerHTML || "").slice(0, 60000);
  const footer = tree.querySelector("footer") || tree.querySelector("#footer") || tree.querySelector(".footer");
  if (footer) page.footer_html = (footer.innerHTML || "").slice(0, 60000);

  // -- landmarks ------------------------------------------------------------------------
  page.has_main_landmark = Boolean(tree.querySelector("main") || tree.querySelector('[role="main"]'));
  page.has_nav_landmark = Boolean(tree.querySelector("nav") || tree.querySelector('[role="navigation"]'));
  for (const a of tree.querySelectorAll("a")) {
    const href = a.getAttribute("href") || "";
    if (!href.startsWith("#")) continue;
    const t = cleanText(a.text).toLowerCase();
    if (t.includes("skip") && (t.includes("content") || t.includes("main") || t.includes("navigation"))) {
      page.has_skip_link = true;
      break;
    }
  }

  const body = tree.querySelector("body");
  if (body) {
    for (const tag of DROP_TAGS) for (const node of body.querySelectorAll(tag)) node.remove();
    page.text = cleanText(body.text);
    page.above_fold_html = (page.header_html || "") + (body.innerHTML || "").slice(0, 18000);
    page.above_fold_text = page.text.slice(0, 1600);
  }

  page.word_count = page.text ? page.text.split(/\s+/).filter(Boolean).length : 0;
  return page;
}

export function jsonldOfType(page: ParsedPage, ...types: string[]): Record<string, any>[] {
  const wanted = new Set(types.map((t) => t.toLowerCase()));
  const out: Record<string, any>[] = [];
  for (const block of page.jsonld) {
    const t = block["@type"] ?? block["type"] ?? "";
    const names = new Set((Array.isArray(t) ? t : [t]).map((x) => String(x).toLowerCase()));
    if ([...names].some((n) => wanted.has(n))) out.push(block);
  }
  return out;
}
