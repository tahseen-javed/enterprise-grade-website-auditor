"""Public contact extraction and email validation (spec 9, 10, 46)."""

from __future__ import annotations

import pytest

from app.core.crawler import CrawlResult
from app.core.email_validate import (
    STATUS_INVALID,
    STATUS_RISKY,
    STATUS_SYNTAX_VALID,
    is_usable_for_outreach,
    validate_found_email,
)
from app.core.extract import FoundEmail, extract_contacts
from app.core.page import parse_html


def make_crawl(pages_html, base="https://brightwaterplumbing.co.uk"):
    """Builds a CrawlResult from (page_type, path, html) tuples."""
    crawl = CrawlResult(start_url=base, final_url=base, ok=True)
    for ptype, path, html in pages_html:
        url = base + path
        crawl.pages.append(parse_html(html, url, final_url=url, status=200, page_type=ptype))
    return crawl


HOME = """<html><body>
<header><a href="tel:+441132960001">0113 296 0001</a></header>
<p>Welcome to Brightwater Plumbing.</p>
<footer>Email <a href="mailto:info@brightwaterplumbing.co.uk">info@brightwaterplumbing.co.uk</a></footer>
</body></html>"""

CONTACT = """<html><body>
<h1>Contact</h1>
<p>Reach us at <a href="mailto:bookings@brightwaterplumbing.co.uk">bookings@brightwaterplumbing.co.uk</a></p>
<p>Or office [at] brightwaterplumbing [dot] co [dot] uk</p>
<p>Accounts: accounts@brightwaterplumbing.co.uk</p>
<a href="https://wa.me/441132960001">WhatsApp us</a>
<form action="/send" method="post">
  <input type="email" name="email"><textarea name="message"></textarea>
  <button>Send</button>
</form>
</body></html>"""

NOISY = """<html><body>
<img src="logo@2x.png" alt="x">
<p>Contact: real.person@brightwaterplumbing.co.uk</p>
<p>Placeholder: yourname@example.com and user@domain.com</p>
<script>var s="1a2b3c4d5e6f7a8b9c0d1e2f@sentry.wixpress.com";</script>
<p>noreply@brightwaterplumbing.co.uk</p>
</body></html>"""


class TestEmailExtraction:
    def test_finds_mailto_addresses(self):
        crawl = make_crawl([("homepage", "/", HOME)])
        r = extract_contacts(crawl, "brightwaterplumbing.co.uk")
        assert "info@brightwaterplumbing.co.uk" in [e.email for e in r.emails]

    def test_finds_visible_and_obfuscated_addresses(self):
        crawl = make_crawl([("contact", "/contact", CONTACT)])
        emails = {e.email for e in extract_contacts(crawl, "brightwaterplumbing.co.uk").emails}
        assert "bookings@brightwaterplumbing.co.uk" in emails
        assert "accounts@brightwaterplumbing.co.uk" in emails
        assert "office@brightwaterplumbing.co.uk" in emails  # de-obfuscated

    def test_source_url_and_page_type_are_recorded(self):
        crawl = make_crawl([("contact", "/contact", CONTACT)])
        found = extract_contacts(crawl, "brightwaterplumbing.co.uk").emails[0]
        assert found.source_url.endswith("/contact")
        assert found.page_type == "contact"
        assert found.source_type in ("mailto", "text", "obfuscated", "footer", "jsonld")

    def test_filenames_placeholders_and_tooling_are_excluded(self):
        crawl = make_crawl([("homepage", "/", NOISY)])
        emails = {e.email for e in extract_contacts(crawl, "brightwaterplumbing.co.uk").emails}
        assert "real.person@brightwaterplumbing.co.uk" in emails
        assert not any("example.com" in e for e in emails)
        assert not any("domain.com" in e for e in emails)
        assert not any("wixpress" in e for e in emails)
        assert not any(e.startswith("noreply@") for e in emails)
        assert not any(e.endswith(".png") for e in emails)

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Multi-label suffixes must survive whole, not truncate to ".co".
            ("office [at] brightwaterplumbing [dot] co [dot] uk",
             "office@brightwaterplumbing.co.uk"),
            ("hello AT acme DOT co DOT nz", "hello@acme.co.nz"),
            ("info (at) acme (dot) co (dot) uk", "info@acme.co.uk"),
            # A following sentence must not be absorbed as another label.
            ("reach us at office [at] brightwaterplumbing [dot] co [dot] uk. Find us at 14 Kirkstall Road.",
             "office@brightwaterplumbing.co.uk"),
            ("mail team [at] studio.co.uk. Thanks", "team@studio.co.uk"),
            ("sales [at] shop [dot] com. Call today.", "sales@shop.com"),
        ],
    )
    def test_obfuscated_addresses_are_decoded_exactly(self, text, expected):
        from app.core.extract import _scan_text

        assert expected in [e for e, _kind, _ctx in _scan_text(text)]

    def test_nothing_is_invented_when_no_address_exists(self):
        crawl = make_crawl([("homepage", "/", "<html><body><h1>Hi</h1></body></html>")])
        r = extract_contacts(crawl, "brightwaterplumbing.co.uk")
        assert r.emails == []

    def test_own_domain_addresses_rank_above_free_providers(self):
        html = """<html><body>
        <a href="mailto:someone@gmail.com">gmail</a>
        <a href="mailto:info@brightwaterplumbing.co.uk">own</a>
        </body></html>"""
        crawl = make_crawl([("contact", "/contact", html)])
        emails = extract_contacts(crawl, "brightwaterplumbing.co.uk").emails
        assert emails[0].email == "info@brightwaterplumbing.co.uk"
        assert emails[0].domain_matches_site is True

    def test_role_addresses_are_ordered_by_usefulness(self):
        html = """<html><body>
        <a href="mailto:support@brightwaterplumbing.co.uk">s</a>
        <a href="mailto:info@brightwaterplumbing.co.uk">i</a>
        </body></html>"""
        crawl = make_crawl([("contact", "/contact", html)])
        emails = [e.email for e in extract_contacts(crawl, "brightwaterplumbing.co.uk").emails]
        assert emails.index("info@brightwaterplumbing.co.uk") < emails.index(
            "support@brightwaterplumbing.co.uk"
        )

    def test_duplicates_collapse_to_best_source(self):
        crawl = make_crawl([("homepage", "/", HOME), ("contact", "/contact", HOME)])
        emails = [e.email for e in extract_contacts(crawl, "brightwaterplumbing.co.uk").emails]
        assert len(emails) == len(set(emails))


