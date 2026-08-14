"""
Optional Google PageSpeed Insights integration (spec 12, 35).

Disabled unless the user supplies their own API key in Settings. The key is
held server-side only and never returned to the frontend unmasked. If the
API is unavailable, the result carries `measured: False` and the audit
reports no performance score rather than inventing one.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

_semaphore = asyncio.Semaphore(2)  # respect the API's rate limits


async def measure(
    url: str,
    api_key: str,
    strategy: str = "mobile",
    timeout_s: float = 60.0,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "measured": False,
        "strategy": strategy,
        "url": url,
        "source": "Google PageSpeed Insights API",
    }
    if not api_key:
        out["error"] = "not_configured"
        out["error_message"] = "No PageSpeed API key is configured."
        return out

    params = {
        "url": url,
        "key": api_key,
        "strategy": strategy,
        "category": "performance",
    }

    try:
        async with _semaphore:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get(ENDPOINT, params=params)
    except httpx.TimeoutException:
        out["error"] = "timeout"
        out["error_message"] = f"PageSpeed did not respond within {timeout_s:.0f}s."
        return out
    except httpx.HTTPError as exc:
        out["error"] = "http_error"
        out["error_message"] = f"PageSpeed request failed: {exc}"
        return out

    if resp.status_code != 200:
        out["error"] = f"http_{resp.status_code}"
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            detail = resp.text[:300]
        out["error_message"] = f"PageSpeed returned HTTP {resp.status_code}: {detail}"
        return out

    try:
        data = resp.json()
    except Exception as exc:
        out["error"] = "parse_error"
        out["error_message"] = f"Could not parse the PageSpeed response: {exc}"
        return out

    lighthouse = data.get("lighthouseResult") or {}
    categories = lighthouse.get("categories") or {}
    audits = lighthouse.get("audits") or {}

    perf = (categories.get("performance") or {}).get("score")
    if perf is None:
        out["error"] = "no_score"
        out["error_message"] = "PageSpeed returned no performance score for this URL."
        return out

    out["measured"] = True
    out["performance_score"] = round(perf * 100)
    out["fetched_url"] = lighthouse.get("finalUrl") or url
    out["lighthouse_version"] = lighthouse.get("lighthouseVersion", "")

    def num(key: str) -> Optional[float]:
        a = audits.get(key) or {}
        v = a.get("numericValue")
        return round(float(v), 3) if isinstance(v, (int, float)) else None

    lcp = num("largest-contentful-paint")
    fcp = num("first-contentful-paint")
    tbt = num("total-blocking-time")
    cls = num("cumulative-layout-shift")
    si = num("speed-index")

    out["lcp_s"] = round(lcp / 1000, 2) if lcp is not None else None
    out["fcp_s"] = round(fcp / 1000, 2) if fcp is not None else None
    out["tbt_ms"] = round(tbt) if tbt is not None else None
    out["cls"] = round(cls, 3) if cls is not None else None
    out["speed_index_s"] = round(si / 1000, 2) if si is not None else None

    opportunities = []
    for key, audit in audits.items():
        details = audit.get("details") or {}
        if details.get("type") != "opportunity":
            continue
        savings = details.get("overallSavingsMs")
        if isinstance(savings, (int, float)) and savings >= 250:
            opportunities.append({
                "id": key,
                "title": audit.get("title", ""),
                "savings_ms": round(savings),
            })
    opportunities.sort(key=lambda o: -o["savings_ms"])
    out["opportunities"] = opportunities[:6]

    # Field data (CrUX), when Google has enough real-user traffic for the site.
    loading = data.get("loadingExperience") or {}
    if loading.get("overall_category"):
        out["field_data_category"] = loading["overall_category"]

    return out


async def check_availability(api_key: str) -> Dict[str, Any]:
    """Used by the System Health page."""
    if not api_key:
        return {"status": "disabled", "detail": "No API key configured (optional integration)."}
    result = await measure("https://example.com", api_key, "mobile", timeout_s=30.0)
    if result.get("measured"):
        return {"status": "healthy", "detail": "PageSpeed API responded successfully."}
    return {
        "status": "error",
        "detail": result.get("error_message", "PageSpeed API did not return a score."),
    }
