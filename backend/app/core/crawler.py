"""
Site crawler (spec 8).

Budgeted, priority-ordered BFS: homepage first, then contact / about /
services / booking / team / testimonials / pricing / locations. Depth, page
count and wall-clock are all capped so no single site can stall a job.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .fetcher import Fetcher, FetchResult
from .page import PAGE_PRIORITY, ParsedPage, classify_page, parse_html, should_skip_url
from .urls import is_crawlable, normalize_url, origin_of, same_site, url_key


@dataclass
class CrawlError:
    url: str
    code: str
    message: str
    retryable: bool = False
    stage: str = "crawl"


@dataclass
class CrawlResult:
    start_url: str
    final_url: str = ""
    ok: bool = False
    pages: List[ParsedPage] = field(default_factory=list)
    errors: List[CrawlError] = field(default_factory=list)

    home_status: Optional[int] = None
    home_response_ms: Optional[int] = None
    redirect_chain: List[str] = field(default_factory=list)
    is_https: Optional[bool] = None
    https_upgrade_works: Optional[bool] = None
    home_headers: Dict[str, str] = field(default_factory=dict)

    robots_txt_found: Optional[bool] = None
    sitemap_found: Optional[bool] = None
    sitemap_url: str = ""

    broken_links: List[Dict[str, str]] = field(default_factory=list)
    links_checked: int = 0

    elapsed_s: float = 0.0
    budget_exhausted: bool = False
    blocked: bool = False

    def page_by_type(self, ptype: str) -> Optional[ParsedPage]:
        for p in self.pages:
            if p.page_type == ptype:
                return p
        return None

    def types_found(self) -> Set[str]:
        return {p.page_type for p in self.pages}

    @property
    def homepage(self) -> Optional[ParsedPage]:
        return self.pages[0] if self.pages else None

    def all_text(self) -> str:
        return " ".join(p.text for p in self.pages)


EventCb = Optional[Callable[[str, str], None]]


async def crawl_site(
    fetcher: Fetcher,
    start_url: str,
    *,
    max_pages: int = 12,
    max_depth: int = 2,
    total_budget_s: float = 90.0,
    check_broken_links: bool = True,
    max_link_checks: int = 12,
    on_event: EventCb = None,
) -> CrawlResult:
    started = time.monotonic()
    norm_start = normalize_url(start_url) or start_url
    result = CrawlResult(start_url=norm_start)

    def emit(msg: str, level: str = "info") -> None:
        if on_event:
            try:
                on_event(msg, level)
            except Exception:
                pass

    # ---- homepage --------------------------------------------------------
    home = await fetcher.fetch(norm_start)
    result.home_status = home.status
    result.home_response_ms = home.elapsed_ms
    result.redirect_chain = home.redirect_chain

    if not home.ok:
        result.errors.append(
            CrawlError(norm_start, home.error_code, home.error_message, home.retryable)
        )
        result.blocked = home.error_code == "blocked"
        # A plain http:// retry is worth one shot when https fails outright.
        if norm_start.startswith("https://") and home.error_code in (
            "ssl_error", "connection_error", "dns_failure",
        ):
            alt = "http://" + norm_start[len("https://") :]
            emit(f"HTTPS failed ({home.error_code}); trying HTTP once")
            home = await fetcher.fetch(alt)
            if home.ok:
                result.errors.append(
                    CrawlError(alt, "https_unavailable",
                               "The site was only reachable over plain HTTP.", False)
                )
                result.home_status = home.status
                result.home_response_ms = home.elapsed_ms
            else:
                result.elapsed_s = time.monotonic() - started
                return result
        else:
            result.elapsed_s = time.monotonic() - started
            return result

    result.ok = True
    result.final_url = home.final_url or norm_start
    result.is_https = result.final_url.startswith("https://")
    result.home_headers = home.headers

    home_page = parse_html(
        home.text, norm_start,
        final_url=home.final_url, status=home.status, depth=0, page_type="homepage",
        elapsed_ms=home.elapsed_ms, bytes_len=home.bytes_len, keep_html=True,
    )
    result.pages.append(home_page)
    emit(f"Homepage fetched ({home.status}, {home.elapsed_ms} ms)")

    # ---- robots / sitemap ------------------------------------------------
    origin = origin_of(result.final_url)
    robots_res = await fetcher.fetch(f"{origin}/robots.txt", check_robots=False)
    result.robots_txt_found = bool(robots_res.ok and robots_res.status == 200)

    sitemap_url = ""
    if robots_res.ok and robots_res.text:
        for line in robots_res.text.splitlines()[:200]:
            if line.lower().startswith("sitemap:"):
                sitemap_url = line.split(":", 1)[1].strip()
                break
    if not sitemap_url:
        probe = await fetcher.fetch(f"{origin}/sitemap.xml", check_robots=False)
        if probe.ok and probe.status == 200 and "<" in probe.text[:2000]:
            sitemap_url = f"{origin}/sitemap.xml"
    result.sitemap_found = bool(sitemap_url)
    result.sitemap_url = sitemap_url

    # ---- frontier --------------------------------------------------------
    seen: Set[str] = {url_key(norm_start), url_key(result.final_url)}
    frontier: List[Dict[str, Any]] = []

    def add_links(page: ParsedPage) -> None:
        if page.depth >= max_depth:
            return
        for link in page.links:
            if not link.internal or not link.href:
                continue
            if not same_site(result.final_url, link.href) or not is_crawlable(link.href):
                continue
            if should_skip_url(link.href):
                continue
            k = url_key(link.href)
            if k in seen:
                continue
            ptype = classify_page(link.href, link.text)
            if ptype in ("other", "blog") and page.depth + 1 >= max_depth:
                continue  # only spend depth budget on pages we actually want
            seen.add(k)
            frontier.append(
                {"url": link.href, "type": ptype, "depth": page.depth + 1,
                 "priority": PAGE_PRIORITY.get(ptype, 20)}
            )

    add_links(home_page)

    while frontier and len(result.pages) < max_pages:
        if time.monotonic() - started > total_budget_s:
            result.budget_exhausted = True
            emit("Crawl budget reached; stopping politely", "warn")
            break

        frontier.sort(key=lambda c: (c["priority"], c["depth"]))
        # Don't fetch a second page of a type we already captured.
        have = {p.page_type for p in result.pages}
        idx = next(
            (i for i, c in enumerate(frontier) if c["type"] not in have or c["priority"] < 10),
            0,
        )
        cand = frontier.pop(idx)
        if cand["type"] in have and cand["type"] != "other":
            continue

        res = await fetcher.fetch(cand["url"])
        if not res.ok:
            result.errors.append(
                CrawlError(cand["url"], res.error_code, res.error_message, res.retryable)
            )
            continue

        parsed = parse_html(
            res.text, cand["url"],
            final_url=res.final_url, status=res.status, depth=cand["depth"],
            page_type=cand["type"], elapsed_ms=res.elapsed_ms, bytes_len=res.bytes_len,
        )
        result.pages.append(parsed)
        emit(f"Crawled {cand['type']} page ({res.status})")
        add_links(parsed)

    if len(result.pages) >= max_pages and frontier:
        result.budget_exhausted = True

    # ---- broken internal links (within crawl scope only) -----------------
    if check_broken_links and result.pages:
        await _check_broken_links(fetcher, result, max_link_checks, started, total_budget_s)

    result.elapsed_s = time.monotonic() - started
    return result


async def _check_broken_links(
    fetcher: Fetcher,
    result: CrawlResult,
    max_checks: int,
    started: float,
    budget_s: float,
) -> None:
    """Sample internal links from crawled pages and report real 4xx/5xx."""
    fetched = {url_key(p.final_url or p.url) for p in result.pages}
    candidates: List[str] = []
    seen: Set[str] = set()
    for page in result.pages:
        for link in page.links:
            if not link.internal or not is_crawlable(link.href):
                continue
            k = url_key(link.href)
            if k in fetched or k in seen:
                continue
            seen.add(k)
            candidates.append(link.href)
            if len(candidates) >= max_checks:
                break
        if len(candidates) >= max_checks:
            break

    if not candidates:
        return
    if time.monotonic() - started > budget_s:
        return

    async def probe(u: str) -> Optional[Dict[str, str]]:
        r = await fetcher.fetch(u, check_robots=False, method="HEAD")
        if r.status and 400 <= r.status < 600 and r.status not in (403, 401, 429):
            # Some servers reject HEAD; confirm with GET before calling it broken.
            g = await fetcher.fetch(u)
            if g.status and 400 <= g.status < 600 and g.status not in (403, 401, 429):
                return {"url": u, "status": str(g.status), "reason": g.error_message or f"HTTP {g.status}"}
            return None
        if r.error_code in ("dns_failure", "connection_error") and r.status is None:
            return {"url": u, "status": "0", "reason": r.error_message}
        return None

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(probe(u) for u in candidates), return_exceptions=True),
            timeout=max(10.0, budget_s * 0.3),
        )
    except (asyncio.TimeoutError, TimeoutError):
        return

    result.links_checked = len(candidates)
    for r in results:
        if isinstance(r, dict):
            result.broken_links.append(r)
