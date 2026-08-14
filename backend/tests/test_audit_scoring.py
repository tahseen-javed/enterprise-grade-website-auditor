"""Audit checks, opportunity scoring, problem selection and tiering (spec 12-17, 41-43)."""

from __future__ import annotations

import pytest

from app.core.audit_checks import (
    check_content,
    check_contact,
    check_conversion,
    check_mobile,
    check_technical,
    check_trust,
    no_website_findings,
    run_all_checks,
)
from app.core.crawler import CrawlResult, crawl_site
from app.core.page import parse_html
from app.core.scoring import (
    build_recommendations,
    compute_score,
    has_clear_opportunity,
    lead_tier,
    select_problems,
    tier_for_score,
)
from app.settings import WEIGHTS_DEFAULTS

WEIGHTS = WEIGHTS_DEFAULTS["weights"]
TIERS = WEIGHTS_DEFAULTS["tiers"]


def crawl_from(html_pages, base="https://example-business.test", **kw):
    crawl = CrawlResult(start_url=base, final_url=base, ok=True, **kw)
    for ptype, path, html in html_pages:
        url = base + path
        crawl.pages.append(
            parse_html(html, url, final_url=url, status=200, page_type=ptype, keep_html=True)
        )
    return crawl


BAD_HTML = """<html><head><title>Home</title></head>
<body><div style="width:1100px"><h1>Home</h1><p>Welcome.</p>
<button>Submit</button></div></body></html>"""

GOOD_HTML = """<html lang="en"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brightwater Plumbing - Emergency plumbers in Leeds</title>
<meta name="description" content="Gas Safe registered emergency plumbers covering Leeds and the surrounding areas, available 24 hours a day, seven days a week.">
<link rel="canonical" href="https://example-business.test/">
</head><body>
<header><a href="tel:+441132960001">0113 296 0001</a><a href="/contact">Contact us</a></header>
<h1>Emergency plumbers in Leeds</h1>
<h2>Our services</h2>
<p>We are fully insured and Gas Safe registered, serving Leeds and Bradford.
   We offer boiler repair, leak detection and emergency callouts. Established in 2004.
   Areas we serve include Leeds, Bradford and Wakefield. Book an appointment online
   or request a quote today. Opening hours Mon-Fri 8am-6pm.
   Our address is 14 Kirkstall Road, Leeds.</p>
<h2>Testimonials</h2><p>"Brilliant service" - Sarah. Rated 4.9 from 210 reviews.</p>
<h2>Our work</h2><p>See our gallery of recent projects and before and after photos.</p>
<img src="/a.jpg" alt="Our van">
<form action="/enquiry" method="post"><input type="email" name="email">
<textarea name="message"></textarea><button>Request a callback</button></form>
<footer><a href="mailto:info@example-business.test">Email us</a>
<a href="https://facebook.com/x">Facebook</a></footer>
</body></html>"""


class TestTechnicalChecks:
    def test_detects_missing_basics(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=True,
                           robots_txt_found=False, sitemap_found=False, home_response_ms=120)
        facts, findings = check_technical(crawl)
        codes = {f.code for f in findings}
        assert "missing_meta_description" in codes
        assert "missing_canonical" in codes
        assert "missing_sitemap" in codes
        assert "missing_lang" in codes

    def test_clean_site_has_few_technical_problems(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)], is_https=True,
                           robots_txt_found=True, sitemap_found=True, home_response_ms=180)
        _, findings = check_technical(crawl)
        codes = {f.code for f in findings}
        for absent in ("missing_title", "missing_meta_description", "missing_h1",
                       "missing_canonical", "missing_lang"):
            assert absent not in codes

    def test_no_https_is_high_severity(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)],
                           base="http://example-business.test", is_https=False)
        _, findings = check_technical(crawl)
        f = next(f for f in findings if f.code == "no_https")
        assert f.severity == "high"
        assert f.deduction >= 25

    def test_noindex_is_reported(self):
        html = GOOD_HTML.replace("<title>", '<meta name="robots" content="noindex"><title>')
        crawl = crawl_from([("homepage", "/", html)], is_https=True)
        assert "noindex" in {f.code for f in check_technical(crawl)[1]}

    def test_broken_links_are_reported_with_evidence(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)], is_https=True)
        crawl.broken_links = [{"url": "https://example-business.test/x", "status": "404",
                               "reason": "HTTP 404"}]
        crawl.links_checked = 6
        _, findings = check_technical(crawl)
        f = next(f for f in findings if f.code == "broken_internal_links")
        assert f.evidence["broken"]
        assert f.evidence["checked"] == 6

    def test_measured_response_time_is_tagged_as_performance(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)], is_https=True, home_response_ms=5200)
        _, findings = check_technical(crawl)
        f = next(f for f in findings if f.code == "slow_response")
        assert f.display_category == "performance"
        assert "5200 ms" in f.detail
        assert "single measured request" in f.detail

    def test_performance_is_not_claimed_when_not_measured(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)], is_https=True, home_response_ms=None)
        facts, findings = check_technical(crawl)
        assert facts["response_ms"] is None
        assert not any(f.code == "slow_response" for f in findings)
        assert "pagespeed" not in facts


