"""
Whole-pipeline integration against the local fixture site.

This closes the gap the HTTP end-to-end run cannot cover: the sample CSV's sites
publish no email address, so the WhatsApp-unusable -> crawl -> public email ->
email draft fallback chain is exercised here instead.

DNS is stubbed rather than mocked away entirely: the fixture site's published
address is on a domain that does not resolve, so without a stub the honest
result would be "invalid" and the chain would fall through to the phone. The
stub supplies the MX answer a real business domain would give, and nothing else
about the pipeline is altered.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core import email_validate
from app.core.pipeline import manager
from app.db import session_scope
from app.models import (
    Business, ContactEmail, ContactPhone, Job, JobItem, OutreachDraft, WebsiteAudit,
)
from app.settings import get_profile, save_profile

PROFILE = {
    "full_name": "PIPELINE TEST USER",
    "company_name": "PIPELINE TEST STUDIO",
    "whatsapp_number": "+441132960001",
    "email": "pipeline@test.invalid",
    "service_name": "website redesign",
    "tone": "professional",
}


@pytest.fixture
def configured_profile():
    original = get_profile()
    save_profile(PROFILE)
    yield
    save_profile({k: original.get(k, "") for k in original})


@pytest.fixture
def resolvable_dns(monkeypatch):
    async def fake_lookup(domain, timeout=4.0):
        if "brightwaterplumbing" in domain:
            return (["mx1.brightwaterplumbing.co.uk"], True, "")
        return ([], False, "nxdomain")

    monkeypatch.setattr(email_validate, "lookup_domain", fake_lookup)
    yield


def seed_job(name: str, rows: list[dict]) -> int:
    """rows: [{name, phone, website, city, country}]"""
    headers = ["Business Name", "Phone", "Website", "City", "Country"]
    with session_scope() as s:
        job = Job(name=name, source_filename="int.csv", stored_path="int.csv",
                  original_columns=headers, column_mapping={}, status="queued",
                  total=len(rows))
        s.add(job)
        s.flush()
        for i, r in enumerate(rows):
            raw = {
                "Business Name": r["name"], "Phone": r["phone"], "Website": r["website"],
                "City": r.get("city", ""), "Country": r.get("country", ""),
            }
            b = Business(
                job_id=job.id, row_index=i, raw=raw, name=r["name"],
                phone_raw=r["phone"], website_original=r["website"],
                city=r.get("city", ""), country=r.get("country", ""),
                category=r.get("category", "Plumber"),
            )
            s.add(b)
            s.flush()
            s.add(JobItem(job_id=job.id, business_id=b.id, status="pending", stage="queued"))
        return job.id


async def run_job(job_id: int, timeout: float = 180.0) -> None:
    await manager.start(job_id)
    deadline = asyncio.get_event_loop().time() + timeout
    while manager.is_running(job_id):
        if asyncio.get_event_loop().time() > deadline:
            await manager.cancel(job_id)
            raise AssertionError("job did not finish within the timeout")
        await asyncio.sleep(0.4)


def cleanup(job_id: int) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job:
            s.delete(job)


class TestWhatsAppConfirmedByWebsite:
    async def test_wa_me_link_on_the_site_upgrades_the_status(
        self, local_site, configured_profile
    ):
        """
        The fixture site publishes wa.me/441132960001. libphonenumber classifies
        that number as a landline, but the business itself advertising it as a
        WhatsApp contact is real evidence and correctly overrides the heuristic.
        """
        job_id = seed_job("INTEGRATION WA CONFIRMED", [{
            "name": "Brightwater Plumbing",
            "phone": "+44 113 296 0001",       # the number published as wa.me on the site
            "website": local_site,
            "city": "Leeds",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)
            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                phone = s.query(ContactPhone).filter(
                    ContactPhone.business_id == biz.id).one()
                drafts = s.query(OutreachDraft).filter(
                    OutreachDraft.business_id == biz.id).all()

            assert phone.whatsapp_status == "confirmed_on_website"
            assert "website" in phone.whatsapp_reason.lower()
            assert biz.best_channel == "whatsapp"
            wa_drafts = [d for d in drafts if d.channel == "whatsapp"]
            assert wa_drafts
            initial = next(d for d in wa_drafts if d.variant == "initial")
            assert initial.draft_url.startswith("https://wa.me/441132960001?text=")
        finally:
            cleanup(job_id)


class TestEmailFallbackChain:
    async def test_landline_falls_through_to_public_email_and_email_draft(
        self, local_site, configured_profile, resolvable_dns
    ):
        """
        A UK landline that the site does NOT advertise on WhatsApp cannot use it,
        so the pipeline must crawl the site, find the published address, validate
        it, and produce an email draft.
        """
        job_id = seed_job("INTEGRATION EMAIL", [{
            "name": "Brightwater Plumbing",
            # A landline that is not the number published as wa.me on the site,
            # so the WhatsApp path is genuinely unavailable.
            "phone": "+44 113 296 0002",
            "website": local_site,
            "city": "Leeds",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)

            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                item = s.query(JobItem).filter(JobItem.business_id == biz.id).one()
                phone = s.query(ContactPhone).filter(ContactPhone.business_id == biz.id).one()
                emails = (s.query(ContactEmail)
                          .filter(ContactEmail.business_id == biz.id)
                          .order_by(ContactEmail.rank).all())
                audit = s.query(WebsiteAudit).filter(WebsiteAudit.business_id == biz.id).one()
                drafts = s.query(OutreachDraft).filter(
                    OutreachDraft.business_id == biz.id).all()

            assert item.status == "completed"

            # 1. the website was validated as belonging to this business
            assert biz.website_status == "valid", biz.website_status
            assert biz.website_identity_confidence is not None

            # 2. WhatsApp was correctly ruled out rather than assumed
            assert phone.phone_normalized == "+441132960002"
            assert phone.whatsapp_status == "unlikely"
            assert phone.whatsapp_url == ""

            # 3. public emails were discovered from the site itself
            found = {e.email for e in emails}
            assert "info@brightwaterplumbing.co.uk" in found
            assert "bookings@brightwaterplumbing.co.uk" in found
            assert "office@brightwaterplumbing.co.uk" in found  # de-obfuscated
            best = emails[0]
            assert best.status in ("valid_public", "mx_valid")
            assert best.source_url.startswith(local_site)
            assert best.page_type in ("homepage", "contact")

            # 4. the channel fell through to email, with a stated reason
            assert biz.best_channel == "email", biz.channel_reason
            assert "whatsapp" in biz.channel_reason.lower()
            assert "email" in biz.channel_reason.lower()

            # 5. the site was audited and scored on real evidence
            assert audit.audit_status in ("completed", "no_clear_opportunity")
            assert audit.pages_crawled >= 2
            assert audit.score is not None
            assert len(audit.score_explanation) == 6

            # 6. an email draft exists, built from the measured findings
            email_drafts = [d for d in drafts if d.channel == "email"]
            if audit.problems:
                assert email_drafts, "expected an email draft"
                initial = next(d for d in email_drafts if d.variant == "initial")
                assert initial.subject
                assert initial.draft_url.startswith("mailto:info@brightwaterplumbing.co.uk")
                assert initial.based_on
                for entry in initial.based_on:
                    assert entry["observation"] in initial.message
                assert "PIPELINE TEST USER" in initial.message
                # follow-ups prepared but, like everything else, not sent
                assert {d.variant for d in email_drafts} >= {"initial", "followup_1"}
            else:
                assert audit.audit_status == "no_clear_opportunity"
        finally:
            cleanup(job_id)


class TestStrictWhatsAppEndToEnd:
    """The core routing rewrite: a WhatsApp-capable mobile number that is NOT
    the number the business actually publishes a wa.me link for must fall
    through to email - exactly like a landline always has. A phone number
    (however it was sourced, including from Google Maps) is never, by
    itself, treated as WhatsApp."""

    async def test_unconfirmed_mobile_falls_through_to_email_not_whatsapp(
        self, local_site, configured_profile, resolvable_dns
    ):
        job_id = seed_job("INTEGRATION STRICT WHATSAPP", [{
            "name": "Brightwater Plumbing",
            # A UK mobile - WhatsApp-capable by TYPE - but not the number
            # published as wa.me (441132960001) on the fixture site, so there
            # is no real evidence for WhatsApp.
            "phone": "+44 7911 555000",
            "website": local_site,
            "city": "Leeds",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)
            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                phone = s.query(ContactPhone).filter(ContactPhone.business_id == biz.id).one()
                drafts = s.query(OutreachDraft).filter(
                    OutreachDraft.business_id == biz.id).all()

            assert phone.phone_normalized == "+447911555000"
            # Informational status is still computed and shown...
            assert phone.whatsapp_status == "usable_unverified"
            # ...but it must NOT have won channel selection or produced a
            # WhatsApp draft; email (published on the site) must have.
            assert biz.best_channel == "email"
            assert phone.whatsapp_url == ""
            assert all(d.channel != "whatsapp" for d in drafts)
        finally:
            cleanup(job_id)


class TestNoContactChannel:
    async def test_no_phone_and_no_website_is_excluded_not_invented(
        self, configured_profile
    ):
        """A business with no website (and no phone) is excluded outright -
        no audit, no score, no draft - rather than given the old "no website"
        opportunity pitch."""
        job_id = seed_job("INTEGRATION NO CONTACT", [{
            "name": "Totally Unreachable Bakery Zzq",
            "phone": "",
            "website": "",
            "city": "Manchester",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)
            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                item = s.query(JobItem).filter(JobItem.business_id == biz.id).one()
                emails = s.query(ContactEmail).filter(
                    ContactEmail.business_id == biz.id).all()
                audits = s.query(WebsiteAudit).filter(
                    WebsiteAudit.business_id == biz.id).all()
                drafts = s.query(OutreachDraft).filter(
                    OutreachDraft.business_id == biz.id).all()

            assert item.status == "skipped"
            assert item.stage == "no_website"
            assert biz.website_status == "no_website"
            assert biz.best_channel == "none"
            assert emails == []          # nothing invented
            assert audits == []          # not audited
            assert drafts == []          # not drafted
            assert biz.score is None
            assert biz.lead_tier == ""   # not scored/tiered
        finally:
            cleanup(job_id)

    async def test_whatsapp_capable_phone_with_no_website_is_still_excluded(
        self, configured_profile
    ):
        """
        Before this rule, a WhatsApp-capable phone number produced a draft
        entirely independently of whether the business had a website. A valid
        website is now required for ANY processing, so this lead must be
        excluded - no crawl, no WhatsApp draft, no channel selection - even
        though the phone number alone would previously have been enough.
        """
        job_id = seed_job("INTEGRATION PHONE NO WEBSITE", [{
            "name": "Mobile Only Bakery Zzq",
            "phone": "+44 7911 987654",   # valid UK mobile - WhatsApp-capable
            "website": "",
            "city": "Leeds",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)
            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                item = s.query(JobItem).filter(JobItem.business_id == biz.id).one()
                phones = s.query(ContactPhone).filter(
                    ContactPhone.business_id == biz.id).all()
                audits = s.query(WebsiteAudit).filter(
                    WebsiteAudit.business_id == biz.id).all()
                drafts = s.query(OutreachDraft).filter(
                    OutreachDraft.business_id == biz.id).all()

            assert item.status == "skipped"
            assert item.stage == "no_website"
            assert biz.website_status == "no_website"
            assert biz.best_channel == "none"
            assert biz.score is None
            assert biz.lead_tier == ""
            assert phones == []                              # not enriched
            assert audits == []                               # not audited
            assert all(d.channel != "whatsapp" for d in drafts)  # no WhatsApp draft
            assert drafts == []                                # nothing drafted at all
        finally:
            cleanup(job_id)


class TestIdentityGuardInPipeline:
    async def test_wrong_site_is_not_attributed_to_the_business(
        self, local_site, configured_profile
    ):
        """
        The CSV points a business at a site that is clearly not theirs. A
        mismatched site counts as "no valid website", so the lead is excluded
        outright rather than audited (which would produce findings about
        someone else's website) or drafted.
        """
        job_id = seed_job("INTEGRATION MISMATCH", [{
            "name": "Completely Unrelated Dental Surgery",
            "phone": "+44 113 296 0002",
            "website": local_site,
            "city": "Bristol",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)
            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                item = s.query(JobItem).filter(JobItem.business_id == biz.id).one()
                audits = s.query(WebsiteAudit).filter(
                    WebsiteAudit.business_id == biz.id).all()
                drafts = s.query(OutreachDraft).filter(
                    OutreachDraft.business_id == biz.id).all()

            assert item.status == "skipped"
            assert item.stage == "no_website"
            assert biz.website_status == "mismatch"
            assert biz.score is None
            assert biz.lead_tier == ""
            assert audits == []      # not audited at all
            assert drafts == []      # no outreach written for a mismatched site
        finally:
            cleanup(job_id)


class TestResumeThroughPipeline:
    async def test_completed_leads_are_not_reprocessed_on_resume(
        self, local_site, configured_profile
    ):
        job_id = seed_job("INTEGRATION RESUME", [
            {"name": "Brightwater Plumbing", "phone": "+44 113 296 0001",
             "website": local_site, "city": "Leeds", "country": "United Kingdom"},
            {"name": "Second Business Zzq", "phone": "", "website": "",
             "city": "Leeds", "country": "United Kingdom"},
        ])
        try:
            await run_job(job_id)

            with session_scope(write=False) as s:
                first = (s.query(Business).filter(Business.job_id == job_id)
                         .order_by(Business.row_index).first())
                processed_at = first.processed_at
                assert processed_at is not None

            # Mark only the second lead as unfinished, then resume.
            with session_scope() as s:
                second = (s.query(Business).filter(Business.job_id == job_id)
                          .order_by(Business.row_index.desc()).first())
                item = s.query(JobItem).filter(JobItem.business_id == second.id).one()
                item.status = "pending"
                item.stage = "queued"

            await run_job(job_id)

            with session_scope(write=False) as s:
                first_again = (s.query(Business).filter(Business.job_id == job_id)
                               .order_by(Business.row_index).first())
                items = s.query(JobItem).filter(JobItem.job_id == job_id).all()

            # The already-completed lead was left exactly as it was. The second
            # lead has no website, so it resumes into "skipped" (excluded), not
            # "completed" - both are terminal, neither is left pending/running.
            assert first_again.processed_at == processed_at
            assert all(i.status in ("completed", "skipped") for i in items)
            assert {i.status for i in items} == {"completed", "skipped"}
        finally:
            cleanup(job_id)


# --------------------------------------------------------------------------
# A second small fixture site, distinct from local_site (conftest.py), whose
# pages deliberately publish no email and no WhatsApp link - so the LinkedIn
# and phone/skip steps of the routing chain can be exercised end-to-end.
# --------------------------------------------------------------------------

LINKEDIN_PAGE = """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contact Routing Test Ltd - Roofing specialists</title></head>
<body>
  <h1>Contact Routing Test Ltd</h1>
  <p>We are Contact Routing Test Ltd, roofing specialists serving Manchester.
     Call <a href="tel:+441615550100">0161 555 0100</a>.</p>
  <p>Established 2010. Fully insured roofers covering Greater Manchester.</p>
  <footer>
    <a href="https://www.linkedin.com/company/contact-routing-test">Follow us on LinkedIn</a>
    <a href="https://www.facebook.com/contactroutingtest">Facebook</a>
  </footer>
</body>
</html>
"""

BARE_PAGE = """<!doctype html>
<html lang="en">
<head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contact Routing Bare Ltd - Roofing specialists</title></head>
<body>
  <h1>Contact Routing Bare Ltd</h1>
  <p>We are Contact Routing Bare Ltd, roofing specialists serving Manchester.
     Call <a href="tel:+441615550200">0161 555 0200</a>.</p>
  <p>Established 2010. Fully insured roofers covering Greater Manchester.</p>
</body>
</html>
"""


class _RoutingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def _send(self, body: str, status: int = 200):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_HEAD(self):  # noqa: N802
        if self.path.split("?")[0] in ("/linkedin", "/bare", "/robots.txt"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/linkedin":
            self._send(LINKEDIN_PAGE)
        elif path == "/bare":
            self._send(BARE_PAGE)
        elif path == "/robots.txt":
            self._send("User-agent: *\nDisallow: /private\n")
        else:
            self._send("<html><body>Not found</body></html>", status=404)


@pytest.fixture(scope="session")
def routing_site():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), _RoutingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


class TestLinkedInFallback:
    async def test_no_whatsapp_no_email_falls_through_to_linkedin(
        self, routing_site, configured_profile
    ):
        job_id = seed_job("INTEGRATION LINKEDIN", [{
            "name": "Contact Routing Test Ltd",
            "phone": "+44 161 555 0100",
            "website": f"{routing_site}/linkedin",
            "city": "Manchester",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)
            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                item = s.query(JobItem).filter(JobItem.business_id == biz.id).one()
                drafts = s.query(OutreachDraft).filter(
                    OutreachDraft.business_id == biz.id).all()

            assert item.status == "completed"
            assert biz.linkedin_status == "found"
            assert biz.linkedin_url == "https://www.linkedin.com/company/contact-routing-test"
            assert biz.best_channel == "linkedin"
            li_drafts = [d for d in drafts if d.channel == "linkedin"]
            if li_drafts:  # only written when a strong problem was detected
                assert li_drafts[0].draft_url == biz.linkedin_url
                assert li_drafts[0].message
        finally:
            cleanup(job_id)


class TestPhoneFallback:
    async def test_no_whatsapp_no_email_no_linkedin_falls_through_to_phone(
        self, routing_site, configured_profile
    ):
        job_id = seed_job("INTEGRATION PHONE FALLBACK", [{
            "name": "Contact Routing Bare Ltd",
            "phone": "+44 161 555 0200",
            "website": f"{routing_site}/bare",
            "city": "Manchester",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)
            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                item = s.query(JobItem).filter(JobItem.business_id == biz.id).one()

            assert item.status == "completed"
            assert biz.linkedin_status == "not_found"
            assert biz.best_channel == "phone"
        finally:
            cleanup(job_id)


class TestSkipNoContactChannel:
    async def test_valid_site_but_no_channel_at_all_is_marked_skip(
        self, routing_site, configured_profile
    ):
        """Same bare site, but this business supplied no phone number at all,
        so every channel comes up empty. It is fully audited (it has a valid
        website) but the contact channel is SKIP, and no draft is written."""
        job_id = seed_job("INTEGRATION SKIP", [{
            "name": "Contact Routing Bare Ltd",
            "phone": "",
            "website": f"{routing_site}/bare",
            "city": "Manchester",
            "country": "United Kingdom",
        }])
        try:
            await run_job(job_id)
            with session_scope(write=False) as s:
                biz = s.query(Business).filter(Business.job_id == job_id).one()
                item = s.query(JobItem).filter(JobItem.business_id == biz.id).one()
                drafts = s.query(OutreachDraft).filter(
                    OutreachDraft.business_id == biz.id).all()

            assert item.status == "completed"  # audited - it has a valid website
            assert biz.best_channel == "none"  # but SKIP for outreach purposes
            assert drafts == []
        finally:
            cleanup(job_id)
