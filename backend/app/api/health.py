"""Health and System Health endpoints (spec 51)."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import sys
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter

from .. import db as dbmod
from ..core import pagespeed as ps
from ..core.pipeline import manager
from ..events import bus
from ..settings import (
    DATA_DIR,
    EXPORT_DIR,
    FRONTEND_DIST,
    REPORT_DIR,
    UPLOAD_DIR,
    config,
    engine_public,
    get_engine,
    profile_status,
)

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "app": config.APP_NAME, "version": config.VERSION}


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


async def _check_dns() -> Dict[str, Any]:
    try:
        import dns.resolver

        def _q():
            r = dns.resolver.Resolver()
            r.timeout = 3
            r.lifetime = 3
            return r.resolve("google.com", "A")

        await asyncio.to_thread(_q)
        return {"status": "healthy", "detail": "DNS resolution is working."}
    except Exception as exc:
        return {
            "status": "error",
            "detail": f"DNS lookups are failing ({type(exc).__name__}). Email MX validation "
                      f"will report 'unknown'.",
        }


async def _check_outbound() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get("https://example.com")
        if r.status_code < 400:
            return {"status": "healthy", "detail": f"Outbound HTTPS works (example.com → {r.status_code})."}
        return {"status": "warning", "detail": f"Outbound request returned HTTP {r.status_code}."}
    except Exception as exc:
        return {
            "status": "error",
            "detail": f"Outbound HTTPS failed ({type(exc).__name__}: {exc}). The crawler cannot "
                      f"reach websites.",
        }


def _check_fs() -> Dict[str, Any]:
    problems: List[str] = []
    for label, path in (
        ("data", DATA_DIR), ("uploads", UPLOAD_DIR),
        ("exports", EXPORT_DIR), ("reports", REPORT_DIR),
    ):
        if not path.exists():
            problems.append(f"{label} folder is missing")
        elif not os.access(path, os.W_OK):
            problems.append(f"{label} folder is not writable")
    try:
        usage = shutil.disk_usage(DATA_DIR)
        free_gb = usage.free / 1e9
    except OSError:
        free_gb = None

    if problems:
        return {"status": "error", "detail": "; ".join(problems)}
    if free_gb is not None and free_gb < 0.5:
        return {"status": "warning", "detail": f"Only {free_gb:.1f} GB of disk space is free."}
    return {
        "status": "healthy",
        "detail": f"All data folders are writable"
                  + (f"; {free_gb:.1f} GB free." if free_gb is not None else "."),
    }


@router.get("/system/health")
async def system_health() -> Dict[str, Any]:
    engine = get_engine()

    dns_res, outbound = await asyncio.gather(_check_dns(), _check_outbound())

    database = dbmod.healthcheck()
    database_component = {
        "status": "healthy" if database.get("status") == "healthy" else "error",
        "detail": (
            f"SQLite ready ({database.get('journal_mode')}, "
            f"{round(database.get('size_bytes', 0) / 1024)} KB)."
            if database.get("status") == "healthy"
            else database.get("detail", "Database unavailable.")
        ),
    }

    try:
        from selectolax.parser import HTMLParser  # noqa: F401

        crawler_status = {
            "status": "healthy",
            "detail": f"Parser loaded. {engine['workers']} worker(s), "
                      f"{engine['per_domain_concurrency']}/domain, "
                      f"{engine['per_domain_delay_ms']}ms delay, robots "
                      f"{'respected' if engine['respect_robots'] else 'IGNORED'}.",
        }
    except Exception as exc:
        crawler_status = {"status": "error", "detail": f"HTML parser unavailable: {exc}"}

    try:
        import email_validator  # noqa: F401
        import phonenumbers

        validator_status = {
            "status": "healthy",
            "detail": f"email-validator ready; phonenumbers covers "
                      f"{len(phonenumbers.SUPPORTED_REGIONS)} regions.",
        }
    except Exception as exc:
        validator_status = {"status": "error", "detail": f"Validation libraries unavailable: {exc}"}

    if engine.get("pagespeed_enabled") and engine.get("pagespeed_api_key"):
        pagespeed_status = await ps.check_availability(engine["pagespeed_api_key"])
    elif engine.get("pagespeed_enabled"):
        pagespeed_status = {
            "status": "warning",
            "detail": "PageSpeed is enabled but no API key is set, so no performance score "
                      "will be recorded.",
        }
    else:
        pagespeed_status = {
            "status": "disabled",
            "detail": "Optional. Not configured, so no PageSpeed score is claimed.",
        }

    browser_status = (
        {"status": "disabled",
         "detail": "Playwright is not enabled. Mobile findings come from HTML and inline CSS "
                   "and are labelled as such."}
        if not engine.get("playwright_enabled")
        else _playwright_status()
    )

    try:
        from openpyxl import Workbook  # noqa: F401

        export_status = {"status": "healthy", "detail": "CSV, XLSX and HTML export engines ready."}
    except Exception as exc:
        export_status = {"status": "error", "detail": f"XLSX export unavailable: {exc}"}

    backend_busy = _port_in_use(config.BACKEND_PORT)
    frontend_built = (FRONTEND_DIST / "index.html").exists()
    ports_status = {
        "status": "healthy" if (backend_busy and frontend_built) else "warning",
        "detail": (
            f"Port {config.BACKEND_PORT}: {'in use by this app' if backend_busy else 'not bound'}. "
            + (
                "Serving the built dashboard from this same process (frontend/dist)."
                if frontend_built
                else "frontend/dist was not found - run setup.bat to build the dashboard."
            )
        ),
    }

    prof = profile_status()
    profile_component = {
        "status": "healthy" if prof["configured"] else "warning",
        "detail": (
            "Your outreach identity is configured."
            if prof["configured"]
            else "Outreach identity incomplete — missing: " + ", ".join(prof["missing_core"])
            + ". Drafts will not be generated until this is filled in."
        ),
    }

    # Confirming the interpreter is the project venv matters: running against a
    # global Python would silently use different package versions.
    in_venv = sys.prefix != sys.base_prefix
    components = {
        "backend": {
            "status": "healthy" if in_venv else "warning",
            "detail": (
                f"FastAPI {config.VERSION} on Python {sys.version.split()[0]}. "
                f"{len(manager.running_job_ids)} job(s) running. "
                + (
                    f"Running from the project virtual environment ({sys.prefix})."
                    if in_venv
                    else f"NOT running from a virtual environment (prefix {sys.prefix}); "
                         f"package versions may differ from requirements.txt."
                )
            ),
        },
        "database": database_component,
        "crawler": crawler_status,
        "dns": dns_res,
        "outbound_http": outbound,
        "email_validator": validator_status,
        "browser_engine": browser_status,
        "pagespeed": pagespeed_status,
        "export_engine": export_status,
        "file_system": _check_fs(),
        "ports": ports_status,
        "outreach_profile": profile_component,
        "event_stream": {
            "status": "healthy",
            "detail": f"{bus.subscriber_count} dashboard client(s) connected.",
        },
    }

    ranks = {"error": 3, "warning": 2, "healthy": 1, "disabled": 0}
    worst = max((ranks.get(c["status"], 0) for c in components.values()), default=1)
    overall = {3: "error", 2: "warning", 1: "healthy", 0: "healthy"}[worst]

    return {
        "overall": overall,
        "components": components,
        "engine": engine_public(),
        "ports": {"backend": config.BACKEND_PORT, "frontend": config.FRONTEND_PORT},
        "paths": {
            "data": str(DATA_DIR), "uploads": str(UPLOAD_DIR),
            "exports": str(EXPORT_DIR), "reports": str(REPORT_DIR),
        },
    }


def _playwright_status() -> Dict[str, Any]:
    try:
        import playwright  # noqa: F401

        return {"status": "healthy", "detail": "Playwright is installed and enabled."}
    except ImportError:
        return {
            "status": "error",
            "detail": "Playwright is enabled in settings but not installed. Run "
                      "`pip install playwright && playwright install chromium`, or disable it.",
        }