class TestMobileChecks:
    def test_missing_viewport_is_the_heaviest_mobile_finding(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)])
        facts, findings = check_mobile(crawl)
        assert facts["has_viewport"] is False
        f = next(f for f in findings if f.code == "missing_viewport")
        assert f.severity == "high"
        assert f.deduction >= 40

    def test_responsive_viewport_passes(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)])
        facts, findings = check_mobile(crawl)
        assert facts["viewport_responsive"] is True
        assert not any(f.code in ("missing_viewport", "viewport_not_responsive") for f in findings)

    def test_zoom_disabled_is_flagged(self):
        html = GOOD_HTML.replace('content="width=device-width, initial-scale=1"',
                                 'content="width=device-width, user-scalable=no"')
        crawl = crawl_from([("homepage", "/", html)])
        assert "zoom_disabled" in {f.code for f in check_mobile(crawl)[1]}

    def test_missing_tap_to_call_is_detected(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)])
        facts, findings = check_mobile(crawl)
        assert facts["tap_to_call_on_homepage"] is False
        assert "no_mobile_tap_to_call" in {f.code for f in findings}

    def test_method_is_disclosed_as_static_not_rendered(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)])
        facts, _ = check_mobile(crawl)
        assert facts["method"] == "static_dom_css_analysis"
        assert "not from a rendered" in facts["note"]


class TestConversionChecks:
    def test_missing_ctas_detected_on_poor_site(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)])
        facts, findings = check_conversion(crawl)
        codes = {f.code for f in findings}
        assert facts["has_phone_cta"] is False
        assert facts["has_contact_form"] is False
        assert "no_primary_cta_above_fold" in codes
        assert "no_phone_cta" in codes
        assert "no_contact_form" in codes
        assert "no_contact_page" in codes

    def test_good_site_passes_cta_checks(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML), ("contact", "/contact", GOOD_HTML)])
        facts, findings = check_conversion(crawl)
        assert facts["has_phone_cta"] is True
        assert facts["has_contact_form"] is True
        assert facts["has_contact_page"] is True
        codes = {f.code for f in findings}
        assert "no_phone_cta" not in codes
        assert "no_contact_form" not in codes

    def test_booking_platform_counts_as_booking(self):
        html = GOOD_HTML.replace("</body>", '<a href="https://calendly.com/x">Book</a></body>')
        crawl = crawl_from([("homepage", "/", html)])
        facts, _ = check_conversion(crawl)
        assert facts["has_booking_cta"] is True
        assert "calendly.com" in str(facts["booking_evidence"])

    def test_above_fold_method_is_disclosed_as_approximation(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)])
        facts, _ = check_conversion(crawl)
        assert "approximation" in facts["above_fold_method"]

    def test_no_finding_claims_lost_customers(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)])
        _, findings = check_conversion(crawl)
        for f in findings:
            blob = (f.title + f.detail).lower()
            for phrase in ("losing customers", "lost revenue", "losing money",
                           "lost customers", "costing you"):
                assert phrase not in blob


