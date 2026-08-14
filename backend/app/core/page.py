"""HTML parsing into a structured page model, plus page-type classification."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from selectolax.parser import HTMLParser

from .urls import absolutize, same_site, url_key


@dataclass
class Link:
    href: str
    text: str = ""
    rel: str = ""
    internal: bool = False
    raw_href: str = ""


@dataclass
class FormInfo:
    action: str = ""
    method: str = "get"
    input_types: List[str] = field(default_factory=list)
    input_names: List[str] = field(default_factory=list)
    has_email_field: bool = False
    has_phone_field: bool = False
    has_message_field: bool = False
    submit_text: str = ""
    is_search: bool = False
    is_newsletter: bool = False
    labelled_inputs: int = 0
    unlabelled_inputs: int = 0


@dataclass
class ParsedPage:
    url: str
    final_url: str = ""
    status: Optional[int] = None
    page_type: str = "other"
    depth: int = 0
    elapsed_ms: int = 0
    bytes_len: int = 0

    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    canonical: str = ""
    viewport: str = ""
    lang: str = ""
    charset: str = ""

    h1: List[str] = field(default_factory=list)
    h2: List[str] = field(default_factory=list)
    h3: List[str] = field(default_factory=list)

    text: str = ""
    text_length: int = 0
    word_count: int = 0

    links: List[Link] = field(default_factory=list)
    internal_links: List[str] = field(default_factory=list)
    external_links: List[str] = field(default_factory=list)

    mailto: List[str] = field(default_factory=list)
    tel: List[str] = field(default_factory=list)
    whatsapp_links: List[str] = field(default_factory=list)
    social_links: List[str] = field(default_factory=list)

    images_total: int = 0
    images_with_alt: int = 0
    images_missing_alt_examples: List[str] = field(default_factory=list)

    forms: List[FormInfo] = field(default_factory=list)
    scripts: List[str] = field(default_factory=list)
    stylesheets: List[str] = field(default_factory=list)
    inline_style_blocks: List[str] = field(default_factory=list)

    jsonld: List[Dict[str, Any]] = field(default_factory=list)
    html_len: int = 0
    raw_html: str = ""

    # header / footer / above-the-fold slices, used by the conversion audit
    header_html: str = ""
    footer_html: str = ""
    above_fold_text: str = ""
    above_fold_html: str = ""

    buttons: List[str] = field(default_factory=list)
    iframes: List[str] = field(default_factory=list)
    has_noscript_only: bool = False
    mixed_content: List[str] = field(default_factory=list)

    # -- premium audit signals (additive; used by the extra check functions) --
    og: Dict[str, str] = field(default_factory=dict)
    twitter: Dict[str, str] = field(default_factory=dict)
    hreflang: List[Dict[str, str]] = field(default_factory=list)
    has_main_landmark: bool = False
    has_nav_landmark: bool = False
    has_skip_link: bool = False
    render_blocking_scripts: int = 0
    empty_link_count: int = 0
    schema_types: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Page type classification
# --------------------------------------------------------------------------

PAGE_TYPE_PATTERNS: List[Tuple[str, List[str]]] = [
    ("contact", ["contact", "kontakt", "contacto", "contactez", "get-in-touch", "getintouch",
                 "reach-us", "reachus", "enquiry", "enquire", "inquiry", "contact-us"]),
    ("booking", ["book", "booking", "appointment", "appointments", "schedule", "reserve",
                 "reservation", "book-now", "book-online", "make-appointment", "buchen"]),
    ("about", ["about", "about-us", "aboutus", "who-we-are", "our-story", "company",
               "ueber-uns", "sobre", "notre-histoire"]),
    ("team", ["team", "our-team", "staff", "people", "meet-the-team", "our-people",
              "practitioners", "doctors", "stylists", "therapists"]),
    ("services", ["service", "services", "what-we-do", "treatments", "solutions",
                  "offerings", "products", "menu", "our-work", "specialties", "leistungen"]),
    ("pricing", ["pricing", "prices", "price-list", "rates", "packages", "plans", "cost",
                 "fees", "tariff"]),
    ("testimonials", ["testimonial", "testimonials", "reviews", "review", "feedback",
                      "client-stories", "case-studies", "case-study", "portfolio", "gallery",
                      "our-work", "projects"]),
    ("locations", ["location", "locations", "areas-we-serve", "service-area", "service-areas",
                   "find-us", "branches", "stores", "coverage", "where-we-work"]),
    ("quote", ["quote", "get-a-quote", "request-quote", "free-quote", "estimate",
               "free-estimate", "request-estimate"]),
]

_SKIP_PATTERNS = [
    "privacy", "terms", "cookie", "gdpr", "disclaimer", "sitemap.xml", "/tag/", "/tags/",
    "/author/", "/category/", "/wp-admin", "/wp-login", "/cart", "/checkout", "/account",
    "/login", "/signin", "/register", "/feed", "?add-to-cart", "/wp-json",
]

# Crawl priority - lower sorts first (spec 8).
PAGE_PRIORITY = {
    "homepage": 0, "contact": 1, "about": 2, "services": 3, "booking": 4, "team": 5,
    "testimonials": 6, "pricing": 7, "locations": 8, "quote": 9, "other": 20,
}


def classify_page(url: str, link_text: str = "", is_home: bool = False) -> str:
    if is_home:
        return "homepage"
    haystack = f"{url.lower()} {link_text.lower()}"
    path = re.sub(r"^https?://[^/]+", "", url.lower())
    if path in ("", "/"):
        return "homepage"
    for ptype, keys in PAGE_TYPE_PATTERNS:
        for k in keys:
            if k in path or re.search(rf"\b{re.escape(k.replace('-', ' '))}\b", link_text.lower()):
                return ptype
    if any(k in haystack for k in ("blog", "news", "article", "post")):
        return "blog"
    return "other"


def should_skip_url(url: str) -> bool:
    low = url.lower()
    return any(p in low for p in _SKIP_PATTERNS)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_MAILTO_RE = re.compile(r"^mailto:([^?]+)", re.I)
_TEL_RE = re.compile(r"^(?:tel|callto):(.+)$", re.I)
_WA_RE = re.compile(r"(wa\.me/|api\.whatsapp\.com|web\.whatsapp\.com|whatsapp://)", re.I)
_SOCIAL_RE = re.compile(
    r"(facebook\.com|instagram\.com|twitter\.com|x\.com|linkedin\.com|youtube\.com|"
    r"tiktok\.com|pinterest\.com)",
    re.I,
)

_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")


def _clean_text(node) -> str:
    if node is None:
        return ""
    try:
        txt = node.text(separator=" ", strip=True)
    except Exception:
        return ""
    return _WS.sub(" ", txt or "").strip()


def parse_html(
    html: str,
    url: str,
    *,
    final_url: str = "",
    status: Optional[int] = None,
    depth: int = 0,
    page_type: str = "other",
    elapsed_ms: int = 0,
    bytes_len: int = 0,
    keep_html: bool = False,
) -> ParsedPage:
    page = ParsedPage(
        url=url,
        final_url=final_url or url,
        status=status,
        depth=depth,
        page_type=page_type,
        elapsed_ms=elapsed_ms,
        bytes_len=bytes_len,
        html_len=len(html or ""),
    )
    if not html:
        return page

    base = page.final_url
    try:
        tree = HTMLParser(html)
    except Exception:
        return page

    if keep_html:
        page.raw_html = html

    # -- head --------------------------------------------------------------
    if tree.head:
        t = tree.head.css_first("title")
        page.title = _clean_text(t)[:500]
        for meta in tree.head.css("meta"):
            name = (meta.attributes.get("name") or "").lower()
            prop = (meta.attributes.get("property") or "").lower()
            content = (meta.attributes.get("content") or "").strip()
            if name == "description" and not page.meta_description:
                page.meta_description = content[:1000]
            elif prop == "og:description" and not page.meta_description:
                page.meta_description = content[:1000]
            elif name == "robots":
                page.meta_robots = content.lower()
            elif name == "viewport":
                page.viewport = content.lower()
            if meta.attributes.get("charset"):
                page.charset = meta.attributes["charset"]
            if prop.startswith("og:") and content:
                page.og.setdefault(prop[3:], content[:500])
            if name.startswith("twitter:") and content:
                page.twitter.setdefault(name[8:], content[:500])
        can = tree.head.css_first('link[rel="canonical"]')
        if can:
            page.canonical = (can.attributes.get("href") or "").strip()
        for link in tree.head.css('link[rel="stylesheet"]'):
            href = link.attributes.get("href")
            if href:
                page.stylesheets.append(href)
        for link in tree.head.css('link[rel="alternate"]'):
            hl = (link.attributes.get("hreflang") or "").strip()
            href = (link.attributes.get("href") or "").strip()
            if hl and href and len(page.hreflang) < 30:
                page.hreflang.append({"lang": hl, "href": href})

    html_node = tree.css_first("html")
    if html_node:
        page.lang = (html_node.attributes.get("lang") or "").strip()

    # -- structured data ---------------------------------------------------
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text(strip=True) if node.text() else ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            page.jsonld.extend([d for d in data if isinstance(d, dict)])
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                page.jsonld.extend([d for d in data["@graph"] if isinstance(d, dict)])
            else:
                page.jsonld.append(data)
    for block in page.jsonld:
        t = block.get("@type") or block.get("type")
        for name in (t if isinstance(t, list) else [t]):
            if name and str(name) not in page.schema_types:
                page.schema_types.append(str(name))

    # -- scripts / inline styles ------------------------------------------
    for node in tree.css("script"):
        src = node.attributes.get("src")
        if src:
            page.scripts.append(src)
            # Boolean attributes (async/defer with no value) come through as a
            # present key mapped to None, so presence must be checked with
            # `in`, not by testing the value.
            has_async = "async" in node.attributes
            has_defer = "defer" in node.attributes
            script_type = (node.attributes.get("type") or "").lower()
            if not has_async and not has_defer and script_type not in ("module", "application/json", "application/ld+json"):
                page.render_blocking_scripts += 1
    for node in tree.css("style"):
        block = node.text() or ""
        if block:
            page.inline_style_blocks.append(block[:20000])
    for node in tree.css("iframe"):
        src = node.attributes.get("src") or ""
        if src:
            page.iframes.append(src)

    # -- mixed content (https page loading http assets) --------------------
    if page.final_url.startswith("https://"):
        for attr_list in (page.scripts, page.stylesheets, page.iframes):
            for src in attr_list:
                if src.startswith("http://"):
                    page.mixed_content.append(src)
        for img in tree.css("img"):
            src = img.attributes.get("src") or ""
            if src.startswith("http://"):
                page.mixed_content.append(src)
        page.mixed_content = page.mixed_content[:20]

    # -- headings ----------------------------------------------------------
    page.h1 = [_clean_text(n)[:300] for n in tree.css("h1") if _clean_text(n)]
    page.h2 = [_clean_text(n)[:300] for n in tree.css("h2") if _clean_text(n)][:40]
    page.h3 = [_clean_text(n)[:300] for n in tree.css("h3") if _clean_text(n)][:40]

    # -- images ------------------------------------------------------------
    for img in tree.css("img"):
        page.images_total += 1
        alt = img.attributes.get("alt")
        if alt is not None and alt.strip():
            page.images_with_alt += 1
        elif len(page.images_missing_alt_examples) < 5:
            src = img.attributes.get("src") or img.attributes.get("data-src") or ""
            if src:
                page.images_missing_alt_examples.append(src[:200])

    # -- links -------------------------------------------------------------
    seen_links: set = set()
    for a in tree.css("a"):
        raw_href = (a.attributes.get("href") or "").strip()
        if not raw_href:
            continue
        text = _clean_text(a)[:200]
        rel = (a.attributes.get("rel") or "").lower()

        if not text and not a.attributes.get("aria-label") and not a.attributes.get("title"):
            has_alt_img = any((img.attributes.get("alt") or "").strip() for img in a.css("img"))
            if not has_alt_img:
                page.empty_link_count += 1

        m = _MAILTO_RE.match(raw_href)
        if m:
            addr = m.group(1).strip().replace("%20", "").lower()
            if addr and addr not in page.mailto:
                page.mailto.append(addr)
            continue
        m = _TEL_RE.match(raw_href)
        if m:
            num = m.group(1).strip()
            if num and num not in page.tel:
                page.tel.append(num)
            continue
        if _WA_RE.search(raw_href):
            if raw_href not in page.whatsapp_links:
                page.whatsapp_links.append(raw_href)
            continue
        if _SOCIAL_RE.search(raw_href):
            if raw_href not in page.social_links and len(page.social_links) < 20:
                page.social_links.append(raw_href)

        abs_url = absolutize(base, raw_href)
        if not abs_url:
            continue
        internal = same_site(base, abs_url)
        key = url_key(abs_url)
        link = Link(href=abs_url, text=text, rel=rel, internal=internal, raw_href=raw_href)
        page.links.append(link)
        if key in seen_links:
            continue
        seen_links.add(key)
        if internal:
            page.internal_links.append(abs_url)
        elif len(page.external_links) < 60:
            page.external_links.append(abs_url)

    # -- buttons -----------------------------------------------------------
    for b in tree.css("button, input[type=submit], [role=button], .btn, .button"):
        label = _clean_text(b) or (b.attributes.get("value") or "")
        label = label.strip()
        if label and label not in page.buttons and len(page.buttons) < 60:
            page.buttons.append(label[:120])

    # -- forms -------------------------------------------------------------
    label_for_ids = {
        lbl.attributes["for"] for lbl in tree.css("label") if lbl.attributes.get("for")
    }
    for form in tree.css("form"):
        info = FormInfo(
            action=(form.attributes.get("action") or "").strip(),
            method=(form.attributes.get("method") or "get").lower(),
        )
        blob = f"{info.action} {form.attributes.get('id','')} {form.attributes.get('class','')}".lower()
        for inp in form.css("input, textarea, select"):
            itype = (inp.attributes.get("type") or inp.tag or "text").lower()
            if itype in ("hidden", "submit", "button", "image"):
                continue
            iname = (inp.attributes.get("name") or inp.attributes.get("id") or "").lower()
            ph = (inp.attributes.get("placeholder") or "").lower()
            info.input_types.append(itype)
            if iname:
                info.input_names.append(iname)

            iid = inp.attributes.get("id")
            has_label = bool(
                (iid and iid in label_for_ids)
                or inp.attributes.get("aria-label")
                or inp.attributes.get("aria-labelledby")
                or inp.attributes.get("title")
            )
            if not has_label:
                anc = inp.parent
                for _ in range(3):
                    if anc is None:
                        break
                    if anc.tag == "label":
                        has_label = True
                        break
                    anc = anc.parent
            if has_label:
                info.labelled_inputs += 1
            else:
                info.unlabelled_inputs += 1

            probe = f"{itype} {iname} {ph}"
            if itype == "email" or "email" in probe or "mail" in probe:
                info.has_email_field = True
            if itype == "tel" or any(k in probe for k in ("phone", "tel", "mobile", "number")):
                info.has_phone_field = True
            if inp.tag == "textarea" or any(
                k in probe for k in ("message", "comment", "enquiry", "inquiry", "detail", "describe")
            ):
                info.has_message_field = True
        sub = form.css_first("button, input[type=submit]")
        if sub is not None:
            info.submit_text = (_clean_text(sub) or sub.attributes.get("value") or "")[:120]
        info.is_search = "search" in blob or any(
            "search" in n or n == "q" or n == "s" for n in info.input_names
        )
        info.is_newsletter = any(
            k in f"{blob} {info.submit_text.lower()}"
            for k in ("newsletter", "subscribe", "mailchimp", "signup-form", "mc4wp")
        )
        page.forms.append(info)

    # -- header / footer / above-the-fold ---------------------------------
    header = tree.css_first("header") or tree.css_first("#header") or tree.css_first(".header")
    if header is not None:
        page.header_html = (header.html or "")[:60000]
    footer = tree.css_first("footer") or tree.css_first("#footer") or tree.css_first(".footer")
    if footer is not None:
        page.footer_html = (footer.html or "")[:60000]

    # -- semantic landmarks (accessibility) --------------------------------
    page.has_main_landmark = bool(
        tree.css_first("main") or tree.css_first('[role="main"]')
    )
    page.has_nav_landmark = bool(
        tree.css_first("nav") or tree.css_first('[role="navigation"]')
    )
    for a in tree.css("a[href^='#']"):
        t = _clean_text(a).lower()
        if "skip" in t and ("content" in t or "main" in t or "navigation" in t):
            page.has_skip_link = True
            break

    body = tree.body
    if body is not None:
        for tag in _DROP_TAGS:
            for node in body.css(tag):
                node.decompose()
        page.text = _clean_text(body)
        # "Above the fold" approximated as header + the first slice of body
        # markup. Labelled as an approximation everywhere it is reported.
        page.above_fold_html = (page.header_html or "") + (body.html or "")[:18000]
        page.above_fold_text = page.text[:1600]

    page.text_length = len(page.text)
    page.word_count = len(page.text.split())
    page.has_noscript_only = page.word_count < 30 and len(page.scripts) > 3
    return page


def jsonld_of_type(page: ParsedPage, *types: str) -> List[Dict[str, Any]]:
    wanted = {t.lower() for t in types}
    out = []
    for block in page.jsonld:
        t = block.get("@type") or block.get("type") or ""
        if isinstance(t, list):
            names = {str(x).lower() for x in t}
        else:
            names = {str(t).lower()}
        if names & wanted:
            out.append(block)
    return out
