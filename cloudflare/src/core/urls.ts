// URL normalization, domain handling, and business/website identity matching.
// Ported from backend/app/core/urls.py — logic and thresholds unchanged.
import { getDomain } from "tldts";

const TRACKING_PARAMS = new Set([
  "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
  "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref", "referrer", "_ga", "yclid",
]);

const SOCIAL_HOSTS = new Set([
  "facebook.com", "m.facebook.com", "fb.com", "fb.me", "instagram.com", "twitter.com",
  "x.com", "linkedin.com", "youtube.com", "youtu.be", "tiktok.com", "pinterest.com",
  "snapchat.com", "threads.net", "wa.me", "api.whatsapp.com", "t.me", "telegram.me",
]);

const DIRECTORY_HOSTS = new Set([
  "yelp.com", "yellowpages.com", "yell.com", "tripadvisor.com", "trustpilot.com",
  "google.com", "goo.gl", "maps.app.goo.gl", "business.site", "bing.com",
  "foursquare.com", "angi.com", "angieslist.com", "houzz.com", "thumbtack.com",
  "checkatrade.com", "bark.com", "truelocal.com.au", "hotfrog.com", "manta.com",
  "bbb.org", "opentable.com", "doordash.com", "ubereats.com", "grubhub.com",
  "booksy.com", "fresha.com", "treatwell.com", "zocdoc.com", "healthgrades.com",
]);

const LINK_IN_BIO_HOSTS = new Set(["linktr.ee", "linkin.bio", "beacons.ai", "carrd.co", "bio.link", "milkshake.app"]);

const NON_HTML_EXT = new Set([
  ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".zip", ".rar",
  ".mp4", ".mp3", ".avi", ".mov", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
  ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf", ".eot", ".dmg", ".exe",
]);

const LEGAL_SUFFIXES = new Set([
  "llc", "inc", "ltd", "limited", "plc", "co", "corp", "corporation", "company",
  "gmbh", "pty", "pvt", "private", "llp", "lp", "sa", "srl", "bv", "nv", "ag", "ab",
  "oy", "as", "kft", "spa", "sl", "the", "and", "of",
]);

const GENERIC_WORDS = new Set([
  "services", "service", "solutions", "group", "center", "centre", "shop", "store",
  "studio", "clinic", "salon", "cafe", "restaurant", "bar", "hotel", "school",
  "academy", "agency", "consulting", "consultants", "partners", "associates",
]);

export function normalizeUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let url = String(raw).trim().replace(/^"|"$/g, "").replace(/^'|'$/g, "");
  if (!url || ["n/a", "na", "none", "null", "-", "no website", "nan"].includes(url.toLowerCase())) return null;

  url = url.replace(/\s+/g, "");
  if (url.startsWith("//")) url = "https:" + url;
  if (!/^[a-zA-Z][a-zA-Z0-9+.\-]*:\/\//.test(url)) {
    if (!url.split("/")[0].includes(".")) return null;
    url = "https://" + url;
  }

  let p: URL;
  try {
    p = new URL(url);
  } catch {
    return null;
  }
  if (p.protocol !== "http:" && p.protocol !== "https:" || !p.host) return null;

  let host = p.host.toLowerCase();
  if (host.endsWith(":80")) host = host.slice(0, -3);
  else if (host.endsWith(":443")) host = host.slice(0, -4);
  if (!host.split(":")[0].includes(".")) return null;

  const path = p.pathname || "/";
  const query = stripTracking(p.search.replace(/^\?/, ""));
  return `${p.protocol}//${host}${path}${query ? "?" + query : ""}`;
}

function stripTracking(query: string): string {
  if (!query) return "";
  const kept: string[] = [];
  for (const part of query.split("&")) {
    if (!part) continue;
    const key = part.split("=", 1)[0].toLowerCase();
    if (!TRACKING_PARAMS.has(key)) kept.push(part);
  }
  return kept.join("&");
}

export function registrableDomain(url: string | null | undefined): string {
  if (!url) return "";
  let host: string;
  try {
    host = new URL(url).host || url;
  } catch {
    host = url;
  }
  host = host.split("@").pop()!.split(":")[0].toLowerCase();
  return getDomain(host, { allowPrivateDomains: true }) || host;
}

export function hostOf(url: string): string {
  try {
    return (new URL(url).host || "").split(":")[0].toLowerCase();
  } catch {
    return "";
  }
}

export function originOf(url: string): string {
  try {
    const p = new URL(url);
    if (!p.host) return "";
    return `${(p.protocol || "https:").toLowerCase()}//${p.host.toLowerCase()}`;
  } catch {
    return "";
  }
}

export function sameSite(a: string, b: string): boolean {
  const da = registrableDomain(a);
  const db = registrableDomain(b);
  return Boolean(da) && da === db;
}