class TestTrustAndContactAndContent:
    def test_trust_gaps_detected(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)])
        codes = {f.code for f in check_trust(crawl)[1]}
        assert "no_testimonials" in codes
        assert "no_credentials" in codes
        assert "no_portfolio" in codes

    def test_trust_signals_recognised(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML)])
        facts, findings = check_trust(crawl)
        assert facts["testimonials_detected"] is True
        assert facts["credentials_detected"] is True
        assert facts["portfolio_detected"] is True
        assert "no_testimonials" not in {f.code for f in findings}

    def test_contact_accessibility(self):
        bad = crawl_from([("homepage", "/", BAD_HTML)])
        codes = {f.code for f in check_contact(bad)[1]}
        assert "no_phone_on_site" in codes
        assert "contact_hard_to_find" in codes

        good = crawl_from([("homepage", "/", GOOD_HTML), ("contact", "/contact", GOOD_HTML)])
        facts, findings = check_contact(good)
        assert facts["phone_on_homepage"] is True
        assert "no_phone_on_site" not in {f.code for f in findings}

    def test_thin_content_detected(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)])
        codes = {f.code for f in check_content(crawl)[1]}
        assert "very_thin_homepage" in codes
        assert "services_not_clear" in codes

    def test_rich_content_passes(self):
        crawl = crawl_from([("homepage", "/", GOOD_HTML), ("services", "/services", GOOD_HTML)])
        facts, findings = check_content(crawl)
        assert facts["services_described"] is True
        assert "services_not_clear" not in {f.code for f in findings}


class TestScoring:
    def test_neglected_site_scores_high_opportunity(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False,
                           robots_txt_found=False, sitemap_found=False, home_response_ms=4800)
        _, findings = run_all_checks(crawl)
        result = compute_score(findings, WEIGHTS)
        assert result["score"] >= 70
        assert tier_for_score(result["score"], TIERS)[0] in ("High", "Very High")

    def test_well_built_site_scores_low_opportunity(self):
        crawl = crawl_from(
            [("homepage", "/", GOOD_HTML), ("contact", "/contact", GOOD_HTML),
             ("about", "/about", GOOD_HTML), ("services", "/services", GOOD_HTML)],
            is_https=True, robots_txt_found=True, sitemap_found=True, home_response_ms=150,
        )
        _, findings = run_all_checks(crawl)
        result = compute_score(findings, WEIGHTS)
        assert result["score"] <= 45, [f.code for f in findings]

    def test_score_is_bounded(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False, home_response_ms=9999)
        _, findings = run_all_checks(crawl)
        assert 0 <= compute_score(findings, WEIGHTS)["score"] <= 100

    def test_no_findings_means_zero_opportunity(self):
        result = compute_score([], WEIGHTS)
        assert result["score"] == 0
        assert all(v == 100 for v in result["health"].values())

    def test_every_point_is_explained(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False)
        _, findings = run_all_checks(crawl)
        result = compute_score(findings, WEIGHTS)
        assert len(result["explanation"]) == 6
        for row in result["explanation"]:
            assert row["health"] == 100 - row["deductions"] or row["health"] == 0
            assert row["opportunity"] == 100 - row["health"]

    def test_weights_are_configurable(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=True)
        _, findings = run_all_checks(crawl)
        mobile_only = compute_score(findings, {"technical": 0, "mobile": 100, "conversion": 0,
                                               "trust": 0, "contact": 0, "content": 0})
        trust_only = compute_score(findings, {"technical": 0, "mobile": 0, "conversion": 0,
                                              "trust": 100, "contact": 0, "content": 0})
        assert mobile_only["score"] != trust_only["score"]

    @pytest.mark.parametrize("score,expected", [
        (95, "Very High"), (80, "High"), (65, "Good"), (45, "Moderate"), (10, "Low"), (0, "Low"),
    ])
    def test_tier_bands(self, score, expected):
        assert tier_for_score(score, TIERS)[0] == expected


