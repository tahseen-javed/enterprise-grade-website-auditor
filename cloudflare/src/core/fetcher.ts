// Polite HTTP layer: robots.txt honoured (cached per host), hard timeouts,
// capped response size, bounded retries with backoff, politeness delay
// between hits on the same host. Ported from backend/app/core/fetcher.py,
// rebuilt on the platform `fetch()` since Workers has no httpx/urllib.
import { hostOf, normalizeUrl, originOf } from "./urls";

export interface FetchResult {
  url: string;
  final_url: string;
  ok: boolean;
  status: number | null;
  text: string;
  content_type: string;
  bytes_len: number;
  elapsed_ms: number;
  redirect_chain: string[];
  error_code: string;
  error_message: string;
  retryable: boolean;
  truncated: boolean;
  headers: Record<string, string>;
}

function emptyResult(url: string): FetchResult {
  return {
    url, final_url: "", ok: false, status: null, text: "", content_type: "", bytes_len: 0,
    elapsed_ms: 0, redirect_chain: [], error_code: "", error_message: "", retryable: false,
    truncated: false, headers: {},
  };
}

interface RobotsRules {
  disallow: string[];
  allow: string[];
}

function parseRobots(body: string, userAgent: string): RobotsRules {
  const lines = body.split(/\r?\n/).slice(0, 5000);
  const groups: { agents: string[]; rules: { type: "allow" | "disallow"; path: string }[] }[] = [];
  let current: { agents: string[]; rules: { type: "allow" | "disallow"; path: string }[] } | null = null;
  let sawAgentBeforeRule = false;

  for (const raw of lines) {
    const line = raw.split("#")[0].trim();
    if (!line) continue;
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim().toLowerCase();
    const value = line.slice(idx + 1).trim();
    if (key === "user-agent") {
      if (!current || !sawAgentBeforeRule) {
        current = { agents: [], rules: [] };
        groups.push(current);
      }
      current.agents.push(value.toLowerCase());
      sawAgentBeforeRule = true;
    } else if (key === "disallow" && current) {
      current.rules.push({ type: "disallow", path: value });
      sawAgentBeforeRule = false;
    } else if (key === "allow" && current) {
      current.rules.push({ type: "allow", path: value });
      sawAgentBeforeRule = false;
    }
  }

  const uaLower = userAgent.toLowerCase();
  const specific = groups.find((g) => g.agents.some((a) => a !== "*" && uaLower.includes(a)));
  const wildcard = groups.find((g) => g.agents.includes("*"));
  const chosen = specific || wildcard;
  if (!chosen) return { disallow: [], allow: [] };
  return {
    disallow: chosen.rules.filter((r) => r.type === "disallow" && r.path).map((r) => r.path),
    allow: chosen.rules.filter((r) => r.type === "allow").map((r) => r.path),
  };
}

function robotsAllows(rules: RobotsRules, path: string): boolean {
  const matchLen = (pattern: string): number => {
    if (!pattern) return -1;
    // Minimal wildcard support: '*' as a glob, '$' as end-anchor - covers the
    // overwhelming majority of real robots.txt files.
    const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\\\$$/, "$");
    try {
      return new RegExp("^" + escaped).test(path) ? pattern.length : -1;
    } catch {
      return path.startsWith(pattern) ? pattern.length : -1;
    }
  };
  let bestAllow = -1;
  let bestDisallow = -1;
  for (const p of rules.allow) bestAllow = Math.max(bestAllow, matchLen(p));
  for (const p of rules.disallow) bestDisallow = Math.max(bestDisallow, matchLen(p));
  if (bestDisallow === -1) return true;
  return bestAllow >= bestDisallow;
}

export interface FetcherOptions {
  userAgent: string;
  timeoutS?: number;
  perDomainDelayMs?: number;
  maxBytes?: number;
  maxRetries?: number;
  backoffBaseS?: number;
  respectRobots?: boolean;
}

export class Fetcher {
  private userAgent: string;
  private timeoutMs: number;
  private perDomainDelayMs: number;
  private maxBytes: number;
  private maxRetries: number;
  private backoffBaseS: number;
  private respectRobots: boolean;
  private domainLastHit = new Map<string, number>();
  private robotsCache = new Map<string, RobotsRules | null>();
  public stats = { requests: 0, errors: 0, bytes: 0, robotsDenied: 0 };

