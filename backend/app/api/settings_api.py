"""Settings endpoints. Secrets are stored server-side and returned masked (spec 45)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..settings import (
    TONES,
    engine_public,
    get_profile,
    get_weights,
    profile_status,
    save_engine,
    save_profile,
    save_weights,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class ProfilePatch(BaseModel):
    full_name: Optional[str] = None
    company_name: Optional[str] = None
    whatsapp_number: Optional[str] = None
    email: Optional[str] = None
    website_url: Optional[str] = None
    service_name: Optional[str] = None
    target_service: Optional[str] = None
    booking_url: Optional[str] = None
    email_signature: Optional[str] = None
    tone: Optional[str] = None
    target_countries: Optional[List[str]] = None
    target_industries: Optional[List[str]] = None


class EnginePatch(BaseModel):
    workers: Optional[int] = Field(default=None, ge=1, le=20)
    per_domain_concurrency: Optional[int] = Field(default=None, ge=1, le=8)
    per_domain_delay_ms: Optional[int] = Field(default=None, ge=0, le=10000)
    max_pages_per_site: Optional[int] = Field(default=None, ge=1, le=60)
    max_crawl_depth: Optional[int] = Field(default=None, ge=1, le=5)
    request_timeout_s: Optional[float] = Field(default=None, ge=3, le=120)
    total_site_budget_s: Optional[float] = Field(default=None, ge=10, le=600)
    max_retries: Optional[int] = Field(default=None, ge=0, le=6)
    backoff_base_s: Optional[float] = Field(default=None, ge=0.2, le=10)
    max_page_bytes: Optional[int] = Field(default=None, ge=100_000)
    respect_robots: Optional[bool] = None
    user_agent: Optional[str] = None
    verify_ssl: Optional[bool] = None
    enable_website_discovery: Optional[bool] = None
    min_identity_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    full_contact_discovery: Optional[bool] = None
    enable_mx_lookup: Optional[bool] = None
    dns_timeout_s: Optional[float] = Field(default=None, ge=1, le=20)
    pagespeed_enabled: Optional[bool] = None
    pagespeed_api_key: Optional[str] = None
    pagespeed_strategy: Optional[str] = None
    llm_polish_enabled: Optional[bool] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    playwright_enabled: Optional[bool] = None
    google_places_enabled: Optional[bool] = None
    google_places_api_key: Optional[str] = None


class WeightsPatch(BaseModel):
    weights: Optional[Dict[str, int]] = None
    max_problems: Optional[int] = Field(default=None, ge=1, le=15)
    min_problems_for_outreach: Optional[int] = Field(default=None, ge=1, le=10)


@router.get("")
def read_all() -> Dict[str, Any]:
    return {
        "profile": get_profile(),
        "profile_status": profile_status(),
        "engine": engine_public(),
        "scoring": get_weights(),
        "tones": TONES,
    }


@router.get("/profile")
def read_profile() -> Dict[str, Any]:
    return {"profile": get_profile(), "status": profile_status(), "tones": TONES}


@router.put("/profile")
def update_profile(patch: ProfilePatch) -> Dict[str, Any]:
    saved = save_profile(patch.model_dump(exclude_none=True))
    return {"profile": saved, "status": profile_status()}


@router.get("/engine")
def read_engine() -> Dict[str, Any]:
    return {"engine": engine_public()}


@router.put("/engine")
def update_engine(patch: EnginePatch) -> Dict[str, Any]:
    save_engine(patch.model_dump(exclude_none=True))
    return {"engine": engine_public()}


@router.get("/scoring")
def read_scoring() -> Dict[str, Any]:
    return {"scoring": get_weights()}


@router.put("/scoring")
def update_scoring(patch: WeightsPatch) -> Dict[str, Any]:
    saved = save_weights(patch.model_dump(exclude_none=True))
    return {"scoring": saved}