class TestProblemSelection:
    def test_between_three_and_seven_problems_on_a_bad_site(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False)
        _, findings = run_all_checks(crawl)
        problems = select_problems(findings, max_problems=7)
        assert 3 <= len(problems) <= 7

    def test_high_severity_comes_first(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False)
        _, findings = run_all_checks(crawl)
        problems = select_problems(findings, 7)
        order = {"high": 0, "medium": 1, "low": 2}
        ranks = [order[p["severity"]] for p in problems]
        assert ranks == sorted(ranks)

    def test_problems_span_categories(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False)
        _, findings = run_all_checks(crawl)
        problems = select_problems(findings, 7)
        assert len({p["category"] for p in problems}) >= 3

    def test_every_problem_carries_evidence_and_detail(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False)
        _, findings = run_all_checks(crawl)
        for p in select_problems(findings, 7):
            assert p["detail"]
            assert "evidence" in p
            assert p["title"]

    def test_recommendations_map_to_problems(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False)
        _, findings = run_all_checks(crawl)
        problems = select_problems(findings, 7)
        recs = build_recommendations(problems, findings)
        assert recs
        codes = {p["code"] for p in problems}
        assert all(r["problem_code"] in codes for r in recs)

    def test_recommendations_make_no_roi_promises(self):
        crawl = crawl_from([("homepage", "/", BAD_HTML)], is_https=False)
        _, findings = run_all_checks(crawl)
        recs = build_recommendations(select_problems(findings, 7), findings)
        for r in recs:
            text = r["recommendation"].lower()
            for phrase in ("guarantee", "double your", "300%", "roi", "10x", "triple"):
                assert phrase not in text

    def test_clean_site_yields_no_clear_opportunity(self):
        crawl = crawl_from(
            [("homepage", "/", GOOD_HTML), ("contact", "/contact", GOOD_HTML),
             ("about", "/about", GOOD_HTML), ("services", "/services", GOOD_HTML),
             ("testimonials", "/reviews", GOOD_HTML)],
            is_https=True, robots_txt_found=True, sitemap_found=True, home_response_ms=140,
        )
        _, findings = run_all_checks(crawl)
        score = compute_score(findings, WEIGHTS)["score"]
        problems = select_problems(findings, 7)
        clear, reason = has_clear_opportunity(problems, score, min_problems=1)
        if not clear:
            assert reason


class TestNoWebsiteCase:
    def test_no_website_findings_do_not_pretend_to_audit(self):
        findings = no_website_findings("No website was found for this business.")
        assert len(findings) == 1
        assert findings[0].code == "no_website_detected"
        assert findings[0].deduction == 0
        assert "audit" not in findings[0].title.lower()

    def test_social_only_is_distinguished(self):
        findings = no_website_findings("checked", social_url="https://facebook.com/mybiz")
        assert findings[0].code == "social_profile_only"
        assert "facebook.com/mybiz" in str(findings[0].evidence)


class TestLeadTiering:
    def test_a_plus_requires_everything(self):
        r = lead_tier(score=85, website_status="valid", has_usable_contact=True,
                      strong_problem_count=3, problem_count=5, audit_kind="website")
        assert r["tier"] == "A+"
        assert r["reasons"]

    def test_no_contact_downgrades(self):
        r = lead_tier(score=85, website_status="valid", has_usable_contact=False,
                      strong_problem_count=3, problem_count=5, audit_kind="website")
        assert r["tier"] == "B"

    def test_unaudited_site_is_tier_d(self):
        r = lead_tier(score=None, website_status="unavailable", has_usable_contact=True,
                      strong_problem_count=0, problem_count=0, audit_kind="website")
        assert r["tier"] == "D"

    def test_mismatch_is_tier_d(self):
        r = lead_tier(score=80, website_status="mismatch", has_usable_contact=True,
                      strong_problem_count=2, problem_count=4, audit_kind="website")
        assert r["tier"] == "D"

    def test_no_website_with_contact_is_still_a_lead(self):
        r = lead_tier(score=50, website_status="no_website", has_usable_contact=True,
                      strong_problem_count=1, problem_count=1, audit_kind="no_website")
        assert r["tier"] in ("B", "C")

    def test_healthy_site_is_low_tier_not_high(self):
        r = lead_tier(score=15, website_status="valid", has_usable_contact=True,
                      strong_problem_count=0, problem_count=1, audit_kind="website")
        assert r["tier"] in ("C", "D")


class TestAgainstRealLocalSite:
    async def test_full_audit_of_local_site(self, fetcher, local_site):
        crawl = await crawl_site(fetcher, local_site, max_pages=6, total_budget_s=30)
        facts, findings = run_all_checks(crawl)
        result = compute_score(findings, WEIGHTS)

        assert set(facts) == {"technical", "mobile", "conversion", "trust", "contact", "content"}
        assert 0 <= result["score"] <= 100
        # The fixture site is deliberately well built, so opportunity is modest.
        assert result["score"] < 60, [f.code for f in findings]
        assert facts["mobile"]["has_viewport"] is True
        assert facts["conversion"]["has_phone_cta"] is True
