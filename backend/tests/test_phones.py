"""International phone normalization and WhatsApp handling (spec 4, 5, 46)."""

from __future__ import annotations

import pytest

from app.core.phones import (
    assess_whatsapp,
    normalize_phone,
    resolve_region,
    whatsapp_is_actionable,
    whatsapp_url,
)


class TestRegionResolution:
    @pytest.mark.parametrize(
        "country,expected",
        [
            ("United States", "US"), ("USA", "US"), ("us", "US"),
            ("United Kingdom", "GB"), ("UK", "GB"), ("England", "GB"),
            ("Australia", "AU"), ("Pakistan", "PK"), ("Canada", "CA"),
            ("New Zealand", "NZ"), ("Germany", "DE"), ("Ireland", "IE"),
        ],
    )
    def test_country_names(self, country, expected):
        assert resolve_region(country=country) == expected

    def test_us_state_code_implies_us(self):
        assert resolve_region(country="", state="TX") == "US"

    def test_canadian_province_implies_canada(self):
        assert resolve_region(country="", state="ON") == "CA"

    def test_address_with_zip_implies_us(self):
        assert resolve_region(country="", state="", address="1600 Main St, Austin TX 78701") == "US"

    def test_unknown_returns_none_rather_than_guessing_us(self):
        assert resolve_region(country="", state="", address="") is None
        assert resolve_region(country="Wakanda") is None


class TestNormalization:
    @pytest.mark.parametrize(
        "raw,region,e164,country",
        [
            ("+1 202-555-0143", None, "+12025550143", "US"),
            ("(212) 555-2368", "US", "+12125552368", "US"),
            ("+44 113 296 0001", None, "+441132960001", "GB"),
            ("0113 296 0001", "GB", "+441132960001", "GB"),
            ("+61 2 9374 4000", None, "+61293744000", "AU"),
            ("02 9374 4000", "AU", "+61293744000", "AU"),
            ("+92 300 1234567", None, "+923001234567", "PK"),
            ("0300 1234567", "PK", "+923001234567", "PK"),
            ("416-555-0199", "CA", "+14165550199", "CA"),
            ("+64 9 379 1234", None, "+6493791234", "NZ"),
        ],
    )
    def test_valid_numbers_across_countries(self, raw, region, e164, country):
        r = normalize_phone(raw, region_hint=region)
        assert r["validation_status"] == "valid", r["notes"]
        assert r["phone_normalized"] == e164
        assert r["phone_country"] == country

    def test_raw_is_always_preserved_exactly(self):
        raw = "  (0113) 296-0001 ext. 22  "
        r = normalize_phone(raw, region_hint="GB")
        assert r["phone_raw"] == raw.strip()

    def test_extension_is_separated_not_dropped(self):
        r = normalize_phone("0113 296 0001 ext 22", region_hint="GB")
        assert r["phone_extension"] == "22"
        assert r["phone_normalized"] == "+441132960001"

    def test_missing_country_code_without_hint_is_ambiguous_not_guessed(self):
        r = normalize_phone("296 0001")
        assert r["validation_status"] == "ambiguous_region"
        assert r["phone_normalized"] == ""

    def test_international_prefix_needs_no_hint(self):
        r = normalize_phone("+441132960001")
        assert r["validation_status"] == "valid"

    @pytest.mark.parametrize("raw", ["not a phone", "abcdefg", "12"])
    def test_junk_is_rejected_without_inventing_digits(self, raw):
        r = normalize_phone(raw, region_hint="US")
        assert r["validation_status"] in ("unparseable", "invalid", "ambiguous_region")
        assert r["phone_normalized"] == ""

    def test_invalid_length_for_region_is_invalid(self):
        r = normalize_phone("+1 202 555", region_hint=None)
        assert r["validation_status"] in ("invalid", "possible")

    def test_empty_is_unavailable(self):
        r = normalize_phone("")
        assert r["validation_status"] == "unavailable"
        assert r["phone_raw"] == ""

    def test_no_digits_are_ever_added(self):
        r = normalize_phone("+44 113 296 0001")
        digits_in = sum(c.isdigit() for c in "+44 113 296 0001")
        digits_out = sum(c.isdigit() for c in r["phone_normalized"])
        assert digits_out == digits_in

    def test_line_type_detected(self):
        mobile = normalize_phone("+447911123456")
        assert mobile["validation_status"] == "valid"
        assert mobile["phone_type"] in ("mobile", "fixed_line_or_mobile")

        landline = normalize_phone("+441132960001")
        assert landline["phone_type"] in ("fixed_line", "fixed_line_or_mobile")


class TestWhatsAppAssessment:
    """WhatsApp is a fallback step, never a gate - and never claimed as verified."""

    def test_mobile_number_is_usable_but_explicitly_unverified(self):
        phone = normalize_phone("+447911123456")
        wa = assess_whatsapp(phone)
        assert wa["whatsapp_status"] == "usable_unverified"
        assert "not verified" in wa["whatsapp_reason"].lower()
        assert whatsapp_is_actionable(wa["whatsapp_status"])

    def test_landline_is_unlikely_and_not_actionable(self):
        phone = normalize_phone("+441132960001")
        if phone["phone_type"] == "fixed_line":
            wa = assess_whatsapp(phone)
            assert wa["whatsapp_status"] == "unlikely"
            assert not whatsapp_is_actionable(wa["whatsapp_status"])

    def test_site_link_upgrades_to_confirmed(self):
        phone = normalize_phone("+441132960001")
        wa = assess_whatsapp(phone, website_whatsapp_numbers=["441132960001"])
        assert wa["whatsapp_status"] == "confirmed_on_website"
        assert whatsapp_is_actionable(wa["whatsapp_status"])

    def test_unrelated_site_link_does_not_confirm(self):
        phone = normalize_phone("+447911123456")
        wa = assess_whatsapp(phone, website_whatsapp_numbers=["19998887777"])
        assert wa["whatsapp_status"] != "confirmed_on_website"

    def test_unparseable_number_is_invalid_not_usable(self):
        phone = normalize_phone("garbage", region_hint="US")
        wa = assess_whatsapp(phone)
        assert wa["whatsapp_status"] == "invalid_number"
        assert not whatsapp_is_actionable(wa["whatsapp_status"])

    def test_absent_number_reports_no_phone(self):
        wa = assess_whatsapp(normalize_phone(""))
        assert wa["whatsapp_status"] == "no_phone"

    def test_status_is_never_a_bare_available_claim(self):
        for raw in ("+447911123456", "+12025550143", "+923001234567"):
            wa = assess_whatsapp(normalize_phone(raw))
            assert wa["whatsapp_status"] != "available"


class TestWhatsAppUrl:
    def test_digits_only_in_phone_portion(self):
        url = whatsapp_url("+44 113 296 0001")
        assert url == "https://wa.me/441132960001"
        assert "+" not in url.split("?")[0]
        assert " " not in url

    def test_message_is_url_encoded(self):
        url = whatsapp_url("+12025550143", "Hi there, how are you? 50% & more")
        assert url.startswith("https://wa.me/12025550143?text=")
        text = url.split("?text=", 1)[1]
        assert "%20" in text and "%26" in text and "%3F" in text
        assert " " not in text

    def test_newlines_survive_encoding(self):
        url = whatsapp_url("+12025550143", "Line one\n\nLine two")
        assert "%0A%0A" in url

    def test_empty_number_yields_no_url(self):
        assert whatsapp_url("") == ""
        assert whatsapp_url("+++") == ""

    def test_no_message_gives_plain_link(self):
        assert whatsapp_url("+12025550143") == "https://wa.me/12025550143"
