"""
Email validation (spec 10).

Layered, and the status never overstates what was actually proven:

  valid_public  - found publicly on the business's own site AND the domain
                  has usable MX records
  mx_valid      - syntax + domain + MX records resolve
  domain_valid  - syntax + the domain resolves (A/AAAA) but no MX found
  syntax_valid  - the address parses correctly, DNS not confirmed
  risky         - disposable domain, or an address unrelated to the site
  invalid       - syntax failure or the domain does not exist
  unknown       - validation could not be completed (DNS timeout, etc.)

Deliverability is never claimed. MX presence means mail *can* be routed to
the domain, not that this mailbox exists.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import dns.exception
import dns.resolver
from email_validator import EmailNotValidError, validate_email

from .extract import ROLE_LOCAL_PARTS, FoundEmail

STATUS_VALID_PUBLIC = "valid_public"
STATUS_MX_VALID = "mx_valid"
STATUS_DOMAIN_VALID = "domain_valid"
STATUS_SYNTAX_VALID = "syntax_valid"
STATUS_RISKY = "risky"
STATUS_INVALID = "invalid"
STATUS_UNKNOWN = "unknown"

DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "temp-mail.org", "throwawaymail.com", "yopmail.com", "sharklasers.com",
    "trashmail.com", "getnada.com", "maildrop.cc", "fakeinbox.com", "dispostable.com",
    "mailnesia.com", "mytemp.email", "spamgourmet.com", "moakt.com", "emailondeck.com",
    "tempinbox.com", "mailcatch.com", "grr.la", "guerrillamailblock.com", "spam4.me",
    "burnermail.io", "33mail.com", "anonaddy.me", "mail.tm", "inboxbear.com",
}

FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.com.au",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com", "aol.com",
    "icloud.com", "me.com", "mac.com", "protonmail.com", "proton.me", "gmx.com",
    "gmx.de", "mail.com", "zoho.com", "yandex.com", "btinternet.com", "bigpond.com",
    "optusnet.com.au", "rediffmail.com", "web.de", "orange.fr", "free.fr",
}


@dataclass
class EmailValidation:
    email: str
    status: str = STATUS_UNKNOWN
    normalized: str = ""
    domain: str = ""
    is_role: bool = False
    is_disposable: bool = False
    is_free_provider: bool = False
    domain_matches_site: bool = False
    mx_records: List[str] = field(default_factory=list)
    has_a_record: bool = False
    notes: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "status": self.status,
            "domain": self.domain,
            "is_role": self.is_role,
            "is_disposable": self.is_disposable,
            "is_free_provider": self.is_free_provider,
            "domain_matches_site": self.domain_matches_site,
            "mx_records": self.mx_records,
            "notes": self.notes,
            "confidence": self.confidence,
        }


# --------------------------------------------------------------------------
# DNS - cached, bounded, and always non-fatal
# --------------------------------------------------------------------------

_dns_cache: Dict[str, Tuple[List[str], bool, str]] = {}
_dns_lock = asyncio.Lock()


def _resolver(timeout: float) -> dns.resolver.Resolver:
    r = dns.resolver.Resolver()
    r.timeout = timeout
    r.lifetime = timeout
    return r


def _lookup_sync(domain: str, timeout: float) -> Tuple[List[str], bool, str]:
    """Returns (mx_hosts, has_a_record, error). Never raises."""
    res = _resolver(timeout)
    mx: List[str] = []
    has_a = False
    err = ""
    try:
        answers = res.resolve(domain, "MX")
        mx = sorted(
            (str(r.exchange).rstrip(".") for r in answers if str(r.exchange).rstrip(".")),
            key=str,
        )
    except dns.resolver.NoAnswer:
        pass
    except dns.resolver.NXDOMAIN:
        return [], False, "nxdomain"
    except (dns.exception.Timeout, dns.resolver.LifetimeTimeout):
        err = "timeout"
    except dns.exception.DNSException as exc:
        err = f"dns_error:{type(exc).__name__}"
    except Exception as exc:
        err = f"dns_error:{exc}"

    if not mx:
        for rtype in ("A", "AAAA"):
            try:
                res.resolve(domain, rtype)
                has_a = True
                break
            except dns.resolver.NXDOMAIN:
                return [], False, "nxdomain"
            except (dns.resolver.NoAnswer, dns.exception.DNSException):
                continue
            except Exception:
                continue
    else:
        has_a = True
    return mx, has_a, err


async def lookup_domain(domain: str, timeout: float = 4.0) -> Tuple[List[str], bool, str]:
    domain = domain.lower().strip(".")
    async with _dns_lock:
        cached = _dns_cache.get(domain)
    if cached is not None:
        return cached

    result = await asyncio.to_thread(_lookup_sync, domain, timeout)
    async with _dns_lock:
        _dns_cache[domain] = result
    return result


# --------------------------------------------------------------------------


async def validate_found_email(
    found: FoundEmail,
    *,
    site_domain: str = "",
    enable_mx: bool = True,
    dns_timeout: float = 4.0,
) -> EmailValidation:
    v = EmailValidation(email=found.email)

    # --- layer 1: syntax --------------------------------------------------
    try:
        info = validate_email(found.email, check_deliverability=False)
        v.normalized = info.normalized.lower()
        v.domain = info.domain.lower()
        v.status = STATUS_SYNTAX_VALID
    except EmailNotValidError as exc:
        v.status = STATUS_INVALID
        v.notes.append(f"Syntax check failed: {exc}")
        v.confidence = 0.0
        return v

    local = v.normalized.split("@", 1)[0]
    v.is_role = local in ROLE_LOCAL_PARTS
    v.is_disposable = v.domain in DISPOSABLE_DOMAINS
    v.is_free_provider = v.domain in FREE_MAIL_DOMAINS
    v.domain_matches_site = bool(site_domain) and v.domain == site_domain.lower()

    if v.is_disposable:
        v.status = STATUS_RISKY
        v.notes.append("The domain is a known disposable/temporary mail provider.")
        v.confidence = 0.1
        return v

    # --- layer 2/3: domain + MX ------------------------------------------
    if not enable_mx:
        v.notes.append("DNS/MX lookup is disabled in settings; DNS was not checked.")
        v.confidence = round(0.45 + 0.1 * found.confidence, 3)
        return v

    mx, has_a, err = await lookup_domain(v.domain, dns_timeout)
    v.mx_records = mx[:6]
    v.has_a_record = has_a

    if err == "nxdomain":
        v.status = STATUS_INVALID
        v.notes.append("The email domain does not exist (NXDOMAIN).")
        v.confidence = 0.0
        return v
    if err.startswith("timeout") or err.startswith("dns_error"):
        v.status = STATUS_UNKNOWN
        v.notes.append(f"DNS lookup could not be completed ({err}); status is unknown.")
        v.confidence = round(0.3 + 0.1 * found.confidence, 3)
        return v

    if mx:
        v.status = STATUS_MX_VALID
        v.notes.append(f"The domain publishes {len(mx)} MX record(s), so it can receive mail.")
    elif has_a:
        v.status = STATUS_DOMAIN_VALID
        v.notes.append("The domain resolves but publishes no MX record.")
    else:
        v.status = STATUS_INVALID
        v.notes.append("The domain does not resolve.")
        v.confidence = 0.0
        return v

    # --- layer 4: publicly-sourced on the business's own domain ----------
    if v.status == STATUS_MX_VALID and v.domain_matches_site and found.source_type in (
        "mailto", "text", "jsonld", "footer", "obfuscated"
    ):
        v.status = STATUS_VALID_PUBLIC
        v.notes.append(
            f"Published on the business's own website ({found.page_type} page) and the "
            f"domain accepts mail."
        )
    elif v.status == STATUS_MX_VALID and not v.domain_matches_site and not v.is_free_provider:
        v.notes.append(
            "The address is on a different domain from the website; confirm it belongs "
            "to this business before using it."
        )

    conf = 0.35
    conf += {
        STATUS_VALID_PUBLIC: 0.55, STATUS_MX_VALID: 0.4, STATUS_DOMAIN_VALID: 0.2,
        STATUS_SYNTAX_VALID: 0.1,
    }.get(v.status, 0.0)
    conf += 0.1 * found.confidence
    if v.domain_matches_site:
        conf += 0.05
    v.confidence = round(min(0.99, conf), 3)

    v.notes.append("Deliverability of the individual mailbox was not tested.")
    return v


async def validate_all(
    emails: List[FoundEmail],
    *,
    site_domain: str = "",
    enable_mx: bool = True,
    dns_timeout: float = 4.0,
    limit: int = 5,
) -> List[EmailValidation]:
    subset = emails[:limit]
    if not subset:
        return []
    results = await asyncio.gather(
        *(
            validate_found_email(
                e, site_domain=site_domain, enable_mx=enable_mx, dns_timeout=dns_timeout
            )
            for e in subset
        ),
        return_exceptions=True,
    )
    out: List[EmailValidation] = []
    for found, r in zip(subset, results):
        if isinstance(r, EmailValidation):
            out.append(r)
        else:
            ev = EmailValidation(email=found.email, status=STATUS_UNKNOWN)
            ev.notes.append(f"Validation failed unexpectedly: {r}")
            out.append(ev)
    return out


USABLE_STATUSES = {STATUS_VALID_PUBLIC, STATUS_MX_VALID, STATUS_DOMAIN_VALID}


def is_usable_for_outreach(status: str) -> bool:
    return status in USABLE_STATUSES
