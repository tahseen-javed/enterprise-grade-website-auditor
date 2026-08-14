"""
Outreach generation (spec 18-22, 39, 40, 43, 53, 54).

These tests exist mainly to pin down the honesty guarantees: no fabricated
claims, no message without a measured finding, no identity invented for the
user, and nothing ever sent.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

import pytest

from app.core.observations import OBSERVATIONS, observation_for, pick_observations
from app.core.outreach import (
    OutreachContext,
    ProfileIncomplete,
    build_call_notes,
    build_email_message,
    build_linkedin_message,
    build_whatsapp_message,
    choose_channel,
    mailto_url,
)
from app.core.phones import whatsapp_url

PROFILE = {
    "full_name": "Alex Morgan",
    "company_name": "Morgan Studio",
    "whatsapp_number": "+447911123456",
    "email": "alex@morganstudio.test",
    "website_url": "https://morganstudio.test",
    "service_name": "website redesign",
    "target_service": "local service businesses",
    "booking_url": "",
    "email_signature": "",
    "tone": "professional",
}

CTA_PROBLEM = {
    "rank": 1, "code": "no_primary_cta_above_fold", "category": "conversion",
    "category_label": "Conversion readiness", "severity": "high",
    "title": "No clear call to action was found near the top of the homepage",
    "detail": "The header and opening section contain no phone link or booking wording.",
    "evidence": {"checked": "header markup"}, "impact_points": 22, "is_strong_signal": True,
}
MOBILE_PROBLEM = {
    "rank": 2, "code": "no_mobile_tap_to_call", "category": "mobile",
    "category_label": "Mobile experience", "severity": "high",
    "title": "The homepage has no tap-to-call phone link",
    "detail": "No tel: link was found on the homepage.",
    "evidence": {"pages_checked": 5, "found_elsewhere": False},
    "impact_points": 20, "is_strong_signal": True,
}
SPEED_PROBLEM = {
    "rank": 3, "code": "slow_response", "category": "performance",
    "category_label": "Performance", "severity": "medium",
    "title": "The homepage was slow to respond",
    "detail": "The homepage took 3800 ms to return.",
    "evidence": {"response_ms": 3800}, "impact_points": 14, "is_strong_signal": True,
}
TRUST_PROBLEM = {
    "rank": 4, "code": "no_testimonials", "category": "trust",
    "category_label": "Trust & proof", "severity": "high",
    "title": "No testimonials or customer reviews were found on the site",
    "detail": "None of the 5 crawled pages mention reviews.",
    "evidence": {"pages_crawled": 5}, "impact_points": 24, "is_strong_signal": True,
}


def ctx(problems=None, **kw):
    base = dict(
        business_id=42, business_name="Brightwater Plumbing", category="Plumber",
        city="Leeds", state="", country="United Kingdom",
        website="https://brightwaterplumbing.co.uk",
        problems=problems if problems is not None else [CTA_PROBLEM, MOBILE_PROBLEM],
        score=78, audit_kind="website", report_available=True,
    )
    base.update(kw)
    return OutreachContext(**base)


BANNED_CLAIMS = [
    "losing customers", "lost customers", "losing money", "costing you",
    "lost revenue", "guaranteed", "guarantee results", "100%", "double your",
    "triple your", "10x", "act now", "limited time", "last chance", "urgent",
    "risk-free", "no-brainer", "skyrocket", "explode your",
]


class TestWhatsAppMessages:
    def test_message_names_the_measured_problem(self):
        """The invariant is that the observation text itself appears verbatim -
        not that any particular phrasing variant was chosen."""
        d = build_whatsapp_message(ctx(), PROFILE)
        assert d.ok
        assert "Brightwater Plumbing" in d.message
        assert d.based_on
        for entry in d.based_on:
            assert entry["observation"] in d.message

    def test_based_on_records_the_evidence_used(self):
        d = build_whatsapp_message(ctx(), PROFILE)
        codes = {b["code"] for b in d.based_on}
        assert codes <= {"no_primary_cta_above_fold", "no_mobile_tap_to_call"}
        assert codes

    def test_no_message_without_a_measured_problem(self):
        d = build_whatsapp_message(ctx(problems=[]), PROFILE)
        assert not d.ok
        assert d.skipped_reason
        assert d.message == ""

    def test_structure_is_intro_observation_offer_permission(self):
        d = build_whatsapp_message(ctx(), PROFILE)
        low = d.message.lower()
        # 1. greeting
        assert low.startswith("hi") or low.startswith("hello") or low.startswith("hey")
        # 2. context naming the business and its industry
        assert "brightwater plumbing" in low
        assert "plumbers" in low
        # 3. the specific observation
        assert d.based_on[0]["observation"] in d.message
        # 4. a permission-based close rather than a demand
        assert "?" in d.message or "happy to" in low or "up to you" in low

    def test_message_is_short_enough_to_read(self):
        d = build_whatsapp_message(ctx(), PROFILE)
        assert len(d.message) < 700
        assert len(d.message.split()) < 120

    def test_at_most_two_observations_are_mentioned(self):
        d = build_whatsapp_message(
            ctx(problems=[CTA_PROBLEM, MOBILE_PROBLEM, SPEED_PROBLEM, TRUST_PROBLEM]), PROFILE
        )
        assert len(d.based_on) <= 2

    def test_no_fabricated_or_pushy_claims(self):
        d = build_whatsapp_message(
            ctx(problems=[CTA_PROBLEM, MOBILE_PROBLEM, SPEED_PROBLEM, TRUST_PROBLEM]), PROFILE
        )
        low = d.message.lower()
        for phrase in BANNED_CLAIMS:
            assert phrase not in low, phrase

    def test_audit_offer_only_when_report_exists(self):
        with_report = build_whatsapp_message(ctx(report_available=True), PROFILE).message.lower()
        without = build_whatsapp_message(ctx(report_available=False), PROFILE).message.lower()
        assert "put together" in with_report or "written up" in with_report
        assert "put together" not in without and "written up" not in without

    def test_different_problems_produce_different_messages(self):
        cta = build_whatsapp_message(ctx(problems=[CTA_PROBLEM]), PROFILE).message
        speed = build_whatsapp_message(ctx(problems=[SPEED_PROBLEM]), PROFILE).message
        trust = build_whatsapp_message(ctx(problems=[TRUST_PROBLEM]), PROFILE).message
        assert len({cta, speed, trust}) == 3

    def test_measured_number_is_quoted_accurately(self):
        d = build_whatsapp_message(ctx(problems=[SPEED_PROBLEM]), PROFILE)
        assert "3800" in d.message

    def test_no_placeholder_survives_into_the_message(self):
        for problems in ([CTA_PROBLEM], [SPEED_PROBLEM], [TRUST_PROBLEM], [MOBILE_PROBLEM]):
            d = build_whatsapp_message(ctx(problems=problems), PROFILE)
            assert "{" not in d.message and "}" not in d.message
            assert "None" not in d.message

    def test_pronoun_i_is_not_lowercased_mid_sentence(self):
        d = build_whatsapp_message(ctx(problems=[MOBILE_PROBLEM]), PROFILE)
        assert not re.search(r"\bnoticed i\b", d.message)
        assert not re.search(r"(?<![A-Za-z])i\s+(couldn't|could not|found|noticed)", d.message)

    def test_industry_phrase_reads_naturally(self):
        for category, expect_not in (("Plumber", "plumberss"), ("Web Testing", "web testings"),
                                     ("Auto Repair", "auto repairs")):
            d = build_whatsapp_message(ctx(category=category), PROFILE)
            assert expect_not not in d.message.lower()

    def test_contact_name_is_used_when_known(self):
        d = build_whatsapp_message(ctx(contact_name="Dave Wilkinson"), PROFILE)
        assert "Dave" in d.message

    def test_no_name_means_no_empty_placeholder(self):
        d = build_whatsapp_message(ctx(contact_name=""), PROFILE)
        assert "Hi," in d.message or "Hello," in d.message

    def test_no_website_case_does_not_pretend_to_have_audited(self):
        no_site = {
            "rank": 1, "code": "no_website_detected", "category": "conversion",
            "category_label": "Conversion readiness", "severity": "high",
            "title": "No website could be found for this business",
            "detail": "Checked the usual places.", "evidence": {}, "impact_points": 0,
            "is_strong_signal": True,
        }
        d = build_whatsapp_message(
            ctx(problems=[no_site], audit_kind="no_website", website="", report_available=False),
            PROFILE,
        )
        assert d.ok
        low = d.message.lower()
        assert "your website" not in low
        assert "couldn't find" in low or "does not look" in low or "doesn't look" in low

    def test_all_tones_produce_valid_messages(self):
        for tone in ("professional", "friendly", "consultant", "founder"):
            profile = {**PROFILE, "tone": tone}
            d = build_whatsapp_message(ctx(), profile)
            assert d.ok
            assert "{" not in d.message
            for phrase in BANNED_CLAIMS:
                assert phrase not in d.message.lower()

    def test_followups_are_short_and_offer_an_exit(self):
        f1 = build_whatsapp_message(ctx(), PROFILE, "followup_1")
        f2 = build_whatsapp_message(ctx(), PROFILE, "followup_2")
        assert f1.ok and f2.ok
        assert len(f1.message) < 400 and len(f2.message) < 400
        assert "no pressure" in f1.message.lower() or "completely fine" in f1.message.lower()
        assert "last message" in f2.message.lower()

    def test_profile_must_be_configured(self):
        for missing in ("full_name", "company_name", "service_name"):
            broken = {**PROFILE, missing: ""}
            with pytest.raises(ProfileIncomplete) as e:
                build_whatsapp_message(ctx(), broken)
            assert missing in e.value.missing

    def test_generation_is_deterministic(self):
        a = build_whatsapp_message(ctx(), PROFILE).message
        b = build_whatsapp_message(ctx(), PROFILE).message
        assert a == b


class TestEmailMessages:
    def test_subject_and_body_are_produced(self):
        d = build_email_message(ctx(), PROFILE)
        assert d.ok and d.subject and d.message
        assert len(d.subject) < 80

    def test_signature_is_built_from_the_user_profile(self):
        d = build_email_message(ctx(), PROFILE)
        assert "Alex Morgan" in d.message
        assert "Morgan Studio" in d.message

    def test_custom_signature_is_respected(self):
        profile = {**PROFILE, "email_signature": "Cheers,\nAlex\nMorgan Studio Ltd"}
        d = build_email_message(ctx(), PROFILE | profile)
        assert "Morgan Studio Ltd" in d.message

    def test_booking_link_included_only_when_set(self):
        without = build_email_message(ctx(), PROFILE).message
        with_link = build_email_message(ctx(), {**PROFILE, "booking_url": "https://cal.test/x"}).message
        assert "cal.test" not in without
        assert "cal.test" in with_link

    def test_email_requires_the_users_address(self):
        with pytest.raises(ProfileIncomplete):
            build_email_message(ctx(), {**PROFILE, "email": ""})

    def test_no_spam_phrases_or_fake_urgency(self):
        d = build_email_message(
            ctx(problems=[CTA_PROBLEM, TRUST_PROBLEM]), PROFILE
        )
        blob = (d.subject + " " + d.message).lower()
        for phrase in BANNED_CLAIMS + ["free money", "no obligation!!!", "click here now"]:
            assert phrase not in blob

    def test_no_message_without_a_problem(self):
        d = build_email_message(ctx(problems=[]), PROFILE)
        assert not d.ok and d.skipped_reason

    def test_followups_reference_the_same_topic(self):
        f1 = build_email_message(ctx(), PROFILE, "followup_1")
        assert f1.ok
        assert f1.subject.startswith("Re:")


class TestCallNotes:
    def test_opener_and_measured_points(self):
        d = build_call_notes(ctx(), PROFILE)
        assert d.ok
        assert "OPENER:" in d.message
        assert "WHAT I ACTUALLY MEASURED" in d.message
        assert "Alex Morgan" in d.message
        assert "Morgan Studio" in d.message

    def test_includes_score_and_website(self):
        d = build_call_notes(ctx(), PROFILE)
        assert "78/100" in d.message
        assert "brightwaterplumbing.co.uk" in d.message

    def test_tells_the_caller_not_to_push(self):
        d = build_call_notes(ctx(), PROFILE)
        assert "do not push" in d.message.lower()

    def test_no_website_opener_differs(self):
        no_site = {**CTA_PROBLEM, "code": "no_website_detected",
                   "title": "No website could be found for this business"}
        d = build_call_notes(ctx(problems=[no_site], audit_kind="no_website", website=""), PROFILE)
        assert "couldn't find one" in d.message.lower() or "looking for your website" in d.message.lower()

    def test_no_notes_without_a_problem(self):
        d = build_call_notes(ctx(problems=[]), PROFILE)
        assert not d.ok


class TestLinkedInMessages:
    def test_message_names_the_measured_problem(self):
        d = build_linkedin_message(ctx(), PROFILE)
        assert d.ok
        assert "Brightwater Plumbing" in d.message
        assert d.based_on
        assert d.based_on[0]["observation"] in d.message

    def test_no_message_without_a_measured_problem(self):
        d = build_linkedin_message(ctx(problems=[]), PROFILE)
        assert not d.ok
        assert d.skipped_reason

    def test_message_is_shorter_than_whatsapp(self):
        """Spec: LinkedIn is even shorter than WhatsApp - no long pitch."""
        wa = build_whatsapp_message(ctx(problems=[CTA_PROBLEM, MOBILE_PROBLEM]), PROFILE)
        li = build_linkedin_message(ctx(problems=[CTA_PROBLEM, MOBILE_PROBLEM]), PROFILE)
        assert len(li.message) <= len(wa.message)

    def test_only_one_observation_is_mentioned(self):
        d = build_linkedin_message(
            ctx(problems=[CTA_PROBLEM, MOBILE_PROBLEM, SPEED_PROBLEM, TRUST_PROBLEM]), PROFILE
        )
        assert len(d.based_on) == 1

    def test_no_fabricated_or_pushy_claims(self):
        d = build_linkedin_message(ctx(), PROFILE)
        low = d.message.lower()
        for phrase in BANNED_CLAIMS:
            assert phrase not in low, phrase

    def test_profile_must_be_configured(self):
        for missing in ("full_name", "company_name", "service_name"):
            broken = {**PROFILE, missing: ""}
            with pytest.raises(ProfileIncomplete):
                build_linkedin_message(ctx(), broken)

    def test_different_problems_produce_different_messages(self):
        cta = build_linkedin_message(ctx(problems=[CTA_PROBLEM]), PROFILE).message
        speed = build_linkedin_message(ctx(problems=[SPEED_PROBLEM]), PROFILE).message
        assert cta != speed


class TestPortfolioLine:
    """spec: the sender's portfolio/website URL is included naturally in
    every channel, only when configured - never hardcoded, never spammy."""

    def test_portfolio_included_in_whatsapp_when_configured(self):
        d = build_whatsapp_message(ctx(), PROFILE)
        assert PROFILE["website_url"] in d.message

    def test_portfolio_omitted_from_whatsapp_when_not_configured(self):
        d = build_whatsapp_message(ctx(), {**PROFILE, "website_url": ""})
        assert "some of my work" not in d.message.lower()

    def test_portfolio_included_in_email_when_configured(self):
        d = build_email_message(ctx(), PROFILE)
        assert PROFILE["website_url"] in d.message

    def test_portfolio_included_in_linkedin_when_configured(self):
        d = build_linkedin_message(ctx(), PROFILE)
        assert PROFILE["website_url"] in d.message

    def test_portfolio_is_not_an_aggressive_cta(self):
        for build in (build_whatsapp_message, build_email_message, build_linkedin_message):
            d = build(ctx(), PROFILE)
            assert "click my portfolio now" not in d.message.lower()
            assert "click here" not in d.message.lower()


class TestDraftLinks:
    """spec: a lead is not 'done' unless the draft link actually carries the
    exact message shown in the UI - never a bare destination link."""

    def test_whatsapp_url_round_trips_the_message(self):
        d = build_whatsapp_message(ctx(), PROFILE)
        url = whatsapp_url("+441132960001", d.message)
        assert "?text=" in url
        assert url.startswith("https://wa.me/441132960001?text=")
        assert unquote(url.split("?text=", 1)[1]) == d.message

    def test_whatsapp_url_survives_special_characters(self):
        """Apostrophes, quotes, newlines, ampersands and emoji must all
        round-trip correctly through the URL encoding."""
        message = "Hi there!\nIt's \"great\" — 100% & more? 🙂 café"
        url = whatsapp_url("+441132960001", message)
        assert "?text=" in url
        assert unquote(url.split("?text=", 1)[1]) == message

    def test_mailto_encodes_subject_and_body(self):
        d = build_email_message(ctx(), PROFILE)
        url = mailto_url("info@brightwaterplumbing.co.uk", d.subject, d.message)
        assert "subject=" in url
        assert "&body=" in url
        assert url.startswith("mailto:info@brightwaterplumbing.co.uk?subject=")
        body = unquote(url.split("&body=", 1)[1])
        assert body == d.message

    def test_mailto_without_recipient_is_empty(self):
        assert mailto_url("", "s", "b") == ""

    def test_a_whatsapp_lead_is_only_complete_with_a_matching_url(self):
        """The exact acceptance rule: whatsapp_message set, whatsapp_url
        contains ?text=, and the decoded text equals the message."""
        d = build_whatsapp_message(ctx(), PROFILE)
        url = whatsapp_url("+441132960001", d.message)
        assert d.message != ""
        assert "?text=" in url
        assert unquote(url.split("?text=", 1)[1]) == d.message

    def test_an_email_lead_is_only_complete_with_subject_and_body_in_the_url(self):
        d = build_email_message(ctx(), PROFILE)
        url = mailto_url("info@brightwaterplumbing.co.uk", d.subject, d.message)
        assert d.subject != "" and d.message != ""
        assert "subject=" in url and "body=" in url


class TestChannelSelection:
    """Priority is WhatsApp (strict) -> email -> LinkedIn -> phone -> skip.

    WhatsApp is chosen ONLY on real evidence (a link confirmed on the
    business's own website) - a phone number merely being a WhatsApp-capable
    mobile is never, by itself, enough. This is the core "final logic"
    guarantee: a Google Maps / CSV phone number must never be auto-treated
    as a WhatsApp number.
    """

    def test_confirmed_whatsapp_wins(self):
        r = choose_channel(
            whatsapp_status="confirmed_on_website", whatsapp_number="+447911123456",
            usable_email="info@x.test", email_status="valid_public",
            linkedin_url="https://www.linkedin.com/company/x",
            phone_normalized="+447911123456", phone_status="valid",
        )
        assert r["channel"] == "whatsapp"
        assert "confirmed" in r["reason"].lower()

    def test_usable_unverified_whatsapp_does_NOT_win(self):
        """The core guarantee: a WhatsApp-capable mobile number alone is not
        evidence. It must fall through to email, exactly like an unlikely
        (landline) number always has."""
        r = choose_channel(
            whatsapp_status="usable_unverified", whatsapp_number="+447911123456",
            usable_email="info@x.test", email_status="valid_public",
            phone_normalized="+447911123456", phone_status="valid",
        )
        assert r["channel"] == "email"

    def test_usable_unverified_whatsapp_alone_falls_to_linkedin_not_whatsapp(self):
        """Same guarantee with no email either: still not WhatsApp."""
        r = choose_channel(
            whatsapp_status="usable_unverified", whatsapp_number="+447911123456",
            usable_email=None, email_status="none_found",
            linkedin_url="https://www.linkedin.com/company/acme",
            phone_normalized="+447911123456", phone_status="valid",
        )
        assert r["channel"] == "linkedin"

    def test_landline_falls_through_to_email(self):
        r = choose_channel(
            whatsapp_status="unlikely", whatsapp_number="+441132960001",
            usable_email="info@x.test", email_status="valid_public",
            phone_normalized="+441132960001", phone_status="valid",
        )
        assert r["channel"] == "email"

    def test_invalid_number_falls_through_to_email(self):
        r = choose_channel(
            whatsapp_status="invalid_number", whatsapp_number="",
            usable_email="info@x.test", email_status="mx_valid",
            phone_normalized="", phone_status="unparseable",
        )
        assert r["channel"] == "email"

    def test_no_email_falls_through_to_linkedin(self):
        r = choose_channel(
            whatsapp_status="unlikely", whatsapp_number="+441132960001",
            usable_email=None, email_status="none_found",
            linkedin_url="https://www.linkedin.com/company/acme",
            phone_normalized="+441132960001", phone_status="valid",
        )
        assert r["channel"] == "linkedin"
        assert "linkedin" in r["reason"].lower()

    def test_no_email_no_linkedin_falls_through_to_phone(self):
        r = choose_channel(
            whatsapp_status="unlikely", whatsapp_number="+441132960001",
            usable_email=None, email_status="none_found",
            linkedin_url="",
            phone_normalized="+441132960001", phone_status="valid",
        )
        assert r["channel"] == "phone"

    def test_nothing_usable_yields_skip_with_a_reason(self):
        r = choose_channel(
            whatsapp_status="no_phone", whatsapp_number="",
            usable_email=None, email_status="none_found",
            linkedin_url="",
            phone_normalized="", phone_status="unavailable",
        )
        assert r["channel"] == "none"
        assert r["reason"]

    def test_every_decision_carries_a_reason(self):
        for status in ("confirmed_on_website", "usable_unverified", "unlikely", "invalid_number", "no_phone"):
            r = choose_channel(
                whatsapp_status=status, whatsapp_number="+447911123456",
                usable_email="a@b.test", email_status="mx_valid",
                phone_normalized="+447911123456", phone_status="valid",
            )
            assert r["reason"].strip()

    def test_priority_order_whatsapp_beats_everything(self):
        r = choose_channel(
            whatsapp_status="confirmed_on_website", whatsapp_number="+447911123456",
            usable_email="a@b.test", email_status="valid_public",
            linkedin_url="https://www.linkedin.com/company/acme",
            phone_normalized="+447911123456", phone_status="valid",
        )
        assert r["channel"] == "whatsapp"

    def test_priority_order_email_beats_linkedin_and_phone(self):
        r = choose_channel(
            whatsapp_status="no_phone", whatsapp_number="",
            usable_email="a@b.test", email_status="valid_public",
            linkedin_url="https://www.linkedin.com/company/acme",
            phone_normalized="+447911123456", phone_status="valid",
        )
        assert r["channel"] == "email"

    def test_priority_order_linkedin_beats_phone(self):
        r = choose_channel(
            whatsapp_status="no_phone", whatsapp_number="",
            usable_email=None, email_status="none_found",
            linkedin_url="https://www.linkedin.com/company/acme",
            phone_normalized="+447911123456", phone_status="valid",
        )
        assert r["channel"] == "linkedin"


class TestObservationCatalogue:
    def test_every_phrasing_renders_without_placeholders(self):
        for code, spec in OBSERVATIONS.items():
            problem = {"code": code, "severity": "high", "category": "conversion",
                       "evidence": {"response_ms": 3200, "word_count": 45, "h1": "Home",
                                    "bytes": 2_600_000, "performance_score": 38,
                                    "broken": [{"url": "x"}], "count": 2}}
            for i in range(len(spec["lines"])):
                obs = observation_for(problem, i)
                assert obs is not None, code
                assert "{" not in obs["line"] and "}" not in obs["line"], code

    def test_missing_measurement_falls_back_instead_of_printing_none(self):
        problem = {"code": "slow_response", "severity": "medium",
                   "category": "performance", "evidence": {}}
        obs = observation_for(problem, 0)
        assert obs is None or "None" not in obs["line"]

    def test_unknown_code_returns_nothing_rather_than_guessing(self):
        assert observation_for({"code": "totally_made_up", "evidence": {}}, 0) is None

    def test_picks_distinct_topics(self):
        obs = pick_observations([CTA_PROBLEM, MOBILE_PROBLEM, SPEED_PROBLEM], seed=1, limit=2)
        assert len(obs) == 2
        assert obs[0]["topic"] != obs[1]["topic"]

    def test_no_observation_asserts_business_harm(self):
        for code, spec in OBSERVATIONS.items():
            blob = " ".join(spec["lines"]).lower() + " " + spec.get("value", "").lower()
            for phrase in ("losing customers", "lost revenue", "costing you", "guaranteed"):
                assert phrase not in blob, code
