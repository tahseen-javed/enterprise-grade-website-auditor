// Public contact extraction from crawled pages — used as audit evidence
// (e.g. "does this site publish a real email/phone/contact route"). Ported
// from backend/app/core/extract.py.
import type { CrawlResult } from "./crawler";
import type { ParsedPage } from "./page";
import { registrableDomain } from "./urls";

const EMAIL_RE = /(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+)/g;

const DOT_SEP = "(?:\\s*(?:\\[dot\\]|\\(dot\\)|\\{dot\\})\\s*|\\s+dot\\s+|\\.)";
const OBFUSCATED_RE = new RegExp(
  `([A-Za-z0-9._%+-]{1,64})\\s*(?:\\[at\\]|\\(at\\)|\\{at\\}|\\s+at\\s+|&#64;|%40)\\s*((?:[A-Za-z0-9-]{1,63}${DOT_SEP})+[A-Za-z]{2,24})`,
  "gi",
);
const DOT_SEP_RE = new RegExp(DOT_SEP, "gi");

function deobfuscateDomain(raw: string): string {
  const parts = raw.split(DOT_SEP_RE).map((p) => p.trim()).filter(Boolean);
  return parts.join(".");
}

const LINKEDIN_COMPANY_RE = /^https?:\/\/(?:[a-z]{2,3}\.)?linkedin\.com\/(company|showcase)\/([^/?#]+)/i;

function linkedinCompanyUrl(href: string): string | null {
  const m = LINKEDIN_COMPANY_RE.exec((href || "").trim());
  if (!m) return null;
  return `https://www.linkedin.com/${m[1].toLowerCase()}/${m[2]}`;
}

const IMAGE_TLD_FALSE_POSITIVES = new Set([
  "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp", "tiff", "css", "js",
  "json", "xml", "woff", "woff2", "ttf", "eot", "mp4", "webm", "pdf", "zip",
]);

const JUNK_LOCAL_PARTS = new Set([
  "example", "user", "username", "your", "youremail", "email", "name", "test",
  "someone", "john.doe", "jane.doe", "firstname", "lastname", "no-reply-test",
  "domain", "yourname", "mail", "abc", "xyz", "sample",
]);

const JUNK_DOMAINS = new Set([
  "example.com", "example.org", "example.net", "domain.com", "yourdomain.com",
  "yoursite.com", "email.com", "test.com", "sentry.io", "sentry-next.wixpress.com",
  "wixpress.com", "wix.com", "squarespace.com", "godaddy.com", "shopify.com",
  "w3.org", "schema.org", "adobe.com", "googleapis.com", "gstatic.com",
  "cloudflare.com", "jquery.com", "bootstrapcdn.com", "fontawesome.com",
  "gravatar.com", "placeholder.com", "mysite.com", "site.com", "company.com",
]);

const JUNK_PREFIXES = ["no-reply", "noreply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster", "abuse", "wordpress", "wp@", "root@"];

export const ROLE_LOCAL_PARTS = new Set([
  "info", "hello", "contact", "sales", "support", "enquiries", "enquiry", "inquiries",
  "admin", "office", "team", "help", "service", "customerservice", "bookings",
  "booking", "reception", "mail", "hi", "hey", "ask", "general", "reservations",
  "appointments", "orders", "accounts", "billing", "care", "frontdesk", "studio",
]);

const PREFERRED_ORDER = [
  "info", "hello", "contact", "enquiries", "enquiry", "inquiries", "office",
  "sales", "bookings", "booking", "appointments", "reception", "hi", "team",
  "admin", "support", "help", "service",
];

const PAGE_TYPE_WEIGHT: Record<string, number> = {
  contact: 1.0, homepage: 0.92, about: 0.85, team: 0.8, booking: 0.8,
  services: 0.7, locations: 0.7, pricing: 0.65, testimonials: 0.5, blog: 0.35, other: 0.5,
};

const SOURCE_TYPE_WEIGHT: Record<string, number> = { mailto: 1.0, jsonld: 0.95, text: 0.85, obfuscated: 0.8, footer: 0.9 };

export interface FoundEmail {
  email: string;
  source_url: string;
  source_type: string;
  page_type: string;
  confidence: number;
  is_role: boolean;
  domain_matches_site: boolean;
  context: string;
}

export interface ExtractionResult {
  emails: FoundEmail[];
  whatsapp_links: string[];
  whatsapp_numbers: string[];
  social_links: string[];
  linkedin_urls: string[];
  contact_form_urls: string[];
  contact_names: string[];
}

function emptyResult(): ExtractionResult {
  return { emails: [], whatsapp_links: [], whatsapp_numbers: [], social_links: [], linkedin_urls: [], contact_form_urls: [], contact_names: [] };
}

function cleanCandidate(localRaw: string, domainRaw: string): string | null {
  const local = localRaw.replace(/^[\s.,;:<>()[\]'"]+|[\s.,;:<>()[\]'"]+$/g, "").replace(/^-+/, "");
  let domain = domainRaw.replace(/^[\s.,;:<>()[\]'"]+|[\s.,;:<>()[\]'"]+$/g, "").toLowerCase().replace(/\.+$/, "");
  if (!local || !domain || !domain.includes(".")) return null;

  const tld = domain.split(".").pop() || "";
  if (IMAGE_TLD_FALSE_POSITIVES.has(tld) || /^\d+$/.test(tld) || tld.length < 2) return null;
  if (local.length > 64 || domain.length > 253) return null;
  if (JUNK_DOMAINS.has(domain) || [...JUNK_DOMAINS].some((d) => domain.endsWith("." + d))) return null;

  const lowLocal = local.toLowerCase();
  if (JUNK_LOCAL_PARTS.has(lowLocal)) return null;
  if (JUNK_PREFIXES.some((p) => lowLocal.startsWith(p.replace(/@$/, "")))) return null;
  if (lowLocal.length > 30 && /^[0-9a-f]+$/.test(lowLocal)) return null;
  if (/^[0-9a-f]{16,}$/.test(lowLocal)) return null;
  if (!/^[A-Za-z0-9._%+-]+$/.test(local)) return null;

  return `${lowLocal}@${domain}`;
}

function scanText(text: string): [string, string, string][] {
  const out: [string, string, string][] = [];
  for (const m of text.matchAll(EMAIL_RE)) {
    const cleaned = cleanCandidate(m[1], m[2]);
    if (cleaned) {
      const start = Math.max(0, (m.index ?? 0) - 60);
      out.push([cleaned, "text", text.slice(start, (m.index ?? 0) + m[0].length + 40).trim()]);
    }
  }
  for (const m of text.matchAll(OBFUSCATED_RE)) {
    const cleaned = cleanCandidate(m[1], deobfuscateDomain(m[2]));
    if (cleaned) {
      const start = Math.max(0, (m.index ?? 0) - 60);
      out.push([cleaned, "obfuscated", text.slice(start, (m.index ?? 0) + m[0].length + 40).trim()]);
    }
  }
  return out;
}

function walkJsonld(obj: any, found: string[]): void {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj)) {
      if (k.toLowerCase() === "email" && typeof v === "string") found.push(v);
      else walkJsonld(v, found);
    }
  } else if (Array.isArray(obj)) {
    for (const item of obj) walkJsonld(item, found);
  }
}

function decodeHtmlEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&#x2f;/gi, "/")
    .replace(/&nbsp;/g, " ");
}

export function extractContacts(crawl: CrawlResult, siteDomain = ""): ExtractionResult {
  const result = emptyResult();
  const domain = (siteDomain || registrableDomain(crawl.final_url || crawl.start_url)).toLowerCase();
  const byEmail = new Map<string, FoundEmail>();

  const record = (email: string, page: ParsedPage, sourceType: string, context = "") => {
    const key = email.toLowerCase();
    const emailDomain = key.split("@")[1];
    const local = key.split("@")[0];
    const isRole = ROLE_LOCAL_PARTS.has(local);
    const matches = Boolean(domain) && emailDomain === domain;

    let conf = 0.5;
    conf += 0.25 * (SOURCE_TYPE_WEIGHT[sourceType] ?? 0.6);
    conf *= 0.6 + 0.4 * (PAGE_TYPE_WEIGHT[page.page_type] ?? 0.5);
    if (matches) conf += 0.22;
    if (isRole) conf += 0.06;
    conf = Math.round(Math.min(0.99, conf) * 1000) / 1000;

    const existing = byEmail.get(key);
    if (existing && existing.confidence >= conf) return;
    byEmail.set(key, {
      email: key, source_url: page.final_url || page.url, source_type: sourceType, page_type: page.page_type,
      confidence: conf, is_role: isRole, domain_matches_site: matches, context: (context || "").slice(0, 240),
    });
  };

  for (const page of crawl.pages) {
    for (const addr of page.mailto) {
      if (addr.includes("@")) {
        const [l, d] = [addr.split("@")[0], addr.split("@").slice(1).join("@")];
        const cleaned = cleanCandidate(l, d);
        if (cleaned) record(cleaned, page, "mailto", "mailto: link");
      }
    }
    for (const [email, kind, ctx] of scanText(page.text)) record(email, page, kind, ctx);

    for (const blob of [page.footer_html, page.header_html]) {
      if (!blob) continue;
      const unescaped = decodeHtmlEntities(blob).replace(/<[^>]+>/g, " ");
      const isFooter = blob === page.footer_html;
      for (const [email, kind, ctx] of scanText(unescaped)) record(email, page, isFooter ? "footer" : kind, ctx);
    }

    const jl: string[] = [];
    for (const block of page.jsonld) walkJsonld(block, jl);
    for (const addr of jl) {
      if (addr.includes("@")) {
        const l = addr.split("@")[0];
        const d = addr.split("@").slice(1).join("@");
        const cleaned = cleanCandidate(l, d);
        if (cleaned) record(cleaned, page, "jsonld", "structured data");
      }
    }

    for (const wa of page.whatsapp_links) {
      if (!result.whatsapp_links.includes(wa)) result.whatsapp_links.push(wa);
      const m = /(?:wa\.me\/|phone=|send\?phone=)(\+?\d{6,20})/.exec(wa);
      if (m) {
        const num = m[1].replace(/\D/g, "");
        if (num && !result.whatsapp_numbers.includes(num)) result.whatsapp_numbers.push(num);
      }
    }
    for (const s of page.social_links) {
      if (!result.social_links.includes(s) && result.social_links.length < 20) result.social_links.push(s);
      const li = linkedinCompanyUrl(s);
      if (li && !result.linkedin_urls.includes(li)) result.linkedin_urls.push(li);
    }

    for (const form of page.forms) {
      if (form.is_search || form.is_newsletter) continue;
      if (form.has_email_field || form.has_message_field || form.has_phone_field) {
        const u = page.final_url || page.url;
        if (!result.contact_form_urls.includes(u)) result.contact_form_urls.push(u);
      }
    }

    result.contact_names.push(...extractContactNames(page));
  }

  const seenNames = new Set<string>();
  result.contact_names = result.contact_names
    .filter((n) => {
      const k = n.toLowerCase();
      if (seenNames.has(k)) return false;
      seenNames.add(k);
      return true;
    })
    .slice(0, 8);

  const emails = [...byEmail.values()].sort((a, b) => b.confidence - a.confidence);
  result.emails = rankEmails(emails, domain);
  return result;
}

function rankEmails(emails: FoundEmail[], siteDomain: string): FoundEmail[] {
  return [...emails].sort((a, b) => {
    const key = (e: FoundEmail): [number, number, number, string] => {
      const local = e.email.split("@")[0];
      let roleRank = PREFERRED_ORDER.indexOf(local);
      if (roleRank === -1) roleRank = PREFERRED_ORDER.length + (e.is_role ? 0 : 1);
      return [e.domain_matches_site ? 0 : 1, roleRank, -e.confidence, e.email];
    };
    const ka = key(a);
    const kb = key(b);
    for (let i = 0; i < 3; i++) {
      if (ka[i] !== kb[i]) return (ka[i] as number) - (kb[i] as number);
    }
    return String(ka[3]).localeCompare(String(kb[3]));
  });
}

const NAME_LABEL_RE = /\b(owner|founder|co-founder|director|manager|principal|proprietor|ceo|practice manager|head of|lead|partner)\b/gi;
const NAME_RE = /\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,20})\b/g;

