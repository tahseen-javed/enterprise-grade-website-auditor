// Website discovery + validation. Ported from backend/app/core/discovery.py.
import { Fetcher } from "./fetcher";
import { parseHtml } from "./page";
import { candidateDomains, isNonWebsiteHost, normalizeUrl, registrableDomain, scoreIdentity, tldsForRegion, IdentityScore } from "./urls";

export const STATUS_VALID = "valid";
export const STATUS_REDIRECTED = "redirected";
export const STATUS_UNAVAILABLE = "unavailable";
export const STATUS_BLOCKED = "blocked";
export const STATUS_MISMATCH = "mismatch";
export const STATUS_NOT_FOUND = "not_found";
export const STATUS_NOT_A_WEBSITE = "not_a_website";
export const STATUS_NO_WEBSITE = "no_website";

export interface DiscoveryResult {
  website_original: string;
  website_final: string;
  status: string;
  source: string;
  identity_confidence: number | null;
  identity_verdict: string;
  identity_signals: IdentityScore["signals"];
  notes: string[];
  error_code: string;
  error_message: string;
  redirect_chain: string[];
  http_status: number | null;
  response_ms: number | null;
  candidates_tried: string[];
  social_profile_url: string;
}

export function hasWebsite(d: DiscoveryResult): boolean {
  return (d.status === STATUS_VALID || d.status === STATUS_REDIRECTED) && Boolean(d.website_final);
}

function base(websiteOriginal: string, source = ""): DiscoveryResult {
  return {
    website_original: websiteOriginal, website_final: "", status: STATUS_NO_WEBSITE, source,
    identity_confidence: null, identity_verdict: "", identity_signals: [], notes: [],
    error_code: "", error_message: "", redirect_chain: [], http_status: null, response_ms: null,
    candidates_tried: [], social_profile_url: "",
  };
}

/** Direct-URL audit path: the user explicitly supplied this URL, so identity
 * scoring does not apply - it is the ground truth. Never guesses a domain. */
export async function verifyDirectWebsite(fetcher: Fetcher, url: string): Promise<DiscoveryResult> {
  const out = base((url || "").trim(), "manual");
  const norm = normalizeUrl(url);
  if (!norm) {
    out.status = STATUS_NOT_FOUND;
    out.notes.push("That URL could not be parsed.");
    return out;
  }

  const { isProfile, kind } = isNonWebsiteHost(norm);
  if (isProfile) {
    out.status = STATUS_NOT_A_WEBSITE;
    out.social_profile_url = norm;
    out.notes.push(`This is a ${kind.replace(/_/g, " ")}, not a standalone website that can be audited.`);
    return out;
  }

  const res = await fetcher.fetch(norm);
  out.http_status = res.status;
  out.response_ms = res.elapsed_ms;
  out.redirect_chain = res.redirect_chain;
  if (!res.ok) {
    out.error_code = res.error_code;
    out.error_message = res.error_message;
    out.status = res.error_code === "blocked" ? STATUS_BLOCKED : STATUS_UNAVAILABLE;
    out.notes.push(res.error_message);
    return out;
  }

  const final = res.final_url || norm;
  out.website_final = final;
  out.identity_confidence = 1.0;
  out.identity_verdict = "explicit_url";
  out.identity_signals = [{ signal: "explicitly_supplied_url", weight: 1.0, detail: norm }];

  const same = registrableDomain(norm) === registrableDomain(final);
  out.status = same ? STATUS_VALID : STATUS_REDIRECTED;
  if (!same) {
    out.notes.push(`Redirects to a different domain: ${registrableDomain(final)}`);
    const { isProfile: isProfile2, kind: kind2 } = isNonWebsiteHost(final);
    if (isProfile2) {
      out.status = STATUS_NOT_A_WEBSITE;
      out.social_profile_url = final;
      out.notes.push(`The domain now redirects to a ${kind2.replace(/_/g, " ")}.`);
    }
  }
  return out;
}

interface Verified {
  finalUrl: string;
  httpStatus: number | null;
  responseMs: number | null;
  redirectChain: string[];
  errorCode: string;
  errorMessage: string;
  identity: IdentityScore;
  html: string;
}

async function fetchAndVerify(
  fetcher: Fetcher,
  url: string,
  ctx: { businessName: string; phoneDigits?: string[]; city?: string; postalCode?: string; address?: string; category?: string },
): Promise<Verified> {
  const res = await fetcher.fetch(url);
  const out: Verified = {
    finalUrl: res.final_url || url, httpStatus: res.status, responseMs: res.elapsed_ms,
    redirectChain: res.redirect_chain, errorCode: res.error_code, errorMessage: res.error_message,
    identity: { confidence: 0, verdict: "no_match", signals: [] }, html: "",
  };
  if (!res.ok) return out;

  const page = parseHtml(res.text, url, { final_url: res.final_url, status: res.status });
  out.html = res.text;
  out.identity = scoreIdentity({
    businessName: ctx.businessName, url: res.final_url || url, pageTitle: page.title,
    pageText: page.text.slice(0, 20000), phoneDigits: ctx.phoneDigits, city: ctx.city,
    postalCode: ctx.postalCode, address: ctx.address, category: ctx.category,
  });
  return out;
}

