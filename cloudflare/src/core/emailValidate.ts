// Email validation. Ported from backend/app/core/email_validate.py. DNS
// (MX/A record) lookups use Cloudflare's own DNS-over-HTTPS endpoint via
// fetch() instead of a resolver library — there is no raw-socket DNS access
// inside a Worker.
import { ROLE_LOCAL_PARTS, FoundEmail } from "./extract";
import { SubrequestBudget } from "./limits";

export const STATUS_VALID_PUBLIC = "valid_public";
export const STATUS_MX_VALID = "mx_valid";
export const STATUS_DOMAIN_VALID = "domain_valid";
export const STATUS_SYNTAX_VALID = "syntax_valid";
export const STATUS_RISKY = "risky";
export const STATUS_INVALID = "invalid";
export const STATUS_UNKNOWN = "unknown";

const DISPOSABLE_DOMAINS = new Set([
  "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
  "temp-mail.org", "throwawaymail.com", "yopmail.com", "sharklasers.com",
  "trashmail.com", "getnada.com", "maildrop.cc", "fakeinbox.com", "dispostable.com",
  "mailnesia.com", "mytemp.email", "spamgourmet.com", "moakt.com", "emailondeck.com",
  "tempinbox.com", "mailcatch.com", "grr.la", "guerrillamailblock.com", "spam4.me",
  "burnermail.io", "33mail.com", "anonaddy.me", "mail.tm", "inboxbear.com",
]);

const FREE_MAIL_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.com.au",
  "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com", "aol.com",
  "icloud.com", "me.com", "mac.com", "protonmail.com", "proton.me", "gmx.com",
  "gmx.de", "mail.com", "zoho.com", "yandex.com", "btinternet.com", "bigpond.com",
  "optusnet.com.au", "rediffmail.com", "web.de", "orange.fr", "free.fr",
]);

// RFC-5322-ish practical syntax check (not the full grammar, matches what
// the original email-validator library rejects/accepts for real addresses).
const EMAIL_SYNTAX_RE = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

export interface EmailValidation {
  email: string;
  status: string;
  domain: string;
  is_role: boolean;
  is_disposable: boolean;
  is_free_provider: boolean;
  domain_matches_site: boolean;
  mx_records: string[];
  notes: string[];
  confidence: number;
}

function baseValidation(email: string): EmailValidation {
  return {
    email, status: STATUS_UNKNOWN, domain: "", is_role: false, is_disposable: false,
    is_free_provider: false, domain_matches_site: false, mx_records: [], notes: [], confidence: 0,
  };
}

interface DnsLookup {
  mx: string[];
  hasA: boolean;
  err: string;
}

const dnsCache = new Map<string, DnsLookup>();

async function lookupDomain(domain: string, timeoutS: number, budget: SubrequestBudget): Promise<DnsLookup> {
  domain = domain.toLowerCase().replace(/\.+$/, "");
  const cached = dnsCache.get(domain);
  if (cached) return cached;
  if (!budget.take()) {
    const r = { mx: [], hasA: false, err: "budget_exhausted" };
    return r; // do not cache: a later, budgeted call might succeed
  }

  const result = await dohLookup(domain, timeoutS);
  dnsCache.set(domain, result);
  return result;
}

async function dohLookup(domain: string, timeoutS: number): Promise<DnsLookup> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutS * 1000);
  try {
    const mxResp = await fetch(`https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(domain)}&type=MX`, {
      headers: { accept: "application/dns-json" },
      signal: controller.signal,
    });
    const mxData = (await mxResp.json()) as any;
    if (mxData.Status === 3) return { mx: [], hasA: false, err: "nxdomain" };
    const mx = ((mxData.Answer || []) as any[])
      .filter((a) => a.type === 15)
      .map((a) => String(a.data).split(" ").slice(1).join(" ").replace(/\.$/, ""))
      .filter(Boolean)
      .sort();
    if (mx.length) return { mx, hasA: true, err: "" };

    const aResp = await fetch(`https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(domain)}&type=A`, {
      headers: { accept: "application/dns-json" },
      signal: controller.signal,
    });
    const aData = (await aResp.json()) as any;
    if (aData.Status === 3) return { mx: [], hasA: false, err: "nxdomain" };
    const hasA = Boolean((aData.Answer || []).length);
    return { mx: [], hasA, err: "" };
  } catch (exc: any) {
    const timedOut = exc?.name === "AbortError";
    return { mx: [], hasA: false, err: timedOut ? "timeout" : `dns_error:${exc?.message || exc}` };
  } finally {
    clearTimeout(timer);
  }
}