class TestOtherContactSignals:
    def test_whatsapp_link_and_number_detected(self):
        crawl = make_crawl([("contact", "/contact", CONTACT)])
        r = extract_contacts(crawl, "brightwaterplumbing.co.uk")
        assert r.whatsapp_links
        assert "441132960001" in r.whatsapp_numbers

    def test_tel_links_detected(self):
        crawl = make_crawl([("homepage", "/", HOME)])
        r = extract_contacts(crawl, "brightwaterplumbing.co.uk")
        assert r.tel_links

    def test_real_contact_form_detected_but_search_ignored(self):
        search_only = """<html><body>
        <form action="/search"><input type="text" name="q"><button>Search</button></form>
        </body></html>"""
        crawl = make_crawl([("contact", "/contact", search_only)])
        assert extract_contacts(crawl, "x.co.uk").contact_form_urls == []

        crawl2 = make_crawl([("contact", "/contact", CONTACT)])
        assert extract_contacts(crawl2, "brightwaterplumbing.co.uk").contact_form_urls

    def test_newsletter_form_is_not_a_contact_form(self):
        html = """<html><body>
        <form class="mc4wp-form newsletter"><input type="email" name="EMAIL">
        <button>Subscribe</button></form></body></html>"""
        crawl = make_crawl([("homepage", "/", html)])
        assert extract_contacts(crawl, "x.co.uk").contact_form_urls == []

    def test_contact_names_extracted_from_about_page(self):
        about = """<html><body><h2>Dave Wilkinson</h2>
        <p>Dave Wilkinson, owner, founded the company in 2004.</p></body></html>"""
        crawl = make_crawl([("about", "/about", about)])
        names = extract_contacts(crawl, "x.co.uk").contact_names
        assert "Dave Wilkinson" in names

    def test_navigation_words_are_not_mistaken_for_names(self):
        about = """<html><body><h2>Contact Us</h2><h2>Our Team</h2>
        <p>Read More about our services</p></body></html>"""
        crawl = make_crawl([("about", "/about", about)])
        names = extract_contacts(crawl, "x.co.uk").contact_names
        assert "Contact Us" not in names
        assert "Our Team" not in names