export function isNonWebsiteHost(url: string): { isProfile: boolean; kind: string } {
  const dom = registrableDomain(url);
  const host = hostOf(url);
  if (!dom) return { isProfile: false, kind: "" };
  if (SOCIAL_HOSTS.has(dom) || SOCIAL_HOSTS.has(host)) return { isProfile: true, kind: "social_profile" };
  if (DIRECTORY_HOSTS.has(dom) || DIRECTORY_HOSTS.has(host)) return { isProfile: true, kind: "directory_listing" };
  if (LINK_IN_BIO_HOSTS.has(dom) || LINK_IN_BIO_HOSTS.has(host)) return { isProfile: true, kind: "link_in_bio" };
  return { isProfile: false, kind: "" };
}

export function isCrawlable(url: string): boolean {
  let p: URL;
  try {
    p = new URL(url);
  } catch {
    return false;
  }
  if (p.protocol !== "http:" && p.protocol !== "https:") return false;
  const path = (p.pathname || "").toLowerCase();
  for (const ext of NON_HTML_EXT) if (path.endsWith(ext)) return false;
  return true;
}

export function absolutize(base: string, href: string | null | undefined): string | null {
  if (!href) return null;
  href = href.trim();
  const low = href.toLowerCase();
  if (["javascript:", "mailto:", "tel:", "sms:", "data:", "#", "callto:", "whatsapp:"].some((p) => low.startsWith(p))) {
    return null;
  }
  let joined: string;
  try {
    joined = new URL(href, base).toString();
  } catch {
    return null;
  }
  joined = joined.split("#")[0];
  return normalizeUrl(joined);
}

export function urlKey(url: string): string {
  if (!url) return "";
  let p: URL;
  try {
    p = new URL(url);
  } catch {
    return url;
  }
  const host = (p.host || "").toLowerCase().replace(/^www\./, "").split(":")[0];
  let path = (p.pathname || "/").replace(/\/(index|default|home)\.(html?|php|aspx?)$/i, "/");
  path = path.replace(/\/+$/, "") || "/";
  const q = p.search ? p.search : "";
  return `${host}${path}${q}`.toLowerCase();
}

// -- identity matching ------------------------------------------------------

export function nameTokens(name: string): string[] {
  let n = (name || "").toLowerCase();
  n = n.replace(/[&+]/g, " and ");
  n = n.replace(/[^a-z0-9]+/g, " ");
  return n.split(/\s+/).filter((t) => t && !LEGAL_SUFFIXES.has(t) && t.length > 1);
}

export function distinctiveTokens(name: string): string[] {
  const toks = nameTokens(name);
  const distinct = toks.filter((t) => !GENERIC_WORDS.has(t));
  return distinct.length ? distinct : toks;
}

function domainCore(url: string): string {
  const dom = registrableDomain(url);
  const ext = getDomain(dom, { allowPrivateDomains: true });
  const label = (ext || dom).split(".")[0] || dom;
  return label.toLowerCase().replace(/[^a-z0-9]/g, "");
}

export interface IdentitySignal {
  signal: string;
  weight: number;
  detail: string;
}

export interface IdentityScore {
  confidence: number;
  verdict: "strong_match" | "probable_match" | "weak_match" | "no_match";
  signals: IdentitySignal[];
}

