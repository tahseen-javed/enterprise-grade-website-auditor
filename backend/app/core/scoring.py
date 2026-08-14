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
# Premium audit scorecard (Overall / Technical SEO / On-Page SEO /
# Off-Page & Authority / Performance / Accessibility / Security / UX /
# Conversion). Purely additive: built on top of the same findings used for
# the opportunity score above, bucketed differently for reporting. Never
# changes `compute_score(findings, weights)`'s legacy two-argument behaviour,
# never changes a Finding's own `.category`, and never feeds back into
# lead tiering or outreach.
# --------------------------------------------------------------------------

AUDIT_CATEGORIES = [
    "technical", "onpage", "offpage", "performance", "accessibility", "security", "ux", "conversion",
]

AUDIT_CATEGORY_LABELS: Dict[str, str] = {
    "technical": "Technical SEO",
    "onpage": "On-Page SEO",
    "offpage": "Off-Page & Authority",
    "performance": "Performance",
    "accessibility": "Accessibility",
    "security": "Security",
    "ux": "UX",
    "conversion": "Conversion",
}

AUDIT_CATEGORY_WHY: Dict[str, str] = {
    "technical": "Search engines must be able to crawl and index a site before anything else about "
                "it can affect organic visibility.",
    "onpage": "Titles, descriptions, headings and social tags are what search engines and shared "
             "links show first, driving click-through before a visitor ever reaches the page.",
    "offpage": "External signals - citations, linked social presence, structured entity data - are "
              "part of how search engines and visitors judge a business's credibility beyond its "
              "own site.",
    "performance": "Slower, heavier pages lose visitors before they see the content, and are "
                  "penalised by search engines' page-experience signals.",
    "accessibility": "Inaccessible pages exclude real visitors - screen reader users, keyboard-only "
                     "users, low-vision users - and carry legal risk in many jurisdictions.",
    "security": "Missing security headers and unencrypted connections expose visitors to real risk "
               "and are flagged by browsers, which damages trust.",
    "ux": "A site that is hard to use on a phone or navigate loses visitors regardless of how good "
         "the content is.",
    "conversion": "Every visitor who cannot find a way to make contact or trust the business is a "
                  "lost enquiry, regardless of how much traffic the site gets.",
}

