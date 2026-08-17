"""
Opportunity scoring (spec 15, 16, 17, 41, 42, 43).

The score answers "how much room is there to improve this website?", so a
healthy site scores LOW and a site with many measured problems scores HIGH.

  health[c]      = 100 - (deductions measured in category c)
  opportunity[c] = 100 - health[c]
  score          = weighted mean of opportunity[c] using the configured weights

Every point is traceable to a finding, and every finding carries the
evidence that produced it. If nothing meaningful was detected, the lead is
marked `no_clear_opportunity` instead of being given an invented problem.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .audit_checks import CATEGORIES, Finding

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "": 3}

CATEGORY_LABELS = {
    "technical": "Technical health",
    "mobile": "Mobile experience",
    "conversion": "Conversion readiness",
    "trust": "Trust & proof",
    "contact": "Contact accessibility",
    "content": "Content clarity",
    "performance": "Performance",
}

# Findings strong enough to justify outreach on their own (spec 42).
STRONG_SIGNALS = {
    "no_primary_cta_above_fold", "no_phone_cta", "no_contact_form", "no_booking_cta",
    "missing_viewport", "viewport_not_responsive", "no_mobile_tap_to_call",
    "no_phone_on_site", "contact_hard_to_find", "broken_internal_links",
    "slow_response", "pagespeed_low", "no_testimonials", "very_thin_homepage",
    "services_not_clear", "no_https", "noindex", "fixed_width_layout",
    "no_website_detected", "social_profile_only", "no_email_on_site",
}


def compute_score(
    findings: List[Finding],
    weights: Dict[str, int],
    *,
    categories: Optional[List[str]] = None,
    category_of=None,
    labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Weighted health/opportunity score over a set of categories.

    `categories`/`category_of`/`labels` default to the original six-category
    opportunity-scoring setup used for lead tiering and outreach, so every
    existing call site (positional `compute_score(findings, weights)`) is
    unaffected. Passing a different `categories` list and `category_of`
    (a callable Finding -> str) reuses this same math for the premium audit
    scorecard, which buckets by a different, additive set of categories -
    see `build_scorecard` below.
    """
    cats = list(categories) if categories is not None else CATEGORIES
    get_cat = category_of or (lambda f: f.category)
    lbls = labels if labels is not None else CATEGORY_LABELS

    ded: Dict[str, int] = {c: 0 for c in cats}
    per_cat: Dict[str, List[Finding]] = {c: [] for c in cats}

    for f in findings:
        c = get_cat(f)
        if c not in ded:
            continue
        ded[c] += max(0, f.deduction)
        per_cat[c].append(f)

    health = {c: max(0, 100 - ded[c]) for c in cats}
    opportunity = {c: 100 - health[c] for c in cats}

    total_w = sum(max(0, int(weights.get(c, 0))) for c in cats) or 1
    weighted = sum(opportunity[c] * max(0, int(weights.get(c, 0))) for c in cats)
    score = int(round(weighted / total_w))
    score = max(0, min(100, score))
    overall_health = max(0, min(100, 100 - score))

    explanation = []
    for c in cats:
        w = max(0, int(weights.get(c, 0)))
        explanation.append({
            "category": c,
            "label": lbls.get(c, c),
            "weight": w,
            "health": health[c],
            "opportunity": opportunity[c],
            "contribution": round(opportunity[c] * w / total_w, 1),
            "findings": len(per_cat[c]),
            "deductions": ded[c],
        })
    explanation.sort(key=lambda e: -e["contribution"])

    return {
        "score": score,
        "overall_health": overall_health,
        "health": health,
        "opportunity": opportunity,
        "subscores": {c: opportunity[c] for c in cats},
        "weights": {c: max(0, int(weights.get(c, 0))) for c in cats},
        "explanation": explanation,
    }


def tier_for_score(score: int, tiers: List[Dict[str, Any]]) -> Tuple[str, str]:
    for t in sorted(tiers, key=lambda x: -int(x.get("min", 0))):
        if score >= int(t.get("min", 0)):
            return t.get("name", "Low"), t.get("key", "low")
    return "Low", "low"


