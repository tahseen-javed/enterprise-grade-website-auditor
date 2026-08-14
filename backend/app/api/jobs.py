"""Job creation, control and statistics."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from ..core.csv_mapping import CsvReadError, read_csv
from ..core.phones import resolve_region
from ..core.pipeline import STAGE_LABELS, manager
from ..core.urls import normalize_url, registrable_domain
from ..db import run_db, session_scope
from ..events import activity, bus
from ..models import (
    AuditError,
    Business,
    ContactEmail,
    ContactPhone,
    EventLog,
    Job,
    JobItem,
    OutreachDraft,
    WebsiteAudit,
    utcnow,
)
from ..settings import REPORT_DIR, UPLOAD_DIR, get_engine

router = APIRouter(prefix="/jobs", tags=["jobs"])


# --------------------------------------------------------------------------


class CreateJob(BaseModel):
    upload_id: str
    name: Optional[str] = None
    mapping: Dict[str, Optional[str]] = Field(default_factory=dict)
    skip_duplicates: bool = True
    start_immediately: bool = True


def _norm_name(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _to_float(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ".").strip())
    except ValueError:
        return None


def _to_int(v: Any) -> Optional[int]:
    if v in (None, ""):
        return None
    digits = re.sub(r"[^\d]", "", str(v))
    return int(digits) if digits else None


@router.post("")
async def create_job(payload: CreateJob) -> Dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", payload.upload_id or ""):
        raise HTTPException(status_code=400, detail="Invalid upload id.")
    path = UPLOAD_DIR / f"{payload.upload_id}.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="That upload no longer exists. Upload the CSV again.")

    mapping = {k: v for k, v in (payload.mapping or {}).items() if v}
    if not mapping.get("business_name"):
        raise HTTPException(
            status_code=400,
            detail="A business name column must be mapped before a job can start.",
        )

    try:
        headers, rows = read_csv(path)
    except CsvReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    for field, column in mapping.items():
        if column not in headers:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{column}' mapped to '{field}' is not present in the file.",
            )

    job_name = (payload.name or "").strip() or f"{Path(path).stem} ({len(rows)} businesses)"

    def _create(s) -> int:
        job = Job(
            name=job_name[:255],
            source_filename=path.name,
            stored_path=str(path),
            original_columns=headers,
            column_mapping=mapping,
            engine_snapshot=get_engine(),
            status="queued",
            total=len(rows),
        )
        s.add(job)
        s.flush()

        seen_keys: Dict[str, int] = {}
        for idx, row in enumerate(rows):
            def cell(field: str) -> str:
                col = mapping.get(field)
                return str(row.get(col, "") or "").strip() if col else ""

            name = cell("business_name")
            website_raw = cell("website")
            phone_raw = cell("phone")
            city = cell("city")

            biz = Business(
                job_id=job.id,
                row_index=idx,
                raw=row,
                name=name or f"(row {idx + 2} has no business name)",
                name_normalized=_norm_name(name),
                category=cell("category"),
                address=cell("address"),
                city=city,
                state=cell("state"),
                country=cell("country"),
                postal_code=cell("postal_code"),
                place_id=cell("place_id"),
                maps_url=cell("google_maps_url"),
                rating=_to_float(cell("rating")),
                review_count=_to_int(cell("review_count")),
                phone_raw=phone_raw,
                website_original=website_raw,
            )
            biz.country_code = resolve_region(
                country=biz.country, state=biz.state, address=biz.address
            ) or ""

            # Dedup key: website domain wins, then place id, then name+city, then phone.
            key = ""
            norm_site = normalize_url(website_raw) if website_raw else None
            if norm_site:
                key = "site:" + registrable_domain(norm_site)
            elif biz.place_id:
                key = "place:" + biz.place_id.lower()
            elif biz.name_normalized:
                key = f"name:{biz.name_normalized}|{_norm_name(city)}"
            elif phone_raw:
                key = "phone:" + re.sub(r"\D", "", phone_raw)
            biz.dedup_key = key

            s.add(biz)
            s.flush()

            is_dup = False
            if key and key in seen_keys:
                biz.is_duplicate_of = seen_keys[key]
                is_dup = True
            elif key:
                seen_keys[key] = biz.id

            item = JobItem(
                job_id=job.id,
                business_id=biz.id,
                status="skipped" if (is_dup and payload.skip_duplicates) else "pending",
                stage="duplicate" if (is_dup and payload.skip_duplicates) else "queued",
            )
            if is_dup and payload.skip_duplicates:
                item.error_message = (
                    f"Duplicate of an earlier row in this file (matched on {key.split(':', 1)[0]}). "
                    f"The original row is preserved in the export."
                )
                item.error_stage = "dedup"
            s.add(item)

        return job.id

    job_id = await run_db(_create)

    dup_count = await run_db(
        lambda s: s.query(func.count(JobItem.id))
        .filter(JobItem.job_id == job_id, JobItem.stage == "duplicate")
        .scalar() or 0,
        write=False,
    )

    activity("", f"Job created: {job_name} — {len(rows)} rows"
                 + (f", {dup_count} duplicate(s) skipped" if dup_count else ""),
             job_id=job_id, stage="job")

    started = False
    if payload.start_immediately:
        result = await manager.start(job_id)
        started = result.get("started", False)

    return {
        "job_id": job_id,
        "name": job_name,
        "total": len(rows),
        "duplicates_skipped": dup_count,
        "started": started,
        "mapping": mapping,
    }


# --------------------------------------------------------------------------


def _job_dto(s, job: Job, include_progress: bool = True) -> Dict[str, Any]:
    counts = dict(
        s.query(JobItem.status, func.count(JobItem.id))
        .filter(JobItem.job_id == job.id)
        .group_by(JobItem.status)
        .all()
    )
    errors = s.query(func.count(AuditError.id)).filter(AuditError.job_id == job.id).scalar() or 0
    live = manager.progress(job.id) if include_progress else None

    total = job.total or sum(counts.values())
    done = counts.get("completed", 0) + counts.get("skipped", 0)
    return {
        "id": job.id,
        "name": job.name,
        "status": job.status,
        "source_kind": job.source_kind or "csv",
        "is_running": manager.is_running(job.id),
        "total": total,
        "counts": {
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
        },
        "processed": done,
        "percent": round(100 * done / total, 1) if total else 0.0,
        "error_count": errors,
        "source_filename": job.source_filename,
        "original_columns": job.original_columns,
        "column_mapping": job.column_mapping,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "last_error": job.last_error,
        "live": live,
    }


@router.get("")
def list_jobs(limit: int = 50) -> Dict[str, Any]:
    with session_scope(write=False) as s:
        jobs = s.query(Job).order_by(Job.id.desc()).limit(max(1, min(200, limit))).all()
        return {"jobs": [_job_dto(s, j) for j in jobs]}


@router.get("/{job_id}")
def get_job(job_id: int) -> Dict[str, Any]:
    with session_scope(write=False) as s:
        job = s.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return _job_dto(s, job)


@router.get("/{job_id}/progress")
def job_progress(job_id: int) -> Dict[str, Any]:
    live = manager.progress(job_id)
    with session_scope(write=False) as s:
        job = s.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        dto = _job_dto(s, job)
    return {"job": dto, "live": live, "stage_labels": STAGE_LABELS}


@router.post("/{job_id}/start")
async def start_job(job_id: int) -> Dict[str, Any]:
    exists = await run_db(lambda s: s.get(Job, job_id) is not None, write=False)
    if not exists:
        raise HTTPException(status_code=404, detail="Job not found.")
    result = await manager.start(job_id)
    if not result.get("started"):
        raise HTTPException(status_code=409, detail=result.get("reason", "Could not start the job."))
    return {"status": "running", "job_id": job_id}


@router.post("/{job_id}/pause")
async def pause_job(job_id: int) -> Dict[str, Any]:
    if not await manager.pause(job_id):
        raise HTTPException(status_code=409, detail="That job is not currently running.")
    return {"status": "paused", "job_id": job_id}


@router.post("/{job_id}/resume")
async def resume_job(job_id: int) -> Dict[str, Any]:
    """Un-pause a live job, or restart a job that was interrupted (spec 28)."""
    if await manager.resume_paused(job_id):
        return {"status": "running", "job_id": job_id, "mode": "unpaused"}

    exists = await run_db(lambda s: s.get(Job, job_id) is not None, write=False)
    if not exists:
        raise HTTPException(status_code=404, detail="Job not found.")

    remaining = await run_db(
        lambda s: s.query(func.count(JobItem.id))
        .filter(JobItem.job_id == job_id, JobItem.status.in_(("pending", "running", "failed")))
        .scalar() or 0,
        write=False,
    )
    if remaining == 0:
        raise HTTPException(status_code=409, detail="Every lead in this job is already processed.")

    result = await manager.start(job_id)
    if not result.get("started"):
        raise HTTPException(status_code=409, detail=result.get("reason", "Could not resume."))
    activity("", f"Job resumed — {remaining} lead(s) still to process",
             job_id=job_id, stage="job")
    return {"status": "running", "job_id": job_id, "mode": "resumed", "remaining": remaining}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: int) -> Dict[str, Any]:
    if not await manager.cancel(job_id):
        raise HTTPException(status_code=409, detail="That job is not currently running.")
    return {"status": "cancelling", "job_id": job_id}


@router.post("/{job_id}/retry-failed")
async def retry_failed(job_id: int) -> Dict[str, Any]:
    def _work(s) -> int:
        items = (
            s.query(JobItem)
            .filter(JobItem.job_id == job_id, JobItem.status == "failed")
            .all()
        )
        for item in items:
            item.status = "pending"
            item.stage = "queued"
            item.error_message = ""
            item.error_stage = ""
        return len(items)

    n = await run_db(_work)
    if n == 0:
        raise HTTPException(status_code=409, detail="There are no failed leads to retry.")
    if not manager.is_running(job_id):
        await manager.start(job_id)
    activity("", f"Retrying {n} failed lead(s)", job_id=job_id, stage="job")
    return {"requeued": n, "job_id": job_id}


@router.delete("/{job_id}")
async def delete_job(job_id: int) -> Dict[str, Any]:
    if manager.is_running(job_id):
        raise HTTPException(
            status_code=409, detail="Stop the job before deleting it."
        )

    def _work(s):
        job = s.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        stored = job.stored_path
        s.query(EventLog).filter(EventLog.job_id == job_id).delete(synchronize_session=False)
        s.query(AuditError).filter(AuditError.job_id == job_id).delete(synchronize_session=False)
        s.delete(job)  # cascades to businesses, items, audits, emails, phones, drafts
        return stored

    stored_path = await run_db(_work)

    # Remove the files this job generated, so deleting a job does not leave the
    # data folder growing. Both paths are checked to be inside their own folder
    # before anything is removed.
    removed = {"reports": 0, "upload": False}

    report_folder = (REPORT_DIR / f"job_{job_id}").resolve()
    if REPORT_DIR.resolve() in report_folder.parents and report_folder.is_dir():
        for f in report_folder.glob("*.html"):
            try:
                f.unlink()
                removed["reports"] += 1
            except OSError:
                pass
        try:
            report_folder.rmdir()
        except OSError:
            pass

    # The stored CSV is this app's own copy of the upload; the user's original
    # file is never touched. Only remove it if no other job still refers to it.
    if stored_path:
        upload = Path(stored_path).resolve()
        if UPLOAD_DIR.resolve() in upload.parents and upload.exists():
            still_used = await run_db(
                lambda s: s.query(func.count(Job.id))
                .filter(Job.stored_path == stored_path)
                .scalar() or 0,
                write=False,
            )
            if not still_used:
                try:
                    upload.unlink()
                    removed["upload"] = True
                except OSError:
                    pass

    return {"deleted": job_id, "files_removed": removed}


# --------------------------------------------------------------------------
# Dashboard statistics (spec 25)
# --------------------------------------------------------------------------


@router.get("/{job_id}/stats")
def job_stats(job_id: int) -> Dict[str, Any]:
    with session_scope(write=False) as s:
        job = s.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return _stats_for(s, job_id)


def _stats_for(s, job_id: Optional[int]) -> Dict[str, Any]:
    bq = s.query(Business)
    iq = s.query(JobItem)
    eq = s.query(AuditError)
    if job_id is not None:
        bq = bq.filter(Business.job_id == job_id)
        iq = iq.filter(JobItem.job_id == job_id)
        eq = eq.filter(AuditError.job_id == job_id)

    total = bq.count()
    item_counts = dict(
        iq.with_entities(JobItem.status, func.count(JobItem.id)).group_by(JobItem.status).all()
    )
    channels = dict(
        bq.with_entities(Business.best_channel, func.count(Business.id))
        .group_by(Business.best_channel).all()
    )
    tiers = dict(
        bq.with_entities(Business.lead_tier, func.count(Business.id))
        .group_by(Business.lead_tier).all()
    )
    opp = dict(
        bq.with_entities(Business.opportunity_tier, func.count(Business.id))
        .group_by(Business.opportunity_tier).all()
    )
    website_status = dict(
        bq.with_entities(Business.website_status, func.count(Business.id))
        .group_by(Business.website_status).all()
    )
    error_codes = dict(
        eq.with_entities(AuditError.code, func.count(AuditError.id))
        .group_by(AuditError.code)
        .order_by(func.count(AuditError.id).desc())
        .limit(12).all()
    )

    processed = bq.filter(Business.processed_at.isnot(None)).count()
    scored = bq.filter(Business.score.isnot(None))
    avg_score = scored.with_entities(func.avg(Business.score)).scalar()
    high_opportunity = bq.filter(Business.score >= 75).count()

    with_email = (
        s.query(func.count(func.distinct(ContactEmail.business_id)))
        .join(Business, Business.id == ContactEmail.business_id)
        .filter(*( [Business.job_id == job_id] if job_id is not None else [] ))
        .scalar() or 0
    )
    wa_usable = (
        s.query(func.count(func.distinct(ContactPhone.business_id)))
        .join(Business, Business.id == ContactPhone.business_id)
        .filter(
            ContactPhone.whatsapp_status.in_(("confirmed_on_website", "usable_unverified")),
            *( [Business.job_id == job_id] if job_id is not None else [] ),
        )
        .scalar() or 0
    )
    drafts = dict(
        s.query(OutreachDraft.channel, func.count(OutreachDraft.id))
        .join(Business, Business.id == OutreachDraft.business_id)
        .filter(OutreachDraft.variant == "initial",
                *( [Business.job_id == job_id] if job_id is not None else [] ))
        .group_by(OutreachDraft.channel)
        .all()
    )
    no_clear = (
        s.query(func.count(WebsiteAudit.id))
        .join(Business, Business.id == WebsiteAudit.business_id)
        .filter(WebsiteAudit.audit_status == "no_clear_opportunity",
                *( [Business.job_id == job_id] if job_id is not None else [] ))
        .scalar() or 0
    )

    return {
        "job_id": job_id,
        "total": total,
        "processed": processed,
        "in_progress": item_counts.get("running", 0),
        "queued": item_counts.get("pending", 0),
        "successful": item_counts.get("completed", 0),
        "failed": item_counts.get("failed", 0),
        "skipped": item_counts.get("skipped", 0),
        "high_opportunity": high_opportunity,
        "average_score": round(float(avg_score), 1) if avg_score is not None else None,
        "no_clear_opportunity": no_clear,
        "channels": {
            "whatsapp": channels.get("whatsapp", 0),
            "email": channels.get("email", 0),
            "linkedin": channels.get("linkedin", 0),
            "phone": channels.get("phone", 0),
            "website_contact": channels.get("website_contact", 0),
            "none": channels.get("none", 0) + channels.get("", 0),
        },
        "drafts": {"whatsapp": drafts.get("whatsapp", 0), "email": drafts.get("email", 0),
                   "linkedin": drafts.get("linkedin", 0), "call": drafts.get("call", 0)},
        "lead_tiers": {k or "unprocessed": v for k, v in tiers.items()},
        "opportunity_tiers": {k or "unscored": v for k, v in opp.items()},
        "website_status": {k or "not_checked": v for k, v in website_status.items()},
        "contacts": {
            "with_public_email": with_email,
            "with_whatsapp_path": wa_usable,
        },
        "error_codes": error_codes,
        "error_total": eq.count(),
    }


@router.get("/{job_id}/errors")
def job_errors(job_id: int, limit: int = 200) -> Dict[str, Any]:
    with session_scope(write=False) as s:
        rows = (
            s.query(AuditError, Business.name)
            .outerjoin(Business, Business.id == AuditError.business_id)
            .filter(AuditError.job_id == job_id)
            .order_by(AuditError.id.desc())
            .limit(max(1, min(1000, limit)))
            .all()
        )
        return {
            "errors": [
                {
                    "id": e.id, "business_id": e.business_id, "business": name or "",
                    "stage": e.stage, "code": e.code, "message": e.message,
                    "retryable": e.retryable, "url": e.url,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e, name in rows
            ]
        }
