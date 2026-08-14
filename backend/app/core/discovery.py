"""
Website discovery + validation (spec 7).

Two paths:
  1. The CSV supplied a website  -> validate it and confirm it belongs to
     this business.
  2. The CSV supplied nothing    -> optionally try a small set of candidate
     domains, each of which must PASS identity matching before it is
     accepted. A guess that cannot be corroborated is discarded, and the
     lead is recorded as no_website rather than given someone else's site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .fetcher import Fetcher
from .page import parse_html
from .urls import (
    candidate_domains,
    is_non_website_host,
    normalize_url,
    registrable_domain,
    score_identity,
    tlds_for_region,
)

# website_status values (spec 7)
STATUS_VALID = "valid"
STATUS_REDIRECTED = "redirected"
STATUS_UNAVAILABLE = "unavailable"
STATUS_BLOCKED = "blocked"
STATUS_MISMATCH = "mismatch"
STATUS_NOT_FOUND = "not_found"
STATUS_NOT_A_WEBSITE = "not_a_website"   # social / directory / link-in-bio URL
STATUS_NO_WEBSITE = "no_website"         # verified: none supplied, none found


@dataclass
class DiscoveryResult:
    website_original: str = ""
    website_final: str = ""
    status: str = STATUS_NO_WEBSITE
    source: str = ""                 # csv | discovered | none
    identity_confidence: Optional[float] = None
    identity_verdict: str = ""
    identity_signals: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    error_code: str = ""
    error_message: str = ""
    redirect_chain: List[str] = field(default_factory=list)
    http_status: Optional[int] = None
    response_ms: Optional[int] = None
    candidates_tried: List[str] = field(default_factory=list)
    social_profile_url: str = ""

    @property
    def has_website(self) -> bool:
        return self.status in (STATUS_VALID, STATUS_REDIRECTED) and bool(self.website_final)


async def discover_website(
    fetcher: Fetcher,
    *,
    business_name: str,
    website_raw: str = "",
    phone_digits: Optional[List[str]] = None,
    city: str = "",
    state: str = "",
    postal_code: str = "",
    address: str = "",
    category: str = "",
    region: Optional[str] = None,
    enable_guessing: bool = True,
    min_confidence: float = 0.55,
    max_candidates: int = 4,
) -> DiscoveryResult:
    out = DiscoveryResult(website_original=(website_raw or "").strip())

    # ---------------- path 1: CSV supplied a URL -------------------------
    if website_raw and str(website_raw).strip():
        norm = normalize_url(website_raw)
        if not norm:
            out.status = STATUS_NOT_FOUND
            out.source = "csv"
            out.notes.append("The website value in the CSV could not be parsed as a URL.")
        else:
            is_profile, kind = is_non_website_host(norm)
            if is_profile:
                out.status = STATUS_NOT_A_WEBSITE
                out.source = "csv"
                out.social_profile_url = norm
                out.notes.append(
                    f"The supplied URL is a {kind.replace('_', ' ')}, not the business's own website."
                )
                return out

            verified = await _fetch_and_verify(
                fetcher, norm, business_name=business_name, phone_digits=phone_digits,
                city=city, postal_code=postal_code, address=address, category=category,
            )
            out.http_status = verified["http_status"]
            out.response_ms = verified["response_ms"]
            out.redirect_chain = verified["redirect_chain"]
            out.source = "csv"

            if verified["error_code"]:
                out.error_code = verified["error_code"]
                out.error_message = verified["error_message"]
                out.status = (
                    STATUS_BLOCKED if verified["error_code"] == "blocked" else STATUS_UNAVAILABLE
                )
                out.notes.append(verified["error_message"])
                return out

            ident = verified["identity"]
            out.identity_confidence = ident["confidence"]
            out.identity_verdict = ident["verdict"]
            out.identity_signals = ident["signals"]
            out.website_final = verified["final_url"]

            # A URL the user gave us is trusted as *theirs*; identity scoring
            # only downgrades it when the page clearly belongs elsewhere.
            if ident["confidence"] < 0.2 and ident["verdict"] == "no_match":
                out.status = STATUS_MISMATCH
                out.notes.append(
                    "The page shows no sign of this business (name, phone or address). "
                    "Treated as a possible mismatch and excluded from outreach."
                )
                return out

            same = registrable_domain(norm) == registrable_domain(verified["final_url"])
            out.status = STATUS_VALID if same else STATUS_REDIRECTED
            if not same:
                out.notes.append(
                    f"Redirects to a different domain: {registrable_domain(verified['final_url'])}"
                )
                is_profile2, kind2 = is_non_website_host(verified["final_url"])
                if is_profile2:
                    out.status = STATUS_NOT_A_WEBSITE
                    out.social_profile_url = verified["final_url"]
                    out.notes.append(
                        f"The domain now redirects to a {kind2.replace('_', ' ')}."
                    )
            return out

    # ---------------- path 2: nothing supplied ---------------------------
    if not enable_guessing:
        out.status = STATUS_NO_WEBSITE
        out.source = "none"
        out.notes.append("No website in the CSV and automatic discovery is disabled.")
        return out

    tlds = tlds_for_region(region)
    candidates = candidate_domains(business_name, tlds)[:max_candidates]
    out.candidates_tried = candidates
    if not candidates:
        out.status = STATUS_NO_WEBSITE
        out.source = "none"
        out.notes.append("The business name did not yield any usable domain candidate.")
        return out

    best: Optional[Dict[str, Any]] = None
    for cand in candidates:
        verified = await _fetch_and_verify(
            fetcher, cand, business_name=business_name, phone_digits=phone_digits,
            city=city, postal_code=postal_code, address=address, category=category,
        )
        if verified["error_code"]:
            continue
        ident = verified["identity"]
        if best is None or ident["confidence"] > best["identity"]["confidence"]:
            best = verified
        if ident["confidence"] >= 0.85:
            break  # good enough, stop hitting more hosts

    if best is None:
        out.status = STATUS_NO_WEBSITE
        out.source = "none"
        out.notes.append(
            f"No reachable website found for {len(candidates)} candidate domain(s)."
        )
        return out

    ident = best["identity"]
    out.identity_confidence = ident["confidence"]
    out.identity_verdict = ident["verdict"]
    out.identity_signals = ident["signals"]
    out.http_status = best["http_status"]
    out.response_ms = best["response_ms"]
    out.redirect_chain = best["redirect_chain"]

    if ident["confidence"] >= min_confidence:
        out.website_final = best["final_url"]
        out.status = STATUS_VALID
        out.source = "discovered"
        out.notes.append(
            f"Discovered by domain guess and confirmed at {int(ident['confidence'] * 100)}% "
            f"identity confidence."
        )
    else:
        out.status = STATUS_NO_WEBSITE
        out.source = "none"
        out.notes.append(
            f"A candidate domain responded but only matched this business at "
            f"{int(ident['confidence'] * 100)}% confidence (threshold "
            f"{int(min_confidence * 100)}%). Not attached, to avoid using another "
            f"company's website."
        )
    return out


async def verify_direct_website(fetcher: Fetcher, url: str) -> DiscoveryResult:
    """
    Path for a URL the user typed directly into the app to have it audited,
    rather than a CSV row being matched against a business identity. There is
    no business name, phone or address to corroborate against, so identity
    scoring does not apply here - the URL itself, explicitly supplied, is the
    ground truth. This never guesses a domain and never falls back to
    candidate matching (spec 7's guessing path is CSV-only).
    """
    out = DiscoveryResult(website_original=(url or "").strip(), source="manual")
    norm = normalize_url(url)
    if not norm:
        out.status = STATUS_NOT_FOUND
        out.notes.append("That URL could not be parsed.")
        return out

    is_profile, kind = is_non_website_host(norm)
    if is_profile:
        out.status = STATUS_NOT_A_WEBSITE
        out.social_profile_url = norm
        out.notes.append(
            f"This is a {kind.replace('_', ' ')}, not a standalone website that can be audited."
        )
        return out

    res = await fetcher.fetch(norm)
    out.http_status = res.status
    out.response_ms = res.elapsed_ms
    out.redirect_chain = res.redirect_chain
    if not res.ok:
        out.error_code = res.error_code
        out.error_message = res.error_message
        out.status = STATUS_BLOCKED if res.error_code == "blocked" else STATUS_UNAVAILABLE
        out.notes.append(res.error_message)
        return out

    final = res.final_url or norm
    out.website_final = final
    out.identity_confidence = 1.0
    out.identity_verdict = "explicit_url"
    out.identity_signals = [{"signal": "explicitly_supplied_url", "weight": 1.0, "detail": norm}]

    same = registrable_domain(norm) == registrable_domain(final)
    out.status = STATUS_VALID if same else STATUS_REDIRECTED
    if not same:
        out.notes.append(f"Redirects to a different domain: {registrable_domain(final)}")
        is_profile2, kind2 = is_non_website_host(final)
        if is_profile2:
            out.status = STATUS_NOT_A_WEBSITE
            out.social_profile_url = final
            out.notes.append(f"The domain now redirects to a {kind2.replace('_', ' ')}.")
    return out


async def _fetch_and_verify(
    fetcher: Fetcher,
    url: str,
    *,
    business_name: str,
    phone_digits: Optional[List[str]],
    city: str,
    postal_code: str,
    address: str,
    category: str,
) -> Dict[str, Any]:
    res = await fetcher.fetch(url)
    out: Dict[str, Any] = {
        "url": url,
        "final_url": res.final_url or url,
        "http_status": res.status,
        "response_ms": res.elapsed_ms,
        "redirect_chain": res.redirect_chain,
        "error_code": res.error_code,
        "error_message": res.error_message,
        "identity": {"confidence": 0.0, "verdict": "no_match", "signals": []},
        "html": "",
    }
    if not res.ok:
        return out

    page = parse_html(res.text, url, final_url=res.final_url, status=res.status)
    out["html"] = res.text
    out["identity"] = score_identity(
        business_name=business_name,
        url=res.final_url or url,
        page_title=page.title,
        page_text=page.text[:20000],
        phone_digits=phone_digits,
        city=city,
        postal_code=postal_code,
        address=address,
        category=category,
    )
    return out


def parked_domain_signals(text: str, title: str) -> List[str]:
    """Detect placeholder / parked / under-construction pages."""
    hits: List[str] = []
    blob = f"{title} {text[:4000]}".lower()
    patterns = {
        "domain is for sale": "The domain appears to be listed for sale.",
        "buy this domain": "The domain appears to be listed for sale.",
        "under construction": "The page says it is under construction.",
        "coming soon": "The page says it is coming soon.",
        "site is temporarily unavailable": "The host reports the site as unavailable.",
        "default web page": "This is the hosting provider's default page.",
        "welcome to nginx": "This is an unconfigured nginx default page.",
        "apache2 ubuntu default page": "This is an unconfigured Apache default page.",
        "future home of something quite cool": "This is a hosting placeholder page.",
        "this domain is parked": "The domain is parked.",
        "godaddy.com": "" ,
    }
    for needle, note in patterns.items():
        if needle in blob and note:
            hits.append(note)
    if len(re.sub(r"\s+", " ", text).strip()) < 200 and not hits:
        hits.append("The page contains almost no content.")
    return hits
