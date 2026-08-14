"""Lead listing, detail, audit reports and draft regeneration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_

from ..core.exporter import _CONTACT_CHANNEL_DISPLAY
from ..core.outreach import (
    OutreachContext,
    ProfileIncomplete,
    build_call_notes,
    build_email_message,
    build_linkedin_message,
    build_whatsapp_message,
    mailto_url,
)
from ..core.phones import whatsapp_url
from ..db import run_db, session_scope
from ..models import (
    AuditError,
    Business,
    ContactEmail,
    ContactPhone,
    JobItem,
    OutreachDraft,
    WebsiteAudit,
)
from ..settings import REPORT_DIR, get_profile, profile_status

router = APIRouter(prefix="/leads", tags=["leads"])


def _lead_row(
    b: Business, phone, emails, audit, drafts, item, *, include_drafts: bool = False
) -> Dict[str, Any]:
    initial = {d.channel: d for d in drafts if d.variant == "initial"}
    row: Dict[str, Any] = {
        "id": b.id,
        "job_id": b.job_id,
        "row_index": b.row_index,
        "name": b.name,
        "category": b.category,
        "city": b.city,
        "state": b.state,
        "country": b.country,
        "address": b.address,
        "rating": b.rating,
        "review_count": b.review_count,
        "maps_url": b.maps_url,
        "website_original": b.website_original,
        "website_final": b.website_final,
        "website_status": b.website_status,
        "website_identity_confidence": b.website_identity_confidence,
        "website_source": b.website_source,
        "score": b.score,
        "opportunity_tier": b.opportunity_tier,
        "lead_tier": b.lead_tier,
        "audit_kind": b.audit_kind,
        "best_channel": b.best_channel,
        "channel_reason": b.channel_reason,
        "contact_channel": _CONTACT_CHANNEL_DISPLAY.get(b.best_channel or "", (b.best_channel or "SKIP").upper()),
        "contact_channel_reason": b.channel_reason,
        "linkedin_url": b.linkedin_url,
        "linkedin_status": b.linkedin_status,
        "processed_at": b.processed_at.isoformat() if b.processed_at else None,
        "is_duplicate_of": b.is_duplicate_of,
        "status": item.status if item else "pending",
        "stage": item.stage if item else "queued",
        "error_message": item.error_message if item else "",
        "phone": {
            "raw": phone.phone_raw if phone else b.phone_raw,
            "normalized": phone.phone_normalized if phone else "",
            "national": phone.phone_national if phone else "",
            "country": phone.phone_country if phone else "",
            "country_name": phone.phone_country_name if phone else "",
            "type": phone.phone_type if phone else "",
            "status": phone.validation_status if phone else "unavailable",
            "whatsapp_status": phone.whatsapp_status if phone else "no_phone",
            "whatsapp_reason": phone.whatsapp_reason if phone else "",
            "whatsapp_url": phone.whatsapp_url if phone else "",
        } if (phone or b.phone_raw) else None,
        "emails": [
            {
                "email": e.email, "status": e.status, "source_url": e.source_url,
                "source_type": e.source_type, "page_type": e.page_type,
                "confidence": e.confidence, "is_role": e.is_role,
                "domain_matches_site": e.domain_matches_site,
                "mx_records": e.mx_records, "notes": e.validation_notes,
            }
            for e in emails
        ],
        "problem_count": len(audit.problems) if audit else 0,
        "problems": (audit.problems if audit else [])[:3],
        "audit_status": audit.audit_status if audit else "",
        "has_report": bool(audit and audit.report_path),
        "premium_score": ((audit.extra or {}).get("scorecard") or {}).get("overall_score") if audit else None,
        "drafts_available": sorted(initial.keys()),
        "draft_preview": (
            initial.get(b.best_channel).message[:220] if initial.get(b.best_channel) else ""
        ),
    }

    # The channel queue pages need the whole draft. Including it on request
    # keeps those pages to one round trip instead of one per visible lead.
    if include_drafts:
        row["initial_drafts"] = {
            d.channel: {
                "id": d.id,
                "channel": d.channel,
                "variant": d.variant,
                "subject": d.subject,
                "message": d.message,
                "draft_url": d.draft_url,
                "based_on": d.based_on,
                "sent_manually": d.sent_manually,
            }
            for d in drafts
            if d.variant == "initial"
        }
    return row


@router.get("")
def list_leads(
    job_id: Optional[int] = None,
    channel: Optional[str] = None,
    lead_tier: Optional[str] = None,
    opportunity_tier: Optional[str] = None,
    status: Optional[str] = None,
    website_status: Optional[str] = None,
    search: Optional[str] = None,
    min_score: Optional[int] = None,
    max_score: Optional[int] = None,
    has_email: Optional[bool] = None,
    has_whatsapp: Optional[bool] = None,
    has_problems: Optional[bool] = None,
    include_drafts: bool = False,
    sort: str = "score_desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    with session_scope(write=False) as s:
        q = s.query(Business)
        if job_id is not None:
            q = q.filter(Business.job_id == job_id)
        if channel:
            q = q.filter(Business.best_channel == channel)
        if lead_tier:
            q = q.filter(Business.lead_tier == lead_tier)
        if opportunity_tier:
            q = q.filter(Business.opportunity_tier == opportunity_tier)
        if website_status:
            q = q.filter(Business.website_status == website_status)
        if min_score is not None:
            q = q.filter(Business.score >= min_score)
        if max_score is not None:
            q = q.filter(Business.score <= max_score)
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(or_(
                Business.name.ilike(like),
                Business.city.ilike(like),
                Business.category.ilike(like),
                Business.website_final.ilike(like),
                Business.website_original.ilike(like),
            ))
        if status:
            q = q.join(JobItem, JobItem.business_id == Business.id).filter(JobItem.status == status)
        if has_email is not None:
            sub = s.query(ContactEmail.business_id).distinct()
            q = q.filter(Business.id.in_(sub) if has_email else ~Business.id.in_(sub))
        if has_whatsapp is not None:
            sub = (
                s.query(ContactPhone.business_id)
                .filter(ContactPhone.whatsapp_status.in_(
                    ("confirmed_on_website", "usable_unverified")))
                .distinct()
            )
            q = q.filter(Business.id.in_(sub) if has_whatsapp else ~Business.id.in_(sub))
        if has_problems is not None:
            sub = s.query(WebsiteAudit.business_id).filter(
                func.json_array_length(WebsiteAudit.problems) > 0
            ).distinct()
            q = q.filter(Business.id.in_(sub) if has_problems else ~Business.id.in_(sub))

        total = q.count()

        order = {
            "score_desc": (Business.score.desc().nullslast(), Business.id.asc()),
            "score_asc": (Business.score.asc().nullsfirst(), Business.id.asc()),
            "name_asc": (Business.name.asc(),),
            "name_desc": (Business.name.desc(),),
            "row_asc": (Business.row_index.asc(),),
            "recent": (Business.processed_at.desc().nullslast(), Business.id.desc()),
        }.get(sort, (Business.score.desc().nullslast(), Business.id.asc()))
        q = q.order_by(*order)

        rows: List[Business] = q.offset((page - 1) * page_size).limit(page_size).all()
        ids = [b.id for b in rows]

        phones = {}
        emails: Dict[int, List[ContactEmail]] = {}
        audits = {}
        drafts: Dict[int, List[OutreachDraft]] = {}
        items = {}
        if ids:
            for p in s.query(ContactPhone).filter(ContactPhone.business_id.in_(ids)).all():
                phones.setdefault(p.business_id, p)
            for e in (s.query(ContactEmail).filter(ContactEmail.business_id.in_(ids))
                      .order_by(ContactEmail.rank).all()):
                emails.setdefault(e.business_id, []).append(e)
            for a in s.query(WebsiteAudit).filter(WebsiteAudit.business_id.in_(ids)).all():
                audits[a.business_id] = a
            for d in s.query(OutreachDraft).filter(OutreachDraft.business_id.in_(ids)).all():
                drafts.setdefault(d.business_id, []).append(d)
            for i in s.query(JobItem).filter(JobItem.business_id.in_(ids)).all():
                items[i.business_id] = i

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "leads": [
                _lead_row(b, phones.get(b.id), emails.get(b.id, []), audits.get(b.id),
                          drafts.get(b.id, []), items.get(b.id), include_drafts=include_drafts)
                for b in rows
            ],
        }


@router.get("/{lead_id}")
def get_lead(lead_id: int) -> Dict[str, Any]:
    with session_scope(write=False) as s:
        b = s.get(Business, lead_id)
        if not b:
            raise HTTPException(status_code=404, detail="Lead not found.")
        phone = s.query(ContactPhone).filter(ContactPhone.business_id == lead_id).first()
        emails = (s.query(ContactEmail).filter(ContactEmail.business_id == lead_id)
                  .order_by(ContactEmail.rank).all())
        audit = s.query(WebsiteAudit).filter(WebsiteAudit.business_id == lead_id).first()
        drafts = s.query(OutreachDraft).filter(OutreachDraft.business_id == lead_id).all()
        item = s.query(JobItem).filter(JobItem.business_id == lead_id).first()
        errors = (s.query(AuditError).filter(AuditError.business_id == lead_id)
                  .order_by(AuditError.id.desc()).limit(30).all())

        base = _lead_row(b, phone, emails, audit, drafts, item)
        base.update({
            "raw": b.raw,
            "audit": {
                "website": audit.website, "audit_kind": audit.audit_kind,
                "http_status": audit.http_status, "is_https": audit.is_https,
                "redirect_chain": audit.redirect_chain, "response_ms": audit.response_ms,
                "pages_crawled": audit.pages_crawled, "pages": audit.pages,
                "technical": audit.technical, "conversion": audit.conversion,
                "mobile": audit.mobile, "trust": audit.trust, "content": audit.content,
                "performance": audit.performance, "subscores": audit.subscores,
                "score": audit.score, "opportunity_tier": audit.opportunity_tier,
                "score_explanation": audit.score_explanation,
                "problems": audit.problems, "recommendations": audit.recommendations,
                "audit_status": audit.audit_status, "audit_error": audit.audit_error,
                "has_report": bool(audit.report_path),
                "created_at": audit.created_at.isoformat() if audit.created_at else None,
                "extra": audit.extra or {},
            } if audit else None,
            "drafts": [
                {
                    "id": d.id, "channel": d.channel, "variant": d.variant,
                    "subject": d.subject, "message": d.message, "draft_url": d.draft_url,
                    "based_on": d.based_on, "generator": d.generator,
                    "sent_manually": d.sent_manually,
                }
                for d in sorted(drafts, key=lambda x: (x.channel, x.variant))
            ],
            "errors": [
                {"stage": e.stage, "code": e.code, "message": e.message,
                 "retryable": e.retryable, "url": e.url,
                 "created_at": e.created_at.isoformat() if e.created_at else None}
                for e in errors
            ],
        })
        return base


@router.get("/{lead_id}/report", response_class=FileResponse)
def get_report(lead_id: int):
    with session_scope(write=False) as s:
        audit = s.query(WebsiteAudit).filter(WebsiteAudit.business_id == lead_id).first()
        if not audit or not audit.report_path:
            raise HTTPException(status_code=404, detail="No audit report exists for this lead.")
        path = Path(audit.report_path).resolve()

    # Path-traversal guard: reports may only be served from the report folder.
    if REPORT_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid report path.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="The report file is missing from disk.")
    return FileResponse(path, media_type="text/html", filename=path.name)


class MarkSent(BaseModel):
    draft_id: int
    sent: bool = True


@router.post("/{lead_id}/mark-sent")
async def mark_sent(lead_id: int, payload: MarkSent) -> Dict[str, Any]:
    def _work(s):
        d = s.get(OutreachDraft, payload.draft_id)
        if not d or d.business_id != lead_id:
            raise HTTPException(status_code=404, detail="Draft not found for this lead.")
        d.sent_manually = payload.sent
        return {"draft_id": d.id, "sent_manually": d.sent_manually}

    return await run_db(_work)


@router.post("/{lead_id}/regenerate-outreach")
async def regenerate_outreach(lead_id: int) -> Dict[str, Any]:
    """
    Rebuild the drafts for one lead using the current profile and the audit
    already stored. Useful after filling in Settings, since the pipeline
    refuses to write outreach while the identity is missing.
    """
    status = profile_status()
    if not status["configured"]:
        raise HTTPException(
            status_code=409,
            detail="Fill in your name, company and service in Settings before generating outreach. "
                   f"Missing: {', '.join(status['missing_core'])}.",
        )
    profile = get_profile()

    def _load(s):
        b = s.get(Business, lead_id)
        if not b:
            raise HTTPException(status_code=404, detail="Lead not found.")
        audit = s.query(WebsiteAudit).filter(WebsiteAudit.business_id == lead_id).first()
        phone = s.query(ContactPhone).filter(ContactPhone.business_id == lead_id).first()
        emails = (s.query(ContactEmail).filter(ContactEmail.business_id == lead_id)
                  .order_by(ContactEmail.rank).all())
        return {
            "name": b.name, "category": b.category, "city": b.city, "state": b.state,
            "country": b.country, "website": b.website_final, "channel": b.best_channel,
            "audit_kind": b.audit_kind, "score": b.score,
            "problems": audit.problems if audit else [],
            "report": bool(audit and audit.report_path),
            "phone_e164": phone.phone_normalized if phone else "",
            "wa_status": phone.whatsapp_status if phone else "no_phone",
            "email": next((e.email for e in emails
                           if e.status in ("valid_public", "mx_valid", "domain_valid")), ""),
            "linkedin_url": b.linkedin_url,
        }

    data = await run_db(_load, write=False)
    if not data["problems"]:
        raise HTTPException(
            status_code=409,
            detail="No measured problems are stored for this lead, so there is nothing specific "
                   "to write about. Re-run the audit first.",
        )

    ctx = OutreachContext(
        business_id=lead_id, business_name=data["name"], category=data["category"],
        city=data["city"], state=data["state"], country=data["country"],
        website=data["website"], problems=data["problems"], score=data["score"],
        audit_kind=data["audit_kind"] or "website", report_available=data["report"],
    )

    channel = data["channel"] or "email"
    built = []
    try:
        if channel == "whatsapp":
            for v in ("initial", "followup_1", "followup_2"):
                d = build_whatsapp_message(ctx, profile, v)
                if d.ok:
                    d.draft_url = whatsapp_url(data["phone_e164"], d.message)
                    built.append(d)
        elif channel == "email":
            for v in ("initial", "followup_1", "followup_2"):
                d = build_email_message(ctx, profile, v)
                if d.ok:
                    d.draft_url = mailto_url(data["email"], d.subject, d.message)
                    built.append(d)
        elif channel == "linkedin":
            d = build_linkedin_message(ctx, profile, "initial")
            if d.ok:
                d.draft_url = data["linkedin_url"]
                built.append(d)
        else:
            d = build_call_notes(ctx, profile)
            if d.ok:
                built.append(d)
    except ProfileIncomplete as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    if not built:
        raise HTTPException(
            status_code=409,
            detail="No draft was produced: none of the detected problems could be phrased into a "
                   "specific, honest message.",
        )

    def _save(s):
        s.query(OutreachDraft).filter(
            OutreachDraft.business_id == lead_id,
            OutreachDraft.channel == channel,
        ).delete()
        for d in built:
            s.add(OutreachDraft(
                business_id=lead_id, channel=d.channel, variant=d.variant,
                subject=d.subject, message=d.message, draft_url=d.draft_url,
                based_on=d.based_on, generator=d.generator,
            ))
        return len(built)

    n = await run_db(_save)
    return {"lead_id": lead_id, "channel": channel, "drafts_written": n}