const NAME_STOPWORDS = new Set([
  "contact", "about", "our", "team", "the", "we", "us", "home", "service", "services",
  "get", "free", "call", "book", "read", "more", "learn", "view", "all", "why",
  "choose", "welcome", "new", "best", "top", "quality", "customer", "client",
  "privacy", "policy", "terms", "google", "facebook", "instagram", "monday",
  "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january",
  "february", "march", "april", "may", "june", "july", "august", "september",
  "october", "november", "december", "united", "states", "kingdom", "north",
  "south", "east", "west", "street", "road", "avenue", "suite",
]);

function isPlausiblePersonName(candidate: string): boolean {
  const parts = candidate.split(" ");
  if (parts.length !== 2) return false;
  return !parts.some((p) => NAME_STOPWORDS.has(p.toLowerCase()));
}

function extractContactNames(page: ParsedPage): string[] {
  if (!["about", "team", "contact", "homepage"].includes(page.page_type)) return [];
  const names: string[] = [];
  const windows: string[] = [...page.h2, ...page.h3];
  for (const m of page.text.matchAll(NAME_LABEL_RE)) {
    const start = Math.max(0, (m.index ?? 0) - 90);
    windows.push(page.text.slice(start, (m.index ?? 0) + m[0].length + 90));
  }
  const headings = new Set([...page.h2, ...page.h3]);
  for (const w of windows) {
    if (!NAME_LABEL_RE.test(w) && !headings.has(w)) continue;
    NAME_LABEL_RE.lastIndex = 0;
    for (const nm of w.matchAll(NAME_RE)) {
      const candidate = `${nm[1]} ${nm[2]}`;
      if (isPlausiblePersonName(candidate)) names.push(candidate);
    }
  }
  return names.slice(0, 5);
}
