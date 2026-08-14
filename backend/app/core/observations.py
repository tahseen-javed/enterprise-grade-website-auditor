"""
Human phrasings for detected problems (spec 18, 40, 43).

Each entry turns one *measured* finding into a sentence a business owner
would actually understand. Nothing here adds a claim the check did not
establish - no "you're losing customers", no invented revenue impact.

Multiple phrasings per code exist so that two leads with the same problem do
not receive identical messages; the variant is picked deterministically from
the lead id, so re-running a job reproduces the same text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# code -> {
#   "short":   one clause for a subject line / call opener
#   "lines":   full observation sentences (rotated)
#   "value":   what fixing it does, stated plainly and honestly
#   "topic":   used to keep the message focused on a single theme
# }

OBSERVATIONS: Dict[str, Dict[str, Any]] = {
    # ---------------- conversion ----------------
    "no_primary_cta_above_fold": {
        "topic": "call to action",
        "short": "no clear next step at the top of the homepage",
        "lines": [
            "the top of your homepage doesn't have an obvious next step — there's no call button or enquiry link before someone starts scrolling",
            "there isn't a clear call-to-action near the top of your homepage, so a first-time visitor has to hunt for how to get in touch",
            "the opening section of your homepage doesn't point visitors to a single next action",
        ],
        "value": "usually a one-line change — a single prominent button in the header",
    },
    "no_phone_cta": {
        "topic": "phone contact",
        "short": "the phone number isn't clickable anywhere on the site",
        "lines": [
            "your phone number isn't set up as a clickable link anywhere on the site, so people on phones can't just tap to call",
            "I couldn't find a tap-to-call phone link on any page of the site",
        ],
        "value": "a small markup change that makes calling a single tap",
    },
    "no_contact_form": {
        "topic": "enquiry form",
        "short": "no enquiry form on the site",
        "lines": [
            "there's no enquiry form on the site, so the only way to reach you is to call during opening hours",
            "I couldn't find a contact form anywhere, which means evening and weekend enquiries have nowhere to go",
        ],
        "value": "a short form captures the enquiries that come in outside opening hours",
    },
    "no_booking_cta": {
        "topic": "booking",
        "short": "no online booking option",
        "lines": [
            "there's no way to book online — everything routes through a phone call",
            "I couldn't find a booking or appointment option on the site",
        ],
        "value": "online booking tends to pick up the enquiries that never turn into a phone call",
    },
    "no_contact_page": {
        "topic": "contact page",
        "short": "no contact page",
        "lines": [
            "there isn't a contact page linked from the homepage, so contact details are harder to find than they need to be",
            "I couldn't find a dedicated contact page from your main navigation",
        ],
        "value": "a simple contact page gives every enquiry one obvious destination",
    },
    "weak_cta_language": {
        "topic": "call to action wording",
        "short": "the buttons use generic wording",
        "lines": [
            "the buttons on the site use generic wording like \"submit\" and \"learn more\" rather than naming what happens next",
            "the calls to action don't say what the visitor actually gets when they click",
        ],
        "value": "naming the outcome on the button is a quick change that usually lifts clicks",
    },
    "no_quote_cta": {
        "topic": "quote request",
        "short": "no quote or consultation option",
        "lines": [
            "there's no 'request a quote' or consultation option for people who aren't ready to phone straight away",
            "the site doesn't offer a quote or estimate request, which is usually the lowest-friction way in",
        ],
        "value": "a quote request captures people who aren't ready to call yet",
    },
    "no_email_cta": {
        "topic": "written contact",
        "short": "no way to get in touch in writing",
        "lines": [
            "there's no email address or form on the site, so there's no way to get in touch in writing",
        ],
        "value": "a written channel catches enquiries that arrive out of hours",
    },
    "social_profile_only": {
        "topic": "no owned website",
        "short": "the listing points to a social profile rather than a website",
        "lines": [
            "the web address on your listing points to a social profile rather than a site you own",
            "it looks like the business is running on a social page rather than its own website",
        ],
        "value": "a small owned site means you control what shows up and can be found in search",
    },
    "no_website_detected": {
        "topic": "no website",
        "short": "no website found",
        "lines": [
            "I couldn't find a website for the business — I checked the usual places and came up empty",
            "it doesn't look like there's a dedicated website for the business at the moment",
        ],
        "value": "even a single well-built page usually pays for itself in search visibility",
    },

    # ---------------- mobile ----------------
    "missing_viewport": {
        "topic": "mobile layout",
        "short": "the site isn't set up for mobile screens",
        "lines": [
            "the site doesn't have a mobile viewport set, which means on a phone it loads at full desktop width and visitors have to pinch and zoom to read it",
            "there's no mobile viewport tag, so phones render the page at desktop size rather than fitting it to the screen",
        ],
        "value": "this is the single change that makes the biggest difference on phones",
    },
    "viewport_not_responsive": {
        "topic": "mobile layout",
        "short": "the mobile layout doesn't adapt to screen width",
        "lines": [
            "the mobile settings on the site don't scale to the device width, so the layout doesn't adapt properly on phones",
        ],
        "value": "a one-line fix that lets the layout reflow correctly",
    },
    "no_mobile_tap_to_call": {
        "topic": "mobile calling",
        "short": "the phone number isn't tappable on mobile",
        "lines": [
            "your phone number on the homepage isn't a tappable link, so anyone on a phone has to copy it out by hand before they can call",
            "on mobile the phone number can't be tapped to dial — it's plain text rather than a call link",
        ],
        "value": "making the number tappable is a small change with an immediate effect on mobile",
    },
    "fixed_width_layout": {
        "topic": "mobile layout",
        "short": "fixed-width layout that's wider than a phone screen",
        "lines": [
            "parts of the layout are set to fixed widths wider than a phone screen, which usually shows up as sideways scrolling on mobile",
        ],
        "value": "switching those to flexible widths removes the horizontal scroll",
    },
    "no_mobile_menu": {
        "topic": "mobile navigation",
        "short": "large navigation with no mobile menu",
        "lines": [
            "the navigation has a lot of links but no mobile menu pattern, so it's likely awkward to use on a phone",
        ],
        "value": "a collapsible menu makes the main services reachable in one tap",
    },
    "zoom_disabled": {
        "topic": "mobile accessibility",
        "short": "pinch-to-zoom is switched off",
        "lines": [
            "pinch-to-zoom is disabled on the site, which makes it hard to use for anyone with less-than-perfect eyesight",
        ],
        "value": "removing that restriction is a one-line accessibility fix",
    },
    "small_mobile_text": {
        "topic": "mobile readability",
        "short": "text set below readable size on mobile",
        "lines": [
            "several text styles are set below 12px, which is small enough that most people will need to zoom on a phone",
        ],
        "value": "bumping the base size up makes the page readable without zooming",
    },

    # ---------------- contact ----------------
    "no_phone_on_site": {
        "topic": "phone contact",
        "short": "no phone number published on the site",
        "lines": [
            "I couldn't find a phone number published anywhere on the site, which is unusual for a local business",
        ],
        "value": "putting the number in the header is the fastest fix available",
    },
    "phone_not_on_homepage": {
        "topic": "phone visibility",
        "short": "the phone number isn't on the homepage",
        "lines": [
            "the phone number is on the site but not on the homepage, so most visitors have to click through before they can find it",
        ],
        "value": "moving it into the header means it's visible immediately",
    },
    "contact_hard_to_find": {
        "topic": "finding contact details",
        "short": "contact details are hard to find",
        "lines": [
            "contact details aren't in the header or footer and there's no contact page linked from the homepage, so getting in touch takes more effort than it should",
        ],
        "value": "putting contact details in the header and footer solves this everywhere at once",
    },
    "no_email_on_site": {
        "topic": "email contact",
        "short": "no email address published",
        "lines": [
            "there's no email address published on the site, so enquiries can only come by phone",
        ],
        "value": "a monitored address catches the enquiries a phone line misses",
    },
    "no_address": {
        "topic": "location",
        "short": "no address or service area listed",
        "lines": [
            "the site doesn't list an address or service area, which both visitors and local search results rely on",
        ],
        "value": "adding the address and area helps local search pick the business up",
    },
    "no_opening_hours": {
        "topic": "opening hours",
        "short": "opening hours aren't published",
        "lines": [
            "opening hours aren't published on the site, so people can't tell when you're available",
        ],
        "value": "publishing hours cuts out a whole category of wasted calls",
    },

    # ---------------- trust ----------------
    "no_testimonials": {
        "topic": "customer proof",
        "short": "no reviews or testimonials on the site",
        "lines": [
            "there aren't any customer reviews or testimonials on the site, which is usually the first thing people look for before getting in touch",
            "I couldn't find testimonials or reviews anywhere on the site",
        ],
        "value": "even three or four short quotes near the contact section make a noticeable difference",
    },
    "no_credentials": {
        "topic": "credentials",
        "short": "no licences, insurance or accreditations mentioned",
        "lines": [
            "the site doesn't mention licences, insurance, accreditations or a guarantee anywhere",
        ],
        "value": "these are usually already true — they just aren't stated on the page",
    },
    "no_portfolio": {
        "topic": "examples of work",
        "short": "no photos or examples of past work",
        "lines": [
            "there aren't any photos or examples of previous work on the site",
        ],
        "value": "a handful of before-and-after photos does a lot of the selling",
    },
    "no_about_page": {
        "topic": "about the business",
        "short": "no about page",
        "lines": [
            "there's no about page, so there's nothing on the site about who runs the business or how long it's been going",
        ],
        "value": "a short about page helps people feel comfortable making the call",
    },
    "reviews_not_structured": {
        "topic": "review markup",
        "short": "reviews aren't marked up for search results",
        "lines": [
            "you have reviews on the site but they aren't marked up as structured data, so the star ratings can't show up in Google results",
        ],
        "value": "the markup is invisible to visitors but makes the listing stand out in search",
    },
    "no_social_presence_linked": {
        "topic": "social links",
        "short": "no social profiles linked",
        "lines": [
            "the site doesn't link to any social profiles, so visitors can't see recent activity",
        ],
        "value": "linking active profiles is quick and shows the business is running",
    },

    # ---------------- technical / performance ----------------
    "no_https": {
        "topic": "site security",
        "short": "the site doesn't load over a secure connection",
        "lines": [
            "the site doesn't load over HTTPS, so browsers show a 'not secure' warning in the address bar",
        ],
        "value": "a certificate is usually free and removes the warning immediately",
    },
    "noindex": {
        "topic": "search visibility",
        "short": "the homepage is blocked from search engines",
        "lines": [
            "the homepage is currently tagged 'noindex', which asks Google not to list it at all — that's usually left over from a rebuild by mistake",
        ],
        "value": "removing one line makes the page eligible to appear in search again",
    },
    "slow_response": {
        "topic": "page speed",
        "short": "the homepage was slow to respond",
        "lines": [
            "the homepage took {response_ms} ms to respond when I loaded it, which is slow enough to be noticeable",
            "your homepage came back in {response_ms} ms on my test — slower than most visitors will wait for comfortably",
        ],
        "value": "usually hosting or caching rather than a rebuild",
    },
    "pagespeed_low": {
        "topic": "page speed",
        "short": "a low Google PageSpeed score",
        "lines": [
            "Google's PageSpeed test scores the mobile homepage at {pagespeed_score}/100",
        ],
        "value": "the biggest wins are normally image sizes and render-blocking scripts",
    },
    "broken_internal_links": {
        "topic": "broken links",
        "short": "broken links on the site",
        "lines": [
            "{broken_count} of the internal links I checked lead to error pages",
            "I found {broken_count} broken link{broken_plural} while going through the site",
        ],
        "value": "quick to fix once you know which ones they are",
    },
    "missing_title": {
        "topic": "search listing",
        "short": "no page title",
        "lines": [
            "the homepage has no title tag, so Google has nothing to show as the headline in search results",
        ],
        "value": "one line of markup controls how the listing reads",
    },
    "missing_meta_description": {
        "topic": "search listing",
        "short": "no search description",
        "lines": [
            "the homepage has no meta description, so Google writes its own snippet from whatever text it finds",
        ],
        "value": "writing it yourself gives you control over the search listing",
    },
    "missing_h1": {
        "topic": "page structure",
        "short": "no main heading",
        "lines": [
            "the homepage doesn't have a main heading, which both visitors and search engines use to work out what the page is about",
        ],
        "value": "a single clear heading fixes it",
    },
    "mixed_content": {
        "topic": "site security",
        "short": "insecure assets on a secure page",
        "lines": [
            "the secure pages load some files over an insecure connection, which can break the padlock in the address bar",
        ],
        "value": "updating those URLs restores the padlock",
    },
    "low_alt_coverage": {
        "topic": "image accessibility",
        "short": "most images have no alt text",
        "lines": [
            "most of the images on the site have no alt text, which affects both accessibility and image search",
        ],
        "value": "straightforward to add and helps on both fronts",
    },
    "missing_sitemap": {
        "topic": "search crawling",
        "short": "no sitemap",
        "lines": [
            "there's no XML sitemap, which makes it slower for search engines to pick up new pages",
        ],
        "value": "most platforms can generate one automatically",
    },
    "heavy_page": {
        "topic": "page weight",
        "short": "a heavy homepage",
        "lines": [
            "the homepage document alone is {page_mb} MB before images, which slows things down on mobile data",
        ],
        "value": "trimming the page weight helps most on phones",
    },

    # ---------------- content ----------------
    "very_thin_homepage": {
        "topic": "homepage content",
        "short": "very little content on the homepage",
        "lines": [
            "the homepage has only about {word_count} words on it, which isn't really enough to explain what you do or to rank for anything",
        ],
        "value": "a section per service is usually all it takes",
    },
    "thin_homepage": {
        "topic": "homepage content",
        "short": "a thin homepage",
        "lines": [
            "the homepage runs to about {word_count} words, which is on the thin side for explaining the services",
        ],
        "value": "expanding each service into its own section helps visitors and search alike",
    },
    "services_not_clear": {
        "topic": "services",
        "short": "the services aren't clearly listed",
        "lines": [
            "the services you offer aren't clearly set out anywhere I could find, so a visitor has to guess what's covered",
        ],
        "value": "listing them plainly is usually the single highest-value change",
    },
    "generic_value_proposition": {
        "topic": "main heading",
        "short": "the main heading doesn't say what you do",
        "lines": [
            "the main heading on the homepage is \"{h1}\", which doesn't tell a new visitor what you do or where you work",
        ],
        "value": "service plus area in the heading does a lot of work",
    },
    "no_service_area": {
        "topic": "service area",
        "short": "the service area isn't stated",
        "lines": [
            "the site doesn't say which areas you cover, which is one of the first things local customers check",
        ],
        "value": "listing the areas helps you show up for nearby searches",
    },
    "minimal_navigation": {
        "topic": "navigation",
        "short": "almost no navigation",
        "lines": [
            "there's very little navigation on the homepage, so there's no clear path to services or contact details",
        ],
        "value": "a simple menu gives visitors somewhere to go",
    },
    "no_heading_structure": {
        "topic": "page structure",
        "short": "no subheadings on the homepage",
        "lines": [
            "the homepage is one long block of text with no subheadings, which makes it hard to scan",
        ],
        "value": "breaking it into sections makes it much easier to read",
    },
}


def observation_for(
    problem: Dict[str, Any], variant_index: int = 0
) -> Optional[Dict[str, str]]:
    """Render one problem into a usable sentence, or None if we have no phrasing."""
    code = problem.get("code", "")
    spec = OBSERVATIONS.get(code)
    if not spec:
        return None

    lines: List[str] = spec["lines"]
    line = lines[variant_index % len(lines)]
    ev = problem.get("evidence") or {}

    # Fill measured values. If a placeholder has no measured value, fall back
    # to a phrasing that does not need it rather than inventing a number.
    subs = {
        "response_ms": ev.get("response_ms"),
        "broken_count": len(ev.get("broken", [])) or ev.get("count"),
        "broken_plural": "s" if (len(ev.get("broken", [])) or 0) != 1 else "",
        "word_count": ev.get("word_count"),
        "h1": ev.get("h1"),
        "pagespeed_score": ev.get("performance_score"),
        "page_mb": round(ev.get("bytes", 0) / 1_000_000, 1) if ev.get("bytes") else None,
    }
    try:
        needed = [
            k for k in subs
            if "{" + k + "}" in line
        ]
        if any(subs.get(k) is None for k in needed):
            alt = next(
                (l for l in lines if not any("{" + k + "}" in l for k in subs)), None
            )
            if alt is None:
                return None
            line = alt
        else:
            line = line.format(**{k: v for k, v in subs.items() if v is not None})
    except (KeyError, IndexError, ValueError):
        return None

    return {
        "code": code,
        "topic": spec["topic"],
        "short": spec["short"],
        "line": line,
        "value": spec.get("value", ""),
        "severity": problem.get("severity", ""),
        "category": problem.get("category", ""),
    }


def pick_observations(
    problems: List[Dict[str, Any]], seed: int, limit: int = 2
) -> List[Dict[str, str]]:
    """
    Choose the 1-2 strongest problems we can phrase naturally, keeping them on
    different topics so the message stays focused (spec 18).
    """
    out: List[Dict[str, str]] = []
    used_topics: set = set()
    for p in problems:
        obs = observation_for(p, variant_index=seed + len(out))
        if not obs:
            continue
        if obs["topic"] in used_topics:
            continue
        out.append(obs)
        used_topics.add(obs["topic"])
        if len(out) >= limit:
            break
    return out