  constructor(opts: FetcherOptions) {
    this.userAgent = opts.userAgent;
    this.timeoutMs = (opts.timeoutS ?? 20) * 1000;
    this.perDomainDelayMs = opts.perDomainDelayMs ?? 750;
    this.maxBytes = opts.maxBytes ?? 3 * 1024 * 1024;
    this.maxRetries = opts.maxRetries ?? 2;
    this.backoffBaseS = opts.backoffBaseS ?? 1.5;
    this.respectRobots = opts.respectRobots ?? true;
  }

  private async waitPoliteness(domain: string): Promise<void> {
    if (this.perDomainDelayMs <= 0) return;
    const last = this.domainLastHit.get(domain) ?? 0;
    const now = Date.now();
    const wait = last + this.perDomainDelayMs - now;
    this.domainLastHit.set(domain, now + Math.max(0, wait));
    if (wait > 0) await sleep(wait);
  }

  async robotsAllowsUrl(url: string): Promise<{ allowed: boolean; reason: string }> {
    if (!this.respectRobots) return { allowed: true, reason: "" };
    if (!hostOf(url)) return { allowed: true, reason: "" };
    const origin = originOf(url);
    if (!origin) return { allowed: true, reason: "" };

    if (!this.robotsCache.has(origin)) {
      this.robotsCache.set(origin, await this.loadRobots(origin));
    }
    const rules = this.robotsCache.get(origin);
    if (!rules) return { allowed: true, reason: "" };

    const p = new URL(url);
    const path = (p.pathname || "/") + (p.search || "");
    const allowed = robotsAllows(rules, path);
    if (!allowed) {
      this.stats.robotsDenied += 1;
      return { allowed: false, reason: "robots.txt disallows this path for our user agent" };
    }
    return { allowed: true, reason: "" };
  }

  private async loadRobots(origin: string): Promise<RobotsRules | null> {
    try {
      const controller = new AbortController();
      const t = setTimeout(() => controller.abort(), 8000);
      const resp = await fetch(`${origin}/robots.txt`, {
        signal: controller.signal,
        headers: { "User-Agent": this.userAgent },
      });
      clearTimeout(t);
      if (resp.status >= 400) return null;
      const body = (await resp.text()).slice(0, 400_000);
      return parseRobots(body, this.userAgent);
    } catch {
      return null;
    }
  }

  async fetch(url: string, opts: { checkRobots?: boolean; method?: string } = {}): Promise<FetchResult> {
    const checkRobots = opts.checkRobots ?? true;
    const method = opts.method ?? "GET";
    const norm = normalizeUrl(url);
    if (!norm) {
      const r = emptyResult(url);
      r.error_code = "invalid_url";
      r.error_message = "The URL could not be parsed.";
      return r;
    }

    if (checkRobots) {
      const { allowed, reason } = await this.robotsAllowsUrl(norm);
      if (!allowed) {
        const r = emptyResult(norm);
        r.error_code = "robots_denied";
        r.error_message = reason;
        return r;
      }
    }

    const domain = hostOf(norm);
    let attempt = 0;
    let last: FetchResult | null = null;

    while (attempt <= this.maxRetries) {
      await this.waitPoliteness(domain);
      const result = await this.doRequest(norm, method);
      this.stats.requests += 1;
      if (result.ok) {
        this.stats.bytes += result.bytes_len;
        return result;
      }
      this.stats.errors += 1;
      last = result;
      if (!result.retryable || attempt >= this.maxRetries) return result;
      await sleep(this.backoffBaseS * 2 ** attempt * 1000);
      attempt += 1;
    }
    return last ?? emptyResult(norm);
  }

  private async doRequest(url: string, method: string): Promise<FetchResult> {
    const started = Date.now();
    const chain: string[] = [];
    let current = url;

    try {
      for (let hop = 0; hop < 8; hop++) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), this.timeoutMs);
        let resp: Response;
        try {
          resp = await fetch(current, {
            method,
            redirect: "manual",
            signal: controller.signal,
            headers: {
              "User-Agent": this.userAgent,
              Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
              "Accept-Language": "en-US,en;q=0.9",
            },
          });
        } finally {
          clearTimeout(timer);
        }

        if ([301, 302, 303, 307, 308].includes(resp.status)) {
          const loc = resp.headers.get("location");
          if (!loc) break;
          chain.push(current);
          current = new URL(loc, current).toString();
          continue;
        }

        chain.push(current);
        const headers: Record<string, string> = {};
        resp.headers.forEach((v, k) => (headers[k.toLowerCase()] = v));
        const ct = headers["content-type"] || "";

