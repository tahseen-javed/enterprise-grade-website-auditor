"""
Outreach draft generation (spec 18-22, 40, 43, 54).

Hard rules enforced here:
  * a draft is only produced when at least one *measured* observation exists;
  * the message names that observation specifically - no generic pitches;
  * nothing is sent, ever. Drafts and links only (spec 39).
  * the audit offer is only made because the HTML audit report genuinely
    exists for this lead;
  * if the user's own identity is not configured, generation is refused
    rather than filled in with invented details (spec 3, 49).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from .observations import pick_observations
from .phones import whatsapp_url

# --------------------------------------------------------------------------
# Tone packs
# --------------------------------------------------------------------------

TONE_PACKS: Dict[str, Dict[str, List[str]]] = {
    "professional": {
        "greeting": ["Hi{name},", "Hello{name},"],
        "intro": [
            "I came across {business} while looking at {industry} in {area}.",
            "I found {business} while researching {industry} around {area}.",
            "I was looking through {industry} in {area} and came across {business}.",
        ],
        "bridge": [
            "I had a quick look at your website and noticed {observation}.",
            "I took a look at your site and noticed {observation}.",
        ],
        "second": ["I also noticed {observation}."],
        "offer": [
            "I put together a short write-up of what I'd change and why.",
            "I've written up a few specific things I'd improve, with the reasoning behind each.",
        ],
        "cta": [
            "Happy to send it over if that's useful — no obligation either way.",
            "I can send it across if you'd like a look. Entirely up to you.",
            "Would it be useful if I sent it over?",
        ],
        "signoff": ["Best regards,", "Kind regards,"],
    },
    "friendly": {
        "greeting": ["Hi{name},", "Hey{name},"],
        "intro": [
            "I came across {business} while looking at {industry} around {area}.",
            "I stumbled on {business} while going through {industry} in {area}.",
        ],
        "bridge": [
            "I had a look at your website and spotted {observation}.",
            "Had a quick look at your site and noticed {observation}.",
        ],
        "second": ["I also spotted {observation}."],
        "offer": [
            "I jotted down a few things I'd change — nothing complicated.",
            "I made a short list of what I'd tidy up first.",
        ],
        "cta": [
            "Want me to send it over? No strings.",
            "Happy to share it if that's helpful — just say the word.",
            "Let me know if you'd like a look.",
        ],
        "signoff": ["Cheers,", "Thanks,"],
    },
    "consultant": {
        "greeting": ["Hi{name},", "Hello{name},"],
        "intro": [
            "I work with {industry} on their websites, and {business} came up while I was reviewing businesses in {area}.",
            "I specialise in websites for {industry}. {business} came up while I was looking at {area}.",
        ],
        "bridge": [
            "Looking at your site, the thing that stood out was {observation}.",
            "Going through your site, what stood out was {observation}.",
        ],
        "second": ["The other thing I noticed was {observation}."],
        "offer": [
            "I've documented what I found along with what I'd do about it.",
            "I've written up the findings and the specific fixes I'd recommend.",
        ],
        "cta": [
            "I'm happy to share it — would that be worth a look?",
            "Happy to send the write-up across if it's of interest.",
        ],
        "signoff": ["Best,", "Regards,"],
    },
    "founder": {
        "greeting": ["Hi{name},", "Hey{name},"],
        "intro": [
            "I run {my_company} — we build websites for {industry}. I came across {business} in {area}.",
            "I'm {my_name}, I run {my_company}. We work with {industry}, and {business} came up while I was looking around {area}.",
        ],
        "bridge": [
            "I had a look at your site and noticed {observation}.",
            "I went through your site and the first thing I noticed was {observation}.",
        ],
        "second": ["I also noticed {observation}."],
        "offer": [
            "I wrote up a few things I'd change — took me about ten minutes.",
            "I've put together a short breakdown of what I'd fix first.",
        ],
        "cta": [
            "Want me to send it over? Happy to, either way.",
            "Happy to send it across if you'd find it useful.",
        ],
        "signoff": ["Cheers,", "Best,"],
    },
}

DEFAULT_TONE = "professional"


def _pick(options: List[str], seed: int) -> str:
    return options[seed % len(options)] if options else ""


def _seed_for(business_id: int, salt: int = 0) -> int:
    return abs(hash((business_id, salt))) % 997


# --------------------------------------------------------------------------


@dataclass
class OutreachContext:
    business_id: int
    business_name: str
    category: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    website: str = ""
    contact_name: str = ""
    problems: List[Dict[str, Any]] = field(default_factory=list)
    score: Optional[int] = None
    audit_kind: str = "website"
    report_available: bool = False


@dataclass
class Draft:
    channel: str
    variant: str
    subject: str = ""
    message: str = ""
    draft_url: str = ""
    based_on: List[Dict[str, Any]] = field(default_factory=list)
    generator: str = "deterministic"
    skipped_reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.message) and not self.skipped_reason


class ProfileIncomplete(Exception):
    def __init__(self, missing: List[str]) -> None:
        self.missing = missing
        super().__init__(
            "Your outreach identity is not configured yet. Missing: " + ", ".join(missing)
        )


# --------------------------------------------------------------------------


# Word endings that mark a category as naming the *practitioner* ("plumber",
# "dentist"), which pluralizes naturally. Anything else reads better as
# "<category> businesses" than as a forced plural ("web testings").
_TRADE_SUFFIXES = ("er", "or", "ist", "ian", "eur", "smith", "wright", "ess", "ant", "ard")
_NON_COUNTABLE_SUFFIXES = ("ing", "al", "ance", "ence", "ment", "care", "work", "repair", "wear")


def _industry_phrase(category: str) -> str:
    c = (category or "").strip().lower()
    if not c:
        return "local businesses"
    c = re.sub(r"\s*[|/,].*$", "", c).strip()
    c = re.sub(r"\b(services?|companies|company|businesses|business)\b", "", c).strip()
    c = re.sub(r"\s+", " ", c)
    if not c:
        return "local businesses"

    words = c.split()
    if len(words) > 1:
        return f"{c} businesses"

    w = words[0]
    if w.endswith("s") and not w.endswith("ss"):
        return w  # already plural
    if w.endswith(_NON_COUNTABLE_SUFFIXES):
        return f"{w} businesses"
    if w.endswith(_TRADE_SUFFIXES):
        return _pluralize(w)
    if w.endswith("y") and not w.endswith(("ay", "ey", "oy", "uy")):
        return w[:-1] + "ies"
    return f"{w} businesses"


def _pluralize(word: str) -> str:
    if word.endswith(("s", "sh", "ch", "x", "z")):
        return word + "es"
    if word.endswith("y") and not word.endswith(("ay", "ey", "oy", "uy")):
        return word[:-1] + "ies"
    return word + "s"


def _area_phrase(ctx: OutreachContext) -> str:
    for part in (ctx.city, ctx.state, ctx.country):
        if part and part.strip():
            return part.strip()
    return "your area"


def _name_suffix(contact_name: str) -> str:
    if not contact_name:
        return ""
    first = contact_name.strip().split()[0]
    return f" {first}" if first else ""


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Observation lines are authored to sit mid-sentence ("...noticed {line}"), so
# they already start lowercase where that is correct. The two that legitimately
# begin with a capital - "I couldn't find..." and "Google's PageSpeed..." - must
# keep it, so nothing is re-cased on the way in.
def _inline(line: str) -> str:
    return line


def _sentence_case(line: str) -> str:
    """Uppercase the first character only. str.capitalize() would lowercase the
    remainder and turn "Google's PageSpeed" into "Google's pagespeed"."""
    return line[0].upper() + line[1:] if line else line


# A quiet credibility reference, never a sales CTA - included in every channel
# only when the sender configured a portfolio/website URL in Settings. Never
# hardcoded: whoever is running this instance controls what link goes out.
def _portfolio_line(profile: Dict[str, Any], phrasing: str = "quick") -> str:
    url = str(profile.get("website_url", "") or "").strip()
    if not url:
        return ""
    if phrasing == "see":
        return f"You can also see some of my work here: {url}"
    return f"If useful, you can also have a quick look at some of my work here: {url}"


# --------------------------------------------------------------------------
# WhatsApp (spec 19)
# --------------------------------------------------------------------------


def build_whatsapp_message(
    ctx: OutreachContext, profile: Dict[str, Any], variant: str = "initial"
) -> Draft:
    missing = [k for k in ("full_name", "company_name", "service_name") if not str(profile.get(k, "")).strip()]
    if missing:
        raise ProfileIncomplete(missing)

    obs = pick_observations(ctx.problems, seed=_seed_for(ctx.business_id), limit=2)
    if not obs:
        return Draft(
            channel="whatsapp", variant=variant,
            skipped_reason="No measured, describable problem was found, so no message was written.",
        )

    tone = profile.get("tone") if profile.get("tone") in TONE_PACKS else DEFAULT_TONE
    pack = TONE_PACKS[tone]
    seed = _seed_for(ctx.business_id, 1)

    if variant == "initial":
        return _whatsapp_initial(ctx, profile, pack, obs, seed)
    if variant == "followup_1":
        return _whatsapp_followup_1(ctx, profile, pack, obs, seed)
    return _whatsapp_followup_2(ctx, profile, pack, obs, seed)


def _whatsapp_initial(ctx, profile, pack, obs, seed) -> Draft:
    greeting = _pick(pack["greeting"], seed).format(name=_name_suffix(ctx.contact_name))
    intro = _pick(pack["intro"], seed).format(
        business=ctx.business_name,
        industry=_industry_phrase(ctx.category),
        area=_area_phrase(ctx),
        my_company=profile.get("company_name", ""),
        my_name=profile.get("full_name", ""),
    )

    portfolio = _portfolio_line(profile, "quick")

    if ctx.audit_kind == "no_website":
        body = f"{_sentence_case(obs[0]['line'])}."
        offer = (
            f"I build simple, fast sites for {_industry_phrase(ctx.category)} — "
            f"the kind that show up in search and make it easy to get in touch."
        )
        cta = "Would it be worth a quick chat about what that would look like?"
        parts = [f"{greeting}", "", intro, "", body, "", offer, "", cta]
    else:
        bridge = _pick(pack["bridge"], seed).format(
            observation=_inline(obs[0]["line"])
        )
        second = ""
        if len(obs) > 1:
            second = _pick(pack["second"], seed).format(
                observation=_inline(obs[1]["line"])
            )
        offer = _pick(pack["offer"], seed) if ctx.report_available else ""
        cta = _pick(pack["cta"], seed) if ctx.report_available else (
            "Happy to explain what I'd change if that's useful."
        )
        parts = [greeting, "", intro, "", bridge]
        if second:
            parts.append(second)
        if offer:
            parts += ["", offer]
        parts += ["", cta]

    if portfolio:
        parts += ["", portfolio]

    message = _clean("\n".join(parts))
    return Draft(
        channel="whatsapp", variant="initial", message=message,
        based_on=[{"code": o["code"], "observation": o["line"]} for o in obs],
    )


def _whatsapp_followup_1(ctx, profile, pack, obs, seed) -> Draft:
    topic = obs[0]["topic"]
    message = _clean(
        f"Hi{_name_suffix(ctx.contact_name)}, following up on my last message about the "
        f"{topic} on your site.\n\n"
        f"No pressure at all — if it's not a priority right now that's completely fine. "
        f"Just let me know either way and I'll leave it there."
    )
    return Draft(
        channel="whatsapp", variant="followup_1", message=message,
        based_on=[{"code": obs[0]["code"], "observation": obs[0]["line"]}],
    )


def _whatsapp_followup_2(ctx, profile, pack, obs, seed) -> Draft:
    message = _clean(
        f"Hi{_name_suffix(ctx.contact_name)}, last message from me on this — I don't want to "
        f"clutter your inbox.\n\n"
        f"The notes on {ctx.business_name}'s site are yours if you ever want them, "
        f"no strings. All the best either way."
    )
    return Draft(
        channel="whatsapp", variant="followup_2", message=message,
        based_on=[{"code": obs[0]["code"], "observation": obs[0]["line"]}] if obs else [],
    )


# --------------------------------------------------------------------------
# Email (spec 21)
# --------------------------------------------------------------------------

SUBJECT_TEMPLATES = [
    "Quick note about {business}'s website",
    "{business} — {short}",
    "Noticed something on your website",
    "One thing on the {business} site",
]


def build_email_message(
    ctx: OutreachContext, profile: Dict[str, Any], variant: str = "initial"
) -> Draft:
    missing = [
        k for k in ("full_name", "company_name", "service_name", "email")
        if not str(profile.get(k, "")).strip()
    ]
    if missing:
        raise ProfileIncomplete(missing)

    obs = pick_observations(ctx.problems, seed=_seed_for(ctx.business_id), limit=2)
    if not obs:
        return Draft(
            channel="email", variant=variant,
            skipped_reason="No measured, describable problem was found, so no message was written.",
        )

    tone = profile.get("tone") if profile.get("tone") in TONE_PACKS else DEFAULT_TONE
    pack = TONE_PACKS[tone]
    seed = _seed_for(ctx.business_id, 2)

    if variant == "followup_1":
        subject = f"Re: {SUBJECT_TEMPLATES[0].format(business=ctx.business_name)}"
        body = _clean(
            f"Hi{_name_suffix(ctx.contact_name)},\n\n"
            f"Just following up on my note about the {obs[0]['topic']} on your website.\n\n"
            f"If it's not something you're looking at right now, no problem at all — "
            f"a one-line reply and I'll stop there.\n\n"
            f"{_signature(profile)}"
        )
        return Draft(channel="email", variant=variant, subject=subject, message=body,
                     based_on=[{"code": obs[0]["code"], "observation": obs[0]["line"]}])

    if variant == "followup_2":
        subject = f"Re: {SUBJECT_TEMPLATES[0].format(business=ctx.business_name)}"
        body = _clean(
            f"Hi{_name_suffix(ctx.contact_name)},\n\n"
            f"Last note from me on this one.\n\n"
            f"The write-up on {ctx.business_name}'s site is yours if you ever want it — "
            f"just reply and I'll send it over. Otherwise I'll leave you to it.\n\n"
            f"{_signature(profile)}"
        )
        return Draft(channel="email", variant=variant, subject=subject, message=body,
                     based_on=[{"code": obs[0]["code"], "observation": obs[0]["line"]}])

    subject = _pick(SUBJECT_TEMPLATES, seed).format(
        business=ctx.business_name, short=obs[0]["short"]
    )

    greeting = _pick(pack["greeting"], seed).format(name=_name_suffix(ctx.contact_name))
    intro = _pick(pack["intro"], seed).format(
        business=ctx.business_name,
        industry=_industry_phrase(ctx.category),
        area=_area_phrase(ctx),
        my_company=profile.get("company_name", ""),
        my_name=profile.get("full_name", ""),
    )

    if ctx.audit_kind == "no_website":
        bridge = f"{_sentence_case(obs[0]['line'])}."
        value = (
            f"I build straightforward websites for {_industry_phrase(ctx.category)} — "
            f"clear services, easy to contact, and set up to be found in search."
        )
        cta = "If that's something you've been meaning to sort out, I'm happy to talk it through."
        blocks = [greeting, "", intro, "", bridge, "", value, "", cta]
    else:
        bridge = _pick(pack["bridge"], seed).format(
            observation=_inline(obs[0]["line"])
        )
        blocks = [greeting, "", intro, "", bridge]
        if len(obs) > 1:
            blocks.append(
                _pick(pack["second"], seed).format(
                    observation=_inline(obs[1]["line"])
                )
            )
        if obs[0].get("value"):
            blocks += ["", f"It's the kind of thing that's {obs[0]['value']}."]
        if ctx.report_available:
            blocks += ["", _pick(pack["offer"], seed)]
        blocks += ["", _pick(pack["cta"], seed)]

    booking = str(profile.get("booking_url", "") or "").strip()
    if booking and ctx.report_available:
        blocks += ["", f"If it's easier to talk it through, my calendar is here: {booking}"]

    portfolio = _portfolio_line(profile, "see")
    if portfolio:
        blocks += ["", portfolio]

    blocks += ["", _signature(profile)]
    message = _clean("\n".join(blocks))

    return Draft(
        channel="email", variant="initial", subject=subject, message=message,
        based_on=[{"code": o["code"], "observation": o["line"]} for o in obs],
    )


def _signature(profile: Dict[str, Any]) -> str:
    custom = str(profile.get("email_signature", "") or "").strip()
    if custom:
        return custom
    lines = [
        TONE_PACKS.get(profile.get("tone", DEFAULT_TONE), TONE_PACKS[DEFAULT_TONE])["signoff"][0],
        str(profile.get("full_name", "")).strip(),
    ]
    company = str(profile.get("company_name", "")).strip()
    if company:
        lines.append(company)
    site = str(profile.get("website_url", "")).strip()
    if site:
        lines.append(site)
    phone = str(profile.get("whatsapp_number", "")).strip()
    if phone:
        lines.append(phone)
    return "\n".join(l for l in lines if l)


def mailto_url(to: str, subject: str, body: str) -> str:
    if not to:
        return ""
    return (
        f"mailto:{quote(to, safe='@')}"
        f"?subject={quote(subject, safe='')}"
        f"&body={quote(body, safe='')}"
    )


# --------------------------------------------------------------------------
# LinkedIn (contact routing step 3 - company page only, never a personal
# profile). Kept deliberately short: this is a message context, not a pitch.
# --------------------------------------------------------------------------


def build_linkedin_message(
    ctx: OutreachContext, profile: Dict[str, Any], variant: str = "initial"
) -> Draft:
    missing = [k for k in ("full_name", "company_name", "service_name") if not str(profile.get(k, "")).strip()]
    if missing:
        raise ProfileIncomplete(missing)

    obs = pick_observations(ctx.problems, seed=_seed_for(ctx.business_id), limit=1)
    if not obs:
        return Draft(
            channel="linkedin", variant=variant,
            skipped_reason="No measured, describable problem was found, so no message was written.",
        )

    tone = profile.get("tone") if profile.get("tone") in TONE_PACKS else DEFAULT_TONE
    pack = TONE_PACKS[tone]
    seed = _seed_for(ctx.business_id, 5)

    greeting = _pick(pack["greeting"], seed).format(name=_name_suffix(ctx.contact_name))
    intro = (
        f"{greeting} came across {ctx.business_name} and had a quick look at the website."
    )
    observation = f"I noticed {_inline(obs[0]['line'])}."
    offer = (
        "I work on website/automation improvements and had a couple of ideas around this. "
        "Happy to share the short breakdown if useful."
    )
    site = str(profile.get("website_url", "") or "").strip()

    parts = [intro, "", observation, "", offer]
    if site:
        parts += ["", f"My work:\n{site}"]
    message = _clean("\n".join(parts))

    return Draft(
        channel="linkedin", variant="initial", message=message,
        based_on=[{"code": obs[0]["code"], "observation": obs[0]["line"]}],
    )


# --------------------------------------------------------------------------
# Call list (spec 22)
# --------------------------------------------------------------------------


def build_call_notes(ctx: OutreachContext, profile: Dict[str, Any]) -> Draft:
    missing = [k for k in ("full_name", "company_name") if not str(profile.get(k, "")).strip()]
    if missing:
        raise ProfileIncomplete(missing)

    obs = pick_observations(ctx.problems, seed=_seed_for(ctx.business_id, 3), limit=2)
    if not obs:
        return Draft(
            channel="call", variant="initial",
            skipped_reason="No measured problem was found, so no call opener was written.",
        )

    name = profile.get("full_name", "")
    company = profile.get("company_name", "")

    if ctx.audit_kind == "no_website":
        opener = (
            f"Hi, is that {ctx.business_name}? My name's {name} from {company}. "
            f"I was looking for your website and couldn't find one — "
            f"is that right, or am I missing it?"
        )
    else:
        opener = (
            f"Hi, is that {ctx.business_name}? My name's {name} from {company}. "
            f"I was looking at your website earlier and noticed {obs[0]['line']}. "
            f"Is the website something you look after yourself?"
        )

    lines = [
        f"OPENER: {opener}",
        "",
        "WHAT I ACTUALLY MEASURED:",
    ]
    for i, o in enumerate(obs, 1):
        lines.append(f"  {i}. {_sentence_case(o['line'])}.")
    if ctx.score is not None:
        lines += ["", f"Opportunity score: {ctx.score}/100 across {len(ctx.problems)} detected issues."]
    if ctx.website:
        lines.append(f"Website: {ctx.website}")
    lines += [
        "",
        "IF THEY ENGAGE: offer to send the written breakdown "
        f"({'the audit report is generated and ready' if ctx.report_available else 'generate the report first'}).",
        "IF NOT INTERESTED: thank them and close. Do not push.",
    ]

    return Draft(
        channel="call", variant="initial",
        subject=obs[0]["short"],
        message=_clean("\n".join(lines)),
        based_on=[{"code": o["code"], "observation": o["line"]} for o in obs],
    )


# --------------------------------------------------------------------------
# Channel selection (spec 6, 53)
# --------------------------------------------------------------------------


def choose_channel(
    *,
    whatsapp_status: str,
    whatsapp_number: str,
    usable_email: Optional[str],
    email_status: str,
    linkedin_url: str = "",
    phone_normalized: str,
    phone_status: str,
) -> Dict[str, str]:
    """
    Priority: WhatsApp (strict) -> Email -> LinkedIn -> Phone -> skip.

    WhatsApp is chosen ONLY when there is real evidence - a WhatsApp link
    actually published on the business's own website for this exact number.
    A phone number being a WhatsApp-capable mobile is not, on its own,
    evidence that WhatsApp is usable, so it never drives channel selection by
    itself (spec: a Google Maps / CSV phone number must not automatically be
    treated as a WhatsApp number).
    """
    if whatsapp_status == "confirmed_on_website" and whatsapp_number:
        return {
            "channel": "whatsapp",
            "reason": "Website contains confirmed WhatsApp link.",
        }

    if usable_email:
        return {
            "channel": "email",
            "reason": "No confirmed WhatsApp; public business email found on the website "
                      f"(status: {email_status}).",
        }

    if linkedin_url:
        return {
            "channel": "linkedin",
            "reason": "No WhatsApp/email; verified company LinkedIn page found on the website.",
        }

    if phone_normalized and phone_status in ("valid", "possible"):
        return {
            "channel": "phone",
            "reason": "No WhatsApp/email/LinkedIn; valid phone number available.",
        }

    return {
        "channel": "none",
        "reason": "No usable contact channel: no confirmed WhatsApp, no public email, "
                  "no LinkedIn page and no valid phone number.",
    }
