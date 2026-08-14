"""
Public contact extraction from crawled pages (spec 9).

Every email returned here was literally present on one of the business's own
pages - as a mailto:, as visible text, as light obfuscation ("name [at]
domain [dot] com"), or in JSON-LD. Nothing is ever constructed from a
first name plus a domain. If a site publishes no address, this returns
nothing, and the pipeline moves on to the phone channel.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .crawler import CrawlResult
from .page import ParsedPage
from .urls import registrable_domain

# --------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])"
    r"([A-Za-z0-9._%+\-]{1,64})@([A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)+)"
)

# "info [at] example [dot] com", "info (at) example.com", "info AT example DOT com".
# The domain half repeats, so multi-label suffixes such as "co [dot] uk" are
# captured whole rather than truncated to the first label.
# A literal "." must have no surrounding whitespace, otherwise a sentence
# boundary is mistaken for another domain label and "…co [dot] uk. Find us"
# becomes "…co.uk.find". The spelled-out forms may be spaced.
_DOT_SEP = r"(?:\s*(?:\[dot\]|\(dot\)|\{dot\})\s*|\s+dot\s+|\.)"
# _DOT_SEP handles its own surrounding whitespace, so no extra \s* is added
# around it here - that would re-introduce the sentence-boundary bug.
_OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+\-]{1,64})\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+|&#64;|%40)\s*"
    r"((?:[A-Za-z0-9\-]{1,63}" + _DOT_SEP + r")+[A-Za-z]{2,24})",
    re.I,
)
_DOT_SEP_RE = re.compile(_DOT_SEP, re.I)


def _deobfuscate_domain(raw: str) -> str:
    """Turn 'brightwaterplumbing [dot] co [dot] uk' into a real domain."""
    parts = [p.strip() for p in _DOT_SEP_RE.split(raw) if p and p.strip()]
    return ".".join(parts)


# LinkedIn discovery only ever accepts a link the business itself published on
# its own site - never a guess, never a search result. /company/ and
# /showcase/ are official business pages; /in/ (a personal profile) is
# deliberately rejected so an employee's page can never be mistaken for the
# business's own LinkedIn presence.
_LINKEDIN_COMPANY_RE = re.compile(
    r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/(company|showcase)/([^/?#]+)", re.I
)


def _linkedin_company_url(href: str) -> Optional[str]:
    m = _LINKEDIN_COMPANY_RE.match((href or "").strip())
    if not m:
        return None
    return f"https://www.linkedin.com/{m.group(1).lower()}/{m.group(2)}"

# File extensions that make an "email" a false positive from a filename.
_IMAGE_TLD_FALSE_POSITIVES = {
    "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp", "tiff", "css", "js",
    "json", "xml", "woff", "woff2", "ttf", "eot", "mp4", "webm", "pdf", "zip",
}

# Addresses that belong to tooling, not the business.
_JUNK_LOCAL_PARTS = {
    "example", "user", "username", "your", "youremail", "email", "name", "test",
    "someone", "john.doe", "jane.doe", "firstname", "lastname", "no-reply-test",
    "domain", "yourname", "mail", "abc", "xyz", "sample",
}

_JUNK_DOMAINS = {
    "example.com", "example.org", "example.net", "domain.com", "yourdomain.com",
    "yoursite.com", "email.com", "test.com", "sentry.io", "sentry-next.wixpress.com",
    "wixpress.com", "wix.com", "squarespace.com", "godaddy.com", "shopify.com",
    "w3.org", "schema.org", "adobe.com", "googleapis.com", "gstatic.com",
    "cloudflare.com", "jquery.com", "bootstrapcdn.com", "fontawesome.com",
    "gravatar.com", "placeholder.com", "mysite.com", "site.com", "company.com",
}

_JUNK_PREFIXES = ("no-reply", "noreply", "donotreply", "do-not-reply", "mailer-daemon",
                  "postmaster", "abuse", "wordpress", "wp@", "root@")

ROLE_LOCAL_PARTS = {
    "info", "hello", "contact", "sales", "support", "enquiries", "enquiry", "inquiries",
    "admin", "office", "team", "help", "service", "customerservice", "bookings",
    "booking", "reception", "mail", "hi", "hey", "ask", "general", "reservations",
    "appointments", "orders", "accounts", "billing", "care", "frontdesk", "studio",
}

# Ranked by how useful they are as a first-touch business address.
_PREFERRED_ORDER = [
    "info", "hello", "contact", "enquiries", "enquiry", "inquiries", "office",
    "sales", "bookings", "booking", "appointments", "reception", "hi", "team",
    "admin", "support", "help", "service",
]

_PAGE_TYPE_WEIGHT = {
    "contact": 1.0, "homepage": 0.92, "about": 0.85, "team": 0.8, "booking": 0.8,
    "services": 0.7, "locations": 0.7, "pricing": 0.65, "testimonials": 0.5,
    "blog": 0.35, "other": 0.5,
}

_SOURCE_TYPE_WEIGHT = {
    "mailto": 1.0, "jsonld": 0.95, "text": 0.85, "obfuscated": 0.8, "footer": 0.9,
}


@dataclass
class FoundEmail:
    email: str
    source_url: str
    source_type: str          # mailto | text | jsonld | obfuscated
    page_type: str
    confidence: float = 0.0
    is_role: bool = False
    domain_matches_site: bool = False
    context: str = ""

    def key(self) -> str:
        return self.email.lower()


@dataclass
class ExtractionResult:
    emails: List[FoundEmail] = field(default_factory=list)
    phones_on_site: List[str] = field(default_factory=list)
    tel_links: List[str] = field(default_factory=list)
    whatsapp_links: List[str] = field(default_factory=list)
    whatsapp_numbers: List[str] = field(default_factory=list)
    social_links: List[str] = field(default_factory=list)
    linkedin_urls: List[str] = field(default_factory=list)
    contact_form_urls: List[str] = field(default_factory=list)
    contact_names: List[str] = field(default_factory=list)
    pages_scanned: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------


def _clean_candidate(local: str, domain: str) -> Optional[str]:
    local = local.strip(" .,;:<>()[]'\"").lstrip("-")
    domain = domain.strip(" .,;:<>()[]'\"").lower().rstrip(".")
    if not local or not domain or "." not in domain:
        return None

    tld = domain.rsplit(".", 1)[-1].lower()
    if tld in _IMAGE_TLD_FALSE_POSITIVES or tld.isdigit() or len(tld) < 2:
        return None
    if len(local) > 64 or len(domain) > 253:
        return None
    if domain in _JUNK_DOMAINS or any(domain.endswith("." + d) for d in _JUNK_DOMAINS):
        return None

    low_local = local.lower()
    if low_local in _JUNK_LOCAL_PARTS:
        return None
    if any(low_local.startswith(p.rstrip("@")) for p in _JUNK_PREFIXES):
        return None
    # Hashes / tracking ids masquerading as addresses.
    if len(local) > 30 and re.fullmatch(r"[0-9a-f]+", low_local):
        return None
    if re.fullmatch(r"[0-9a-f]{16,}", low_local):
        return None
    if not re.fullmatch(r"[A-Za-z0-9._%+\-]+", local):
        return None

    return f"{low_local}@{domain}"


def _scan_text(text: str) -> List[tuple]:
    out: List[tuple] = []
    for m in _EMAIL_RE.finditer(text):
        cleaned = _clean_candidate(m.group(1), m.group(2))
        if cleaned:
            start = max(0, m.start() - 60)
            out.append((cleaned, "text", text[start : m.end() + 40].strip()))
    for m in _OBFUSCATED_RE.finditer(text):
        cleaned = _clean_candidate(m.group(1), _deobfuscate_domain(m.group(2)))
        if cleaned:
            start = max(0, m.start() - 60)
            out.append((cleaned, "obfuscated", text[start : m.end() + 40].strip()))
    return out


def _walk_jsonld(obj: Any, found: List[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == "email" and isinstance(v, str):
                found.append(v)
            else:
                _walk_jsonld(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _walk_jsonld(item, found)


def extract_contacts(crawl: CrawlResult, site_domain: str = "") -> ExtractionResult:
    result = ExtractionResult()
    site_domain = (site_domain or registrable_domain(crawl.final_url or crawl.start_url)).lower()
    by_email: Dict[str, FoundEmail] = {}

    def record(email: str, page: ParsedPage, source_type: str, context: str = "") -> None:
        key = email.lower()
        domain = key.split("@", 1)[1]
        local = key.split("@", 1)[0]
        is_role = local in ROLE_LOCAL_PARTS
        matches = bool(site_domain) and domain == site_domain

        conf = 0.5
        conf += 0.25 * _SOURCE_TYPE_WEIGHT.get(source_type, 0.6)
        conf *= 0.6 + 0.4 * _PAGE_TYPE_WEIGHT.get(page.page_type, 0.5)
        if matches:
            conf += 0.22
        if is_role:
            conf += 0.06
        conf = round(min(0.99, conf), 3)

        existing = by_email.get(key)
        if existing and existing.confidence >= conf:
            return
        by_email[key] = FoundEmail(
            email=key,
            source_url=page.final_url or page.url,
            source_type=source_type,
            page_type=page.page_type,
            confidence=conf,
            is_role=is_role,
            domain_matches_site=matches,
            context=(context or "")[:240],
        )

    for page in crawl.pages:
        result.pages_scanned.append(page.final_url or page.url)

        for addr in page.mailto:
            cleaned = _clean_candidate(*addr.split("@", 1)) if "@" in addr else None
            if cleaned:
                record(cleaned, page, "mailto", "mailto: link")

        for email, kind, ctx in _scan_text(page.text):
            record(email, page, kind, ctx)

        # Footer/header often hold the address even when body text does not.
        for blob in (page.footer_html, page.header_html):
            if not blob:
                continue
            unescaped = html_lib.unescape(blob)
            for email, kind, ctx in _scan_text(re.sub(r"<[^>]+>", " ", unescaped)):
                record(email, page, "footer" if blob is page.footer_html else kind, ctx)

        jl: List[str] = []
        for block in page.jsonld:
            _walk_jsonld(block, jl)
        for addr in jl:
            if "@" in addr:
                cleaned = _clean_candidate(*addr.split("@", 1))
                if cleaned:
                    record(cleaned, page, "jsonld", "structured data")

        # -- non-email contact signals ------------------------------------
        for t in page.tel:
            if t not in result.tel_links:
                result.tel_links.append(t)
        for wa in page.whatsapp_links:
            if wa not in result.whatsapp_links:
                result.whatsapp_links.append(wa)
            m = re.search(r"(?:wa\.me/|phone=|send\?phone=)(\+?\d{6,20})", wa)
            if m:
                num = re.sub(r"\D", "", m.group(1))
                if num and num not in result.whatsapp_numbers:
                    result.whatsapp_numbers.append(num)
        for s in page.social_links:
            if s not in result.social_links and len(result.social_links) < 20:
                result.social_links.append(s)
            li = _linkedin_company_url(s)
            if li and li not in result.linkedin_urls:
                result.linkedin_urls.append(li)

        for form in page.forms:
            if form.is_search or form.is_newsletter:
                continue
            if form.has_email_field or form.has_message_field or form.has_phone_field:
                u = page.final_url or page.url
                if u not in result.contact_form_urls:
                    result.contact_form_urls.append(u)

        result.contact_names.extend(_extract_contact_names(page))

    # De-dup names, keep order.
    seen_names: Set[str] = set()
    result.contact_names = [
        n for n in result.contact_names if not (n.lower() in seen_names or seen_names.add(n.lower()))
    ][:8]

    emails = sorted(by_email.values(), key=lambda e: -e.confidence)
    result.emails = _rank_emails(emails, site_domain)
    return result


def _rank_emails(emails: List[FoundEmail], site_domain: str) -> List[FoundEmail]:
    """Own-domain first, then the most contactable role addresses."""

    def sort_key(e: FoundEmail):
        local = e.email.split("@", 1)[0]
        try:
            role_rank = _PREFERRED_ORDER.index(local)
        except ValueError:
            role_rank = len(_PREFERRED_ORDER) + (0 if e.is_role else 1)
        return (
            0 if e.domain_matches_site else 1,
            role_rank,
            -e.confidence,
            e.email,
        )

    return sorted(emails, key=sort_key)


_NAME_LABEL_RE = re.compile(
    r"\b(owner|founder|co-founder|director|manager|principal|proprietor|ceo|"
    r"practice manager|head of|lead|partner)\b",
    re.I,
)
_NAME_RE = re.compile(r"\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,20})\b")


def _extract_contact_names(page: ParsedPage) -> List[str]:
    """
    Names published on About/Team pages, used only to address a message
    politely. Never invented, and never guessed into an email address.
    """
    if page.page_type not in ("about", "team", "contact", "homepage"):
        return []
    names: List[str] = []
    windows: List[str] = []
    for heading in page.h2 + page.h3:
        windows.append(heading)
    for m in _NAME_LABEL_RE.finditer(page.text):
        start = max(0, m.start() - 90)
        windows.append(page.text[start : m.end() + 90])

    for w in windows:
        if not _NAME_LABEL_RE.search(w) and w not in page.h2 + page.h3:
            continue
        for nm in _NAME_RE.finditer(w):
            candidate = f"{nm.group(1)} {nm.group(2)}"
            if _is_plausible_person_name(candidate):
                names.append(candidate)
    return names[:5]


_NAME_STOPWORDS = {
    "contact", "about", "our", "team", "the", "we", "us", "home", "service", "services",
    "get", "free", "call", "book", "read", "more", "learn", "view", "all", "why",
    "choose", "welcome", "new", "best", "top", "quality", "customer", "client",
    "privacy", "policy", "terms", "google", "facebook", "instagram", "monday",
    "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january",
    "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "united", "states", "kingdom", "north",
    "south", "east", "west", "street", "road", "avenue", "suite",
}


def _is_plausible_person_name(candidate: str) -> bool:
    parts = candidate.split()
    if len(parts) != 2:
        return False
    return not any(p.lower() in _NAME_STOPWORDS for p in parts)