def select_problems(
    findings: List[Finding], max_problems: int = 7
) -> List[Dict[str, Any]]:
    """
    Pick the 3-7 highest-impact *detected* problems (spec 16).

    Spread across categories first so the list is not seven variations of one
    issue, then fill remaining slots by impact.
    """
    scored = sorted(
        [f for f in findings if f.deduction > 0 or f.code in STRONG_SIGNALS],
        key=lambda f: (SEVERITY_RANK.get(f.severity, 3), -f.deduction),
    )
    if not scored:
        return []

    chosen: List[Finding] = []
    seen_cat: set = set()
    for f in scored:
        if f.display_category not in seen_cat:
            chosen.append(f)
            seen_cat.add(f.display_category)
        if len(chosen) >= max_problems:
            break
    for f in scored:
        if len(chosen) >= max_problems:
            break
        if f not in chosen:
            chosen.append(f)

    chosen.sort(key=lambda f: (SEVERITY_RANK.get(f.severity, 3), -f.deduction))
    return [
        {
            "rank": i + 1,
            "code": f.code,
            "category": f.display_category,
            "category_label": CATEGORY_LABELS.get(f.display_category, f.display_category),
            "severity": f.severity,
            "title": f.title,
            "detail": f.detail,
            "evidence": f.evidence,
            "impact_points": f.deduction,
            "is_strong_signal": f.code in STRONG_SIGNALS,
        }
        for i, f in enumerate(chosen[:max_problems])
    ]


def build_recommendations(problems: List[Dict[str, Any]], findings: List[Finding]) -> List[Dict[str, Any]]:
    by_code = {f.code: f for f in findings}
    out: List[Dict[str, Any]] = []
    for p in problems:
        f = by_code.get(p["code"])
        if f and f.recommendation:
            out.append({
                "rank": p["rank"],
                "problem_code": p["code"],
                "problem": p["title"],
                "recommendation": f.recommendation,
                "category": p["category"],
                "severity": p["severity"],
            })
    return out


# --------------------------------------------------------------------------
# Lead tiering (spec 41) - transparent, evidence-driven
# --------------------------------------------------------------------------


def lead_tier(
    *,
    score: Optional[int],
    website_status: str,
    has_usable_contact: bool,
    strong_problem_count: int,
    problem_count: int,
    audit_kind: str,
    review_count: Optional[int] = None,
    rating: Optional[float] = None,
) -> Dict[str, Any]:
    """
    A+ : high measured opportunity + valid website + usable contact + a strong,
         specific problem to lead the conversation with
    A  : good opportunity + usable contact
    B  : some opportunity, or good opportunity without a usable contact channel
    C  : weak opportunity
    D  : not enough information to judge
    """
    reasons: List[str] = []

    if score is None:
        return {
            "tier": "D",
            "reasons": ["The website could not be audited, so there is no measured opportunity."],
        }

    website_ok = website_status in ("valid", "redirected")
    no_website = audit_kind == "no_website"

    # Business-activity signal, used only as a tie-breaker and only if present.
    active = None
    if review_count is not None:
        active = review_count >= 5
        if active:
            reasons.append(f"{review_count} reviews on the source listing suggest an active business.")

    if no_website:
        # A business with no website is a real opportunity, but it is a
        # different conversation and cannot carry a website-specific problem.
        if has_usable_contact:
            tier = "B" if (active is not False) else "C"
            reasons.append("No website was found, which is an opportunity, but there is no site to reference.")
        else:
            tier = "D"
            reasons.append("No website and no usable contact channel.")
        return {"tier": tier, "reasons": reasons}

    if not website_ok:
        reasons.append(f"The website status is '{website_status}', so the audit is not reliable.")
        return {"tier": "D", "reasons": reasons}

    if score >= 75 and has_usable_contact and strong_problem_count >= 2:
        tier = "A+"
        reasons.append(f"Measured opportunity {score}/100 with {strong_problem_count} strong, "
                       f"specific problems and a usable contact channel.")
    elif score >= 60 and has_usable_contact and strong_problem_count >= 1:
        tier = "A"
        reasons.append(f"Measured opportunity {score}/100 with a usable contact channel and at "
                       f"least one strong problem to open with.")
    elif score >= 60 and not has_usable_contact:
        tier = "B"
        reasons.append(f"Measured opportunity {score}/100, but no usable contact channel was found.")
    elif score >= 40:
        tier = "B" if has_usable_contact else "C"
        reasons.append(f"Moderate measured opportunity ({score}/100).")
    elif problem_count == 0:
        tier = "D"
        reasons.append("No meaningful problems were detected on this website.")
    else:
        tier = "C"
        reasons.append(f"Low measured opportunity ({score}/100); the site is in reasonable shape.")

    if not has_usable_contact and tier in ("A+", "A"):
        tier = "B"
        reasons.append("Downgraded: no usable contact channel.")

    return {"tier": tier, "reasons": reasons}


# --------------------------------------------------------------------------
# Premium audit scorecard (Overall / Technical SEO / On-Page SEO / Local SEO /
# Off-Page & Authority / Performance / Accessibility / Security /
# UX & Conversion). Purely additive: built on top of the same findings used
# for the opportunity score above, bucketed differently for reporting. Never
# changes `compute_score(findings, weights)`'s legacy two-argument behaviour,
# never changes a Finding's own `.category`, and never feeds back into
# lead tiering or outreach.
#
# UX and Conversion are reported as one combined category here (a business
# owner cares about one question - "is this site easy to use and does it get
# me enquiries" - not two separate scores), even though the legacy
# opportunity-scoring categories above keep them apart.
# --------------------------------------------------------------------------