/** CSV-import identity-matching path. Reserved for API completeness — the
 * live UI only creates jobs via verifyDirectWebsite (Quick Audit). */
export async function discoverWebsite(
  fetcher: Fetcher,
  ctx: {
    businessName: string;
    websiteRaw?: string;
    phoneDigits?: string[];
    city?: string;
    state?: string;
    postalCode?: string;
    address?: string;
    category?: string;
    region?: string;
    enableGuessing?: boolean;
    minConfidence?: number;
    maxCandidates?: number;
  },
): Promise<DiscoveryResult> {
  const out = base((ctx.websiteRaw || "").trim());

  if (ctx.websiteRaw && ctx.websiteRaw.trim()) {
    const norm = normalizeUrl(ctx.websiteRaw);
    if (!norm) {
      out.status = STATUS_NOT_FOUND;
      out.source = "csv";
      out.notes.push("The website value in the CSV could not be parsed as a URL.");
      return out;
    }
    const { isProfile, kind } = isNonWebsiteHost(norm);
    if (isProfile) {
      out.status = STATUS_NOT_A_WEBSITE;
      out.source = "csv";
      out.social_profile_url = norm;
      out.notes.push(`The supplied URL is a ${kind.replace(/_/g, " ")}, not the business's own website.`);
      return out;
    }

    const verified = await fetchAndVerify(fetcher, norm, ctx);
    out.http_status = verified.httpStatus;
    out.response_ms = verified.responseMs;
    out.redirect_chain = verified.redirectChain;
    out.source = "csv";

    if (verified.errorCode) {
      out.error_code = verified.errorCode;
      out.error_message = verified.errorMessage;
      out.status = verified.errorCode === "blocked" ? STATUS_BLOCKED : STATUS_UNAVAILABLE;
      out.notes.push(verified.errorMessage);
      return out;
    }

    out.identity_confidence = verified.identity.confidence;
    out.identity_verdict = verified.identity.verdict;
    out.identity_signals = verified.identity.signals;
    out.website_final = verified.finalUrl;

    if (verified.identity.confidence < 0.2 && verified.identity.verdict === "no_match") {
      out.status = STATUS_MISMATCH;
      out.notes.push(
        "The page shows no sign of this business (name, phone or address). Treated as a possible mismatch and excluded from outreach.",
      );
      return out;
    }

    const same = registrableDomain(norm) === registrableDomain(verified.finalUrl);
    out.status = same ? STATUS_VALID : STATUS_REDIRECTED;
    if (!same) {
      out.notes.push(`Redirects to a different domain: ${registrableDomain(verified.finalUrl)}`);
      const { isProfile: isProfile2, kind: kind2 } = isNonWebsiteHost(verified.finalUrl);
      if (isProfile2) {
        out.status = STATUS_NOT_A_WEBSITE;
        out.social_profile_url = verified.finalUrl;
        out.notes.push(`The domain now redirects to a ${kind2.replace(/_/g, " ")}.`);
      }
    }
    return out;
  }

  if (!(ctx.enableGuessing ?? true)) {
    out.status = STATUS_NO_WEBSITE;
    out.source = "none";
    out.notes.push("No website in the CSV and automatic discovery is disabled.");
    return out;
  }

  const tlds = tldsForRegion(ctx.region);
  const candidates = candidateDomains(ctx.businessName, tlds).slice(0, ctx.maxCandidates ?? 4);
  out.candidates_tried = candidates;
  if (!candidates.length) {
    out.status = STATUS_NO_WEBSITE;
    out.source = "none";
    out.notes.push("The business name did not yield any usable domain candidate.");
    return out;
  }

  let best: Verified | null = null;
  for (const cand of candidates) {
    const verified = await fetchAndVerify(fetcher, cand, ctx);
    if (verified.errorCode) continue;
    if (!best || verified.identity.confidence > best.identity.confidence) best = verified;
    if (verified.identity.confidence >= 0.85) break;
  }

  if (!best) {
    out.status = STATUS_NO_WEBSITE;
    out.source = "none";
    out.notes.push(`No reachable website found for ${candidates.length} candidate domain(s).`);
    return out;
  }

  out.identity_confidence = best.identity.confidence;
  out.identity_verdict = best.identity.verdict;
  out.identity_signals = best.identity.signals;
  out.http_status = best.httpStatus;
  out.response_ms = best.responseMs;
  out.redirect_chain = best.redirectChain;

  const minConfidence = ctx.minConfidence ?? 0.55;
  if (best.identity.confidence >= minConfidence) {
    out.website_final = best.finalUrl;
    out.status = STATUS_VALID;
    out.source = "discovered";
    out.notes.push(`Discovered by domain guess and confirmed at ${Math.round(best.identity.confidence * 100)}% identity confidence.`);
  } else {
    out.status = STATUS_NO_WEBSITE;
    out.source = "none";
    out.notes.push(
      `A candidate domain responded but only matched this business at ${Math.round(best.identity.confidence * 100)}% confidence ` +
        `(threshold ${Math.round(minConfidence * 100)}%). Not attached, to avoid using another company's website.`,
    );
  }
  return out;
}
