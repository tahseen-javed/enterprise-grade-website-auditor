// Budgeted, priority-ordered crawl: homepage first, then contact / about /
// services / booking / team / testimonials / pricing / locations. Depth,
// page count, wall-clock and (Cloudflare-specific) subrequest count are all
// capped so no single site can stall or exceed the Workflow instance's
// subrequest budget. Ported from backend/app/core/crawler.py.
import { Fetcher } from "./fetcher";
import { PAGE_PRIORITY, ParsedPage, classifyPage, parseHtml, shouldSkipUrl } from "./page";
import { isCrawlable, normalizeUrl, originOf, sameSite, urlKey } from "./urls";
import { SubrequestBudget } from "./limits";

export interface CrawlError {
  url: string;
  code: string;
  message: string;
  retryable: boolean;
}

export interface CrawlResult {
  start_url: string;
  final_url: string;
  ok: boolean;
  pages: ParsedPage[];
  errors: CrawlError[];

  home_status: number | null;
  home_response_ms: number | null;
  redirect_chain: string[];
  is_https: boolean | null;
  home_headers: Record<string, string>;

  robots_txt_found: boolean | null;
  sitemap_found: boolean | null;
  sitemap_url: string;

  broken_links: { url: string; status: string; reason: string }[];
  links_checked: number;

  budget_exhausted: boolean;
  blocked: boolean;
}

function emptyCrawl(startUrl: string): CrawlResult {
  return {
    start_url: startUrl, final_url: "", ok: false, pages: [], errors: [],
    home_status: null, home_response_ms: null, redirect_chain: [], is_https: null, home_headers: {},
    robots_txt_found: null, sitemap_found: null, sitemap_url: "",
    broken_links: [], links_checked: 0, budget_exhausted: false, blocked: false,
  };
}

export function typesFound(result: CrawlResult): Set<string> {
  return new Set(result.pages.map((p) => p.page_type));
}

export function homepage(result: CrawlResult): ParsedPage | null {
  return result.pages[0] ?? null;
}

interface FrontierItem {
  url: string;
  type: string;
  depth: number;
  priority: number;
}

