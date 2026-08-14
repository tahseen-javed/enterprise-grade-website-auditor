"""
International phone normalization (spec 4) and WhatsApp click-to-chat (spec 5).

Rules that are never broken:
  * the raw number is preserved exactly as supplied;
  * digits are never invented, guessed or padded;
  * if a number cannot be parsed with confidence, the status says so.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberType, geocoder, carrier

# --------------------------------------------------------------------------
# Region resolution
# --------------------------------------------------------------------------

_COUNTRY_NAME_TO_REGION: Dict[str, str] = {
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US",
    "america": "US",
    "canada": "CA", "ca": "CA",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "britain": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB", "gb": "GB",
    "australia": "AU", "au": "AU",
    "new zealand": "NZ", "nz": "NZ",
    "ireland": "IE", "republic of ireland": "IE", "ie": "IE",
    "pakistan": "PK", "pk": "PK",
    "india": "IN", "in": "IN",
    "united arab emirates": "AE", "uae": "AE", "ae": "AE",
    "saudi arabia": "SA", "sa": "SA",
    "south africa": "ZA", "za": "ZA",
    "germany": "DE", "deutschland": "DE", "de": "DE",
    "france": "FR", "fr": "FR",
    "spain": "ES", "espana": "ES", "es": "ES",
    "italy": "IT", "italia": "IT", "it": "IT",
    "netherlands": "NL", "holland": "NL", "nl": "NL",
    "belgium": "BE", "be": "BE",
    "switzerland": "CH", "ch": "CH",
    "austria": "AT", "at": "AT",
    "sweden": "SE", "se": "SE",
    "norway": "NO", "no": "NO",
    "denmark": "DK", "dk": "DK",
    "finland": "FI", "fi": "FI",
    "poland": "PL", "pl": "PL",
    "portugal": "PT", "pt": "PT",
    "greece": "GR", "gr": "GR",
    "czech republic": "CZ", "czechia": "CZ", "cz": "CZ",
    "romania": "RO", "ro": "RO",
    "hungary": "HU", "hu": "HU",
    "mexico": "MX", "mx": "MX",
    "brazil": "BR", "brasil": "BR", "br": "BR",
    "argentina": "AR", "ar": "AR",
    "singapore": "SG", "sg": "SG",
    "malaysia": "MY", "my": "MY",
    "indonesia": "ID", "id": "ID",
    "philippines": "PH", "ph": "PH",
    "japan": "JP", "jp": "JP",
    "china": "CN", "cn": "CN",
    "turkey": "TR", "turkiye": "TR", "tr": "TR",
    "egypt": "EG", "eg": "EG",
    "nigeria": "NG", "ng": "NG",
    "kenya": "KE", "ke": "KE",
    "bangladesh": "BD", "bd": "BD",
    "sri lanka": "LK", "lk": "LK",
    "qatar": "QA", "qa": "QA",
    "kuwait": "KW", "kw": "KW",
    "oman": "OM", "om": "OM",
    "israel": "IL", "il": "IL",
}

# US/CA state and province codes, used to infer region when the CSV has no
# country column (very common with Google Maps exports).
_US_STATES = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia","ks","ky",
    "la","me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj","nm","ny","nc","nd",
    "oh","ok","or","pa","ri","sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy","dc",
}
_CA_PROVINCES = {"ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe", "qc", "sk", "yt"}

_TYPE_NAMES = {
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
    PhoneNumberType.UNKNOWN: "unknown",
}

# Line types that cannot receive WhatsApp - the only cases we downgrade.
_WHATSAPP_UNLIKELY_TYPES = {"fixed_line", "toll_free", "premium_rate", "shared_cost", "pager", "voicemail"}


def resolve_region(
    country: str = "", state: str = "", address: str = "", default: Optional[str] = None
) -> Optional[str]:
    """Best-effort ISO region hint for parsing. Returns None when unsure."""
    c = (country or "").strip().lower()
    if c:
        if c in _COUNTRY_NAME_TO_REGION:
            return _COUNTRY_NAME_TO_REGION[c]
        cleaned = re.sub(r"[^a-z ]+", "", c).strip()
        if cleaned in _COUNTRY_NAME_TO_REGION:
            return _COUNTRY_NAME_TO_REGION[cleaned]
        if len(cleaned) == 2 and cleaned.upper() in phonenumbers.SUPPORTED_REGIONS:
            return cleaned.upper()

    s = (state or "").strip().lower()
    if s:
        if s in _US_STATES:
            return "US"
        if s in _CA_PROVINCES:
            return "CA"

    a = (address or "").strip().lower()
    if a:
        for name, region in _COUNTRY_NAME_TO_REGION.items():
            if len(name) > 3 and re.search(rf"\b{re.escape(name)}\b", a):
                return region
        m = re.search(r"\b([a-z]{2})\s+\d{5}(-\d{4})?\b", a)  # "TX 78701"
        if m and m.group(1) in _US_STATES:
            return "US"

    return default


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------

_EXT_RE = re.compile(r"(?:\s*(?:ext|x|extension|ext\.)\s*\.?\s*)(\d{1,6})\s*$", re.I)


def normalize_phone(
    raw: str,
    *,
    region_hint: Optional[str] = None,
    source: str = "csv",
    source_url: str = "",
) -> Dict[str, Any]:
    """
    Parse one number. Result always carries `phone_raw` unchanged.

    validation_status:
      valid            - parsed and phonenumbers says it is a real, valid number
      possible         - parses and looks plausible, but not confirmed valid
      invalid          - parses but is not a valid number for that region
      unparseable      - could not be parsed at all
      unavailable      - nothing was supplied
      ambiguous_region - no country code and no reliable region hint
    """
    raw = (raw or "").strip()
    out: Dict[str, Any] = {
        "phone_raw": raw,
        "phone_normalized": "",
        "phone_national": "",
        "phone_country": "",
        "phone_country_name": "",
        "phone_calling_code": "",
        "phone_extension": "",
        "phone_type": "unknown",
        "phone_carrier": "",
        "validation_status": "unavailable",
        "source": source,
        "source_url": source_url,
        "notes": [],
    }
    if not raw:
        return out

    working = raw
    ext_match = _EXT_RE.search(working)
    if ext_match:
        out["phone_extension"] = ext_match.group(1)
        working = working[: ext_match.start()].strip()
        out["notes"].append("extension separated from the main number")

    has_plus = working.strip().startswith("+") or working.strip().startswith("00")
    if not has_plus and not region_hint:
        out["validation_status"] = "ambiguous_region"
        out["notes"].append(
            "no country code in the number and no country could be inferred from the row"
        )
        return out

    parsed = None
    for candidate_region in ([None] if has_plus else []) + [region_hint]:
        try:
            parsed = phonenumbers.parse(working, candidate_region)
            break
        except NumberParseException:
            continue

    if parsed is None:
        out["validation_status"] = "unparseable"
        out["notes"].append("the value could not be parsed as a phone number")
        return out

    is_valid = phonenumbers.is_valid_number(parsed)
    is_possible = phonenumbers.is_possible_number(parsed)

    region = phonenumbers.region_code_for_number(parsed) or (region_hint or "")
    out["phone_country"] = region or ""
    out["phone_calling_code"] = f"+{parsed.country_code}" if parsed.country_code else ""
    try:
        out["phone_country_name"] = geocoder.country_name_for_number(parsed, "en") or ""
    except Exception:
        out["phone_country_name"] = ""

    if is_valid:
        out["phone_normalized"] = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.E164
        )
        out["phone_national"] = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.NATIONAL
        )
        out["validation_status"] = "valid"
        num_type = phonenumbers.number_type(parsed)
        out["phone_type"] = _TYPE_NAMES.get(num_type, "unknown")
        try:
            out["phone_carrier"] = carrier.name_for_number(parsed, "en") or ""
        except Exception:
            pass
    elif is_possible:
        out["phone_normalized"] = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.E164
        )
        out["validation_status"] = "possible"
        out["notes"].append(
            "the number has a plausible length but is not confirmed valid for its region"
        )
    else:
        out["validation_status"] = "invalid"
        out["notes"].append("the number is not valid for the detected region")

    return out


def extract_phones_from_text(text: str, region_hint: Optional[str] = None) -> List[str]:
    """Find phone-looking strings on a page (used to enrich, never to replace)."""
    found: List[str] = []
    try:
        for match in phonenumbers.PhoneNumberMatcher(text, region_hint or "US"):
            found.append(
                phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
            )
    except Exception:
        pass
    seen: set = set()
    return [p for p in found if not (p in seen or seen.add(p))]


# --------------------------------------------------------------------------
# WhatsApp (spec 5, as clarified: a fallback step, not a gate)
# --------------------------------------------------------------------------

WHATSAPP_STATUSES = {
    "confirmed_on_website",  # a real WhatsApp link for this number exists on their site
    "usable_unverified",     # valid number, WhatsApp-capable line type, chat link prepared
    "unlikely",              # valid but a line type WhatsApp cannot use (e.g. landline)
    "invalid_number",        # could not be normalized
    "no_phone",              # nothing supplied
}


def assess_whatsapp(
    phone: Dict[str, Any], website_whatsapp_numbers: Optional[List[str]] = None
) -> Dict[str, str]:
    """
    Decide whether the WhatsApp path is usable for this number.

    This deliberately does NOT claim verified availability. `usable_unverified`
    means exactly what it says: the number is valid and of a type that can use
    WhatsApp, so a click-to-chat link is worth preparing. Only a WhatsApp link
    actually published on the business's own website upgrades it to confirmed.
    """
    status_in = phone.get("validation_status", "unavailable")
    normalized = phone.get("phone_normalized", "")
    ptype = phone.get("phone_type", "unknown")

    if not phone.get("phone_raw"):
        return {"whatsapp_status": "no_phone", "whatsapp_reason": "No phone number in the source row."}

    if status_in not in ("valid", "possible") or not normalized:
        return {
            "whatsapp_status": "invalid_number",
            "whatsapp_reason": (
                f"The number could not be normalized to international format "
                f"(status: {status_in})."
            ),
        }

    site_numbers = {re.sub(r"\D", "", n) for n in (website_whatsapp_numbers or [])}
    if site_numbers and re.sub(r"\D", "", normalized) in site_numbers:
        return {
            "whatsapp_status": "confirmed_on_website",
            "whatsapp_reason": "A WhatsApp link for this number was found on the business website.",
        }

    if ptype in _WHATSAPP_UNLIKELY_TYPES:
        return {
            "whatsapp_status": "unlikely",
            "whatsapp_reason": (
                f"The number is a {ptype.replace('_', ' ')}, which normally cannot use WhatsApp."
            ),
        }

    if status_in == "possible":
        return {
            "whatsapp_status": "usable_unverified",
            "whatsapp_reason": (
                "The number normalized to international format but is not confirmed valid; "
                "a chat link is prepared for manual review. WhatsApp presence itself is "
                "not verified."
            ),
        }

    label = ptype.replace("_", " ")
    return {
        "whatsapp_status": "usable_unverified",
        "whatsapp_reason": (
            f"Valid international number ({label}); a click-to-chat link is prepared. "
            f"WhatsApp presence itself is not verified."
        ),
    }


def whatsapp_url(e164: str, message: str = "") -> str:
    """
    wa.me click-to-chat. The phone portion must be digits only - no '+',
    no spaces, no punctuation.
    """
    digits = re.sub(r"\D", "", e164 or "")
    if not digits:
        return ""
    base = f"https://wa.me/{digits}"
    if message:
        return f"{base}?text={quote(message, safe='')}"
    return base


def whatsapp_is_actionable(status: str) -> bool:
    return status in ("confirmed_on_website", "usable_unverified")
