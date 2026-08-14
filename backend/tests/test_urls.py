"""URL normalization and website identity matching (spec 7, 46)."""

from __future__ import annotations

import pytest

from app.core.urls import (
    absolutize,
    candidate_domains,
    is_crawlable,
    is_non_website_host,
    normalize_url,
    registrable_domain,
    same_site,
    score_identity,
    tlds_for_region,
    url_key,
)


class TestNormalizeUrl:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("example.com", "https://example.com/"),
            ("www.example.com", "https://www.example.com/"),
            ("http://example.com", "http://example.com/"),
            ("HTTPS://Example.COM/Path", "https://example.com/Path"),
            ("//example.com", "https://example.com/"),
            ("  https://example.com/x  ", "https://example.com/x"),
            ("example.co.uk/contact", "https://example.co.uk/contact"),
        ],
    )
    def test_messy_values_become_canonical(self, raw, expected):
        assert normalize_url(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "N/A", "na", "none", "-", "no website", "nan", "notaurl"])
    def test_placeholder_values_are_rejected(self, raw):
        assert normalize_url(raw) is None

    def test_tracking_parameters_are_stripped(self):
        url = normalize_url("https://example.com/p?utm_source=x&id=7&fbclid=abc")
        assert "utm_source" not in url and "fbclid" not in url
        assert "id=7" in url

    def test_default_ports_are_removed(self):
        assert normalize_url("http://example.com:80/") == "http://example.com/"
        assert normalize_url("https://example.com:443/") == "https://example.com/"

    def test_fragment_dropped_by_absolutize(self):
        assert absolutize("https://example.com/", "/a#section") == "https://example.com/a"

    def test_non_http_schemes_rejected(self):
        assert normalize_url("ftp://example.com") is None
        assert normalize_url("javascript:alert(1)") is None


class TestDomains:
    @pytest.mark.parametrize(
        "url,domain",
        [
            ("https://www.example.co.uk/x", "example.co.uk"),
            ("https://shop.example.com", "example.com"),
            ("http://example.com.au/", "example.com.au"),
        ],
    )
    def test_registrable_domain(self, url, domain):
        assert registrable_domain(url) == domain

    def test_same_site_ignores_subdomains(self):
        assert same_site("https://www.example.com/a", "https://shop.example.com/b")
        assert not same_site("https://example.com", "https://example.org")

    def test_url_key_deduplicates_equivalent_urls(self):
        keys = {
            url_key("https://www.example.com/"),
            url_key("http://example.com"),
            url_key("https://example.com/index.html"),
            url_key("https://example.com"),
        }
        assert len(keys) == 1

    @pytest.mark.parametrize(
        "url,kind",
        [
            ("https://facebook.com/mybiz", "social_profile"),
            ("https://www.instagram.com/mybiz", "social_profile"),
            ("https://www.yelp.com/biz/mybiz", "directory_listing"),
            ("https://linktr.ee/mybiz", "link_in_bio"),
            ("https://mybiz.business.site", "directory_listing"),
        ],
    )
    def test_profiles_are_not_treated_as_websites(self, url, kind):
        is_profile, detected = is_non_website_host(url)
        assert is_profile and detected == kind

    def test_real_site_is_not_flagged(self):
        assert is_non_website_host("https://brightwaterplumbing.co.uk")[0] is False

    @pytest.mark.parametrize("url,ok", [
        ("https://example.com/page", True),
        ("https://example.com/file.pdf", False),
        ("https://example.com/img.jpg", False),
        ("https://example.com/style.css", False),
    ])
    def test_only_html_like_urls_are_crawlable(self, url, ok):
        assert is_crawlable(url) is ok


class TestIdentityMatching:
    """A website is only attributed to a business on corroborating evidence."""

    def test_strong_match_scores_high(self):
        r = score_identity(
            business_name="Brightwater Plumbing",
            url="https://brightwaterplumbing.co.uk",
            page_title="Brightwater Plumbing - Emergency plumbers in Leeds",
            page_text="Brightwater Plumbing serve Leeds. Call 0113 296 0001. 14 Kirkstall Road LS1 4AB",
            phone_digits=["+441132960001"],
            city="Leeds",
            postal_code="LS1 4AB",
        )
        assert r["confidence"] >= 0.8
        assert r["verdict"] == "strong_match"

    def test_unrelated_site_scores_no_match(self):
        r = score_identity(
            business_name="Brightwater Plumbing",
            url="https://www.iana.org",
            page_title="Internet Assigned Numbers Authority",
            page_text="IANA is responsible for coordinating the DNS root and IP addressing.",
            phone_digits=["+441132960001"],
            city="Leeds",
        )
        assert r["confidence"] < 0.3
        assert r["verdict"] == "no_match"

    def test_phone_on_page_is_strong_corroboration(self):
        with_phone = score_identity(
            business_name="Totally Generic Services",
            url="https://somehost.example",
            page_text="Give us a ring on 0113 296 0001 today",
            phone_digits=["+441132960001"],
        )
        without = score_identity(
            business_name="Totally Generic Services",
            url="https://somehost.example",
            page_text="Give us a ring today",
            phone_digits=["+441132960001"],
        )
        assert with_phone["confidence"] > without["confidence"]

    def test_similarly_named_business_is_not_confused(self):
        """The classic failure mode: two firms sharing a generic word."""
        r = score_identity(
            business_name="Anderson Dental Clinic",
            url="https://smithdental.com",
            page_title="Smith Dental - Family dentist in Portland",
            page_text="Smith Dental has served Portland families since 1998.",
            city="Boston",
        )
        assert r["confidence"] < 0.55

    def test_signals_are_reported_for_explainability(self):
        r = score_identity(
            business_name="Brightwater Plumbing",
            url="https://brightwaterplumbing.co.uk",
            page_title="Brightwater Plumbing",
        )
        assert r["signals"]
        assert all({"signal", "weight"} <= set(s) for s in r["signals"])

    def test_confidence_is_bounded(self):
        r = score_identity(
            business_name="Brightwater Plumbing",
            url="https://brightwaterplumbing.co.uk",
            page_title="Brightwater Plumbing Leeds",
            page_text="Brightwater Plumbing Leeds LS1 4AB 0113 296 0001 Kirkstall Road plumbing",
            phone_digits=["+441132960001"],
            city="Leeds", postal_code="LS1 4AB",
            address="14 Kirkstall Road", category="plumber",
        )
        assert 0.0 <= r["confidence"] <= 1.0


class TestCandidateDomains:
    def test_generates_plausible_candidates(self):
        cands = candidate_domains("Brightwater Plumbing", [".co.uk", ".com"])
        assert any("brightwaterplumbing.co.uk" in c for c in cands)

    def test_legal_suffixes_are_ignored(self):
        cands = candidate_domains("Brightwater Plumbing Ltd", [".com"])
        assert all("ltd" not in c for c in cands)

    def test_empty_name_yields_nothing(self):
        assert candidate_domains("") == []

    def test_region_specific_tlds(self):
        assert ".co.uk" in tlds_for_region("GB")
        assert ".com.au" in tlds_for_region("AU")
        assert ".ca" in tlds_for_region("CA")
        assert tlds_for_region(None) == [".com", ".net"]