export async function validateFoundEmail(
  found: FoundEmail,
  opts: { siteDomain?: string; enableMx?: boolean; dnsTimeoutS?: number; budget: SubrequestBudget },
): Promise<EmailValidation> {
  const v = baseValidation(found.email);

  if (!EMAIL_SYNTAX_RE.test(found.email)) {
    v.status = STATUS_INVALID;
    v.notes.push("Syntax check failed.");
    v.confidence = 0;
    return v;
  }
  v.domain = found.email.split("@")[1].toLowerCase();
  const local = found.email.split("@")[0].toLowerCase();
  v.is_role = ROLE_LOCAL_PARTS.has(local);
  v.is_disposable = DISPOSABLE_DOMAINS.has(v.domain);
  v.is_free_provider = FREE_MAIL_DOMAINS.has(v.domain);
  v.domain_matches_site = Boolean(opts.siteDomain) && v.domain === (opts.siteDomain || "").toLowerCase();
  v.status = STATUS_SYNTAX_VALID;

  if (v.is_disposable) {
    v.status = STATUS_RISKY;
    v.notes.push("The domain is a known disposable/temporary mail provider.");
    v.confidence = 0.1;
    return v;
  }

  if (!(opts.enableMx ?? true)) {
    v.notes.push("DNS/MX lookup is disabled in settings; DNS was not checked.");
    v.confidence = round(0.45 + 0.1 * found.confidence, 3);
    return v;
  }

  const { mx, hasA, err } = await lookupDomain(v.domain, opts.dnsTimeoutS ?? 4, opts.budget);
  v.mx_records = mx.slice(0, 6);

  if (err === "nxdomain") {
    v.status = STATUS_INVALID;
    v.notes.push("The email domain does not exist (NXDOMAIN).");
    v.confidence = 0;
    return v;
  }
  if (err.startsWith("timeout") || err.startsWith("dns_error") || err === "budget_exhausted") {
    v.status = STATUS_UNKNOWN;
    v.notes.push(`DNS lookup could not be completed (${err}); status is unknown.`);
    v.confidence = round(0.3 + 0.1 * found.confidence, 3);
    return v;
  }

  if (mx.length) {
    v.status = STATUS_MX_VALID;
    v.notes.push(`The domain publishes ${mx.length} MX record(s), so it can receive mail.`);
  } else if (hasA) {
    v.status = STATUS_DOMAIN_VALID;
    v.notes.push("The domain resolves but publishes no MX record.");
  } else {
    v.status = STATUS_INVALID;
    v.notes.push("The domain does not resolve.");
    v.confidence = 0;
    return v;
  }

  if (v.status === STATUS_MX_VALID && v.domain_matches_site && ["mailto", "text", "jsonld", "footer", "obfuscated"].includes(found.source_type)) {
    v.status = STATUS_VALID_PUBLIC;
    v.notes.push(`Published on the business's own website (${found.page_type} page) and the domain accepts mail.`);
  } else if (v.status === STATUS_MX_VALID && !v.domain_matches_site && !v.is_free_provider) {
    v.notes.push("The address is on a different domain from the website; confirm it belongs to this business before using it.");
  }

  let conf = 0.35;
  conf += { [STATUS_VALID_PUBLIC]: 0.55, [STATUS_MX_VALID]: 0.4, [STATUS_DOMAIN_VALID]: 0.2, [STATUS_SYNTAX_VALID]: 0.1 }[v.status] ?? 0;
  conf += 0.1 * found.confidence;
  if (v.domain_matches_site) conf += 0.05;
  v.confidence = round(Math.min(0.99, conf), 3);
  v.notes.push("Deliverability of the individual mailbox was not tested.");
  return v;
}

export async function validateAll(
  emails: FoundEmail[],
  opts: { siteDomain?: string; enableMx?: boolean; dnsTimeoutS?: number; limit?: number; budget: SubrequestBudget },
): Promise<EmailValidation[]> {
  const subset = emails.slice(0, opts.limit ?? 5);
  const out: EmailValidation[] = [];
  for (const e of subset) {
    try {
      out.push(await validateFoundEmail(e, opts));
    } catch (exc: any) {
      const ev = baseValidation(e.email);
      ev.notes.push(`Validation failed unexpectedly: ${exc?.message || exc}`);
      out.push(ev);
    }
  }
  return out;
}

const USABLE_STATUSES = new Set([STATUS_VALID_PUBLIC, STATUS_MX_VALID, STATUS_DOMAIN_VALID]);
export function isUsableForOutreach(status: string): boolean {
  return USABLE_STATUSES.has(status);
}

function round(n: number, digits: number): number {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}
