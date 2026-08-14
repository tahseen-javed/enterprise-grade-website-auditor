"""
Runtime configuration.

Two distinct layers, deliberately kept apart:

1. `RuntimeConfig` - infrastructure settings (ports, paths, worker counts,
   crawl limits). Safe technical defaults, overridable via environment.
2. `UserProfile` / `ScoringWeights` - user identity + tuning, stored in
   data/config/*.json. NEVER hardcoded, NEVER guessed. The app refuses to
   generate outreach until the user fills these in through Settings.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# The built frontend (frontend/dist, produced by `npm run build` - setup.bat
# does this automatically). The backend serves it directly when present, so
# the packaged app is a single process on a single port. Shared here so both
# main.py (serving) and the health check (reporting) agree on one definition.
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

DATA_DIR = Path(os.environ.get("WAE_DATA_DIR", PROJECT_ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
REPORT_DIR = DATA_DIR / "reports"
CONFIG_DIR = DATA_DIR / "config"
LOG_DIR = DATA_DIR / "logs"
RUN_DIR = DATA_DIR / "run"

for _d in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR, REPORT_DIR, CONFIG_DIR, LOG_DIR, RUN_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "app.db"

PROFILE_FILE = CONFIG_DIR / "profile.json"
WEIGHTS_FILE = CONFIG_DIR / "weights.json"
ENGINE_FILE = CONFIG_DIR / "engine.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Infrastructure config (technical defaults are fine here)
# --------------------------------------------------------------------------


class RuntimeConfig:
    BACKEND_HOST: str = os.environ.get("WAE_BACKEND_HOST", "127.0.0.1")
    BACKEND_PORT: int = _env_int("WAE_BACKEND_PORT", 8001)
    FRONTEND_PORT: int = _env_int("WAE_FRONTEND_PORT", 5174)

    # CSV upload guard
    MAX_UPLOAD_BYTES: int = _env_int("WAE_MAX_UPLOAD_BYTES", 64 * 1024 * 1024)

    APP_NAME = "Advanced Website Auditor"
    APP_SHORT = "Website Auditor"
    VERSION = "1.0.0"

    @classmethod
    def cors_origins(cls) -> List[str]:
        raw = os.environ.get("WAE_CORS_ORIGINS", "")
        if raw.strip():
            return [o.strip() for o in raw.split(",") if o.strip()]
        ports = {cls.FRONTEND_PORT, 5173, 5174}
        out: List[str] = []
        for p in sorted(ports):
            out.append(f"http://localhost:{p}")
            out.append(f"http://127.0.0.1:{p}")
        return out


config = RuntimeConfig()


# --------------------------------------------------------------------------
# JSON-backed config store
# --------------------------------------------------------------------------

_store_lock = threading.RLock()


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    with _store_lock:
        if not path.exists():
            return dict(default)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return dict(default)
            merged = dict(default)
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            return dict(default)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    with _store_lock:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


# --------------------------------------------------------------------------
# User profile - the outreach identity. All blank by default, on purpose.
# --------------------------------------------------------------------------

TONES = ["professional", "friendly", "consultant", "founder"]

PROFILE_DEFAULTS: Dict[str, Any] = {
    "full_name": "",
    "company_name": "",
    "whatsapp_number": "",       # must include country code
    "email": "",
    "website_url": "",
    "service_name": "",          # e.g. "website redesign"
    "target_service": "",        # e.g. "local service businesses"
    "booking_url": "",
    "email_signature": "",
    "tone": "professional",
    "target_countries": [],
    "target_industries": [],
}

# Fields without which no outreach may be generated.
PROFILE_REQUIRED = ["full_name", "company_name", "service_name"]
# Channel-specific requirements.
PROFILE_REQUIRED_WHATSAPP = ["whatsapp_number"]
PROFILE_REQUIRED_EMAIL = ["email"]


def get_profile() -> Dict[str, Any]:
    return _read_json(PROFILE_FILE, PROFILE_DEFAULTS)


def save_profile(patch: Dict[str, Any]) -> Dict[str, Any]:
    current = get_profile()
    for k, v in patch.items():
        if k in PROFILE_DEFAULTS:
            current[k] = v
    if current.get("tone") not in TONES:
        current["tone"] = "professional"
    _write_json(PROFILE_FILE, current)
    return current


def profile_status() -> Dict[str, Any]:
    """What the UI shows on the setup banner, and what the engine gates on."""
    p = get_profile()

    def missing(keys: List[str]) -> List[str]:
        return [k for k in keys if not str(p.get(k, "")).strip()]

    core_missing = missing(PROFILE_REQUIRED)
    return {
        "configured": not core_missing,
        "missing_core": core_missing,
        "missing_for_whatsapp": missing(PROFILE_REQUIRED_WHATSAPP),
        "missing_for_email": missing(PROFILE_REQUIRED_EMAIL),
    }


# --------------------------------------------------------------------------
# Scoring weights - transparent + user-tunable (spec 15)
# --------------------------------------------------------------------------

WEIGHTS_DEFAULTS: Dict[str, Any] = {
    "weights": {
        "technical": 20,
        "mobile": 20,
        "conversion": 25,
        "trust": 15,
        "contact": 10,
        "content": 10,
    },
    "tiers": [
        {"name": "Very High", "min": 90, "key": "very_high"},
        {"name": "High", "min": 75, "key": "high"},
        {"name": "Good", "min": 60, "key": "good"},
        {"name": "Moderate", "min": 40, "key": "moderate"},
        {"name": "Low", "min": 0, "key": "low"},
    ],
    "max_problems": 7,
    "min_problems_for_outreach": 1,
}


def get_weights() -> Dict[str, Any]:
    return _read_json(WEIGHTS_FILE, WEIGHTS_DEFAULTS)


def save_weights(patch: Dict[str, Any]) -> Dict[str, Any]:
    current = get_weights()
    if "weights" in patch and isinstance(patch["weights"], dict):
        w = dict(current["weights"])
        for k, v in patch["weights"].items():
            if k in WEIGHTS_DEFAULTS["weights"]:
                try:
                    w[k] = max(0, int(v))
                except (TypeError, ValueError):
                    pass
        current["weights"] = w
    for key in ("max_problems", "min_problems_for_outreach"):
        if key in patch:
            try:
                current[key] = max(1, int(patch[key]))
            except (TypeError, ValueError):
                pass
    _write_json(WEIGHTS_FILE, current)
    return current


# --------------------------------------------------------------------------
# Engine config - crawler + concurrency + optional integrations
# --------------------------------------------------------------------------

ENGINE_DEFAULTS: Dict[str, Any] = {
    # concurrency
    "workers": 5,                    # 1..20
    "per_domain_concurrency": 2,
    "per_domain_delay_ms": 750,      # politeness delay between hits on one host

    # crawl budget
    "max_pages_per_site": 12,
    "max_crawl_depth": 2,
    "request_timeout_s": 20.0,
    "total_site_budget_s": 90.0,
    "max_retries": 2,
    "backoff_base_s": 1.5,
    "max_page_bytes": 3 * 1024 * 1024,

    "respect_robots": True,
    "user_agent": (
        "Mozilla/5.0 (compatible; WebsiteAuditBot/1.0; local business website audit; "
        "+contact via site owner)"
    ),
    "verify_ssl": True,

    # discovery
    "enable_website_discovery": True,   # guess domain from business name when CSV lacks one
    "min_identity_confidence": 0.55,

    # contact routing (WhatsApp -> email -> LinkedIn -> phone -> skip). By
    # default LinkedIn is only looked for once WhatsApp/email both come up
    # empty (short-circuit, spec 17); this forces it to always be checked.
    "full_contact_discovery": False,

    # email validation
    "enable_mx_lookup": True,
    "dns_timeout_s": 4.0,

    # optional integrations - all OFF until the user supplies a key
    "pagespeed_enabled": False,
    "pagespeed_api_key": "",
    "pagespeed_strategy": "mobile",

    "llm_polish_enabled": False,
    "llm_api_key": "",
    "llm_model": "claude-sonnet-5",

    "playwright_enabled": False,     # optional rendered-mobile engine

    "google_places_enabled": False,
    "google_places_api_key": "",
}

_SECRET_KEYS = {"pagespeed_api_key", "llm_api_key", "google_places_api_key"}


def get_engine() -> Dict[str, Any]:
    e = _read_json(ENGINE_FILE, ENGINE_DEFAULTS)
    try:
        e["workers"] = max(1, min(20, int(e.get("workers", 5))))
    except (TypeError, ValueError):
        e["workers"] = 5
    return e


def save_engine(patch: Dict[str, Any]) -> Dict[str, Any]:
    current = get_engine()
    for k, v in patch.items():
        if k not in ENGINE_DEFAULTS:
            continue
        # Never let the UI blank a stored secret by echoing back the mask.
        if k in _SECRET_KEYS and isinstance(v, str) and set(v.strip()) == {"*"}:
            continue
        current[k] = v
    try:
        current["workers"] = max(1, min(20, int(current.get("workers", 5))))
    except (TypeError, ValueError):
        current["workers"] = 5
    _write_json(ENGINE_FILE, current)
    return current


def engine_public() -> Dict[str, Any]:
    """Engine config with secrets masked - this is what the frontend may see."""
    e = get_engine()
    out = dict(e)
    for k in _SECRET_KEYS:
        val = str(e.get(k, "") or "")
        out[k] = "********" if val else ""
        out[k + "_set"] = bool(val)
    return out
