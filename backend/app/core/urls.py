"""URL normalization, domain handling, and business/website identity matching."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import tldextract

# Offline extractor: never phones home for the public-suffix list mid-crawl.
_extract = tldextract.TLDExtract(suffix_list_urls=())

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref", "referrer", "_ga", "yclid",
}

# Platforms that are a *profile*, not the business's own website. Treating a
# Facebook page as "their website" would poison the whole audit.
SOCIAL_HOSTS = {
    "facebook.com", "m.facebook.com", "fb.com", "fb.me", "instagram.com", "twitter.com",
    "x.com", "linkedin.com", "youtube.com", "youtu.be", "tiktok.com", "pinterest.com",
    "snapchat.com", "threads.net", "wa.me", "api.whatsapp.com", "t.me", "telegram.me",
}

DIRECTORY_HOSTS = {
    "yelp.com", "yellowpages.com", "yell.com", "tripadvisor.com", "trustpilot.com",
    "google.com", "goo.gl", "maps.app.goo.gl", "business.site", "bing.com",
    "foursquare.com", "angi.com", "angieslist.com", "houzz.com", "thumbtack.com",
    "checkatrade.com", "bark.com", "truelocal.com.au", "hotfrog.com", "manta.com",
    "bbb.org", "opentable.com", "doordash.com", "ubereats.com", "grubhub.com",
    "booksy.com", "fresha.com", "treatwell.com", "zocdoc.com", "healthgrades.com",
}

LINK_IN_BIO_HOSTS = {
    "linktr.ee", "linkin.bio", "beacons.ai", "carrd.co", "bio.link", "milkshake.app",
}

NON_WEBSITE_HOSTS = SOCIAL_HOSTS | DIRECTORY_HOSTS | LINK_IN_BIO_HOSTS

NON_HTML_EXT = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".zip", ".rar",
    ".mp4", ".mp3", ".avi", ".mov", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf", ".eot", ".dmg", ".exe",
}

_LEGAL_SUFFIXES = {
    "llc", "inc", "ltd", "limited", "plc", "co", "corp", "corporation", "company",
    "gmbh", "pty", "pvt", "private", "llp", "lp", "sa", "srl", "bv", "nv", "ag", "ab",
    "oy", "as", "kft", "spa", "sl", "the", "and", "of",
}

_GENERIC_WORDS = {
    "services", "service", "solutions", "group", "center", "centre", "shop", "store",
    "studio", "clinic", "salon", "cafe", "restaurant", "bar", "hotel", "school",
    "academy", "agency", "consulting", "consultants", "partners", "associates",
}


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------


def normalize_url(raw: str) -> Optional[str]:
    """Turn a messy CSV cell into a canonical absolute URL, or None."""
    if not raw:
        return None
    url = str(raw).strip().strip('"').strip("'")
    if not url or url.lower() in {"n/a", "na", "none", "null", "-", "no website", "nan"}:
        return None

    url = re.sub(r"\s+", "", url)
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", url):
        if "." not in url.split("/")[0]:
            return None
        url = "https://" + url

    try:
        p = urlparse(url)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None

    host = p.netloc.lower()
    if host.endswith(":80"):
        host = host[:-3]
    elif host.endswith(":443"):
        host = host[:-4]
    if "." not in host.split(":")[0]:
        return None

    path = p.path or "/"
    query = _strip_tracking(p.query)
    return urlunparse((p.scheme, host, path, "", query, ""))


def _strip_tracking(query: str) -> str:
    if not query:
        return ""
    kept = []
    for part in query.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0].lower()
        if key not in TRACKING_PARAMS:
            kept.append(part)
    return "&".join(kept)


def registrable_domain(url: str) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc or url
    except ValueError:
        host = url
    host = host.split("@")[-1].split(":")[0].lower()
    ext = _extract(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return host


def host_of(url: str) -> str:
    """Hostname without the port - used for grouping and comparisons."""
    try:
        return (urlparse(url).netloc or "").split(":")[0].lower()
    except ValueError:
        return ""


def netloc_of(url: str) -> str:
    """Hostname *with* the port, when one is present."""
    try:
        return (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""


def origin_of(url: str) -> str:
    """
    scheme://host[:port] - the base for /robots.txt and /sitemap.xml.

    The port must be kept: dropping it sends those lookups to port 80 and makes
    every site on a non-standard port look as though it publishes neither file.
    """
    try:
        p = urlparse(url)
    except ValueError:
        return ""
    if not p.netloc:
        return ""
    return f"{(p.scheme or 'https').lower()}://{p.netloc.lower()}"


def same_site(a: str, b: str) -> bool:
    da, db = registrable_domain(a), registrable_domain(b)
    return bool(da) and da == db


def is_non_website_host(url: str) -> Tuple[bool, str]:
    """True when the URL is a social/directory profile rather than a real site."""
    dom = registrable_domain(url)
    host = host_of(url)
    if not dom:
        return False, ""
    if dom in SOCIAL_HOSTS or host in SOCIAL_HOSTS:
        return True, "social_profile"
    if dom in DIRECTORY_HOSTS or host in DIRECTORY_HOSTS:
        return True, "directory_listing"
    if dom in LINK_IN_BIO_HOSTS or host in LINK_IN_BIO_HOSTS:
        return True, "link_in_bio"
    return False, ""


def is_crawlable(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    path = (p.path or "").lower()
    return not any(path.endswith(ext) for ext in NON_HTML_EXT)


def absolutize(base: str, href: str) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    low = href.lower()
    if low.startswith(("javascript:", "mailto:", "tel:", "sms:", "data:", "#", "callto:", "whatsapp:")):
        return None
    try:
        joined = urljoin(base, href)
    except ValueError:
        return None
    joined = joined.split("#", 1)[0]
    return normalize_url(joined)


def url_key(url: str) -> str:
    """Dedup key: ignores scheme, leading www, trailing slash, and index files."""
    if not url:
        return ""
    try:
        p = urlparse(url)
    except ValueError:
        return url
    host = (p.netloc or "").lower().replace("www.", "", 1).split(":")[0]
    path = re.sub(r"/(index|default|home)\.(html?|php|aspx?)$", "/", p.path or "/", flags=re.I)
    path = path.rstrip("/") or "/"
    q = f"?{p.query}" if p.query else ""
    return f"{host}{path}{q}".lower()


# --------------------------------------------------------------------------
# Identity matching (spec 7) - never attach another company's website
# --------------------------------------------------------------------------


def name_tokens(name: str) -> List[str]:
    n = (name or "").lower()
    n = re.sub(r"[&+]", " and ", n)
    n = re.sub(r"[^a-z0-9]+", " ", n)
    toks = [t for t in n.split() if t and t not in _LEGAL_SUFFIXES and len(t) > 1]
    return toks


def distinctive_tokens(name: str) -> List[str]:
    toks = name_tokens(name)
    distinct = [t for t in toks if t not in _GENERIC_WORDS]
    return distinct or toks


def _domain_core(url: str) -> str:
    dom = registrable_domain(url)
    ext = _extract(dom)
    return re.sub(r"[^a-z0-9]", "", (ext.domain or dom).lower())


def score_identity(
    *,
    business_name: str,
    url: str,
    page_title: str = "",
    page_text: str = "",
    phone_digits: Optional[List[str]] = None,
    city: str = "",
    postal_code: str = "",
    address: str = "",
    category: str = "",
) -> Dict[str, Any]:
    """
    Confidence 0..1 that `url` really belongs to `business_name`.

    Weighted signals, each independently evidenced so the UI can explain the
    verdict rather than showing a bare number.
    """
    signals: List[Dict[str, Any]] = []
    score = 0.0

    toks = name_tokens(business_name)
    distinct = distinctive_tokens(business_name)
    core = _domain_core(url)
    text_l = (page_text or "").lower()
    title_l = (page_title or "").lower()

    # 1. Domain contains the business name tokens (strongest single signal).
    if core and distinct:
        joined = "".join(distinct)
        initials = "".join(t[0] for t in distinct if t)
        if joined and joined in core:
            score += 0.45
            signals.append({"signal": "domain_matches_full_name", "weight": 0.45, "detail": core})
        else:
            hits = [t for t in distinct if len(t) >= 4 and t in core]
            if hits:
                frac = len(hits) / len(distinct)
                gain = 0.34 * frac
                score += gain
                signals.append(
                    {"signal": "domain_matches_name_tokens", "weight": round(gain, 3),
                     "detail": ",".join(hits)}
                )
            elif len(initials) >= 3 and initials in core:
                score += 0.16
                signals.append({"signal": "domain_matches_initials", "weight": 0.16, "detail": initials})

    # 2. Business name appears in the page title.
    if title_l and distinct:
        hits = [t for t in distinct if t in title_l]
        if hits and len(hits) / len(distinct) >= 0.6:
            score += 0.22
            signals.append({"signal": "name_in_title", "weight": 0.22, "detail": page_title[:120]})
        elif hits:
            score += 0.10
            signals.append({"signal": "partial_name_in_title", "weight": 0.10, "detail": ",".join(hits)})

    # 3. Business name appears in page body.
    if text_l and distinct:
        hits = [t for t in distinct if t in text_l]
        if len(hits) == len(distinct):
            score += 0.14
            signals.append({"signal": "name_in_page_text", "weight": 0.14, "detail": "all tokens"})
        elif hits:
            score += 0.07
            signals.append({"signal": "partial_name_in_page_text", "weight": 0.07, "detail": ",".join(hits)})

    # 4. The CSV phone number appears on the site - very strong corroboration.
    if phone_digits:
        page_digits = re.sub(r"\D", "", text_l)
        for pd in phone_digits:
            tail = re.sub(r"\D", "", pd)[-9:]
            if len(tail) >= 7 and tail in page_digits:
                score += 0.28
                signals.append({"signal": "phone_found_on_site", "weight": 0.28, "detail": pd})
                break

    # 5. Location corroboration.
    if postal_code and len(postal_code.strip()) >= 4:
        pc = postal_code.strip().lower().replace(" ", "")
        if pc and pc in text_l.replace(" ", ""):
            score += 0.12
            signals.append({"signal": "postal_code_on_site", "weight": 0.12, "detail": postal_code})
    if city and len(city) > 2 and city.lower() in text_l:
        score += 0.08
        signals.append({"signal": "city_on_site", "weight": 0.08, "detail": city})
    if address:
        street = re.sub(r"[^a-z0-9 ]", " ", address.lower())
        parts = [p for p in street.split() if len(p) > 3][:4]
        if parts and sum(1 for p in parts if p in text_l) >= max(2, len(parts) - 1):
            score += 0.10
            signals.append({"signal": "address_on_site", "weight": 0.10, "detail": address[:120]})

    # 6. Weak category corroboration.
    if category:
        cat_toks = [t for t in re.split(r"[^a-z]+", category.lower()) if len(t) > 3]
        if cat_toks and any(t in text_l for t in cat_toks):
            score += 0.05
            signals.append({"signal": "category_language_present", "weight": 0.05, "detail": category})

    confidence = round(min(1.0, score), 3)
    if confidence >= 0.8:
        verdict = "strong_match"
    elif confidence >= 0.55:
        verdict = "probable_match"
    elif confidence >= 0.3:
        verdict = "weak_match"
    else:
        verdict = "no_match"

    return {"confidence": confidence, "verdict": verdict, "signals": signals}


def candidate_domains(business_name: str, tlds: Optional[List[str]] = None) -> List[str]:
    """
    Conservative domain guesses for businesses whose CSV row has no website.

    A guess is only ever a *candidate* - it must still pass identity matching
    against the fetched page before it is accepted (spec 7).
    """
    distinct = distinctive_tokens(business_name)
    if not distinct:
        return []
    tlds = tlds or [".com"]
    joined = "".join(distinct)
    hyphen = "-".join(distinct)

    bases: List[str] = []
    if 3 <= len(joined) <= 30:
        bases.append(joined)
    if len(distinct) > 1 and 3 <= len(hyphen) <= 34:
        bases.append(hyphen)
    if len(distinct) > 2:
        short = "".join(distinct[:2])
        if 3 <= len(short) <= 30:
            bases.append(short)

    out: List[str] = []
    seen: Set[str] = set()
    for base in bases:
        for tld in tlds:
            d = f"https://{base}{tld}"
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out[:6]


COUNTRY_TLDS = {
    "US": [".com", ".net"],
    "CA": [".ca", ".com"],
    "GB": [".co.uk", ".com", ".uk"],
    "AU": [".com.au", ".com", ".au"],
    "NZ": [".co.nz", ".com"],
    "IE": [".ie", ".com"],
    "PK": [".com.pk", ".pk", ".com"],
    "IN": [".in", ".co.in", ".com"],
    "DE": [".de", ".com"],
    "FR": [".fr", ".com"],
    "NL": [".nl", ".com"],
    "ES": [".es", ".com"],
    "IT": [".it", ".com"],
    "ZA": [".co.za", ".com"],
    "AE": [".ae", ".com"],
}


def tlds_for_region(region: Optional[str]) -> List[str]:
    return COUNTRY_TLDS.get((region or "").upper(), [".com", ".net"])
