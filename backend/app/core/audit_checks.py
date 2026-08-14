"""
Rule-based website audit (spec 12-14, 16).

Every check reports an *observable fact* with the evidence that produced it.
Nothing here infers lost revenue, lost customers, or anything else that was
not measured. A check that cannot run reports `not_measured` rather than
guessing a result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .crawler import CrawlResult
from .page import ParsedPage, jsonld_of_type
from .urls import registrable_domain

# --------------------------------------------------------------------------


@dataclass
class Finding:
    code: str
    category: str            # technical | mobile | conversion | trust | contact | content
    display_category: str    # same, or "performance" for perf-tagged findings
    severity: str            # high | medium | low
    title: str               # the observable fact, phrased neutrally
    detail: str              # what was measured
    deduction: int           # health points removed from `category`
    evidence: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "display_category": self.display_category,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "deduction": self.deduction,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


CATEGORIES = ["technical", "mobile", "conversion", "trust", "contact", "content"]


def _f(**kw) -> Finding:
    return Finding(**kw)


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

BOOKING_WORDS = [
    "book now", "book online", "book a", "book an", "make a booking", "booking",
    "appointment", "make an appointment", "schedule", "reserve", "reservation",
    "request a visit", "arrange a visit",
]
QUOTE_WORDS = [
    "get a quote", "free quote", "request a quote", "get quote", "free estimate",
    "request an estimate", "get pricing", "request pricing", "instant quote",
]
CONSULT_WORDS = [
    "consultation", "free consultation", "book a consultation", "talk to us",
    "speak to us", "discovery call", "free assessment",
]
CONTACT_WORDS = [
    "contact us", "contact", "get in touch", "reach us", "enquire", "enquiry",
    "inquire", "inquiry", "send us a message", "message us", "email us", "call us",
]
GENERIC_CTA = {"submit", "send", "click here", "read more", "learn more", "more", "go", "ok"}

BOOKING_PLATFORMS = [
    "calendly.com", "acuityscheduling.com", "squareup.com/appointments", "booksy.com",
    "fresha.com", "treatwell", "setmore.com", "simplybook.me", "mindbodyonline.com",
    "opentable.com", "resy.com", "sevenrooms.com", "timely.com", "vagaro.com",
    "square.site", "schedulicity.com", "appointy.com", "10to8.com", "youcanbook.me",
    "cal.com", "housecallpro.com", "jobber.com", "servicetitan.com", "zocdoc.com",
]

TESTIMONIAL_WORDS = [
    "testimonial", "testimonials", "what our clients say", "what our customers say",
    "client stories", "customer stories", "reviews", "review", "rated", "5 star",
    "five star", "happy clients", "happy customers", "kind words", "success stories",
]
CREDENTIAL_WORDS = [
    "licensed", "licence", "license", "insured", "certified", "certification",
    "accredited", "accreditation", "qualified", "member of", "registered",
    "award", "awards", "award-winning", "gas safe", "niceic", "checkatrade",
    "city & guilds", "bbb accredited", "iso 900", "years of experience",
    "years experience", "established in", "since 19", "since 20", "guarantee",
    "warranty", "dbs checked", "fully insured",
]
PORTFOLIO_WORDS = [
    "portfolio", "our work", "case study", "case studies", "gallery", "projects",
    "before and after", "before & after", "recent work", "past work",
]
HOURS_WORDS = [
    "opening hours", "open hours", "business hours", "hours of operation", "we are open",
    "mon-fri", "mon - fri", "monday to friday", "monday - friday", "monday-friday",
    "open today", "opening times",
]
SERVICE_AREA_WORDS = [
    "areas we serve", "service area", "service areas", "areas covered", "we cover",
    "serving", "we serve", "coverage area", "locations we serve", "surrounding areas",
]

_RE_PX = re.compile(r"(?:^|[;{\s])(?:min-)?width\s*:\s*(\d{3,5})px", re.I)
_RE_FONT_PX = re.compile(r"font-size\s*:\s*(\d{1,2}(?:\.\d+)?)px", re.I)


def _blob(pages: List[ParsedPage], limit: int = 60000) -> str:
    return " ".join(p.text for p in pages)[:limit].lower()


def _any_word(text: str, words: List[str]) -> Optional[str]:
    for w in words:
        if w in text:
            return w
    return None


def _cta_texts(pages: List[ParsedPage]) -> List[str]:
    out: List[str] = []
    for p in pages:
        out.extend(b.lower().strip() for b in p.buttons if b.strip())
        for link in p.links:
            t = link.text.lower().strip()
            if 2 <= len(t) <= 60:
                out.append(t)
    return out


# ==========================================================================
# TECHNICAL (measured performance is reported under this category, tagged
# for display as "performance")
# ==========================================================================


def check_technical(crawl: CrawlResult, perf: Optional[Dict[str, Any]] = None) -> tuple:
    home = crawl.homepage
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    if home is None:
        return facts, findings

    facts["final_url"] = crawl.final_url
    facts["http_status"] = crawl.home_status
    facts["is_https"] = crawl.is_https
    facts["response_ms"] = crawl.home_response_ms
    facts["redirect_chain"] = crawl.redirect_chain
    facts["redirect_count"] = max(0, len(crawl.redirect_chain) - 1)
    facts["title"] = home.title
    facts["title_length"] = len(home.title)
    facts["meta_description"] = home.meta_description
    facts["meta_description_length"] = len(home.meta_description)
    facts["h1_count"] = len(home.h1)
    facts["h1"] = home.h1[:3]
    facts["canonical"] = home.canonical
    facts["meta_robots"] = home.meta_robots
    facts["lang"] = home.lang
    facts["robots_txt_found"] = crawl.robots_txt_found
    facts["sitemap_found"] = crawl.sitemap_found
    facts["sitemap_url"] = crawl.sitemap_url
    facts["pages_crawled"] = len(crawl.pages)
    facts["broken_links"] = crawl.broken_links
    facts["links_checked"] = crawl.links_checked
    facts["mixed_content_count"] = len(home.mixed_content)
    facts["page_bytes"] = home.bytes_len
    facts["script_count"] = len(home.scripts)

    images_total = sum(p.images_total for p in crawl.pages)
    images_alt = sum(p.images_with_alt for p in crawl.pages)
    facts["images_total"] = images_total
    facts["images_with_alt"] = images_alt
    facts["alt_coverage"] = round(images_alt / images_total, 3) if images_total else None

    # -- HTTPS -------------------------------------------------------------
    if crawl.is_https is False:
        findings.append(_f(
            code="no_https", category="technical", display_category="technical",
            severity="high",
            title="The site does not load over HTTPS",
            detail=f"The homepage resolved to {crawl.final_url}, which is not a secure connection.",
            deduction=30,
            evidence={"final_url": crawl.final_url},
            recommendation="Install an SSL certificate and force all traffic to https:// with a 301 redirect.",
        ))
    if home.mixed_content:
        findings.append(_f(
            code="mixed_content", category="technical", display_category="technical",
            severity="medium",
            title="The secure page loads some assets over plain HTTP",
            detail=f"{len(home.mixed_content)} asset(s) on the homepage are requested over http://, "
                   f"which browsers flag or block.",
            deduction=12,
            evidence={"examples": home.mixed_content[:5]},
            recommendation="Update those asset URLs to https:// so the padlock is not broken.",
        ))

    # -- indexability ------------------------------------------------------
    if "noindex" in (home.meta_robots or ""):
        findings.append(_f(
            code="noindex", category="technical", display_category="technical",
            severity="high",
            title="The homepage is set to noindex",
            detail=f'The homepage carries <meta name="robots" content="{home.meta_robots}">, '
                   f"which asks search engines not to index it.",
            deduction=40,
            evidence={"meta_robots": home.meta_robots},
            recommendation="Remove the noindex directive so the homepage can appear in search results.",
        ))

    # -- title / description / h1 -----------------------------------------
    if not home.title.strip():
        findings.append(_f(
            code="missing_title", category="technical", display_category="technical",
            severity="high",
            title="The homepage has no title tag",
            detail="No <title> element was found on the homepage.",
            deduction=18, evidence={},
            recommendation="Add a title of roughly 50-60 characters naming the service and the location.",
        ))
    elif len(home.title) < 15:
        findings.append(_f(
            code="title_too_short", category="technical", display_category="technical",
            severity="low",
            title="The homepage title is very short",
            detail=f'The title is {len(home.title)} characters: "{home.title}".',
            deduction=6, evidence={"title": home.title},
            recommendation="Expand the title to around 50-60 characters including the main service and location.",
        ))
    elif len(home.title) > 70:
        findings.append(_f(
            code="title_too_long", category="technical", display_category="technical",
            severity="low",
            title="The homepage title is longer than search results display",
            detail=f"The title is {len(home.title)} characters; search results typically show about 60.",
            deduction=3, evidence={"title": home.title[:120]},
            recommendation="Trim the title so the important words are not cut off in search results.",
        ))

    if not home.meta_description.strip():
        findings.append(_f(
            code="missing_meta_description", category="technical", display_category="technical",
            severity="medium",
            title="The homepage has no meta description",
            detail="No meta description was found, so search engines generate the snippet themselves.",
            deduction=14, evidence={},
            recommendation="Write a 140-160 character description covering the service, area and one reason to choose them.",
        ))
    elif len(home.meta_description) < 50:
        findings.append(_f(
            code="meta_description_short", category="technical", display_category="technical",
            severity="low",
            title="The homepage meta description is very short",
            detail=f"The description is {len(home.meta_description)} characters.",
            deduction=5, evidence={"meta_description": home.meta_description},
            recommendation="Expand it to 140-160 characters to use the full search snippet.",
        ))

    if not home.h1:
        findings.append(_f(
            code="missing_h1", category="technical", display_category="technical",
            severity="medium",
            title="The homepage has no H1 heading",
            detail="No <h1> element was found on the homepage.",
            deduction=14, evidence={},
            recommendation="Add a single H1 that states what the business does and where.",
        ))
    elif len(home.h1) > 1:
        findings.append(_f(
            code="multiple_h1", category="technical", display_category="technical",
            severity="low",
            title="The homepage has more than one H1",
            detail=f"{len(home.h1)} H1 headings were found: " + "; ".join(home.h1[:3]),
            deduction=4, evidence={"h1": home.h1[:5]},
            recommendation="Keep one H1 as the page's main heading and demote the others to H2.",
        ))

    if not home.canonical:
        findings.append(_f(
            code="missing_canonical", category="technical", display_category="technical",
            severity="low",
            title="No canonical URL is declared on the homepage",
            detail="No <link rel=\"canonical\"> was found.",
            deduction=4, evidence={},
            recommendation="Add a canonical link so duplicate URLs consolidate onto one address.",
        ))
    if not home.lang:
        findings.append(_f(
            code="missing_lang", category="technical", display_category="technical",
            severity="low",
            title="The page does not declare a language",
            detail="The <html> element has no lang attribute, which screen readers rely on.",
            deduction=3, evidence={},
            recommendation='Add lang="en" (or the correct language) to the <html> element.',
        ))

    if crawl.sitemap_found is False:
        findings.append(_f(
            code="missing_sitemap", category="technical", display_category="technical",
            severity="low",
            title="No XML sitemap was found",
            detail="Neither robots.txt nor /sitemap.xml pointed to a sitemap.",
            deduction=6, evidence={},
            recommendation="Publish an XML sitemap and reference it from robots.txt.",
        ))
    if crawl.robots_txt_found is False:
        findings.append(_f(
            code="missing_robots", category="technical", display_category="technical",
            severity="low",
            title="No robots.txt file was found",
            detail="A request to /robots.txt did not return a file.",
            deduction=3, evidence={},
            recommendation="Add a robots.txt that allows crawling and links the sitemap.",
        ))

    if crawl.broken_links:
        n = len(crawl.broken_links)
        findings.append(_f(
            code="broken_internal_links", category="technical", display_category="technical",
            severity="high" if n >= 3 else "medium",
            title=f"{n} broken internal link{'s' if n != 1 else ''} were found",
            detail=f"Of {crawl.links_checked} internal links checked, {n} returned an error.",
            deduction=min(20, 8 + 4 * n),
            evidence={"broken": crawl.broken_links[:6], "checked": crawl.links_checked},
            recommendation="Fix or remove the broken links so visitors do not hit dead ends.",
        ))

    if images_total >= 5 and facts["alt_coverage"] is not None and facts["alt_coverage"] < 0.5:
        findings.append(_f(
            code="low_alt_coverage", category="technical", display_category="technical",
            severity="medium",
            title="Most images have no alt text",
            detail=f"{images_alt} of {images_total} images across {len(crawl.pages)} crawled pages "
                   f"have alt text ({int(facts['alt_coverage'] * 100)}%).",
            deduction=8,
            evidence={"examples": home.images_missing_alt_examples[:4]},
            recommendation="Add descriptive alt text to meaningful images for accessibility and image search.",
        ))

    if facts["redirect_count"] > 2:
        findings.append(_f(
            code="long_redirect_chain", category="technical", display_category="technical",
            severity="low",
            title="The homepage goes through several redirects",
            detail=f"{facts['redirect_count']} redirects were followed before the page loaded.",
            deduction=4, evidence={"chain": crawl.redirect_chain[:6]},
            recommendation="Point the entry URL straight at the final address to remove the extra hops.",
        ))

    # -- measured performance (tagged for display) -------------------------
    rt = crawl.home_response_ms
    if rt is not None:
        if rt > 4000:
            sev, ded = "high", 20
        elif rt > 2500:
            sev, ded = "medium", 14
        elif rt > 1500:
            sev, ded = "low", 7
        else:
            sev, ded = "", 0
        if ded:
            findings.append(_f(
                code="slow_response", category="technical", display_category="performance",
                severity=sev,
                title="The homepage was slow to respond",
                detail=f"The homepage took {rt} ms to return from this machine "
                       f"(single measured request, not a full performance profile).",
                deduction=ded,
                evidence={"response_ms": rt, "method": "single server-side HTTP request"},
                recommendation="Investigate server response time, caching and hosting; a sub-1s response is a reasonable target.",
            ))

    if home.bytes_len > 2_500_000:
        findings.append(_f(
            code="heavy_page", category="technical", display_category="performance",
            severity="medium",
            title="The homepage HTML download is large",
            detail=f"The homepage document alone was {home.bytes_len / 1_000_000:.1f} MB "
                   f"(images and scripts not included).",
            deduction=10, evidence={"bytes": home.bytes_len},
            recommendation="Reduce the page weight - compress, lazy-load and remove unused markup.",
        ))
    if len(home.scripts) > 25:
        findings.append(_f(
            code="many_scripts", category="technical", display_category="performance",
            severity="low",
            title="The homepage loads a large number of scripts",
            detail=f"{len(home.scripts)} external scripts were referenced on the homepage.",
            deduction=6, evidence={"script_count": len(home.scripts)},
            recommendation="Audit third-party scripts and remove or defer the ones that are not needed on load.",
        ))

    # -- optional PageSpeed ------------------------------------------------
    if perf and perf.get("measured"):
        facts["pagespeed"] = perf
        score = perf.get("performance_score")
        if isinstance(score, (int, float)):
            if score < 40:
                sev, ded = "high", 18
            elif score < 60:
                sev, ded = "medium", 12
            elif score < 80:
                sev, ded = "low", 6
            else:
                sev, ded = "", 0
            if ded:
                findings.append(_f(
                    code="pagespeed_low", category="technical", display_category="performance",
                    severity=sev,
                    title=f"Google PageSpeed scored the {perf.get('strategy', 'mobile')} page {int(score)}/100",
                    detail=_pagespeed_detail(perf),
                    deduction=ded,
                    evidence=perf,
                    recommendation="Work through the PageSpeed opportunities, starting with the largest contentful paint.",
                ))
    elif perf and perf.get("error"):
        facts["pagespeed"] = perf

    return facts, findings


def _pagespeed_detail(perf: Dict[str, Any]) -> str:
    bits = [f"Google PageSpeed Insights returned {perf.get('performance_score')}/100 "
            f"for the {perf.get('strategy')} strategy."]
    for key, label in (("lcp_s", "Largest Contentful Paint"), ("cls", "Cumulative Layout Shift"),
                       ("tbt_ms", "Total Blocking Time"), ("fcp_s", "First Contentful Paint")):
        v = perf.get(key)
        if v is not None:
            unit = {"lcp_s": " s", "fcp_s": " s", "tbt_ms": " ms", "cls": ""}[key]
            bits.append(f"{label}: {v}{unit}.")
    return " ".join(bits)


# ==========================================================================
# MOBILE  (static DOM/CSS signals - labelled as such, never as a render)
# ==========================================================================


def check_mobile(crawl: CrawlResult) -> tuple:
    home = crawl.homepage
    findings: List[Finding] = []
    facts: Dict[str, Any] = {"method": "static_dom_css_analysis"}
    if home is None:
        return facts, findings

    vp = (home.viewport or "").strip()
    facts["viewport"] = vp
    facts["has_viewport"] = bool(vp)

    if not vp:
        findings.append(_f(
            code="missing_viewport", category="mobile", display_category="mobile",
            severity="high",
            title="The page has no mobile viewport tag",
            detail='No <meta name="viewport"> was found, so mobile browsers render the page at '
                   'desktop width and the visitor has to pinch and zoom.',
            deduction=45, evidence={},
            recommendation='Add <meta name="viewport" content="width=device-width, initial-scale=1"> '
                           "and confirm the layout reflows on a phone.",
        ))
    else:
        responsive = "width=device-width" in vp
        facts["viewport_responsive"] = responsive
        blocks_zoom = "user-scalable=no" in vp.replace(" ", "") or re.search(
            r"maximum-scale\s*=\s*1(\.0)?\b", vp
        )
        facts["viewport_blocks_zoom"] = bool(blocks_zoom)

        if not responsive:
            findings.append(_f(
                code="viewport_not_responsive", category="mobile", display_category="mobile",
                severity="high",
                title="The viewport tag is not set to the device width",
                detail=f'The viewport is "{vp}", which does not use width=device-width, so the '
                       f"layout will not adapt to phone screens.",
                deduction=25, evidence={"viewport": vp},
                recommendation='Set the viewport to "width=device-width, initial-scale=1".',
            ))
        if blocks_zoom:
            findings.append(_f(
                code="zoom_disabled", category="mobile", display_category="mobile",
                severity="medium",
                title="Pinch-to-zoom is disabled on mobile",
                detail=f'The viewport "{vp}" prevents visitors from zooming, which is an '
                       f"accessibility problem for anyone with low vision.",
                deduction=10, evidence={"viewport": vp},
                recommendation="Remove user-scalable=no / maximum-scale=1 so visitors can zoom.",
            ))

    # -- fixed-width layout signals ---------------------------------------
    css = " ".join(home.inline_style_blocks)[:120000]
    html_slice = (home.raw_html or "")[:200000]
    widths = [int(m) for m in _RE_PX.findall(css)]
    attr_widths = [
        int(m) for m in re.findall(r'<(?:table|div|img)[^>]+width\s*=\s*"?(\d{3,5})', html_slice, re.I)
    ]
    big = [w for w in widths + attr_widths if w > 600]
    facts["fixed_width_declarations"] = len(big)
    facts["largest_fixed_width_px"] = max(big) if big else None

    if len(big) >= 3:
        findings.append(_f(
            code="fixed_width_layout", category="mobile", display_category="mobile",
            severity="medium",
            title="The layout uses fixed pixel widths wider than a phone screen",
            detail=f"{len(big)} declarations set a fixed width above 600px "
                   f"(largest {max(big)}px) in the page's own markup and inline CSS. "
                   f"Fixed widths above roughly 400px commonly cause sideways scrolling on phones.",
            deduction=15,
            evidence={"count": len(big), "largest_px": max(big), "samples": sorted(set(big))[-5:]},
            recommendation="Replace fixed pixel widths with max-width plus percentage/flex layout.",
        ))

    fonts = [float(m) for m in _RE_FONT_PX.findall(css)]
    small_fonts = [f for f in fonts if f < 12]
    facts["small_font_declarations"] = len(small_fonts)
    if len(small_fonts) >= 3:
        findings.append(_f(
            code="small_mobile_text", category="mobile", display_category="mobile",
            severity="low",
            title="Several text styles are set below 12px",
            detail=f"{len(small_fonts)} font-size declarations under 12px were found in the page's "
                   f"inline CSS, which is hard to read on a phone without zooming.",
            deduction=8, evidence={"count": len(small_fonts), "smallest_px": min(small_fonts)},
            recommendation="Use a base body size of at least 16px on mobile.",
        ))

    # -- tap-to-call, the single most important mobile CTA -----------------
    has_tel_home = bool(home.tel)
    facts["tap_to_call_on_homepage"] = has_tel_home
    facts["tap_to_call_anywhere"] = any(p.tel for p in crawl.pages)

    if not has_tel_home:
        anywhere = facts["tap_to_call_anywhere"]
        findings.append(_f(
            code="no_mobile_tap_to_call", category="mobile", display_category="mobile",
            severity="high" if not anywhere else "medium",
            title="The homepage has no tap-to-call phone link",
            detail=("No <a href=\"tel:\"> link was found on the homepage, so a phone visitor "
                    "cannot tap the number to call. " +
                    ("A tap-to-call link does exist on another page." if anywhere
                     else "No tap-to-call link was found on any crawled page.")),
            deduction=20 if not anywhere else 12,
            evidence={"pages_checked": len(crawl.pages), "found_elsewhere": anywhere},
            recommendation="Make the phone number a tel: link and place it in the mobile header so it is "
                           "tappable without scrolling.",
        ))

    # -- legacy / non-mobile tech -----------------------------------------
    if re.search(r"<(object|embed|applet)\b", html_slice, re.I):
        findings.append(_f(
            code="legacy_plugin_content", category="mobile", display_category="mobile",
            severity="low",
            title="The page embeds legacy plugin content",
            detail="An <object>, <embed> or <applet> element was found; this content typically "
                   "does not run on mobile browsers.",
            deduction=6, evidence={},
            recommendation="Replace legacy embeds with HTML5 equivalents.",
        ))

    nav_links = len([l for l in home.links if l.internal])
    facts["internal_link_count_home"] = nav_links
    has_mobile_menu = bool(
        re.search(r"(hamburger|mobile-menu|menu-toggle|navbar-toggle|nav-toggle|burger)",
                  html_slice, re.I)
    )
    facts["mobile_menu_detected"] = has_mobile_menu
    if nav_links > 25 and not has_mobile_menu:
        findings.append(_f(
            code="no_mobile_menu", category="mobile", display_category="mobile",
            severity="medium",
            title="A large navigation with no mobile menu pattern detected",
            detail=f"The homepage has {nav_links} internal links and no recognisable mobile menu "
                   f"markup (hamburger/toggle), so navigation may be unusable on a phone.",
            deduction=10, evidence={"internal_links": nav_links},
            recommendation="Add a collapsible mobile menu that exposes the main services and contact link.",
        ))

    facts["note"] = (
        "Mobile findings are derived from the page's HTML and inline CSS, not from a "
        "rendered phone browser. External stylesheets were not downloaded."
    )
    return facts, findings


# ==========================================================================
# CONVERSION
# ==========================================================================


def check_conversion(crawl: CrawlResult) -> tuple:
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    home = crawl.homepage
    if home is None:
        return facts, findings

    pages = crawl.pages
    text_all = _blob(pages)
    ctas = _cta_texts(pages)
    cta_blob = " | ".join(ctas)
    types = crawl.types_found()
    html_all = " ".join((p.raw_html or "") for p in pages)[:200000].lower()

    has_tel = any(p.tel for p in pages)
    has_mailto = any(p.mailto for p in pages)
    real_forms = [
        f for p in pages for f in p.forms
        if not f.is_search and not f.is_newsletter
        and (f.has_email_field or f.has_message_field or f.has_phone_field)
    ]
    has_form = bool(real_forms)

    booking_word = _any_word(cta_blob, BOOKING_WORDS) or _any_word(text_all, BOOKING_WORDS)
    booking_platform = next((p for p in BOOKING_PLATFORMS if p in html_all), None)
    has_booking = bool(booking_word or booking_platform or "booking" in types)

    quote_word = _any_word(cta_blob, QUOTE_WORDS) or _any_word(text_all, QUOTE_WORDS)
    consult_word = _any_word(cta_blob, CONSULT_WORDS) or _any_word(text_all, CONSULT_WORDS)
    contact_word = _any_word(cta_blob, CONTACT_WORDS)

    has_whatsapp = any(p.whatsapp_links for p in pages)

    facts.update({
        "has_phone_cta": has_tel,
        "has_email_cta": has_mailto,
        "has_contact_form": has_form,
        "contact_form_count": len(real_forms),
        "has_booking_cta": has_booking,
        "booking_evidence": booking_platform or booking_word or ("booking page" if "booking" in types else ""),
        "has_quote_cta": bool(quote_word),
        "has_consultation_cta": bool(consult_word),
        "has_whatsapp_cta": has_whatsapp,
        "has_contact_page": "contact" in types,
        "cta_samples": ctas[:15],
    })

    # -- above-the-fold primary CTA ---------------------------------------
    af = (home.above_fold_html or "").lower()
    af_text = (home.above_fold_text or "").lower()
    af_signals: List[str] = []
    if 'href="tel:' in af or "href='tel:" in af:
        af_signals.append("tap-to-call link")
    if "mailto:" in af:
        af_signals.append("email link")
    for w in BOOKING_WORDS + QUOTE_WORDS + CONSULT_WORDS + CONTACT_WORDS:
        if w in af_text:
            af_signals.append(f'"{w}"')
            break
    facts["above_fold_cta_signals"] = af_signals
    facts["above_fold_method"] = "header markup plus the first ~18KB of body HTML (approximation)"

    if not af_signals:
        findings.append(_f(
            code="no_primary_cta_above_fold", category="conversion", display_category="conversion",
            severity="high",
            title="No clear call to action was found near the top of the homepage",
            detail="The header and the opening section of the homepage contain no phone link, "
                   "email link, or booking/quote/contact wording. (Measured from the page markup, "
                   "which approximates what appears before scrolling.)",
            deduction=22, evidence={"checked": facts["above_fold_method"]},
            recommendation="Put one primary action - call, book, or request a quote - in the header "
                           "and repeat it in the opening section.",
        ))

    if not has_tel:
        findings.append(_f(
            code="no_phone_cta", category="conversion", display_category="conversion",
            severity="high",
            title="No clickable phone link was found anywhere on the site",
            detail=f"No tel: link was found across {len(pages)} crawled pages.",
            deduction=22, evidence={"pages_crawled": len(pages)},
            recommendation="Add the phone number as a tel: link in the header, footer and contact page.",
        ))

    if not has_form:
        findings.append(_f(
            code="no_contact_form", category="conversion", display_category="conversion",
            severity="high" if not has_tel and not has_mailto else "medium",
            title="No contact or enquiry form was detected",
            detail=f"No form with a name/email/message field was found on the {len(pages)} pages "
                   f"crawled (search and newsletter forms were excluded).",
            deduction=15, evidence={"pages_crawled": len(pages)},
            recommendation="Add a short enquiry form - name, contact detail and message - on the contact page "
                           "and after the main service section.",
        ))

    if not has_booking:
        findings.append(_f(
            code="no_booking_cta", category="conversion", display_category="conversion",
            severity="medium",
            title="No booking or appointment option was detected",
            detail="No booking wording, booking page or recognised scheduling platform was found "
                   "on the crawled pages.",
            deduction=16, evidence={"platforms_checked": len(BOOKING_PLATFORMS)},
            recommendation="If the business takes appointments, add an online booking option; otherwise "
                           "make 'request a callback' the equivalent primary action.",
        ))

    if not quote_word and not consult_word:
        findings.append(_f(
            code="no_quote_cta", category="conversion", display_category="conversion",
            severity="low",
            title="No quote or consultation offer was found",
            detail="The site does not invite visitors to request a quote, estimate or consultation.",
            deduction=8, evidence={},
            recommendation="Add a 'Request a free quote' or 'Book a consultation' action for visitors "
                           "who are not ready to call.",
        ))

    if not has_mailto and not has_form:
        findings.append(_f(
            code="no_email_cta", category="conversion", display_category="conversion",
            severity="medium",
            title="There is no way to make contact in writing",
            detail="Neither an email link nor a contact form was found on the crawled pages.",
            deduction=10, evidence={},
            recommendation="Publish an email address or add a form so visitors can enquire outside opening hours.",
        ))

    if "contact" not in types:
        findings.append(_f(
            code="no_contact_page", category="conversion", display_category="conversion",
            severity="medium",
            title="No contact page was found",
            detail="No page identifiable as a contact page was reachable from the homepage "
                   f"within {len(pages)} crawled pages.",
            deduction=12, evidence={"pages_found": sorted(types)},
            recommendation="Add a clearly linked Contact page with phone, email, address and a form.",
        ))

    generic = [c for c in ctas if c in GENERIC_CTA]
    strong = [
        c for c in ctas
        if any(w in c for w in BOOKING_WORDS + QUOTE_WORDS + CONSULT_WORDS + ["call", "contact"])
    ]
    facts["generic_cta_count"] = len(generic)
    facts["strong_cta_count"] = len(strong)
    if generic and not strong:
        findings.append(_f(
            code="weak_cta_language", category="conversion", display_category="conversion",
            severity="low",
            title="The calls to action use generic wording",
            detail="Buttons and links use wording like " +
                   ", ".join(f'"{g}"' for g in sorted(set(generic))[:4]) +
                   " with no action-specific alternative found.",
            deduction=6, evidence={"generic": sorted(set(generic))[:6]},
            recommendation="Name the outcome in the button - 'Get a free quote', 'Book an appointment' - "
                           "rather than 'Submit' or 'Learn more'.",
        ))

    if not has_whatsapp:
        facts["whatsapp_cta_note"] = "No WhatsApp link found on the site."

    return facts, findings


# ==========================================================================
# TRUST / PROOF
# ==========================================================================


def check_trust(crawl: CrawlResult) -> tuple:
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    pages = crawl.pages
    if not pages:
        return facts, findings

    text_all = _blob(pages)
    types = crawl.types_found()

    testimonial_hit = _any_word(text_all, TESTIMONIAL_WORDS)
    credential_hit = _any_word(text_all, CREDENTIAL_WORDS)
    portfolio_hit = _any_word(text_all, PORTFOLIO_WORDS)
    review_schema = any(jsonld_of_type(p, "Review", "AggregateRating") for p in pages)
    social = sorted({s for p in pages for s in p.social_links})

    facts.update({
        "testimonials_detected": bool(testimonial_hit) or "testimonials" in types,
        "testimonial_evidence": testimonial_hit or ("testimonials page" if "testimonials" in types else ""),
        "credentials_detected": bool(credential_hit),
        "credential_evidence": credential_hit or "",
        "portfolio_detected": bool(portfolio_hit),
        "portfolio_evidence": portfolio_hit or "",
        "review_structured_data": review_schema,
        "about_page": "about" in types,
        "team_page": "team" in types,
        "social_links": social[:10],
    })

    if not facts["testimonials_detected"]:
        findings.append(_f(
            code="no_testimonials", category="trust", display_category="trust",
            severity="high",
            title="No testimonials or customer reviews were found on the site",
            detail=f"None of the {len(pages)} crawled pages mention testimonials, reviews or "
                   f"customer feedback.",
            deduction=24, evidence={"pages_crawled": len(pages)},
            recommendation="Add three to five short customer quotes with a name and location near the "
                           "main call to action.",
        ))
    elif not review_schema:
        findings.append(_f(
            code="reviews_not_structured", category="trust", display_category="trust",
            severity="low",
            title="Reviews are shown but not marked up as structured data",
            detail="Review wording appears on the site but no Review/AggregateRating structured "
                   "data was found, so ratings cannot show in search results.",
            deduction=5, evidence={},
            recommendation="Add Review/AggregateRating schema so star ratings can appear in search listings.",
        ))

    if not credential_hit:
        findings.append(_f(
            code="no_credentials", category="trust", display_category="trust",
            severity="medium",
            title="No licences, insurance, certifications or guarantees are mentioned",
            detail="No wording about being licensed, insured, certified, accredited, guaranteed or "
                   "award-winning was found on the crawled pages.",
            deduction=14, evidence={},
            recommendation="State the licences, insurance, accreditations or guarantee near the top of the "
                           "homepage - it is one of the cheapest trust wins available.",
        ))

    if not portfolio_hit:
        findings.append(_f(
            code="no_portfolio", category="trust", display_category="trust",
            severity="medium",
            title="No portfolio, gallery or case studies were found",
            detail="No 'our work', gallery, project or case-study content was detected.",
            deduction=12, evidence={},
            recommendation="Publish photos of recent work or a few short case studies with the outcome.",
        ))

    if "about" not in types:
        findings.append(_f(
            code="no_about_page", category="trust", display_category="trust",
            severity="low",
            title="No About page was found",
            detail="No page describing the business or its people was reachable from the homepage.",
            deduction=10, evidence={"pages_found": sorted(types)},
            recommendation="Add a short About page covering who runs the business and how long they have traded.",
        ))

    if not social:
        findings.append(_f(
            code="no_social_presence_linked", category="trust", display_category="trust",
            severity="low",
            title="No social media profiles are linked from the site",
            detail="No links to Facebook, Instagram, LinkedIn or similar were found.",
            deduction=6, evidence={},
            recommendation="Link the active social profiles so visitors can see recent activity.",
        ))

    return facts, findings


# ==========================================================================
# CONTACT ACCESSIBILITY
# ==========================================================================


def check_contact(crawl: CrawlResult, extracted: Any = None) -> tuple:
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    pages = crawl.pages
    home = crawl.homepage
    if home is None:
        return facts, findings

    text_all = _blob(pages)
    types = crawl.types_found()

    tel_anywhere = any(p.tel for p in pages)
    tel_home = bool(home.tel)
    mail_anywhere = any(p.mailto for p in pages)
    emails_found = len(getattr(extracted, "emails", []) or []) if extracted else 0

    addr_schema = any(jsonld_of_type(p, "LocalBusiness", "Organization", "PostalAddress") for p in pages)
    hours_hit = _any_word(text_all, HOURS_WORDS)
    hours_schema = any(
        "openinghours" in str(k).lower()
        for p in pages for b in p.jsonld for k in b.keys()
    )
    # A street address pattern, or address structured data.
    addr_pattern = bool(
        re.search(r"\b\d{1,5}\s+[A-Za-z][A-Za-z.\- ]{3,40}\s+(street|st|road|rd|avenue|ave|lane|ln|"
                  r"drive|dr|way|court|ct|boulevard|blvd|place|pl|parade|terrace)\b", text_all, re.I)
    )

    footer_has_contact = any(
        ("tel:" in (p.footer_html or "").lower() or "mailto:" in (p.footer_html or "").lower())
        for p in pages
    )
    header_has_contact = any(
        ("tel:" in (p.header_html or "").lower() or "mailto:" in (p.header_html or "").lower())
        for p in pages
    )

    facts.update({
        "phone_on_site": tel_anywhere,
        "phone_on_homepage": tel_home,
        "email_on_site": mail_anywhere,
        "public_emails_found": emails_found,
        "address_detected": addr_pattern or addr_schema,
        "address_structured_data": addr_schema,
        "opening_hours_detected": bool(hours_hit) or hours_schema,
        "contact_page": "contact" in types,
        "contact_in_header": header_has_contact,
        "contact_in_footer": footer_has_contact,
    })

    if not tel_anywhere:
        findings.append(_f(
            code="no_phone_on_site", category="contact", display_category="contact",
            severity="high",
            title="No phone number is published as a link on the website",
            detail=f"No tel: link was found on any of the {len(pages)} crawled pages.",
            deduction=30, evidence={"pages_crawled": len(pages)},
            recommendation="Publish the phone number as a tel: link in the header and footer of every page.",
        ))
    elif not tel_home:
        findings.append(_f(
            code="phone_not_on_homepage", category="contact", display_category="contact",
            severity="medium",
            title="The phone number is not linked on the homepage",
            detail="A tap-to-call link exists elsewhere on the site but not on the homepage, so most "
                   "visitors have to navigate before they can call.",
            deduction=15, evidence={},
            recommendation="Move the phone number into the homepage header where it is visible immediately.",
        ))

    if not mail_anywhere and emails_found == 0:
        findings.append(_f(
            code="no_email_on_site", category="contact", display_category="contact",
            severity="medium",
            title="No email address is published on the website",
            detail=f"No mailto: link or visible email address was found across {len(pages)} pages.",
            deduction=15, evidence={},
            recommendation="Publish a monitored business email address on the contact page.",
        ))

    if not facts["address_detected"]:
        findings.append(_f(
            code="no_address", category="contact", display_category="contact",
            severity="medium",
            title="No business address was found on the site",
            detail="No street address text or address structured data was detected on the crawled pages.",
            deduction=12, evidence={},
            recommendation="Publish the trading address (or service area) plus LocalBusiness structured data.",
        ))

    if not facts["opening_hours_detected"]:
        findings.append(_f(
            code="no_opening_hours", category="contact", display_category="contact",
            severity="low",
            title="No opening hours were found on the site",
            detail="No opening-hours wording or openingHours structured data was detected.",
            deduction=10, evidence={},
            recommendation="Publish opening hours on the contact page and in structured data.",
        ))

    if not (header_has_contact or footer_has_contact) and "contact" not in types:
        findings.append(_f(
            code="contact_hard_to_find", category="contact", display_category="contact",
            severity="high",
            title="Contact details are not reachable from the header, footer or a contact page",
            detail="No contact link was found in the site header or footer, and no contact page was "
                   "reachable from the homepage.",
            deduction=20, evidence={},
            recommendation="Put the phone number in the header, repeat contact details in the footer, and "
                           "link a dedicated contact page from the main navigation.",
        ))

    return facts, findings


# ==========================================================================
# CONTENT CLARITY
# ==========================================================================


def check_content(crawl: CrawlResult, category_hint: str = "") -> tuple:
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    home = crawl.homepage
    if home is None:
        return facts, findings

    pages = crawl.pages
    types = crawl.types_found()
    text_all = _blob(pages)

    facts["homepage_word_count"] = home.word_count
    facts["h2_count"] = len(home.h2)
    facts["pages_found"] = sorted(types)
    facts["services_page"] = "services" in types
    facts["nav_link_count"] = len({l.href for l in home.links if l.internal})

    if home.word_count < 120:
        findings.append(_f(
            code="very_thin_homepage", category="content", display_category="content",
            severity="high",
            title="The homepage has very little text",
            detail=f"The homepage contains about {home.word_count} words of readable text, which is "
                   f"not enough to explain the service or rank in search.",
            deduction=28, evidence={"word_count": home.word_count},
            recommendation="Expand the homepage to clearly cover the services, the area served and why "
                           "someone should choose this business.",
        ))
    elif home.word_count < 300:
        findings.append(_f(
            code="thin_homepage", category="content", display_category="content",
            severity="medium",
            title="The homepage content is thin",
            detail=f"The homepage contains about {home.word_count} words of readable text.",
            deduction=14, evidence={"word_count": home.word_count},
            recommendation="Add a section per main service with a short description and a call to action.",
        ))

    service_words = ["service", "services", "we offer", "we provide", "what we do", "our work",
                     "specialis", "specializ", "treatments", "products"]
    has_services = "services" in types or any(w in text_all for w in service_words)
    facts["services_described"] = has_services
    if not has_services:
        findings.append(_f(
            code="services_not_clear", category="content", display_category="content",
            severity="high",
            title="The services offered are not clearly presented",
            detail="No services page and no service wording was found on the crawled pages.",
            deduction=22, evidence={"pages_found": sorted(types)},
            recommendation="List the main services on the homepage, each with its own short section or page.",
        ))

    if not home.h1:
        facts["value_proposition"] = ""
    else:
        facts["value_proposition"] = home.h1[0]
        generic_h1 = home.h1[0].strip().lower() in {
            "home", "welcome", "welcome to our website", "homepage", "untitled",
        }
        if generic_h1:
            findings.append(_f(
                code="generic_value_proposition", category="content", display_category="content",
                severity="medium",
                title="The main heading does not say what the business does",
                detail=f'The homepage H1 is "{home.h1[0]}", which does not state the service or the area.',
                deduction=12, evidence={"h1": home.h1[0]},
                recommendation="Rewrite the H1 as service + area, for example "
                               "\"Emergency plumbing in <city>, 24/7\".",
            ))

    area_hit = _any_word(text_all, SERVICE_AREA_WORDS)
    facts["service_area_detected"] = bool(area_hit) or "locations" in types
    if not facts["service_area_detected"]:
        findings.append(_f(
            code="no_service_area", category="content", display_category="content",
            severity="low",
            title="The service area is not stated",
            detail="No 'areas we serve' wording or locations page was found.",
            deduction=10, evidence={},
            recommendation="State the towns or radius covered - it helps both visitors and local search.",
        ))

    if len(home.h2) == 0 and home.word_count > 200:
        findings.append(_f(
            code="no_heading_structure", category="content", display_category="content",
            severity="low",
            title="The homepage has no subheadings",
            detail=f"The homepage has {home.word_count} words but no H2 headings, so the content is "
                   f"one undifferentiated block.",
            deduction=8, evidence={"word_count": home.word_count},
            recommendation="Break the page into sections with descriptive H2 subheadings.",
        ))

    nav = facts["nav_link_count"]
    if nav < 3:
        findings.append(_f(
            code="minimal_navigation", category="content", display_category="content",
            severity="medium",
            title="The site has almost no internal navigation",
            detail=f"Only {nav} distinct internal link(s) were found on the homepage.",
            deduction=12, evidence={"internal_links": nav},
            recommendation="Add a navigation menu covering services, about and contact.",
        ))

    return facts, findings


# ==========================================================================
# NO-WEBSITE case (spec 52)
# ==========================================================================


def no_website_findings(reason: str, social_url: str = "") -> List[Finding]:
    """
    Findings for a business we verified has no usable website. This never
    pretends a site was audited.
    """
    if social_url:
        return [_f(
            code="social_profile_only", category="conversion", display_category="conversion",
            severity="high",
            title="The business appears to rely on a social or directory profile instead of a website",
            detail=f"The listed web address is {social_url}, which is a third-party profile rather "
                   f"than a site the business controls.",
            deduction=0,
            evidence={"profile_url": social_url, "checked": reason},
            recommendation="A small owned website would let them rank in search, publish services and "
                           "prices, and capture enquiries directly.",
        )]
    return [_f(
        code="no_website_detected", category="conversion", display_category="conversion",
        severity="high",
        title="No website could be found for this business",
        detail=reason,
        deduction=0,
        evidence={"checked": reason},
        recommendation="A simple website covering services, area, proof and one clear contact action "
                       "would give them a presence they own.",
    )]


# ==========================================================================
# SECURITY  (new, additive category - independent of the legacy `technical`
# bucket above, so it never changes existing opportunity-scoring behaviour)
# ==========================================================================

_SERVER_VERSION_RE = re.compile(r"[/ ]\d+\.\d+")


def check_security(crawl: CrawlResult) -> tuple:
    home = crawl.homepage
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    if home is None:
        return facts, findings

    headers = {k.lower(): v for k, v in (crawl.home_headers or {}).items()}
    facts["is_https"] = crawl.is_https
    facts["headers_measured"] = bool(headers)
    facts["hsts_present"] = "strict-transport-security" in headers
    facts["csp_present"] = "content-security-policy" in headers
    facts["x_content_type_options"] = headers.get("x-content-type-options", "")
    facts["x_frame_options"] = headers.get("x-frame-options", "")
    facts["referrer_policy_present"] = "referrer-policy" in headers
    facts["permissions_policy_present"] = "permissions-policy" in headers
    facts["server_header"] = headers.get("server", "")

    if not headers:
        facts["note"] = (
            "Response headers were not available for this fetch, so header-based security checks "
            "could not run."
        )
        return facts, findings

    if crawl.is_https and not facts["hsts_present"]:
        findings.append(_f(
            code="security_hsts_missing", category="security", display_category="security",
            severity="medium",
            title="No HTTP Strict-Transport-Security header",
            detail="The homepage is served over HTTPS but did not send a Strict-Transport-Security "
                   "header, so browsers are not told to always use HTTPS for this site.",
            deduction=12, evidence={"checked_header": "Strict-Transport-Security"},
            recommendation="Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains' "
                           "once HTTPS is confirmed working on every subdomain.",
        ))

    frame_protected = bool(facts["x_frame_options"]) or "frame-ancestors" in (
        headers.get("content-security-policy", "").lower()
    )
    if not frame_protected:
        findings.append(_f(
            code="security_frame_protection_missing", category="security", display_category="security",
            severity="medium",
            title="No clickjacking protection header",
            detail="Neither an X-Frame-Options header nor a Content-Security-Policy with "
                   "frame-ancestors was found, so the page could potentially be embedded in a "
                   "hidden frame on another site.",
            deduction=10,
            evidence={"checked_headers": ["X-Frame-Options", "Content-Security-Policy: frame-ancestors"]},
            recommendation="Add 'X-Frame-Options: SAMEORIGIN' or a CSP frame-ancestors directive.",
        ))

    if not facts["csp_present"]:
        findings.append(_f(
            code="security_csp_missing", category="security", display_category="security",
            severity="low",
            title="No Content-Security-Policy header",
            detail="No Content-Security-Policy header was found. CSP is the strongest available "
                   "browser-level defence against cross-site scripting and unauthorised resource "
                   "loading.",
            deduction=6, evidence={},
            recommendation="Introduce a Content-Security-Policy, starting in report-only mode if needed.",
        ))

    if facts["x_content_type_options"].lower() != "nosniff":
        findings.append(_f(
            code="security_xcto_missing", category="security", display_category="security",
            severity="low",
            title="No X-Content-Type-Options header",
            detail="The response did not send 'X-Content-Type-Options: nosniff', so some browsers "
                   "may try to guess ('sniff') a file's type instead of trusting the declared one.",
            deduction=5, evidence={},
            recommendation="Add 'X-Content-Type-Options: nosniff' to every response.",
        ))

    if not facts["referrer_policy_present"]:
        findings.append(_f(
            code="security_referrer_policy_missing", category="security", display_category="security",
            severity="low",
            title="No Referrer-Policy header",
            detail="No Referrer-Policy header was found, so the browser's default behaviour applies, "
                   "which can leak the full page URL to third-party sites linked from this page.",
            deduction=4, evidence={},
            recommendation="Add 'Referrer-Policy: strict-origin-when-cross-origin' (a safe modern default).",
        ))

    server = facts["server_header"]
    if server and _SERVER_VERSION_RE.search(server):
        findings.append(_f(
            code="security_server_header_discloses_version", category="security", display_category="security",
            severity="low",
            title="The server header discloses software version details",
            detail=f'The Server response header is "{server}", which names the exact software '
                   f"version in use and can help an attacker target known vulnerabilities.",
            deduction=4, evidence={"server_header": server},
            recommendation="Configure the web server to omit or generalise the Server header.",
        ))

    return facts, findings


# ==========================================================================
# ACCESSIBILITY  (new, additive category)
# ==========================================================================


def check_accessibility(crawl: CrawlResult) -> tuple:
    home = crawl.homepage
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    if home is None:
        return facts, findings

    facts["has_main_landmark"] = home.has_main_landmark
    facts["has_nav_landmark"] = home.has_nav_landmark
    facts["has_skip_link"] = home.has_skip_link
    facts["lang_declared"] = bool(home.lang)
    facts["contrast"] = "not_measured"
    facts["contrast_note"] = (
        "Colour contrast requires a rendered page and computed styles; it cannot be measured "
        "reliably from static HTML/CSS, so it is reported as not measured rather than guessed."
    )

    total_inputs = sum(fm.labelled_inputs + fm.unlabelled_inputs for p in crawl.pages for fm in p.forms)
    unlabelled = sum(fm.unlabelled_inputs for p in crawl.pages for fm in p.forms)
    facts["form_inputs_checked"] = total_inputs
    facts["unlabelled_form_inputs"] = unlabelled

    empty_links = sum(p.empty_link_count for p in crawl.pages)
    facts["empty_links"] = empty_links

    if not home.has_main_landmark:
        findings.append(_f(
            code="a11y_no_main_landmark", category="accessibility", display_category="accessibility",
            severity="low",
            title="No <main> landmark on the homepage",
            detail='No <main> element or role="main" was found, which screen reader users rely on '
                   "to jump straight to the primary content.",
            deduction=6, evidence={},
            recommendation="Wrap the primary content in a <main> element.",
        ))

    if total_inputs > 0 and unlabelled > 0:
        findings.append(_f(
            code="a11y_unlabelled_form_inputs", category="accessibility", display_category="accessibility",
            severity="medium" if unlabelled >= 2 else "low",
            title=f"{unlabelled} form field{'s' if unlabelled != 1 else ''} have no associated label",
            detail=f"Of {total_inputs} form field(s) checked across {len(crawl.pages)} crawled "
                   f"pages, {unlabelled} have no <label>, aria-label or aria-labelledby, so screen "
                   f"reader users cannot tell what to enter.",
            deduction=min(16, 6 + 4 * unlabelled),
            evidence={"unlabelled": unlabelled, "checked": total_inputs},
            recommendation='Associate every input with a <label for="..."> (or aria-label) naming '
                           "the field.",
        ))

    if empty_links > 0:
        findings.append(_f(
            code="a11y_empty_links", category="accessibility", display_category="accessibility",
            severity="low",
            title=f"{empty_links} link{'s' if empty_links != 1 else ''} with no accessible text",
            detail=f"{empty_links} link(s) across {len(crawl.pages)} crawled pages have no visible "
                   f"text, aria-label or alt text on an image inside them, so a screen reader "
                   f'announces them as just "link".',
            deduction=min(10, 3 * empty_links),
            evidence={"count": empty_links},
            recommendation="Add descriptive link text or an aria-label to every link, especially "
                           "icon-only links.",
        ))

    if home.h3 and not home.h2:
        findings.append(_f(
            code="a11y_heading_order_skipped", category="accessibility", display_category="accessibility",
            severity="low",
            title="Heading levels skip from H1 to H3",
            detail="The homepage uses H3 headings with no H2 in between, which breaks the logical "
                   "outline screen reader users navigate by.",
            deduction=5, evidence={"h3_count": len(home.h3)},
            recommendation="Use heading levels in order (H1 -> H2 -> H3) without skipping a level.",
        ))

    return facts, findings


# ==========================================================================
# ON-PAGE SEO EXTRAS  (new, additive category - complements the title/meta/
# H1/alt signals already measured in check_technical above)
# ==========================================================================


def check_onpage(crawl: CrawlResult) -> tuple:
    home = crawl.homepage
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    if home is None:
        return facts, findings

    facts["open_graph_tags"] = sorted(home.og.keys())
    facts["twitter_card_tags"] = sorted(home.twitter.keys())
    facts["hreflang_count"] = len(home.hreflang)
    facts["hreflang_languages"] = sorted({h["lang"] for h in home.hreflang})
    facts["schema_types_found"] = sorted({t for p in crawl.pages for t in p.schema_types})

    if not home.og.get("title") and not home.og.get("description"):
        findings.append(_f(
            code="onpage_missing_open_graph", category="onpage", display_category="onpage",
            severity="medium",
            title="No Open Graph tags on the homepage",
            detail="No og:title or og:description meta tags were found, so links shared on "
                   "Facebook, LinkedIn and most chat apps will show a blank or generic preview.",
            deduction=10, evidence={},
            recommendation="Add og:title, og:description and og:image so shared links preview correctly.",
        ))

    if not home.twitter.get("card"):
        findings.append(_f(
            code="onpage_missing_twitter_card", category="onpage", display_category="onpage",
            severity="low",
            title="No Twitter/X card meta tag",
            detail="No twitter:card meta tag was found, so links shared on X/Twitter fall back to a "
                   "plain link instead of a rich preview.",
            deduction=4, evidence={},
            recommendation="Add twitter:card (summary_large_image works well), twitter:title and twitter:image.",
        ))

    titles = [p.title.strip().lower() for p in crawl.pages if p.title.strip()]
    dup_titles = {t for t in titles if titles.count(t) > 1}
    if dup_titles:
        findings.append(_f(
            code="onpage_duplicate_titles", category="onpage", display_category="onpage",
            severity="medium",
            title="Multiple crawled pages share the same title tag",
            detail=f"{len(dup_titles)} title(s) are reused across more than one crawled page, which "
                   f"makes it harder for search engines to tell the pages apart.",
            deduction=10, evidence={"examples": list(dup_titles)[:3]},
            recommendation="Give every page a unique, descriptive title.",
        ))

    descs = [p.meta_description.strip().lower() for p in crawl.pages if p.meta_description.strip()]
    dup_descs = {d for d in descs if descs.count(d) > 1}
    if dup_descs:
        findings.append(_f(
            code="onpage_duplicate_meta_description", category="onpage", display_category="onpage",
            severity="low",
            title="Multiple crawled pages share the same meta description",
            detail=f"{len(dup_descs)} meta description(s) are reused across more than one crawled page.",
            deduction=5, evidence={"examples": [d[:120] for d in list(dup_descs)[:2]]},
            recommendation="Write a unique meta description for every page.",
        ))

    return facts, findings


# ==========================================================================
# OFF-PAGE / AUTHORITY  (new, additive category)
#
# Backlink counts, referring domains and domain-authority-style scores all
# require a paid third-party index (Ahrefs / Moz / Majestic / SEMrush). None
# is integrated, so none of that is measured, guessed or estimated here - it
# is reported as explicitly unavailable, the same pattern already used by the
# optional PageSpeed integration.
# ==========================================================================


def check_offpage(crawl: CrawlResult) -> tuple:
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    pages = crawl.pages
    if not pages:
        return facts, findings

    social = sorted({s for p in pages for s in p.social_links})
    same_as: List[str] = []
    for p in pages:
        for block in p.jsonld:
            sa = block.get("sameAs")
            if isinstance(sa, str):
                same_as.append(sa)
            elif isinstance(sa, list):
                same_as.extend(str(x) for x in sa if isinstance(x, str))
    same_as = sorted(set(same_as))[:20]

    external_domains = sorted({
        registrable_domain(u) for p in pages for u in p.external_links if registrable_domain(u)
    })[:30]

    facts["social_profiles_linked"] = social
    facts["structured_data_sameas"] = same_as
    facts["external_domains_referenced"] = external_domains
    facts["external_domains_referenced_count"] = len(external_domains)

    facts["backlinks"] = {
        "measured": False,
        "reason": "No backlink index (e.g. Ahrefs, Moz, Majestic, SEMrush) is configured. Backlink "
                  "counts are never estimated or fabricated.",
    }
    facts["referring_domains"] = {
        "measured": False,
        "reason": "Same as backlinks - requires a paid third-party index that is not configured.",
    }
    facts["domain_authority"] = {
        "measured": False,
        "reason": "Domain authority-style scores (Moz DA, Ahrefs DR, etc.) are proprietary to each "
                  "vendor and are never approximated here.",
    }

    if not social and not same_as:
        findings.append(_f(
            code="offpage_no_social_profiles", category="offpage", display_category="offpage",
            severity="low",
            title="No social media profiles are linked from the site",
            detail="No links to Facebook, Instagram, LinkedIn, X or similar were found on the "
                   "crawled pages, and no sameAs structured data points to any.",
            deduction=8, evidence={"pages_checked": len(pages)},
            recommendation="Link active social profiles from the site and add them as sameAs entries "
                           "in Organization/LocalBusiness structured data.",
        ))
    elif social and not same_as:
        findings.append(_f(
            code="offpage_sameas_not_structured", category="offpage", display_category="offpage",
            severity="low",
            title="Social profiles are linked but not declared as structured data",
            detail="Social links were found on the page, but no sameAs entries in Organization/"
                   "LocalBusiness structured data connect them to the business entity.",
            deduction=4, evidence={"social_links": social[:5]},
            recommendation='Add the social profile URLs as "sameAs" in your Organization/'
                           "LocalBusiness JSON-LD so search engines can connect them to the business.",
        ))

    return facts, findings


# ==========================================================================
# PERFORMANCE EXTRAS  (new, additive category - complements the response-time
# and page-weight signals already measured in check_technical above)
# ==========================================================================


def check_performance_extra(crawl: CrawlResult) -> tuple:
    home = crawl.homepage
    findings: List[Finding] = []
    facts: Dict[str, Any] = {}
    if home is None:
        return facts, findings

    headers = {k.lower(): v for k, v in (crawl.home_headers or {}).items()}
    facts["render_blocking_scripts"] = home.render_blocking_scripts
    facts["stylesheet_count"] = len(home.stylesheets)
    facts["content_encoding"] = headers.get("content-encoding", "")
    facts["cache_control"] = headers.get("cache-control", "")
    facts["note"] = (
        "Asset weight here counts requests and response headers only; it does not download every "
        "image, script and stylesheet, so it is not a full byte-for-byte page-weight measurement."
    )

    if home.render_blocking_scripts > 4:
        findings.append(_f(
            code="perf_render_blocking_scripts", category="performance", display_category="performance",
            severity="medium",
            title="Several render-blocking scripts load before the page can render",
            detail=f"{home.render_blocking_scripts} <script> tag(s) with a src attribute and neither "
                   f"async nor defer were found, which can delay when the page becomes visible.",
            deduction=10, evidence={"count": home.render_blocking_scripts},
            recommendation="Add defer (or async, if order does not matter) to non-critical scripts, "
                           "or move them to the end of the page.",
        ))

    if headers and not facts["content_encoding"]:
        findings.append(_f(
            code="perf_no_compression", category="performance", display_category="performance",
            severity="medium",
            title="The homepage response is not compressed",
            detail="No Content-Encoding header (gzip/br) was found on the homepage response, so the "
                   "page transfers larger than it needs to.",
            deduction=8, evidence={"headers_checked": "Content-Encoding"},
            recommendation="Enable gzip or Brotli compression on the web server.",
        ))

    if headers and (not facts["cache_control"] or "no-store" in facts["cache_control"].lower()):
        findings.append(_f(
            code="perf_no_cache_headers", category="performance", display_category="performance",
            severity="low",
            title="No caching guidance in the response headers",
            detail="No usable Cache-Control header was found on the homepage response, so repeat "
                   "visits may re-download content unnecessarily.",
            deduction=4, evidence={"cache_control": facts["cache_control"]},
            recommendation="Add Cache-Control headers appropriate to each asset type.",
        ))

    return facts, findings


def run_extra_checks(crawl: CrawlResult) -> tuple:
    """
    Additive premium checks: security, accessibility, on-page extras,
    off-page/authority, performance extras. Kept entirely separate from
    `run_all_checks`'s six legacy categories so existing opportunity-scoring
    and outreach-tiering behaviour is unchanged; these feed the premium audit
    scorecard only (see scoring.build_scorecard).
    """
    facts: Dict[str, Dict[str, Any]] = {}
    findings: List[Finding] = []

    for name, fn in (
        ("security", check_security),
        ("accessibility", check_accessibility),
        ("onpage", check_onpage),
        ("offpage", check_offpage),
        ("performance_extra", check_performance_extra),
    ):
        try:
            f, fi = fn(crawl)
        except Exception as exc:  # a broken check must not kill the audit
            f, fi = {"error": f"{type(exc).__name__}: {exc}"}, []
        facts[name] = f
        findings.extend(fi)

    return facts, findings


# ==========================================================================


def run_all_checks(
    crawl: CrawlResult,
    *,
    extracted: Any = None,
    perf: Optional[Dict[str, Any]] = None,
    category_hint: str = "",
) -> tuple:
    """Returns (facts_by_category, all_findings)."""
    facts: Dict[str, Dict[str, Any]] = {}
    findings: List[Finding] = []

    for name, fn, args in (
        ("technical", check_technical, (crawl, perf)),
        ("mobile", check_mobile, (crawl,)),
        ("conversion", check_conversion, (crawl,)),
        ("trust", check_trust, (crawl,)),
        ("contact", check_contact, (crawl, extracted)),
        ("content", check_content, (crawl, category_hint)),
    ):
        try:
            f, fi = fn(*args)
        except Exception as exc:  # a broken check must not kill the audit
            f, fi = {"error": f"{type(exc).__name__}: {exc}"}, []
        facts[name] = f
        findings.extend(fi)

    return facts, findings
