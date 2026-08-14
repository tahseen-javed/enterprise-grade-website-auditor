"""
Polite async HTTP layer (spec 8 / 29 / 44).

Guarantees:
  * bounded concurrency per host plus a minimum delay between hits;
  * robots.txt honoured (cached per host) when enabled;
  * hard timeouts, capped response size, bounded retries with backoff;
  * no CAPTCHA / anti-bot circumvention - a block is recorded as a block.
"""

from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from .urls import host_of, normalize_url, origin_of

# --------------------------------------------------------------------------


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    ok: bool = False
    status: Optional[int] = None
    text: str = ""
    content_type: str = ""
    bytes_len: int = 0
    elapsed_ms: int = 0
    redirect_chain: List[str] = field(default_factory=list)
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    truncated: bool = False
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def is_html(self) -> bool:
        ct = (self.content_type or "").lower()
        return "html" in ct or "xml" in ct or not ct


NON_RETRYABLE = {
    "robots_denied", "non_html", "invalid_url", "too_large", "http_client_error",
    "blocked", "ssl_error", "dns_failure",
}


class Fetcher:
    """One instance per job run. Owns the connection pool and all throttling."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout_s: float = 20.0,
        per_domain_concurrency: int = 2,
        per_domain_delay_ms: int = 750,
        max_bytes: int = 3 * 1024 * 1024,
        max_retries: int = 2,
        backoff_base_s: float = 1.5,
        respect_robots: bool = True,
        verify_ssl: bool = True,
        global_connections: int = 60,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.per_domain_concurrency = max(1, per_domain_concurrency)
        self.per_domain_delay = max(0.0, per_domain_delay_ms / 1000.0)
        self.max_bytes = max_bytes
        self.max_retries = max(0, max_retries)
        self.backoff_base_s = backoff_base_s
        self.respect_robots = respect_robots

        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            },
            timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            follow_redirects=True,
            max_redirects=8,
            verify=verify_ssl,
            limits=httpx.Limits(
                max_connections=global_connections,
                max_keepalive_connections=20,
                keepalive_expiry=20.0,
            ),
        )

        self._domain_sems: Dict[str, asyncio.Semaphore] = {}
        self._domain_last_hit: Dict[str, float] = {}
        self._domain_lock = asyncio.Lock()
        self._robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._robots_locks: Dict[str, asyncio.Lock] = {}
        self.stats = {"requests": 0, "errors": 0, "bytes": 0, "robots_denied": 0}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    # -- throttling -------------------------------------------------------

    async def _sem_for(self, domain: str) -> asyncio.Semaphore:
        async with self._domain_lock:
            sem = self._domain_sems.get(domain)
            if sem is None:
                sem = asyncio.Semaphore(self.per_domain_concurrency)
                self._domain_sems[domain] = sem
            return sem

    async def _wait_politeness(self, domain: str) -> None:
        if self.per_domain_delay <= 0:
            return
        async with self._domain_lock:
            last = self._domain_last_hit.get(domain, 0.0)
            now = time.monotonic()
            wait = (last + self.per_domain_delay) - now
            self._domain_last_hit[domain] = now + max(0.0, wait)
        if wait > 0:
            await asyncio.sleep(wait)

    # -- robots -----------------------------------------------------------

    async def robots_allows(self, url: str) -> Tuple[bool, str]:
        if not self.respect_robots:
            return True, ""
        if not host_of(url):
            return True, ""
        # Keep the port: robots.txt lives on the same origin as the page.
        key = origin_of(url)
        if not key:
            return True, ""

        async with self._domain_lock:
            lock = self._robots_locks.setdefault(key, asyncio.Lock())

        async with lock:
            if key not in self._robots:
                self._robots[key] = await self._load_robots(key)

        rp = self._robots[key]
        if rp is None:
            return True, ""  # unreadable robots.txt is not a denial
        try:
            allowed = rp.can_fetch(self.user_agent, url) or rp.can_fetch("*", url)
        except Exception:
            return True, ""
        if not allowed:
            self.stats["robots_denied"] += 1
            return False, "robots.txt disallows this path for our user agent"
        return True, ""

    async def _load_robots(self, origin: str):
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = await self._client.get(
                f"{origin}/robots.txt", timeout=httpx.Timeout(8.0, connect=5.0)
            )
            if resp.status_code >= 400:
                return None
            body = resp.text[:400_000]
            rp.parse(body.splitlines())
            return rp
        except Exception:
            return None

    def crawl_delay_for(self, url: str) -> Optional[float]:
        rp = self._robots.get(origin_of(url))
        if rp is None:
            return None
        try:
            d = rp.crawl_delay(self.user_agent) or rp.crawl_delay("*")
            return float(d) if d else None
        except Exception:
            return None

    # -- fetching ---------------------------------------------------------

    async def fetch(self, url: str, *, check_robots: bool = True, method: str = "GET") -> FetchResult:
        norm = normalize_url(url)
        if not norm:
            return FetchResult(
                url=url, error_code="invalid_url",
                error_message="The URL could not be parsed.", retryable=False,
            )

        if check_robots:
            allowed, why = await self.robots_allows(norm)
            if not allowed:
                return FetchResult(
                    url=norm, error_code="robots_denied", error_message=why, retryable=False,
                )

        domain = host_of(norm)
        sem = await self._sem_for(domain)
        attempt = 0
        last: Optional[FetchResult] = None

        while attempt <= self.max_retries:
            async with sem:
                await self._wait_politeness(domain)
                result = await self._do_request(norm, method)
            self.stats["requests"] += 1
            if result.ok:
                self.stats["bytes"] += result.bytes_len
                return result

            self.stats["errors"] += 1
            last = result
            if not result.retryable or attempt >= self.max_retries:
                return result
            await asyncio.sleep(self.backoff_base_s * (2**attempt))
            attempt += 1

        return last or FetchResult(url=norm, error_code="unknown", error_message="Fetch failed.")

    async def _do_request(self, url: str, method: str) -> FetchResult:
        started = time.perf_counter()
        try:
            async with self._client.stream(method, url) as resp:
                chain = [str(r.url) for r in resp.history] + [str(resp.url)]
                ct = resp.headers.get("content-type", "")
                res = FetchResult(
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    content_type=ct,
                    redirect_chain=chain,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                )

                if resp.status_code in (403, 401, 429) or resp.status_code == 503:
                    res.error_code = "blocked"
                    res.error_message = (
                        f"The site returned HTTP {resp.status_code}. Not bypassed by design."
                    )
                    res.retryable = resp.status_code in (429, 503)
                    res.elapsed_ms = int((time.perf_counter() - started) * 1000)
                    return res

                if resp.status_code >= 500:
                    res.error_code = "http_server_error"
                    res.error_message = f"The server returned HTTP {resp.status_code}."
                    res.retryable = True
                    res.elapsed_ms = int((time.perf_counter() - started) * 1000)
                    return res

                if resp.status_code >= 400:
                    res.error_code = "http_client_error"
                    res.error_message = f"The page returned HTTP {resp.status_code}."
                    res.retryable = False
                    res.elapsed_ms = int((time.perf_counter() - started) * 1000)
                    return res

                if ct and not any(t in ct.lower() for t in ("html", "xml", "text/plain")):
                    res.error_code = "non_html"
                    res.error_message = f"Content type is {ct.split(';')[0]}, not a web page."
                    res.retryable = False
                    res.elapsed_ms = int((time.perf_counter() - started) * 1000)
                    return res

                chunks: List[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > self.max_bytes:
                        res.truncated = True
                        chunks.append(chunk[: max(0, self.max_bytes - (total - len(chunk)))])
                        break
                    chunks.append(chunk)

                body = b"".join(chunks)
                res.bytes_len = total
                encoding = resp.encoding or "utf-8"
                try:
                    res.text = body.decode(encoding, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    res.text = body.decode("utf-8", errors="replace")
                res.ok = True
                res.elapsed_ms = int((time.perf_counter() - started) * 1000)
                return res

        except httpx.ConnectTimeout as exc:
            return self._err(url, started, "timeout", f"Connection timed out after {self.timeout_s:.0f}s.", True, exc)
        except httpx.ReadTimeout as exc:
            return self._err(url, started, "timeout", f"The site did not respond within {self.timeout_s:.0f}s.", True, exc)
        except httpx.TooManyRedirects as exc:
            return self._err(url, started, "redirect_loop", "The site redirected too many times.", False, exc)
        except httpx.ConnectError as exc:
            msg = str(exc).lower()
            if "certificate" in msg or "ssl" in msg or "tls" in msg:
                return self._err(url, started, "ssl_error", f"SSL/TLS certificate problem: {exc}", False, exc)
            if "name or service not known" in msg or "getaddrinfo" in msg or "nodename" in msg or "no address" in msg:
                return self._err(url, started, "dns_failure", "The domain name could not be resolved.", False, exc)
            return self._err(url, started, "connection_error", f"Could not connect: {exc}", True, exc)
        except (httpx.RemoteProtocolError, httpx.ProtocolError) as exc:
            return self._err(url, started, "protocol_error", f"Protocol error: {exc}", True, exc)
        except httpx.HTTPError as exc:
            return self._err(url, started, "http_error", f"HTTP error: {exc}", True, exc)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            return self._err(url, started, "timeout", "The request timed out.", True, exc)
        except Exception as exc:  # last-resort guard: one site must never kill a job
            return self._err(url, started, "fetch_failed", f"Unexpected fetch failure: {exc}", False, exc)

    @staticmethod
    def _err(url, started, code, message, retryable, _exc) -> FetchResult:
        return FetchResult(
            url=url,
            error_code=code,
            error_message=message,
            retryable=retryable,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    async def head_ok(self, url: str) -> bool:
        """Cheap existence probe used by website discovery."""
        try:
            r = await self.fetch(url, check_robots=False, method="HEAD")
            if r.status and 200 <= r.status < 400:
                return True
            if r.error_code in ("non_html", "blocked"):
                return True  # it exists, we just cannot read it that way
            return False
        except Exception:
            return False