export function scoreIdentity(opts: {
  businessName: string;
  url: string;
  pageTitle?: string;
  pageText?: string;
  phoneDigits?: string[];
  city?: string;
  postalCode?: string;
  address?: string;
  category?: string;
}): IdentityScore {
  const signals: IdentitySignal[] = [];
  let score = 0;

  const distinct = distinctiveTokens(opts.businessName);
  const core = domainCore(opts.url);
  const textL = (opts.pageText || "").toLowerCase();
  const titleL = (opts.pageTitle || "").toLowerCase();

  if (core && distinct.length) {
    const joined = distinct.join("");
    const initials = distinct.map((t) => t[0]).join("");
    if (joined && core.includes(joined)) {
      score += 0.45;
      signals.push({ signal: "domain_matches_full_name", weight: 0.45, detail: core });
    } else {
      const hits = distinct.filter((t) => t.length >= 4 && core.includes(t));
      if (hits.length) {
        const gain = 0.34 * (hits.length / distinct.length);
        score += gain;
        signals.push({ signal: "domain_matches_name_tokens", weight: round(gain, 3), detail: hits.join(",") });
      } else if (initials.length >= 3 && core.includes(initials)) {
        score += 0.16;
        signals.push({ signal: "domain_matches_initials", weight: 0.16, detail: initials });
      }
    }
  }

  if (titleL && distinct.length) {
    const hits = distinct.filter((t) => titleL.includes(t));
    if (hits.length && hits.length / distinct.length >= 0.6) {
      score += 0.22;
      signals.push({ signal: "name_in_title", weight: 0.22, detail: (opts.pageTitle || "").slice(0, 120) });
    } else if (hits.length) {
      score += 0.1;
      signals.push({ signal: "partial_name_in_title", weight: 0.1, detail: hits.join(",") });
    }
  }

  if (textL && distinct.length) {
    const hits = distinct.filter((t) => textL.includes(t));
    if (hits.length === distinct.length) {
      score += 0.14;
      signals.push({ signal: "name_in_page_text", weight: 0.14, detail: "all tokens" });
    } else if (hits.length) {
      score += 0.07;
      signals.push({ signal: "partial_name_in_page_text", weight: 0.07, detail: hits.join(",") });
    }
  }

  if (opts.phoneDigits?.length) {
    const pageDigits = textL.replace(/\D/g, "");
    for (const pd of opts.phoneDigits) {
      const tail = pd.replace(/\D/g, "").slice(-9);
      if (tail.length >= 7 && pageDigits.includes(tail)) {
        score += 0.28;
        signals.push({ signal: "phone_found_on_site", weight: 0.28, detail: pd });
        break;
      }
    }
  }

  if (opts.postalCode && opts.postalCode.trim().length >= 4) {
    const pc = opts.postalCode.trim().toLowerCase().replace(/\s+/g, "");
    if (pc && textL.replace(/\s+/g, "").includes(pc)) {
      score += 0.12;
      signals.push({ signal: "postal_code_on_site", weight: 0.12, detail: opts.postalCode });
    }
  }
  if (opts.city && opts.city.length > 2 && textL.includes(opts.city.toLowerCase())) {
    score += 0.08;
    signals.push({ signal: "city_on_site", weight: 0.08, detail: opts.city });
  }
  if (opts.address) {
    const street = opts.address.toLowerCase().replace(/[^a-z0-9 ]/g, " ");
    const parts = street.split(/\s+/).filter((p) => p.length > 3).slice(0, 4);
    if (parts.length && parts.filter((p) => textL.includes(p)).length >= Math.max(2, parts.length - 1)) {
      score += 0.1;
      signals.push({ signal: "address_on_site", weight: 0.1, detail: opts.address.slice(0, 120) });
    }
  }
  if (opts.category) {
    const catToks = opts.category.toLowerCase().split(/[^a-z]+/).filter((t) => t.length > 3);
    if (catToks.length && catToks.some((t) => textL.includes(t))) {
      score += 0.05;
      signals.push({ signal: "category_language_present", weight: 0.05, detail: opts.category });
    }
  }

  const confidence = round(Math.min(1, score), 3);
  const verdict = confidence >= 0.8 ? "strong_match" : confidence >= 0.55 ? "probable_match" : confidence >= 0.3 ? "weak_match" : "no_match";
  return { confidence, verdict, signals };
}

export function candidateDomains(businessName: string, tlds: string[] = [".com"]): string[] {
  const distinct = distinctiveTokens(businessName);
  if (!distinct.length) return [];
  const joined = distinct.join("");
  const hyphen = distinct.join("-");

  const bases: string[] = [];
  if (joined.length >= 3 && joined.length <= 30) bases.push(joined);
  if (distinct.length > 1 && hyphen.length >= 3 && hyphen.length <= 34) bases.push(hyphen);
  if (distinct.length > 2) {
    const short = distinct.slice(0, 2).join("");
    if (short.length >= 3 && short.length <= 30) bases.push(short);
  }

  const out: string[] = [];
  const seen = new Set<string>();
  for (const base of bases) {
    for (const tld of tlds) {
      const d = `https://${base}${tld}`;
      if (!seen.has(d)) {
        seen.add(d);
        out.push(d);
      }
    }
  }
  return out.slice(0, 6);
}

const COUNTRY_TLDS: Record<string, string[]> = {
  US: [".com", ".net"], CA: [".ca", ".com"], GB: [".co.uk", ".com", ".uk"],
  AU: [".com.au", ".com", ".au"], NZ: [".co.nz", ".com"], IE: [".ie", ".com"],
  PK: [".com.pk", ".pk", ".com"], IN: [".in", ".co.in", ".com"], DE: [".de", ".com"],
  FR: [".fr", ".com"], NL: [".nl", ".com"], ES: [".es", ".com"], IT: [".it", ".com"],
  ZA: [".co.za", ".com"], AE: [".ae", ".com"],
};

export function tldsForRegion(region?: string | null): string[] {
  return COUNTRY_TLDS[(region || "").toUpperCase()] || [".com", ".net"];
}

function round(n: number, digits: number): number {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}