AUDIT_CATEGORIES = [
    "technical", "onpage", "local_seo", "offpage", "performance",
    "accessibility", "security", "ux_conversion",
]

AUDIT_CATEGORY_LABELS: Dict[str, str] = {
    "technical": "Technical SEO",
    "onpage": "On-Page SEO",
    "local_seo": "Local SEO",
    "offpage": "Off-Page & Authority",
    "performance": "Performance",
    "accessibility": "Accessibility",
    "security": "Security",
    "ux_conversion": "UX & Conversion",
}

AUDIT_CATEGORY_WHY: Dict[str, str] = {
    "technical": "Search engines must be able to crawl and index a site before anything else about "
                "it can affect organic visibility.",
    "onpage": "Titles, descriptions, headings and social tags are what search engines and shared "
             "links show first, driving click-through before a visitor ever reaches the page.",
    "local_seo": "For a business that serves customers in a physical area, showing up in local "
                "search and map results depends on address, service-area and business details that "
                "search engines can find and verify - separate from general organic SEO.",
    "offpage": "External signals - citations, linked social presence, structured entity data - are "
              "part of how search engines and visitors judge a business's credibility beyond its "
              "own site.",
    "performance": "Slower, heavier pages lose visitors before they see the content, and are "
                  "penalised by search engines' page-experience signals.",
    "accessibility": "Inaccessible pages exclude real visitors - screen reader users, keyboard-only "
                     "users, low-vision users - and carry legal risk in many jurisdictions.",
    "security": "Missing security headers and unencrypted connections expose visitors to real risk "
               "and are flagged by browsers, which damages trust.",
    "ux_conversion": "A site that is hard to use, unclear about what it offers, or gives visitors no "
                     "obvious way to make contact loses real enquiries, regardless of how much "
                     "traffic it gets.",
}

# Default weights for the premium scorecard's overall score. Independent of
# the outreach-opportunity WEIGHTS_DEFAULTS in settings.py. Sums to 100 for
# readability (weight = percentage of the overall score) but is not required
# to - compute_score normalises by whatever total is active.
AUDIT_WEIGHTS_DEFAULTS: Dict[str, int] = {
    "technical": 13, "onpage": 13, "local_seo": 10, "offpage": 5, "performance": 13,
    "accessibility": 9, "security": 13, "ux_conversion": 24,
}

# Every finding code from the six legacy checks (check_technical, check_mobile,
# check_conversion, check_trust, check_contact, check_content) plus
# no_website_findings, mapped to its primary premium scorecard category. This
# is a read-only *reporting* remap - it does not touch Finding.category, so
# `compute_score(findings, weights)` (legacy, 2-arg) is completely unaffected.
LEGACY_CODE_TO_AUDIT_CATEGORY: Dict[str, str] = {
    # technical (crawlability / indexability / redirects / sitemap / robots / links)
    "noindex": "technical",
    "missing_sitemap": "technical",
    "missing_robots": "technical",
    "broken_internal_links": "technical",
    "long_redirect_chain": "technical",
    # security
    "no_https": "security",
    "mixed_content": "security",
    # on-page SEO
    "missing_title": "onpage",
    "title_too_short": "onpage",
    "title_too_long": "onpage",
    "missing_meta_description": "onpage",
    "meta_description_short": "onpage",
    "missing_h1": "onpage",
    "multiple_h1": "onpage",
    "missing_canonical": "onpage",
    "generic_value_proposition": "onpage",
    "no_heading_structure": "onpage",
    "very_thin_homepage": "onpage",
    "thin_homepage": "onpage",
    "services_not_clear": "onpage",
    "no_service_area": "onpage",
    # accessibility
    "missing_lang": "accessibility",
    "low_alt_coverage": "accessibility",
    # performance
    "slow_response": "performance",
    "heavy_page": "performance",
    "many_scripts": "performance",
    "pagespeed_low": "performance",
    # ux & conversion (mobile experience, navigation, CTAs, trust/proof, contact)
    "missing_viewport": "ux_conversion",
    "viewport_not_responsive": "ux_conversion",
    "zoom_disabled": "ux_conversion",
    "fixed_width_layout": "ux_conversion",
    "small_mobile_text": "ux_conversion",
    "no_mobile_tap_to_call": "ux_conversion",
    "legacy_plugin_content": "ux_conversion",
    "no_mobile_menu": "ux_conversion",
    "minimal_navigation": "ux_conversion",
    "no_primary_cta_above_fold": "ux_conversion",
    "no_phone_cta": "ux_conversion",
    "no_contact_form": "ux_conversion",
    "no_booking_cta": "ux_conversion",
    "no_quote_cta": "ux_conversion",
    "no_email_cta": "ux_conversion",
    "no_contact_page": "ux_conversion",
    "weak_cta_language": "ux_conversion",
    "no_testimonials": "ux_conversion",
    "reviews_not_structured": "ux_conversion",
    "no_credentials": "ux_conversion",
    "no_portfolio": "ux_conversion",
    "no_about_page": "ux_conversion",
    "no_phone_on_site": "ux_conversion",
    "phone_not_on_homepage": "ux_conversion",
    "no_email_on_site": "ux_conversion",
    "no_address": "ux_conversion",
    "no_opening_hours": "ux_conversion",
    "contact_hard_to_find": "ux_conversion",
    "no_website_detected": "ux_conversion",
    "social_profile_only": "ux_conversion",
    # off-page / authority
    "no_social_presence_linked": "offpage",
}


