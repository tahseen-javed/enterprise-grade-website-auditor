"""SQLAlchemy models. One business = one logical lead, always (spec 11)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str] = mapped_column(String(512), default="")
    stored_path: Mapped[str] = mapped_column(String(1024), default="")
    # csv | url - "url" jobs are a single direct-website quick audit, created
    # from the New Audit screen rather than an uploaded file.
    source_kind: Mapped[str] = mapped_column(String(16), default="csv")

    # Full original header order, so exports can reproduce the input exactly.
    original_columns: Mapped[List[str]] = mapped_column(JSON, default=list)
    column_mapping: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    engine_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # queued | running | paused | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")

    businesses: Mapped[List["Business"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Business(Base):
    """The lead. `raw` holds every original CSV column, untouched."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    row_index: Mapped[int] = mapped_column(Integer, default=0)

    raw: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    name: Mapped[str] = mapped_column(String(512), default="")
    name_normalized: Mapped[str] = mapped_column(String(512), default="", index=True)
    category: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(String(1024), default="")
    city: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(255), default="")
    country: Mapped[str] = mapped_column(String(128), default="")
    country_code: Mapped[str] = mapped_column(String(8), default="")
    postal_code: Mapped[str] = mapped_column(String(64), default="")
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    place_id: Mapped[str] = mapped_column(String(255), default="")
    maps_url: Mapped[str] = mapped_column(String(1024), default="")

    phone_raw: Mapped[str] = mapped_column(String(128), default="")
    website_original: Mapped[str] = mapped_column(String(1024), default="")

    dedup_key: Mapped[str] = mapped_column(String(512), default="", index=True)
    is_duplicate_of: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ---- outcome fields (denormalized for fast dashboard/table queries) ----
    website_final: Mapped[str] = mapped_column(String(1024), default="")
    website_status: Mapped[str] = mapped_column(String(32), default="not_checked", index=True)
    website_identity_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    website_source: Mapped[str] = mapped_column(String(32), default="")

    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    opportunity_tier: Mapped[str] = mapped_column(String(32), default="", index=True)
    lead_tier: Mapped[str] = mapped_column(String(4), default="", index=True)  # A+ A B C D
    audit_kind: Mapped[str] = mapped_column(String(32), default="")  # website | no_website

    best_channel: Mapped[str] = mapped_column(String(32), default="", index=True)
    channel_reason: Mapped[str] = mapped_column(String(512), default="")

    linkedin_url: Mapped[str] = mapped_column(String(1024), default="")
    # not_checked | found | not_found
    linkedin_status: Mapped[str] = mapped_column(String(32), default="not_checked")

    processed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    job: Mapped[Job] = relationship(back_populates="businesses")
    item: Mapped[Optional["JobItem"]] = relationship(
        back_populates="business", cascade="all, delete-orphan", uselist=False
    )
    emails: Mapped[List["ContactEmail"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    phones: Mapped[List["ContactPhone"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    audit: Mapped[Optional["WebsiteAudit"]] = relationship(
        back_populates="business", cascade="all, delete-orphan", uselist=False
    )
    drafts: Mapped[List["OutreachDraft"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    errors: Mapped[List["AuditError"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )


Index("ix_business_job_tier", Business.job_id, Business.lead_tier)
Index("ix_business_job_channel", Business.job_id, Business.best_channel)


class JobItem(Base):
    """Per-lead processing checkpoint. This is what makes resume work (spec 28)."""

    __tablename__ = "job_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), unique=True, index=True
    )

    # pending | running | completed | failed | skipped
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    stage: Mapped[str] = mapped_column(String(48), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    # Completed stage outputs, so a resume skips work already done.
    stage_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_stages: Mapped[List[str]] = mapped_column(JSON, default=list)

    error_message: Mapped[str] = mapped_column(Text, default="")
    error_stage: Mapped[str] = mapped_column(String(48), default="")
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)

    started_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    business: Mapped[Business] = relationship(back_populates="item")


Index("ix_jobitem_job_status", JobItem.job_id, JobItem.status)


class WebsiteAudit(Base):
    __tablename__ = "website_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), unique=True, index=True
    )

    website: Mapped[str] = mapped_column(String(1024), default="")
    audit_kind: Mapped[str] = mapped_column(String(32), default="website")
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_https: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    redirect_chain: Mapped[List[str]] = mapped_column(JSON, default=list)
    response_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    technical: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    conversion: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    mobile: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    performance: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    trust: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    content: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    subscores: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    opportunity_tier: Mapped[str] = mapped_column(String(32), default="")
    score_explanation: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    problems: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    recommendations: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Premium audit data: facts from the extra checks (security, accessibility,
    # onpage, offpage, performance_extra) plus the 9-scorecard breakdown from
    # scoring.build_scorecard. Kept as one JSON blob, additive to the columns
    # above, so the existing opportunity-scoring columns are untouched.
    extra: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    report_path: Mapped[str] = mapped_column(String(1024), default="")
    audit_status: Mapped[str] = mapped_column(String(32), default="")
    audit_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    business: Mapped[Business] = relationship(back_populates="audit")


class ContactEmail(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), default="")
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    source_type: Mapped[str] = mapped_column(String(48), default="")  # mailto|text|jsonld|meta
    page_type: Mapped[str] = mapped_column(String(48), default="")    # homepage|contact|about...
    status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_role: Mapped[bool] = mapped_column(Boolean, default=False)
    is_disposable: Mapped[bool] = mapped_column(Boolean, default=False)
    domain_matches_site: Mapped[bool] = mapped_column(Boolean, default=False)
    mx_records: Mapped[List[str]] = mapped_column(JSON, default=list)
    validation_notes: Mapped[List[str]] = mapped_column(JSON, default=list)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("business_id", "email", name="uq_business_email"),)

    business: Mapped[Business] = relationship(back_populates="emails")


class ContactPhone(Base):
    __tablename__ = "phones"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    phone_raw: Mapped[str] = mapped_column(String(128), default="")
    phone_normalized: Mapped[str] = mapped_column(String(64), default="")   # E.164
    phone_national: Mapped[str] = mapped_column(String(64), default="")
    phone_country: Mapped[str] = mapped_column(String(8), default="")       # region code, e.g. US
    phone_country_name: Mapped[str] = mapped_column(String(128), default="")
    phone_calling_code: Mapped[str] = mapped_column(String(8), default="")
    phone_type: Mapped[str] = mapped_column(String(32), default="unknown")
    validation_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    source: Mapped[str] = mapped_column(String(48), default="csv")          # csv|website
    source_url: Mapped[str] = mapped_column(String(1024), default="")

    whatsapp_status: Mapped[str] = mapped_column(String(32), default="not_checked", index=True)
    whatsapp_reason: Mapped[str] = mapped_column(String(512), default="")
    whatsapp_url: Mapped[str] = mapped_column(Text, default="")
    rank: Mapped[int] = mapped_column(Integer, default=0)

    business: Mapped[Business] = relationship(back_populates="phones")


class OutreachDraft(Base):
    __tablename__ = "outreach_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(32), default="", index=True)  # whatsapp|email|call
    variant: Mapped[str] = mapped_column(String(32), default="initial")       # initial|followup_1|followup_2
    subject: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    draft_url: Mapped[str] = mapped_column(Text, default="")
    # Which detected problems this message was built from - the audit trail
    # that proves the personalization is real and not invented.
    based_on: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    generator: Mapped[str] = mapped_column(String(32), default="deterministic")
    sent_manually: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("business_id", "channel", "variant", name="uq_draft_variant"),
    )

    business: Mapped[Business] = relationship(back_populates="drafts")


class AuditError(Base):
    __tablename__ = "audit_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    business_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stage: Mapped[str] = mapped_column(String(48), default="")
    code: Mapped[str] = mapped_column(String(64), default="", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    business: Mapped[Optional[Business]] = relationship(back_populates="errors")


class EventLog(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    business_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    business_name: Mapped[str] = mapped_column(String(512), default="")
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    stage: Mapped[str] = mapped_column(String(48), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SettingRow(Base):
    """Key/value store for anything that outgrows the JSON config files."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