class TestLinkedInDiscovery:
    """LinkedIn is only ever a link the business published on its own site -
    found during the same crawl already done for the audit, never a separate
    LinkedIn.com request and never a guess (spec: contact routing step 3)."""

    def test_company_page_link_detected(self):
        html = """<html><body><footer>
        <a href="https://www.linkedin.com/company/brightwater-plumbing">LinkedIn</a>
        </footer></body></html>"""
        crawl = make_crawl([("homepage", "/", html)])
        r = extract_contacts(crawl, "brightwaterplumbing.co.uk")
        assert r.linkedin_urls == ["https://www.linkedin.com/company/brightwater-plumbing"]

    def test_showcase_page_is_accepted(self):
        html = '<html><body><a href="https://linkedin.com/showcase/acme-widgets/">LinkedIn</a></body></html>'
        crawl = make_crawl([("homepage", "/", html)])
        r = extract_contacts(crawl, "x.co.uk")
        assert r.linkedin_urls

    def test_personal_profile_is_never_accepted(self):
        """spec: never a personal employee profile, only the official
        company page - even when it's the only LinkedIn link on the site."""
        html = '<html><body><a href="https://www.linkedin.com/in/dave-wilkinson-123">Dave on LinkedIn</a></body></html>'
        crawl = make_crawl([("about", "/about", html)])
        r = extract_contacts(crawl, "x.co.uk")
        assert r.linkedin_urls == []

    def test_no_linkedin_link_on_site_yields_nothing(self):
        crawl = make_crawl([("homepage", "/", HOME)])
        r = extract_contacts(crawl, "brightwaterplumbing.co.uk")
        assert r.linkedin_urls == []

    def test_other_social_links_are_not_mistaken_for_linkedin(self):
        html = """<html><body>
        <a href="https://www.facebook.com/brightwaterplumbing">Facebook</a>
        <a href="https://www.instagram.com/brightwaterplumbing">Instagram</a>
        </body></html>"""
        crawl = make_crawl([("homepage", "/", html)])
        r = extract_contacts(crawl, "brightwaterplumbing.co.uk")
        assert r.linkedin_urls == []
        assert r.social_links  # still captured generically

    def test_duplicate_links_across_pages_are_deduplicated(self):
        html = '<html><body><a href="https://www.linkedin.com/company/acme">LinkedIn</a></body></html>'
        crawl = make_crawl([("homepage", "/", html), ("contact", "/contact", html)])
        r = extract_contacts(crawl, "x.co.uk")
        assert r.linkedin_urls == ["https://www.linkedin.com/company/acme"]


class TestEmailValidation:
    def _found(self, email, **kw):
        kw.setdefault("source_url", "https://brightwaterplumbing.co.uk/contact")
        kw.setdefault("source_type", "mailto")
        kw.setdefault("page_type", "contact")
        kw.setdefault("confidence", 0.9)
        return FoundEmail(email=email, **kw)

    async def test_syntax_failure_is_invalid(self):
        v = await validate_found_email(self._found("not-an-email"), enable_mx=False)
        assert v.status == STATUS_INVALID
        assert v.confidence == 0.0

    async def test_disposable_domain_is_risky(self):
        v = await validate_found_email(self._found("a@mailinator.com"), enable_mx=False)
        assert v.status == STATUS_RISKY

    async def test_without_dns_only_syntax_is_claimed(self):
        v = await validate_found_email(
            self._found("info@brightwaterplumbing.co.uk"), enable_mx=False
        )
        assert v.status == STATUS_SYNTAX_VALID
        assert any("not checked" in n.lower() or "disabled" in n.lower() for n in v.notes)

    async def test_role_and_free_provider_flags(self):
        role = await validate_found_email(self._found("info@brightwaterplumbing.co.uk"), enable_mx=False)
        assert role.is_role is True
        free = await validate_found_email(self._found("someone@gmail.com"), enable_mx=False)
        assert free.is_free_provider is True

    async def test_domain_match_is_recorded(self):
        v = await validate_found_email(
            self._found("info@brightwaterplumbing.co.uk"),
            site_domain="brightwaterplumbing.co.uk",
            enable_mx=False,
        )
        assert v.domain_matches_site is True

    async def test_deliverability_is_never_claimed(self):
        v = await validate_found_email(
            self._found("info@brightwaterplumbing.co.uk"), enable_mx=False
        )
        assert not any("deliverable" in n.lower() and "not" not in n.lower() for n in v.notes)

    async def test_nonexistent_domain_is_invalid(self):
        v = await validate_found_email(
            self._found("a@this-domain-truly-does-not-exist-zzq123.example"),
            enable_mx=True, dns_timeout=4.0,
        )
        # NXDOMAIN -> invalid; if DNS is unavailable the honest answer is unknown.
        assert v.status in (STATUS_INVALID, "unknown")

    def test_usable_statuses(self):
        assert is_usable_for_outreach("valid_public")
        assert is_usable_for_outreach("mx_valid")
        assert is_usable_for_outreach("domain_valid")
        assert not is_usable_for_outreach("invalid")
        assert not is_usable_for_outreach("risky")
        assert not is_usable_for_outreach("unknown")