def audit_category_of(finding: Finding) -> str:
    mapped = LEGACY_CODE_TO_AUDIT_CATEGORY.get(finding.code)
    if mapped:
        return mapped
    if finding.category in AUDIT_CATEGORIES:
        return finding.category
    return finding.display_category if finding.display_category in AUDIT_CATEGORIES else finding.category


def priority_for(finding: Finding) -> str:
    """P1/P2/P3, derived deterministically from severity and points removed."""
    if finding.severity == "high" or finding.deduction >= 20:
        return "P1"
    if finding.severity == "medium" or finding.deduction >= 10:
        return "P2"
    return "P3"


# A curated catalogue of binary checks, used only to populate the premium
# report's "Passed checks" section. A check counts as passed when none of its
# associated finding codes fired - nothing here is measured independently of
# the findings already produced by the check functions.
CHECK_CATALOG: List[Dict[str, Any]] = [
    {"id": "https", "category": "security", "label": "Site is served over HTTPS", "fail_codes": ["no_https"]},
    {"id": "mixed_content", "category": "security", "label": "No mixed HTTP content on an HTTPS page", "fail_codes": ["mixed_content"]},
    {"id": "hsts", "category": "security", "label": "Strict-Transport-Security header present", "fail_codes": ["security_hsts_missing"]},
    {"id": "csp", "category": "security", "label": "Content-Security-Policy header present", "fail_codes": ["security_csp_missing"]},
    {"id": "frame_protection", "category": "security", "label": "Clickjacking protection header present", "fail_codes": ["security_frame_protection_missing"]},
    {"id": "xcto", "category": "security", "label": "X-Content-Type-Options header present", "fail_codes": ["security_xcto_missing"]},
    {"id": "referrer_policy", "category": "security", "label": "Referrer-Policy header present", "fail_codes": ["security_referrer_policy_missing"]},

    {"id": "indexable", "category": "technical", "label": "Homepage is indexable (no noindex)", "fail_codes": ["noindex"]},
    {"id": "sitemap", "category": "technical", "label": "XML sitemap found", "fail_codes": ["missing_sitemap"]},
    {"id": "robots_txt", "category": "technical", "label": "robots.txt found", "fail_codes": ["missing_robots"]},
    {"id": "broken_links", "category": "technical", "label": "No broken internal links detected", "fail_codes": ["broken_internal_links"]},
    {"id": "redirects", "category": "technical", "label": "No excessive redirect chain", "fail_codes": ["long_redirect_chain"]},

    {"id": "title", "category": "onpage", "label": "Title tag present and well-sized", "fail_codes": ["missing_title", "title_too_short", "title_too_long"]},
    {"id": "meta_description", "category": "onpage", "label": "Meta description present and well-sized", "fail_codes": ["missing_meta_description", "meta_description_short"]},
    {"id": "h1", "category": "onpage", "label": "Homepage has exactly one H1", "fail_codes": ["missing_h1", "multiple_h1"]},
    {"id": "canonical", "category": "onpage", "label": "Canonical URL declared", "fail_codes": ["missing_canonical"]},
    {"id": "open_graph", "category": "onpage", "label": "Open Graph tags present", "fail_codes": ["onpage_missing_open_graph"]},
    {"id": "twitter_card", "category": "onpage", "label": "Twitter/X card tag present", "fail_codes": ["onpage_missing_twitter_card"]},
    {"id": "duplicate_titles", "category": "onpage", "label": "No duplicate titles across crawled pages", "fail_codes": ["onpage_duplicate_titles"]},

    {"id": "viewport", "category": "ux_conversion", "label": "Mobile viewport configured correctly", "fail_codes": ["missing_viewport", "viewport_not_responsive"]},
    {"id": "tap_to_call", "category": "ux_conversion", "label": "Tap-to-call link present on the homepage", "fail_codes": ["no_mobile_tap_to_call"]},
    {"id": "fixed_width", "category": "ux_conversion", "label": "No fixed-width layout wider than a phone screen", "fail_codes": ["fixed_width_layout"]},
    {"id": "mobile_menu", "category": "ux_conversion", "label": "Mobile navigation pattern detected", "fail_codes": ["no_mobile_menu"]},

    {"id": "alt_text", "category": "accessibility", "label": "Good image alt-text coverage", "fail_codes": ["low_alt_coverage"]},
    {"id": "lang", "category": "accessibility", "label": "Page language declared", "fail_codes": ["missing_lang"]},
    {"id": "main_landmark", "category": "accessibility", "label": "<main> landmark present", "fail_codes": ["a11y_no_main_landmark"]},
    {"id": "form_labels", "category": "accessibility", "label": "Form fields have associated labels", "fail_codes": ["a11y_unlabelled_form_inputs"]},
    {"id": "link_text", "category": "accessibility", "label": "Links have accessible text", "fail_codes": ["a11y_empty_links"]},

    {"id": "response_time", "category": "performance", "label": "Homepage responded quickly", "fail_codes": ["slow_response"]},
    {"id": "page_weight", "category": "performance", "label": "Homepage HTML is a reasonable size", "fail_codes": ["heavy_page"]},
    {"id": "compression", "category": "performance", "label": "Response is compressed", "fail_codes": ["perf_no_compression"]},
    {"id": "render_blocking", "category": "performance", "label": "No excessive render-blocking scripts", "fail_codes": ["perf_render_blocking_scripts"]},

    {"id": "phone_cta", "category": "ux_conversion", "label": "Clickable phone link present", "fail_codes": ["no_phone_cta"]},
    {"id": "contact_form", "category": "ux_conversion", "label": "Contact/enquiry form present", "fail_codes": ["no_contact_form"]},
    {"id": "contact_page", "category": "ux_conversion", "label": "Contact page present", "fail_codes": ["no_contact_page"]},
    {"id": "testimonials", "category": "ux_conversion", "label": "Testimonials/reviews present", "fail_codes": ["no_testimonials"]},
    {"id": "credentials", "category": "ux_conversion", "label": "Trust signals (licences/insurance/guarantees) present", "fail_codes": ["no_credentials"]},
    {"id": "address", "category": "ux_conversion", "label": "Business address published", "fail_codes": ["no_address"]},

    {"id": "social_profiles", "category": "offpage", "label": "Social profiles linked from the site", "fail_codes": ["offpage_no_social_profiles"]},

    {"id": "local_business_schema", "category": "local_seo", "label": "LocalBusiness/Organization structured data present", "fail_codes": ["local_no_business_schema"]},
    {"id": "local_address", "category": "local_seo", "label": "Business address published", "fail_codes": ["local_no_address_signal"]},
    {"id": "local_map_or_gbp", "category": "local_seo", "label": "Map embed or Google Business Profile link present", "fail_codes": ["local_no_map_or_gbp_link"]},
    {"id": "local_service_area", "category": "local_seo", "label": "Service-area or local landing-page content present", "fail_codes": ["local_no_service_area_content"]},
    {"id": "local_hours", "category": "local_seo", "label": "Opening hours published", "fail_codes": ["local_no_opening_hours"]},
    {"id": "local_reviews", "category": "local_seo", "label": "Reviews or testimonials present", "fail_codes": ["local_no_reviews_or_testimonials"]},
    {"id": "local_reviews_structured", "category": "local_seo", "label": "Reviews marked up as structured data (Review/AggregateRating)", "fail_codes": ["local_reviews_not_structured"]},
    {"id": "local_name_consistency", "category": "local_seo", "label": "Business name consistent between structured data and page content", "fail_codes": ["local_name_mismatch"]},
]

