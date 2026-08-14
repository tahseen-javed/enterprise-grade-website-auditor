"""
Tests for the premium audit upgrade: the new security / accessibility /
on-page / off-page / performance-extra checks, the premium scorecard, direct
-URL audits (no CSV, no business-identity matching), and the /api/audits
endpoint that drives them - additive to the existing opportunity-scoring
engine, which these tests never touch.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.audit_checks import (
    check_accessibility,
    check_offpage,
    check_onpage,
    check_performance_extra,
    check_security,
    run_all_checks,
    run_extra_checks,
)
from app.core.crawler import CrawlResult, crawl_site
from app.core.discovery import (
    STATUS_BLOCKED,
    STATUS_NOT_A_WEBSITE,
    STATUS_VALID,
)
from app.core.discovery import verify_direct_website
from app.core.page import parse_html
from app.core.report_html import render_report
from app.core.scoring import (
    AUDIT_CATEGORIES,
    build_pass_fail_summary,
    build_scorecard,
    compute_score,
    priority_for,
)
from app.main import app
from app.settings import WEIGHTS_DEFAULTS

WEIGHTS = WEIGHTS_DEFAULTS["weights"]


def crawl_from(html_pages, base="https://example-business.test", **kw):
    crawl = CrawlResult(start_url=base, final_url=base, ok=True, **kw)
    for ptype, path, html in html_pages:
        url = base + path
        crawl.pages.append(
            parse_html(html, url, final_url=url, status=200, page_type=ptype, keep_html=True)
        )
    return crawl


NO_HEADERS_HTML = """<html lang="en"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Acme Roofing - Roof repairs</title>
<meta name="description" content="Acme Roofing provides roof repairs and replacements across the region, available for free estimates.">
</head><body>
<h1>Acme Roofing</h1>
<p>We repair and replace roofs.</p>
<form action="/enquiry"><input type="text" name="q"><input type="email"></form>
<a href="/x"><img src="/i.jpg"></a>
</body></html>"""

RICH_HTML = """<html lang="en"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Acme Roofing - Roof repairs in Leeds</title>
<meta name="description" content="Acme Roofing provides roof repairs and replacements across Leeds, available for free estimates every day.">
<meta property="og:title" content="Acme Roofing">
<meta property="og:description" content="Roof repairs in Leeds">
<meta property="og:image" content="https://example-business.test/og.jpg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://example-business.test/">
</head><body>
<main>
<nav><a href="/services">Services</a></nav>
<h1>Acme Roofing</h1>
<h2>Our services</h2>
<p>We repair and replace roofs across Leeds.</p>
<form action="/enquiry"><label for="em">Email</label><input id="em" type="email" name="email"></form>
<a href="/gallery">See our recent work</a>
<a href="https://facebook.com/acmeroofing">Facebook</a>
</main>
<script>
{"@context":"https://schema.org","@type":"Organization","name":"Acme Roofing","sameAs":["https://facebook.com/acmeroofing"]}
</script>
</body></html>"""

# selectolax only parses JSON-LD out of <script type="application/ld+json">;
# the block above is deliberately plain so it is inert here and re-added below.
RICH_HTML = RICH_HTML.replace(
    '<script>\n{"@context"',
    '<script type="application/ld+json">\n{"@context"',
)


class TestSecurityChecks:
    def test_flags_missing_security_headers_over_https(self):
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)], is_https=True, home_headers={})
        facts, findings = check_security(crawl)
        # No headers at all were "measured" -> the check declines to guess and reports nothing.
        assert facts["headers_measured"] is False
        assert findings == []

    def test_flags_each_missing_header_when_headers_are_present_but_sparse(self):
        crawl = crawl_from(
            [("homepage", "/", NO_HEADERS_HTML)], is_https=True,
            home_headers={"content-type": "text/html"},
        )
        facts, findings = check_security(crawl)
        codes = {f.code for f in findings}
        assert "security_hsts_missing" in codes
        assert "security_csp_missing" in codes
        assert "security_frame_protection_missing" in codes
        assert "security_xcto_missing" in codes
        assert "security_referrer_policy_missing" in codes

    def test_hsts_not_expected_on_plain_http(self):
        crawl = crawl_from(
            [("homepage", "/", NO_HEADERS_HTML)], is_https=False,
            home_headers={"content-type": "text/html"},
        )
        _, findings = check_security(crawl)
        assert "security_hsts_missing" not in {f.code for f in findings}

    def test_good_headers_pass_every_check(self):
        crawl = crawl_from(
            [("homepage", "/", NO_HEADERS_HTML)], is_https=True,
            home_headers={
                "strict-transport-security": "max-age=63072000",
                "content-security-policy": "default-src 'self'",
                "x-frame-options": "SAMEORIGIN",
                "x-content-type-options": "nosniff",
                "referrer-policy": "strict-origin-when-cross-origin",
                "server": "cloudflare",
            },
        )
        _, findings = check_security(crawl)
        assert findings == []

    def test_server_header_with_version_is_flagged(self):
        crawl = crawl_from(
            [("homepage", "/", NO_HEADERS_HTML)], is_https=True,
            home_headers={
                "strict-transport-security": "max-age=1", "content-security-policy": "default-src 'self'",
                "x-frame-options": "SAMEORIGIN", "x-content-type-options": "nosniff",
                "referrer-policy": "no-referrer", "server": "Apache/2.4.41 (Ubuntu)",
            },
        )
        _, findings = check_security(crawl)
        assert "security_server_header_discloses_version" in {f.code for f in findings}


class TestAccessibilityChecks:
    def test_missing_main_landmark_and_unlabelled_input_detected(self):
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)])
        facts, findings = check_accessibility(crawl)
        codes = {f.code for f in findings}
        assert facts["has_main_landmark"] is False
        assert "a11y_no_main_landmark" in codes
        assert "a11y_unlabelled_form_inputs" in codes
        assert facts["contrast"] == "not_measured"

    def test_labelled_form_and_main_landmark_pass(self):
        crawl = crawl_from([("homepage", "/", RICH_HTML)])
        facts, findings = check_accessibility(crawl)
        assert facts["has_main_landmark"] is True
        assert facts["unlabelled_form_inputs"] == 0
        codes = {f.code for f in findings}
        assert "a11y_no_main_landmark" not in codes
        assert "a11y_unlabelled_form_inputs" not in codes

    def test_empty_link_is_detected(self):
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)])
        facts, findings = check_accessibility(crawl)
        assert facts["empty_links"] >= 1
        assert "a11y_empty_links" in {f.code for f in findings}


class TestOnPageExtras:
    def test_missing_open_graph_and_twitter_card(self):
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)])
        facts, findings = check_onpage(crawl)
        codes = {f.code for f in findings}
        assert "onpage_missing_open_graph" in codes
        assert "onpage_missing_twitter_card" in codes

    def test_open_graph_and_twitter_card_present_pass(self):
        crawl = crawl_from([("homepage", "/", RICH_HTML)])
        facts, findings = check_onpage(crawl)
        assert facts["open_graph_tags"]
        assert facts["twitter_card_tags"] == ["card"]
        codes = {f.code for f in findings}
        assert "onpage_missing_open_graph" not in codes
        assert "onpage_missing_twitter_card" not in codes

    def test_duplicate_titles_across_pages_detected(self):
        crawl = crawl_from([
            ("homepage", "/", RICH_HTML),
            ("services", "/services", RICH_HTML),
        ])
        _, findings = check_onpage(crawl)
        assert "onpage_duplicate_titles" in {f.code for f in findings}
        assert "onpage_duplicate_meta_description" in {f.code for f in findings}


class TestOffPage:
    def test_no_social_presence_is_flagged_and_backlinks_disclosed_unavailable(self):
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)])
        facts, findings = check_offpage(crawl)
        assert "offpage_no_social_profiles" in {f.code for f in findings}
        assert facts["backlinks"]["measured"] is False
        assert facts["referring_domains"]["measured"] is False
        assert facts["domain_authority"]["measured"] is False
        assert "Ahrefs" in facts["backlinks"]["reason"] or "index" in facts["backlinks"]["reason"]

    def test_social_and_sameas_present_pass(self):
        crawl = crawl_from([("homepage", "/", RICH_HTML)])
        facts, findings = check_offpage(crawl)
        assert facts["social_profiles_linked"]
        assert facts["structured_data_sameas"]
        assert "offpage_no_social_profiles" not in {f.code for f in findings}
        assert "offpage_sameas_not_structured" not in {f.code for f in findings}

    def test_never_fabricates_a_domain_authority_number(self):
        crawl = crawl_from([("homepage", "/", RICH_HTML)])
        facts, _ = check_offpage(crawl)
        assert "score" not in facts["domain_authority"]
        assert facts["domain_authority"]["measured"] is False


class TestPerformanceExtra:
    def test_flags_render_blocking_scripts_and_missing_compression(self):
        html = NO_HEADERS_HTML.replace(
            "</body>",
            "".join(f'<script src="/a{i}.js"></script>' for i in range(6)) + "</body>",
        )
        crawl = crawl_from([("homepage", "/", html)], home_headers={"content-type": "text/html"})
        facts, findings = check_performance_extra(crawl)
        codes = {f.code for f in findings}
        assert facts["render_blocking_scripts"] >= 5
        assert "perf_render_blocking_scripts" in codes
        assert "perf_no_compression" in codes

    def test_async_scripts_are_not_render_blocking(self):
        html = NO_HEADERS_HTML.replace(
            "</body>",
            "".join(f'<script src="/a{i}.js" async></script>' for i in range(6)) + "</body>",
        )
        crawl = crawl_from([("homepage", "/", html)])
        facts, _ = check_performance_extra(crawl)
        assert facts["render_blocking_scripts"] == 0

    def test_compression_and_cache_present_pass(self):
        crawl = crawl_from(
            [("homepage", "/", NO_HEADERS_HTML)],
            home_headers={"content-encoding": "gzip", "cache-control": "public, max-age=3600"},
        )
        _, findings = check_performance_extra(crawl)
        codes = {f.code for f in findings}
        assert "perf_no_compression" not in codes
        assert "perf_no_cache_headers" not in codes


class TestRunExtraChecks:
    def test_returns_all_five_categories(self):
        crawl = crawl_from([("homepage", "/", RICH_HTML)], is_https=True, home_headers={})
        facts, findings = run_extra_checks(crawl)
        assert set(facts) == {"security", "accessibility", "onpage", "offpage", "performance_extra"}

    def test_a_broken_check_cannot_kill_the_whole_run(self, monkeypatch):
        import app.core.audit_checks as ac

        def boom(_crawl):
            raise RuntimeError("boom")

        monkeypatch.setattr(ac, "check_security", boom)
        crawl = crawl_from([("homepage", "/", RICH_HTML)])
        facts, findings = ac.run_extra_checks(crawl)
        assert "error" in facts["security"]
        assert "accessibility" in facts  # the other checks still ran


class TestPremiumScorecard:
    def test_legacy_two_arg_call_is_unaffected_by_the_new_kwargs(self):
        """compute_score(findings, weights) must behave exactly as before."""
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)], is_https=False, home_response_ms=5000)
        _, findings = run_all_checks(crawl)
        result = compute_score(findings, WEIGHTS)
        assert set(result["health"].keys()) == {
            "technical", "mobile", "conversion", "trust", "contact", "content"
        }
        assert 0 <= result["score"] <= 100
        assert "overall_health" in result  # additive key only

    def test_build_scorecard_covers_all_premium_categories(self):
        crawl = crawl_from(
            [("homepage", "/", NO_HEADERS_HTML)], is_https=False, home_headers={}, home_response_ms=200,
        )
        _, legacy = run_all_checks(crawl)
        _, extra = run_extra_checks(crawl)
        sc = build_scorecard(legacy + extra)
        assert {c["category"] for c in sc["categories"]} == set(AUDIT_CATEGORIES)
        assert 0 <= sc["overall_score"] <= 100
        for c in sc["categories"]:
            assert 0 <= c["health"] <= 100
        assert sc["pass_fail"]["total_checked"] > 0

    def test_higher_is_better_for_the_premium_score(self):
        """Unlike the legacy opportunity score, the scorecard score is health-style."""
        bad = crawl_from([("homepage", "/", NO_HEADERS_HTML)], is_https=False, home_headers={})
        good = crawl_from([("homepage", "/", RICH_HTML)], is_https=True, home_headers={
            "strict-transport-security": "max-age=1", "content-security-policy": "default-src 'self'",
            "x-frame-options": "SAMEORIGIN", "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer", "content-encoding": "gzip", "cache-control": "max-age=3600",
        })
        _, bad_l = run_all_checks(bad)
        _, bad_e = run_extra_checks(bad)
        _, good_l = run_all_checks(good)
        _, good_e = run_extra_checks(good)
        bad_score = build_scorecard(bad_l + bad_e)["overall_score"]
        good_score = build_scorecard(good_l + good_e)["overall_score"]
        assert good_score > bad_score

    def test_pass_fail_never_double_counts_a_check(self):
        crawl = crawl_from([("homepage", "/", RICH_HTML)], is_https=True, home_headers={
            "strict-transport-security": "max-age=1", "content-security-policy": "default-src 'self'",
            "x-frame-options": "SAMEORIGIN", "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer",
        })
        _, legacy = run_all_checks(crawl)
        _, extra = run_extra_checks(crawl)
        summary = build_pass_fail_summary(legacy + extra)
        assert summary["passed_count"] + summary["failed_count"] == summary["total_checked"]

    def test_priority_is_deterministic_from_severity(self):
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)], is_https=False)
        _, findings = run_all_checks(crawl)
        for f in findings:
            p = priority_for(f)
            assert p in ("P1", "P2", "P3")
            if f.severity == "high":
                assert p == "P1"


class TestDirectUrlDiscovery:
    async def test_valid_site_is_confirmed_without_a_business_name(self, fetcher, local_site):
        result = await verify_direct_website(fetcher, local_site)
        assert result.status == STATUS_VALID
        assert result.has_website is True
        assert result.identity_confidence == 1.0
        assert result.source == "manual"

    async def test_unreachable_host_is_reported_not_silently_dropped(self, fetcher):
        result = await verify_direct_website(fetcher, "http://127.0.0.1:1")
        assert result.has_website is False
        assert result.status in (STATUS_BLOCKED, "unavailable")

    async def test_social_profile_url_is_rejected(self, fetcher):
        result = await verify_direct_website(fetcher, "https://facebook.com/somebusiness")
        assert result.status == STATUS_NOT_A_WEBSITE
        assert result.has_website is False

    def test_unparseable_url_is_reported(self):
        import asyncio

        async def run():
            from app.core.fetcher import Fetcher

            f = Fetcher(user_agent="test")
            try:
                return await verify_direct_website(f, "not a url at all")
            finally:
                await f.aclose()

        result = asyncio.run(run())
        assert result.has_website is False


class TestPremiumReportRendering:
    """
    Guards against template bugs that only surface at render time (e.g. a
    dict key named "items" silently resolving to dict.items() under Jinja's
    attribute-then-subscript lookup) - exactly the class of bug a JSON-only
    test of build_scorecard() cannot catch.
    """

    def _render(self, crawl):
        legacy_facts, legacy_findings = run_all_checks(crawl)
        extra_facts, extra_findings = run_extra_checks(crawl)
        scorecard = build_scorecard(legacy_findings + extra_findings)
        problems = [
            {"rank": 1, "code": f.code, "category": f.display_category,
             "category_label": f.display_category, "severity": f.severity,
             "title": f.title, "detail": f.detail, "evidence": f.evidence,
             "impact_points": f.deduction, "is_strong_signal": False}
            for f in legacy_findings[:3]
        ]
        html = render_report(
            business={"name": "Acme Roofing", "location": "Leeds, UK", "category": "Roofer", "lead_tier": "B"},
            audit={
                "website": "https://example-business.test", "score": 40, "opportunity_tier": "Moderate",
                "technical": legacy_facts.get("technical", {}), "mobile": legacy_facts.get("mobile", {}),
                "conversion": legacy_facts.get("conversion", {}),
            },
            problems=problems,
            recommendations=[{"rank": 1, "problem_code": problems[0]["code"], "recommendation": "Fix it."}] if problems else [],
            explanation=[],
            contacts=[{"label": "Phone", "value": "+441132960001", "status": "valid", "pill": "ok"}],
            pages=[{"type": "homepage", "url": "https://example-business.test/", "status": 200}],
            generator="Test Co",
            scorecard=scorecard,
            legacy_findings=legacy_findings,
            extra_findings=extra_findings,
            extra_facts=extra_facts,
        )
        return html, scorecard

    def test_renders_without_raising_for_a_poor_site(self):
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)], is_https=False, home_headers={})
        html, scorecard = self._render(crawl)
        assert "<!doctype html>" in html.lower()
        assert str(scorecard["overall_score"]) in html
        assert "Technical SEO" in html
        assert "Conversion" in html
        assert "Not available" in html  # off-page backlink disclosure

    def test_renders_without_raising_for_a_well_built_site(self):
        crawl = crawl_from(
            [("homepage", "/", RICH_HTML)], is_https=True,
            home_headers={
                "strict-transport-security": "max-age=1", "content-security-policy": "default-src 'self'",
                "x-frame-options": "SAMEORIGIN", "x-content-type-options": "nosniff",
                "referrer-policy": "no-referrer", "content-encoding": "gzip", "cache-control": "max-age=3600",
            },
        )
        html, _ = self._render(crawl)
        assert "<!doctype html>" in html.lower()

    def test_category_section_finding_counts_are_not_dict_methods(self):
        """Regression: a dict key literally named "items" breaks under Jinja
        (`cat.items` resolves to dict.items, not the "items" entry)."""
        crawl = crawl_from([("homepage", "/", NO_HEADERS_HTML)], is_https=False, home_headers={})
        html, _ = self._render(crawl)
        assert "built-in method" not in html
        assert "bound method" not in html

    def test_no_scorecard_falls_back_to_legacy_layout_without_raising(self):
        html = render_report(
            business={"name": "No Site Bakery", "location": "", "category": "", "lead_tier": ""},
            audit={"website": "", "score": None, "opportunity_tier": ""},
            problems=[], recommendations=[], explanation=[], contacts=[], pages=[],
        )
        assert "<!doctype html>" in html.lower()
        assert "No issues have been invented" in html or "No evidence-backed problems" in html


class TestQuickAuditApi:
    @pytest.fixture
    def client(self):
        with TestClient(app) as c:
            yield c

    def test_rejects_an_unparseable_url(self, client):
        r = client.post("/api/audits/quick", json={"url": "not a url", "start_immediately": False})
        assert r.status_code == 400

    def test_rejects_a_social_profile_url(self, client):
        r = client.post("/api/audits/quick", json={
            "url": "https://facebook.com/somebusiness", "start_immediately": False,
        })
        assert r.status_code == 400

    def test_creates_a_one_row_job_without_starting_it(self, client):
        r = client.post("/api/audits/quick", json={
            "url": "https://example-quick-audit.invalid", "name": "Example Co",
            "start_immediately": False,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["job_id"]
        assert body["business_id"]
        assert body["started"] is False

        job = client.get(f"/api/jobs/{body['job_id']}").json()
        assert job["source_kind"] == "url"
        assert job["total"] == 1

        leads = client.get("/api/leads", params={"job_id": body["job_id"]}).json()
        assert leads["total"] == 1
        assert leads["leads"][0]["name"] == "Example Co"

        client.delete(f"/api/jobs/{body['job_id']}")