        const res: FetchResult = {
          url, final_url: current, ok: false, status: resp.status, text: "", content_type: ct,
          bytes_len: 0, elapsed_ms: 0, redirect_chain: chain, error_code: "", error_message: "",
          retryable: false, truncated: false, headers,
        };

        if ([401, 403, 429, 503].includes(resp.status)) {
          res.error_code = "blocked";
          res.error_message = `The site returned HTTP ${resp.status}. Not bypassed by design.`;
          res.retryable = resp.status === 429 || resp.status === 503;
          res.elapsed_ms = Date.now() - started;
          return res;
        }
        if (resp.status >= 500) {
          res.error_code = "http_server_error";
          res.error_message = `The server returned HTTP ${resp.status}.`;
          res.retryable = true;
          res.elapsed_ms = Date.now() - started;
          return res;
        }
        if (resp.status >= 400) {
          res.error_code = "http_client_error";
          res.error_message = `The page returned HTTP ${resp.status}.`;
          res.elapsed_ms = Date.now() - started;
          return res;
        }
        if (ct && !["html", "xml", "text/plain"].some((t) => ct.toLowerCase().includes(t))) {
          res.error_code = "non_html";
          res.error_message = `Content type is ${ct.split(";")[0]}, not a web page.`;
          res.elapsed_ms = Date.now() - started;
          return res;
        }

        const { text, bytesLen, truncated } = await this.readBody(resp);
        res.text = text;
        res.bytes_len = bytesLen;
        res.truncated = truncated;
        res.ok = true;
        res.elapsed_ms = Date.now() - started;
        return res;
      }

      const r = emptyResult(url);
      r.final_url = current;
      r.redirect_chain = chain;
      r.error_code = "redirect_loop";
      r.error_message = "The site redirected too many times.";
      r.elapsed_ms = Date.now() - started;
      return r;
    } catch (exc: any) {
      return this.classifyError(url, started, exc);
    }
  }

  private async readBody(resp: Response): Promise<{ text: string; bytesLen: number; truncated: boolean }> {
    if (!resp.body) {
      const buf = await resp.arrayBuffer();
      const bytes = new Uint8Array(buf).slice(0, this.maxBytes);
      return { text: new TextDecoder().decode(bytes), bytesLen: buf.byteLength, truncated: buf.byteLength > this.maxBytes };
    }
    const reader = resp.body.getReader();
    let total = 0;
    let truncated = false;
    const chunks: Uint8Array[] = [];
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > this.maxBytes) {
        chunks.push(value.slice(0, Math.max(0, this.maxBytes - (total - value.byteLength))));
        truncated = true;
        try {
          await reader.cancel();
        } catch {
          /* best-effort */
        }
        break;
      }
      chunks.push(value);
    }
    const merged = new Uint8Array(chunks.reduce((n, c) => n + c.byteLength, 0));
    let offset = 0;
    for (const c of chunks) {
      merged.set(c, offset);
      offset += c.byteLength;
    }
    return { text: new TextDecoder("utf-8", { fatal: false, ignoreBOM: false }).decode(merged), bytesLen: total, truncated };
  }

  private classifyError(url: string, started: number, exc: any): FetchResult {
    const r = emptyResult(url);
    r.elapsed_ms = Date.now() - started;
    const msg = String(exc?.message || exc || "").toLowerCase();
    const name = String(exc?.name || "");

    if (name === "AbortError" || msg.includes("timeout") || msg.includes("timed out")) {
      r.error_code = "timeout";
      r.error_message = `The site did not respond within ${(this.timeoutMs / 1000).toFixed(0)}s.`;
      r.retryable = true;
    } else if (msg.includes("certificate") || msg.includes("ssl") || msg.includes("tls")) {
      r.error_code = "ssl_error";
      r.error_message = `SSL/TLS certificate problem: ${exc?.message || exc}`;
      r.retryable = false;
    } else if (
      msg.includes("dns") ||
      msg.includes("could not resolve") ||
      msg.includes("name not resolved") ||
      msg.includes("enotfound")
    ) {
      r.error_code = "dns_failure";
      r.error_message = "The domain name could not be resolved.";
      r.retryable = false;
    } else {
      r.error_code = "connection_error";
      r.error_message = `Could not connect: ${exc?.message || exc}`;
      r.retryable = true;
    }
    return r;
  }

  async headOk(url: string): Promise<boolean> {
    try {
      const r = await this.fetch(url, { checkRobots: false, method: "HEAD" });
      if (r.status !== null && r.status >= 200 && r.status < 400) return true;
      if (["non_html", "blocked"].includes(r.error_code)) return true;
      return false;
    } catch {
      return false;
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
