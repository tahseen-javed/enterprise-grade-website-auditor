"""
Direct website audits - a single URL typed into the app, rather than an
uploaded CSV/XLSX. Reuses the exact same Job/Business pipeline as an import
(so crawling, checks, scoring, reporting, SSE progress and CSV/XLSX export
all work identically); the only difference is a one-row job created from a
URL instead of an uploaded file, and website discovery skips identity
matching since the user supplied the exact site to audit (see
discovery.verify_direct_website).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.pipeline import manager
from ..core.urls import is_non_website_host, normalize_url, registrable_domain
from ..db import run_db
from ..events import activity
from ..models import Business, Job, JobItem
from ..settings import get_engine

router = APIRouter(prefix="/audits", tags=["audits"])


class QuickAudit(BaseModel):
    url: str
    name: Optional[str] = Field(default=None, max_length=255)
    start_immediately: bool = True


@router.post("/quick")
async def quick_audit(payload: QuickAudit) -> Dict[str, Any]:
    raw = (payload.url or "").strip()
    norm = normalize_url(raw)
    if not norm:
        raise HTTPException(
            status_code=400,
            detail="That does not look like a valid website URL. Include the domain, e.g. "
                   "example.com or https://example.com.",
        )
    is_profile, kind = is_non_website_host(norm)
    if is_profile:
        raise HTTPException(
            status_code=400,
            detail=f"That URL is a {kind.replace('_', ' ')}, not a standalone website, so it "
                   f"cannot be crawled and audited the same way.",
        )

    domain = registrable_domain(norm)
    label = (payload.name or "").strip() or domain or norm

    def _create(s) -> int:
        job = Job(
            name=f"Website audit — {label}"[:255],
            source_filename="", stored_path="",
            source_kind="url",
            original_columns=[], column_mapping={},
            engine_snapshot=get_engine(),
            status="queued", total=1,
        )
        s.add(job)
        s.flush()

        biz = Business(
            job_id=job.id, row_index=0, raw={"url": raw},
            name=label[:512], name_normalized=re.sub(r"[^a-z0-9]+", " ", label.lower()).strip(),
            website_original=norm,
            dedup_key=f"site:{domain}" if domain else "",
        )
        s.add(biz)
        s.flush()

        s.add(JobItem(job_id=job.id, business_id=biz.id, status="pending", stage="queued"))
        return job.id

    job_id = await run_db(_create)
    activity("", f"Direct audit started: {norm}", job_id=job_id, stage="job")

    started = False
    if payload.start_immediately:
        result = await manager.start(job_id)
        started = result.get("started", False)

    business_id = await run_db(
        lambda s: s.query(Business.id).filter(Business.job_id == job_id).scalar(), write=False
    )

    return {
        "job_id": job_id, "business_id": business_id, "url": norm, "started": started,
    }