# Checks this engine can never measure without a paid third-party service or
# a rendered browser. Always reported as "not verified" here - never
# estimated or guessed (spec: accuracy rule).
NOT_VERIFIED_CATALOG: List[Dict[str, str]] = [
    {
        "id": "color_contrast", "category": "accessibility",
        "label": "Colour contrast meets WCAG guidelines",
        "detail": "Requires a rendered page with computed styles; not measurable from static HTML/CSS.",
    },
    {
        "id": "backlink_profile", "category": "offpage",
        "label": "Backlink count and referring domains",
        "detail": "Requires a paid third-party index (e.g. Ahrefs, Moz, Majestic, SEMrush); never estimated.",
    },
    {
        "id": "domain_authority", "category": "offpage",
        "label": "Domain authority / DR-style score",
        "detail": "Proprietary to each vendor; never approximated.",
    },
]


STATUS_PASS = "pass"
STATUS_WARNING = "warning"
STATUS_FAIL = "fail"
STATUS_NOT_VERIFIED = "not_verified"
STATUS_NOT_APPLICABLE = "not_applicable"

# Display labels matching the premium report's colour grading:
# green=Passed, yellow=Needs Improvement, red=Critical, gray=Not Verified/N-A.
STATUS_LABELS: Dict[str, str] = {
    STATUS_PASS: "Passed",
    STATUS_WARNING: "Needs Improvement",
    STATUS_FAIL: "Critical",
    STATUS_NOT_VERIFIED: "Not Verified",
    STATUS_NOT_APPLICABLE: "Not Applicable",
}


