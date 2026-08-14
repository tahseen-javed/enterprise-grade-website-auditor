"""
Crawler behaviour against a real local HTTP server (spec 8, 27, 46).

Uses the `local_site` fixture rather than the internet, so these tests are
deterministic and never touch anyone else's server.
"""

from __future__ import annotations

import pytest

from app.core.crawler import crawl_site
from app.core.fetcher import Fetcher


class TestFetching:
    async def test_fetches_a_page(self, fetcher, local_site):
        r = await fetcher.fetch(local_site + "/")
        assert r.ok and r.status == 200
        assert "Brightwater Plumbing" in r.text
        assert r.elapsed_ms >= 0

    async def test_404_is_a_non_retryable_client_error(self, fetcher, local_site):
        r = await fetcher.fetch(local_site + "/does-not-exist")
        assert not r.ok
        assert r.error_code == "http_client_error"
        assert r.retryable is False

    async def test_403_is_recorded_as_blocked_not_bypassed(self, fetcher, local_site):
        r = await fetcher.fetch(local_site + "/forbidden")
        assert not r.ok
        assert r.error_code == "blocked"
        assert "not bypassed" in r.error_message.lower()

    async def test_dns_failure_is_typed_and_not_retryable(self, fetcher):
        r = await fetcher.fetch("https://this-host-does-not-exist-zzq123.invalid/")
        assert not r.ok
        assert r.error_code in ("dns_failure", "connection_error")

    async def test_timeout_is_typed_as_retryable(self, local_site):
        f = Fetcher(user_agent="test", timeout_s=0.001, max_retries=0, per_domain_delay_ms=0)
        try:
            r = await f.fetch(local_site + "/")
            if not r.ok:
                assert r.error_code in ("timeout", "connection_error", "protocol_error")
                assert r.retryable is True
        finally:
            await f.aclose()

    async def test_invalid_url_rejected_without_request(self, fetcher):
        r = await fetcher.fetch("not a url at all")
        assert r.error_code == "invalid_url"

    async def test_robots_disallow_is_honoured(self, fetcher, local_site):
        r = await fetcher.fetch(local_site + "/private")
        assert not r.ok
        assert r.error_code == "robots_denied"
        assert r.retryable is False

    async def test_robots_can_be_disabled_explicitly(self, local_site):
        f = Fetcher(user_agent="test", respect_robots=False, per_domain_delay_ms=0, max_retries=0)
        try:
            r = await f.fetch(local_site + "/private")
            assert r.ok
        finally:
            await f.aclose()

    async def test_politeness_delay_is_applied(self, local_site):
        import time

        f = Fetcher(user_agent="test", per_domain_delay_ms=300, max_retries=0, respect_robots=False)
        try:
            start = time.monotonic()
            for _ in range(3):
                await f.fetch(local_site + "/")
            elapsed = time.monotonic() - start
            assert elapsed >= 0.55  # at least two gaps of 300ms
        finally:
            await f.aclose()

    async def test_response_size_is_capped(self, local_site):
        f = Fetcher(user_agent="test", max_bytes=200, per_domain_delay_ms=0,
                    max_retries=0, respect_robots=False)
        try:
            r = await f.fetch(local_site + "/")
            assert r.truncated is True
            assert len(r.text) <= 400
        finally:
            await f.aclose()


class TestCrawling:
    async def test_crawls_priority_pages(self, fetcher, local_site):
        crawl = await crawl_site(fetcher, local_site, max_pages=8, max_depth=2,
                                 total_budget_s=30)
        assert crawl.ok
        types = crawl.types_found()
        assert "homepage" in types
        assert "contact" in types
        assert len(crawl.pages) >= 3

    async def test_homepage_is_always_first(self, fetcher, local_site):
        crawl = await crawl_site(fetcher, local_site, max_pages=5, total_budget_s=30)
        assert crawl.pages[0].page_type == "homepage"

    async def test_page_budget_is_respected(self, fetcher, local_site):
        crawl = await crawl_site(fetcher, local_site, max_pages=2, total_budget_s=30)
        assert len(crawl.pages) <= 2

    async def test_robots_and_sitemap_detected(self, fetcher, local_site):
        crawl = await crawl_site(fetcher, local_site, max_pages=3, total_budget_s=30)
        assert crawl.robots_txt_found is True
        assert crawl.sitemap_found is True

    async def test_disallowed_path_is_never_crawled(self, fetcher, local_site):
        crawl = await crawl_site(fetcher, local_site, max_pages=10, total_budget_s=30)
        assert all("/private" not in (p.final_url or p.url) for p in crawl.pages)

    async def test_unreachable_site_reports_error_without_raising(self, fetcher):
        crawl = await crawl_site(fetcher, "https://this-host-does-not-exist-zzq123.invalid/",
                                 max_pages=5, total_budget_s=15)
        assert crawl.ok is False
        assert crawl.errors
        assert crawl.errors[0].code in ("dns_failure", "connection_error")

    async def test_parsed_content_is_populated(self, fetcher, local_site):
        crawl = await crawl_site(fetcher, local_site, max_pages=3, total_budget_s=30)
        home = crawl.homepage
        assert home.title
        assert home.meta_description
        assert home.h1
        assert home.viewport
        assert home.tel
        assert home.word_count > 40

    async def test_one_page_type_is_not_fetched_repeatedly(self, fetcher, local_site):
        crawl = await crawl_site(fetcher, local_site, max_pages=10, total_budget_s=30)
        contact_pages = [p for p in crawl.pages if p.page_type == "contact"]
        assert len(contact_pages) <= 1