# Default weights for the premium scorecard's overall score. Independent of
# the outreach-opportunity WEIGHTS_DEFAULTS in settings.py.
AUDIT_WEIGHTS_DEFAULTS: Dict[str, int] = {
    "technical": 15, "onpage": 15, "offpage": 5, "performance": 15,
    "accessibility": 10, "security": 15, "ux": 15, "conversion": 10,
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
    # ux (mobile experience + navigation)
    "missing_viewport": "ux",
    "viewport_not_responsive": "ux",
    "zoom_disabled": "ux",
    "fixed_width_layout": "ux",
    "small_mobile_text": "ux",
    "no_mobile_tap_to_call": "ux",
    "legacy_plugin_content": "ux",
    "no_mobile_menu": "ux",
    "minimal_navigation": "ux",
    # conversion (CTAs, trust/proof, contact & business info)
    "no_primary_cta_above_fold": "conversion",
    "no_phone_cta": "conversion",
    "no_contact_form": "conversion",
    "no_booking_cta": "conversion",
    "no_quote_cta": "conversion",
    "no_email_cta": "conversion",
    "no_contact_page": "conversion",
    "weak_cta_language": "conversion",
    "no_testimonials": "conversion",
    "reviews_not_structured": "conversion",
    "no_credentials": "conversion",
    "no_portfolio": "conversion",
    "no_about_page": "conversion",
    "no_phone_on_site": "conversion",
    "phone_not_on_homepage": "conversion",
    "no_email_on_site": "conversion",
    "no_address": "conversion",
    "no_opening_hours": "conversion",
    "contact_hard_to_find": "conversion",
    "no_website_detected": "conversion",
    "social_profile_only": "conversion",
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

    {"id": "viewport", "category": "ux", "label": "Mobile viewport configured correctly", "fail_codes": ["missing_viewport", "viewport_not_responsive"]},
    {"id": "tap_to_call", "category": "ux", "label": "Tap-to-call link present on the homepage", "fail_codes": ["no_mobile_tap_to_call"]},
    {"id": "fixed_width", "category": "ux", "label": "No fixed-width layout wider than a phone screen", "fail_codes": ["fixed_width_layout"]},
    {"id": "mobile_menu", "category": "ux", "label": "Mobile navigation pattern detected", "fail_codes": ["no_mobile_menu"]},

    {"id": "alt_text", "category": "accessibility", "label": "Good image alt-text coverage", "fail_codes": ["low_alt_coverage"]},
    {"id": "lang", "category": "accessibility", "label": "Page language declared", "fail_codes": ["missing_lang"]},
    {"id": "main_landmark", "category": "accessibility", "label": "<main> landmark present", "fail_codes": ["a11y_no_main_landmark"]},
    {"id": "form_labels", "category": "accessibility", "label": "Form fields have associated labels", "fail_codes": ["a11y_unlabelled_form_inputs"]},
    {"id": "link_text", "category": "accessibility", "label": "Links have accessible text", "fail_codes": ["a11y_empty_links"]},

    {"id": "response_time", "category": "performance", "label": "Homepage responded quickly", "fail_codes": ["slow_response"]},
    {"id": "page_weight", "category": "performance", "label": "Homepage HTML is a reasonable size", "fail_codes": ["heavy_page"]},
    {"id": "compression", "category": "performance", "label": "Response is compressed", "fail_codes": ["perf_no_compression"]},
    {"id": "render_blocking", "category": "performance", "label": "No excessive render-blocking scripts", "fail_codes": ["perf_render_blocking_scripts"]},

    {"id": "phone_cta", "category": "conversion", "label": "Clickable phone link present", "fail_codes": ["no_phone_cta"]},
    {"id": "contact_form", "category": "conversion", "label": "Contact/enquiry form present", "fail_codes": ["no_contact_form"]},
    {"id": "contact_page", "category": "conversion", "label": "Contact page present", "fail_codes": ["no_contact_page"]},
    {"id": "testimonials", "category": "conversion", "label": "Testimonials/reviews present", "fail_codes": ["no_testimonials"]},
    {"id": "credentials", "category": "conversion", "label": "Trust signals (licences/insurance/guarantees) present", "fail_codes": ["no_credentials"]},
    {"id": "address", "category": "conversion", "label": "Business address published", "fail_codes": ["no_address"]},

    {"id": "social_profiles", "category": "offpage", "label": "Social profiles linked from the site", "fail_codes": ["offpage_no_social_profiles"]},
]


def build_pass_fail_summary(findings: List[Finding]) -> Dict[str, Any]:
    present = {f.code for f in findings}
    passed: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for chk in CHECK_CATALOG:
        hit = next((c for c in chk["fail_codes"] if c in present), None)
        if hit:
            failed.append({"id": chk["id"], "category": chk["category"], "code": hit})
        else:
            passed.append({"id": chk["id"], "category": chk["category"], "label": chk["label"]})
    return {
        "passed": passed,
        "failed": failed,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "total_checked": len(CHECK_CATALOG),
    }


def build_scorecard(
    findings: List[Finding], weights: Optional[Dict[str, int]] = None
) -> Dict[str, Any]:
    """
    The premium audit scorecard: Overall + Technical SEO + On-Page SEO +
    Off-Page & Authority + Performance + Accessibility + Security + UX +
    Conversion, all HIGHER-IS-BETTER (unlike the opportunity score above,
    which is inverted for lead-gen prioritisation). Reuses `compute_score`'s
    math over the additive AUDIT_CATEGORIES set via `audit_category_of`, so
    it is built from the exact same findings without recomputing anything.
    """
    w = weights or AUDIT_WEIGHTS_DEFAULTS
    result = compute_score(
        findings, w, categories=AUDIT_CATEGORIES,
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
        })
    categories.sort(key=lambda r: AUDIT_CATEGORIES.index(r["category"]))

    return {
        "overall_score": result["overall_health"],
        "categories": categories,
        "weights": result["weights"],
        "severity_counts": severity_counts,
        "pass_fail": build_pass_fail_summary(findings),
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