def build_check_results(
    findings: List[Finding],
    *,
    category_applicability: Optional[Dict[str, bool]] = None,
    applicability_reason: Optional[Dict[str, str]] = None,
    pagespeed_measured: bool = False,
) -> Dict[str, Any]:
    """
    Every catalogued check resolves to exactly one status - PASS, WARNING,
    FAIL, NOT VERIFIED or NOT APPLICABLE - never a fabricated result for
    something that was not actually measured (spec: accuracy rule).

    A check FAILs when its worst matching finding is high-severity, WARNs
    when medium/low, PASSes when none of its fail_codes fired, is NOT
    APPLICABLE when its whole category was ruled inapplicable to this site
    (e.g. Local SEO on a site with no location signals), and NOT VERIFIED
    for the handful of things this engine can never measure without a paid
    third-party service or a rendered browser.
    """
    applicability = category_applicability or {}
    reasons = applicability_reason or {}
    present: Dict[str, Finding] = {}
    for f in findings:
        present.setdefault(f.code, f)

    results: List[Dict[str, Any]] = []

    for chk in CHECK_CATALOG:
        cat = chk["category"]
        if applicability.get(cat) is False:
            results.append({
                "id": chk["id"], "category": cat, "label": chk["label"],
                "status": STATUS_NOT_APPLICABLE,
                "detail": reasons.get(cat, "Not applicable to this website."),
            })
            continue
        hit = next((c for c in chk["fail_codes"] if c in present), None)
        if not hit:
            results.append({
                "id": chk["id"], "category": cat, "label": chk["label"],
                "status": STATUS_PASS, "detail": "",
            })
        else:
            f = present[hit]
            status = STATUS_FAIL if f.severity == "high" else STATUS_WARNING
            results.append({
                "id": chk["id"], "category": cat, "label": chk["label"],
                "status": status, "detail": f.title,
            })

    for chk in NOT_VERIFIED_CATALOG:
        cat = chk["category"]
        if applicability.get(cat) is False:
            results.append({
                "id": chk["id"], "category": cat, "label": chk["label"],
                "status": STATUS_NOT_APPLICABLE, "detail": reasons.get(cat, "Not applicable to this website."),
            })
        else:
            results.append({
                "id": chk["id"], "category": cat, "label": chk["label"],
                "status": STATUS_NOT_VERIFIED, "detail": chk["detail"],
            })

    cwv_status: str
    cwv_detail: str
    if applicability.get("performance") is False:
        cwv_status, cwv_detail = STATUS_NOT_APPLICABLE, reasons.get("performance", "Not applicable to this website.")
    elif pagespeed_measured:
        hit = present.get("pagespeed_low")
        if hit:
            cwv_status = STATUS_FAIL if hit.severity == "high" else STATUS_WARNING
            cwv_detail = hit.title
        else:
            cwv_status, cwv_detail = STATUS_PASS, ""
    else:
        cwv_status = STATUS_NOT_VERIFIED
        cwv_detail = "Configure a Google PageSpeed Insights API key in Settings to measure Core Web Vitals."
    results.append({
        "id": "core_web_vitals", "category": "performance",
        "label": "Core Web Vitals / PageSpeed performance score",
        "status": cwv_status, "detail": cwv_detail,
    })

    counts = {STATUS_PASS: 0, STATUS_WARNING: 0, STATUS_FAIL: 0, STATUS_NOT_VERIFIED: 0, STATUS_NOT_APPLICABLE: 0}
    for r in results:
        counts[r["status"]] += 1
    evaluated = counts[STATUS_PASS] + counts[STATUS_WARNING] + counts[STATUS_FAIL]

    return {
        "checks": results,
        "passed": [r for r in results if r["status"] == STATUS_PASS],
        "warnings": [r for r in results if r["status"] == STATUS_WARNING],
        "failed": [r for r in results if r["status"] == STATUS_FAIL],
        "not_verified": [r for r in results if r["status"] == STATUS_NOT_VERIFIED],
        "not_applicable": [r for r in results if r["status"] == STATUS_NOT_APPLICABLE],
        "passed_count": counts[STATUS_PASS],
        "warning_count": counts[STATUS_WARNING],
        "failed_count": counts[STATUS_FAIL],
        "not_verified_count": counts[STATUS_NOT_VERIFIED],
        "not_applicable_count": counts[STATUS_NOT_APPLICABLE],
        "total_checked": evaluated,
        "total_catalogued": len(results),
    }