export async function crawlSite(
  fetcher: Fetcher,
  startUrl: string,
  opts: {
    maxPages?: number;
    maxDepth?: number;
    totalBudgetS?: number;
    checkBrokenLinks?: boolean;
    maxLinkChecks?: number;
    budget: SubrequestBudget;
    onEvent?: (msg: string, level?: string) => void;
  },
): Promise<CrawlResult> {
  const started = Date.now();
  const maxPages = opts.maxPages ?? 10;
  const maxDepth = opts.maxDepth ?? 2;
  const totalBudgetMs = (opts.totalBudgetS ?? 60) * 1000;
  const maxLinkChecks = opts.maxLinkChecks ?? 5;
  const budget = opts.budget;
  const emit = (msg: string, level = "info") => opts.onEvent?.(msg, level);

  const normStart = normalizeUrl(startUrl) || startUrl;
  const result = emptyCrawl(normStart);

  if (!budget.take()) {
    result.budget_exhausted = true;
    result.errors.push({
      url: normStart, code: "budget_exhausted", retryable: true,
      message: `Subrequest budget exhausted (${budget.left}/${budget.startedWith} left) before the crawl could start — ` +
        "the earlier discovery/validation steps used it all. This is a Cloudflare Free-plan safety ceiling, not a site problem.",
    });
    return result;
  }

  // ---- homepage -------------------------------------------------------------
  let home = await fetcher.fetch(normStart);
  result.home_status = home.status;
  result.home_response_ms = home.elapsed_ms;
  result.redirect_chain = home.redirect_chain;

  if (!home.ok) {
    result.errors.push({ url: normStart, code: home.error_code, message: home.error_message, retryable: home.retryable });
    result.blocked = home.error_code === "blocked";
    if (normStart.startsWith("https://") && ["ssl_error", "connection_error", "dns_failure"].includes(home.error_code) && budget.take()) {
      const alt = "http://" + normStart.slice("https://".length);
      emit("HTTPS failed; trying HTTP once");
      home = await fetcher.fetch(alt);
      if (home.ok) {
        result.errors.push({ url: alt, code: "https_unavailable", message: "The site was only reachable over plain HTTP.", retryable: false });
        result.home_status = home.status;
        result.home_response_ms = home.elapsed_ms;
      } else {
        return result;
      }
    } else {
      return result;
    }
  }

  result.ok = true;
  result.final_url = home.final_url || normStart;
  result.is_https = result.final_url.startsWith("https://");
  result.home_headers = home.headers;

  const homePage = parseHtml(home.text, normStart, {
    final_url: home.final_url, status: home.status, depth: 0, page_type: "homepage",
    elapsed_ms: home.elapsed_ms, bytes_len: home.bytes_len, keep_html: true,
  });
  result.pages.push(homePage);
  emit(`Homepage fetched (${home.status}, ${home.elapsed_ms} ms)`);

  // ---- robots / sitemap -------------------------------------------------------
  const origin = originOf(result.final_url);
  if (budget.take()) {
    const robotsRes = await fetcher.fetch(`${origin}/robots.txt`, { checkRobots: false });
    result.robots_txt_found = Boolean(robotsRes.ok && robotsRes.status === 200);
    let sitemapUrl = "";
    if (robotsRes.ok && robotsRes.text) {
      for (const line of robotsRes.text.split("\n").slice(0, 200)) {
        if (line.toLowerCase().startsWith("sitemap:")) {
          sitemapUrl = line.split(":", 2).slice(1).join(":").trim();
          break;
        }
      }
    }
    if (!sitemapUrl && budget.take()) {
      const probe = await fetcher.fetch(`${origin}/sitemap.xml`, { checkRobots: false });
      if (probe.ok && probe.status === 200 && probe.text.slice(0, 2000).includes("<")) sitemapUrl = `${origin}/sitemap.xml`;
    }
    result.sitemap_found = Boolean(sitemapUrl);
    result.sitemap_url = sitemapUrl;
  }

  // ---- frontier -----------------------------------------------------------------
  const seen = new Set<string>([urlKey(normStart), urlKey(result.final_url)]);
  const frontier: FrontierItem[] = [];

  const addLinks = (page: ParsedPage) => {
    if (page.depth >= maxDepth) return;
    for (const link of page.links) {
      if (!link.internal || !link.href) continue;
      if (!sameSite(result.final_url, link.href) || !isCrawlable(link.href)) continue;
      if (shouldSkipUrl(link.href)) continue;
      const k = urlKey(link.href);
      if (seen.has(k)) continue;
      const ptype = classifyPage(link.href, link.text);
      if ((ptype === "other" || ptype === "blog") && page.depth + 1 >= maxDepth) continue;
      seen.add(k);
      frontier.push({ url: link.href, type: ptype, depth: page.depth + 1, priority: PAGE_PRIORITY[ptype] ?? 20 });
    }
  };
  addLinks(homePage);

  while (frontier.length && result.pages.length < maxPages) {
    if (Date.now() - started > totalBudgetMs) {
      result.budget_exhausted = true;
      emit("Crawl budget reached; stopping politely", "warn");
      break;
    }
    if (!budget.take()) {
      result.budget_exhausted = true;
      emit("Subrequest budget reached; stopping politely", "warn");
      break;
    }

    frontier.sort((a, b) => a.priority - b.priority || a.depth - b.depth);
    const have = new Set(result.pages.map((p) => p.page_type));
    let idx = frontier.findIndex((c) => !have.has(c.type) || c.priority < 10);
    if (idx === -1) idx = 0;
    const cand = frontier.splice(idx, 1)[0];
    if (have.has(cand.type) && cand.type !== "other") continue;

    const res = await fetcher.fetch(cand.url);
    if (!res.ok) {
      result.errors.push({ url: cand.url, code: res.error_code, message: res.error_message, retryable: res.retryable });
      continue;
    }
    const parsed = parseHtml(res.text, cand.url, {
      final_url: res.final_url, status: res.status, depth: cand.depth, page_type: cand.type,
      elapsed_ms: res.elapsed_ms, bytes_len: res.bytes_len,
    });
    result.pages.push(parsed);
    emit(`Crawled ${cand.type} page (${res.status})`);
    addLinks(parsed);
  }

  if (result.pages.length >= maxPages && frontier.length) result.budget_exhausted = true;

  if ((opts.checkBrokenLinks ?? true) && result.pages.length) {
    await checkBrokenLinks(fetcher, result, maxLinkChecks, started, totalBudgetMs, budget);
  }

  return result;
}

async function checkBrokenLinks(
  fetcher: Fetcher,
  result: CrawlResult,
  maxChecks: number,
  started: number,
  budgetMs: number,
  budget: SubrequestBudget,
): Promise<void> {
  const fetched = new Set(result.pages.map((p) => urlKey(p.final_url || p.url)));
  const candidates: string[] = [];
  const seen = new Set<string>();
  outer: for (const page of result.pages) {
    for (const link of page.links) {
      if (!link.internal || !isCrawlable(link.href)) continue;
      const k = urlKey(link.href);
      if (fetched.has(k) || seen.has(k)) continue;
      seen.add(k);
      candidates.push(link.href);
      if (candidates.length >= maxChecks) break outer;
    }
  }
  if (!candidates.length) return;
  if (Date.now() - started > budgetMs) return;

  let checked = 0;
  for (const u of candidates) {
    if (!budget.take()) break;
    checked += 1;
    const r = await fetcher.fetch(u, { checkRobots: false, method: "HEAD" });
    if (r.status !== null && r.status >= 400 && r.status < 600 && ![403, 401, 429].includes(r.status)) {
      if (!budget.take()) {
        result.broken_links.push({ url: u, status: String(r.status), reason: r.error_message || `HTTP ${r.status}` });
        continue;
      }
      checked += 1;
      const g = await fetcher.fetch(u);
      if (g.status !== null && g.status >= 400 && g.status < 600 && ![403, 401, 429].includes(g.status)) {
        result.broken_links.push({ url: u, status: String(g.status), reason: g.error_message || `HTTP ${g.status}` });
      }
    } else if (["dns_failure", "connection_error"].includes(r.error_code) && r.status === null) {
      result.broken_links.push({ url: u, status: "0", reason: r.error_message });
    }
  }
  result.links_checked = checked;
}