def build_scorecard(
    findings: List[Finding],
    weights: Optional[Dict[str, int]] = None,
    *,
    category_applicability: Optional[Dict[str, bool]] = None,
    applicability_reason: Optional[Dict[str, str]] = None,
    pagespeed_measured: bool = False,
) -> Dict[str, Any]:
    """
    The premium audit scorecard: Overall + Technical SEO + On-Page SEO +
    Local SEO + Off-Page & Authority + Performance + Accessibility +
    Security + UX & Conversion, all HIGHER-IS-BETTER (unlike the opportunity
    score above, which is inverted for lead-gen prioritisation). Reuses
    `compute_score`'s math over the additive AUDIT_CATEGORIES set via
    `audit_category_of`, so it is built from the exact same findings without
    recomputing anything.

    `category_applicability` (e.g. {"local_seo": False}) removes a category
    from the weighted average entirely rather than scoring it 0 or 100 -
    an inapplicable category must never move the overall score either way.
    """
    w = weights or AUDIT_WEIGHTS_DEFAULTS
    applicability = category_applicability or {}
    reasons = applicability_reason or {}

    active_cats = [c for c in AUDIT_CATEGORIES if applicability.get(c) is not False]
    active_weights = {c: w.get(c, 0) for c in active_cats}

    result = compute_score(
        findings, active_weights, categories=active_cats,
        category_of=audit_category_of, labels=AUDIT_CATEGORY_LABELS,
    )
    severity_counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        if f.severity in severity_counts and f.deduction > 0:
            severity_counts[f.severity] += 1

    categories = []
    for row in result["explanation"]:
        c = row["category"]
        categories.append({
            **row,
            "score": row["health"],
            "why_it_matters": AUDIT_CATEGORY_WHY.get(c, ""),
            "applicable": True,
        })
    for c in AUDIT_CATEGORIES:
        if applicability.get(c) is False:
            categories.append({
                "category": c,
                "label": AUDIT_CATEGORY_LABELS.get(c, c.title()),
                "weight": 0, "health": None, "opportunity": None, "contribution": 0,
                "findings": 0, "deductions": 0, "score": None,
                "why_it_matters": AUDIT_CATEGORY_WHY.get(c, ""),
                "applicable": False,
                "not_applicable_reason": reasons.get(c, "Not applicable to this website."),
            })
    categories.sort(key=lambda r: AUDIT_CATEGORIES.index(r["category"]))

    return {
        "overall_score": result["overall_health"],
        "categories": categories,
        "weights": result["weights"],
        "severity_counts": severity_counts,
        "checks": build_check_results(
            findings, category_applicability=applicability, applicability_reason=reasons,
            pagespeed_measured=pagespeed_measured,
        ),
    }


def has_clear_opportunity(
    problems: List[Dict[str, Any]], score: Optional[int], min_problems: int = 1
) -> Tuple[bool, str]:
    """
    Spec 43: if no meaningful problem was found, say so - never manufacture one.
    """
    if score is None:
        return False, "The website could not be audited."
    strong = [p for p in problems if p.get("is_strong_signal")]
    if len(problems) < min_problems:
        return False, "No meaningful, evidence-backed problems were detected on this website."
    if not strong and score < 40:
        return False, (
            "Only minor issues were detected and the overall opportunity score is low; "
            "there is no strong, specific observation to open a conversation with."
        )
    return True, ""


# --------------------------------------------------------------------------
# Top priorities + structured executive summary, for the first page of the
# premium report. Both are built entirely from the scorecard/findings that
# were already computed above - nothing here is invented.
# --------------------------------------------------------------------------


def top_priorities(findings: List[Finding], n: int = 5) -> List[Dict[str, Any]]:
    """
    The N most important, evidence-backed issues across every premium
    category. Spread across categories first (same diversity rule as
    `select_problems`) so the list is not five variations of one problem,
    then filled by impact.
    """
    scored = sorted(
        [f for f in findings if f.deduction > 0],
        key=lambda f: (SEVERITY_RANK.get(f.severity, 3), -f.deduction),
    )
    if not scored:
        return []

    chosen: List[Finding] = []
    seen_cat: set = set()
    for f in scored:
        cat = audit_category_of(f)
        if cat not in seen_cat:
            chosen.append(f)
            seen_cat.add(cat)
        if len(chosen) >= n:
            break
    for f in scored:
        if len(chosen) >= n:
            break
        if f not in chosen:
            chosen.append(f)

    chosen.sort(key=lambda f: (SEVERITY_RANK.get(f.severity, 3), -f.deduction))
    out = []
    for i, f in enumerate(chosen[:n]):
        cat = audit_category_of(f)
        out.append({
            "rank": i + 1,
            "code": f.code,
            "category": cat,
            "category_label": AUDIT_CATEGORY_LABELS.get(cat, cat.title()),
            "severity": f.severity,
            "priority": priority_for(f),
            "title": f.title,
            "detail": f.detail,
            "why_it_matters": AUDIT_CATEGORY_WHY.get(cat, ""),
            "recommendation": f.recommendation,
            "impact_points": f.deduction,
        })
    return out


# Plain-language sentence fragments used to build the "business impact" line
# of the executive summary - one clause per category that actually has a
# meaningful (medium/high severity) issue, never speculative revenue figures.
_BUSINESS_IMPACT_BY_CATEGORY: Dict[str, str] = {
    "technical": "search engines may struggle to fully crawl and index the site",
    "onpage": "the site is less likely to appear for the searches that matter, and shared links look unpolished",
    "local_seo": "the business is less likely to appear in local search and map results for nearby customers",
    "offpage": "the site has less credibility signal to search engines and visitors than it could",
    "performance": "visitors on slower connections may leave before the page finishes loading",
    "accessibility": "some real visitors cannot use the site properly, which also carries legal risk in many places",
    "security": "visitors' browsers may warn them the connection is not fully secure, which damages trust",
    "ux_conversion": "interested visitors may leave without ever making contact",
}


def build_executive_summary(
    scorecard: Dict[str, Any], findings: List[Finding], priorities: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    A structured, plain-language summary for the first page of the report:
    a headline, what's working, the top problems, the biggest opportunities,
    the likely business impact, and what to do next. Every field is derived
    from the scorecard/findings/priorities already computed - nothing here
    is invented to fill a gap.
    """
    categories = scorecard.get("categories", [])
    checks = scorecard.get("checks", {})

    working = [
        c["label"] for c in sorted(
            [c for c in categories if c.get("applicable", True) and c.get("score") is not None],
            key=lambda c: -(c["score"] or 0),
        )
        if c["score"] >= 85
    ][:4]

    top_problems = [p["title"] for p in priorities[:3]]

    opportunity_cats = sorted(
        [c for c in categories if c.get("applicable", True) and c.get("score") is not None and c["score"] < 70],
        key=lambda c: (c["score"] or 0),
    )
    biggest_opportunities = [f"{c['label']} ({c['score']}/100)" for c in opportunity_cats[:3]]

    impacted_cats: List[str] = []
    for f in findings:
        if f.deduction > 0 and f.severity in ("high", "medium"):
            cat = audit_category_of(f)
            if cat not in impacted_cats:
                impacted_cats.append(cat)
    impact_sentences = [
        _BUSINESS_IMPACT_BY_CATEGORY[c] for c in AUDIT_CATEGORIES
        if c in impacted_cats and c in _BUSINESS_IMPACT_BY_CATEGORY
    ][:3]
    business_impact = (
        ("Left unaddressed, " + "; ".join(impact_sentences) + ".")
        if impact_sentences
        else "No high-impact issues were found that are likely to cost the business enquiries."
    )

    next_steps = [p["recommendation"] for p in priorities if p.get("recommendation")][:5]

    overall = scorecard.get("overall_score")
    if overall is None:
        headline = "This site could not be fully audited."
    elif overall >= 85:
        headline = f"This site is in strong shape overall, scoring {overall}/100."
    elif overall >= 70:
        headline = f"This site is in reasonable shape overall, scoring {overall}/100, with room to improve."
    elif overall >= 50:
        headline = f"This site scores {overall}/100 overall — several important issues are holding it back."
    else:
        headline = f"This site scores {overall}/100 overall — a number of significant issues need attention."

    return {
        "headline": headline,
        "whats_working": working,
        "top_problems": top_problems,
        "biggest_opportunities": biggest_opportunities,
        "business_impact": business_impact,
        "next_steps": next_steps,
        "checks_summary": {
            "passed": checks.get("passed_count", 0),
            "warnings": checks.get("warning_count", 0),
            "critical": checks.get("failed_count", 0),
            "not_verified": checks.get("not_verified_count", 0),
            "not_applicable": checks.get("not_applicable_count", 0),
            "total": checks.get("total_checked", 0),
        },
    }
