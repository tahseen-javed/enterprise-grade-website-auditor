"""
Job orchestrator (spec 25-29, 44).

Bounded worker pool over the leads of a job. Each lead is checkpointed at the
stage level, so closing the app mid-run and restarting resumes exactly where
it stopped and never re-processes a completed business.

One bad website can never stop the job: every stage is individually guarded,
and failures are recorded as typed, retryable/non-retryable errors.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select

from ..db import run_db, session_scope
from ..events import activity, bus
from ..models import (
    AuditError,
    Business,
    ContactEmail,
    ContactPhone,
    Job,
    JobItem,
    OutreachDraft,
    WebsiteAudit,
    utcnow,
)
from ..settings import get_engine, get_profile, get_weights, profile_status
from . import pagespeed as ps
from .audit_checks import Finding, no_website_findings, run_all_checks, run_extra_checks
from .crawler import crawl_site
from .discovery import (
    STATUS_NO_WEBSITE,
    STATUS_NOT_A_WEBSITE,
    discover_website,
    verify_direct_website,
)
from .email_validate import is_usable_for_outreach, validate_all
from .extract import ExtractionResult, extract_contacts
from .fetcher import Fetcher
from .observations import OBSERVATIONS
from .outreach import (
    Draft,
    OutreachContext,
    ProfileIncomplete,
    build_call_notes,
    build_email_message,
    build_linkedin_message,
    build_whatsapp_message,
    choose_channel,
    mailto_url,
)
from .phones import assess_whatsapp, normalize_phone, resolve_region, whatsapp_url
from .report_html import render_report, write_report
from .scoring import (
    CATEGORY_LABELS,
    build_recommendations,
    build_scorecard,
    compute_score,
    has_clear_opportunity,
    lead_tier,
    select_problems,
    tier_for_score,
)
from .urls import registrable_domain

STAGES = [
    "normalize", "discovery", "crawl", "extract", "validate_emails",
    "audit", "score", "whatsapp_check", "email_discovery", "linkedin_discovery",
    "message_generation", "report", "done",
]

STAGE_LABELS = {
    "queued": "Queued",
    "normalize": "Normalizing business data",
    "discovery": "Website discovery",
    "crawl": "Website crawl",
    "extract": "Contact extraction",
    "validate_emails": "Email validation",
    "audit": "Website audit",
    "score": "Opportunity scoring",
    "whatsapp_check": "WhatsApp check",
    "email_discovery": "Email discovery",
    "linkedin_discovery": "LinkedIn discovery",
    "message_generation": "Message generation",
    "report": "Audit report",
    "done": "Complete",
}


# --------------------------------------------------------------------------


@dataclass
class WorkerState:
    worker_id: int
    busy: bool = False
    business_id: Optional[int] = None
    business_name: str = ""
    stage: str = "idle"
    started_at: Optional[float] = None


@dataclass
class JobProgress:
    job_id: int
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    whatsapp_found: int = 0
    email_found: int = 0
    linkedin_found: int = 0
    phone_found: int = 0
    no_channel: int = 0
    started_at: float = field(default_factory=time.monotonic)
    workers: List[WorkerState] = field(default_factory=list)

    def snapshot(self) -> Dict[str, Any]:
        elapsed = max(0.001, time.monotonic() - self.started_at)
        rate = self.processed / elapsed  # leads per second
        remaining = max(0, self.total - self.processed)
        eta = int(remaining / rate) if rate > 0 and remaining else None
        return {
            "job_id": self.job_id,
            "total": self.total,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "whatsapp_found": self.whatsapp_found,
            "email_found": self.email_found,
            "linkedin_found": self.linkedin_found,
            "phone_found": self.phone_found,
            "no_channel": self.no_channel,
            "queued": remaining,
            "percent": round(100 * self.processed / self.total, 1) if self.total else 0.0,
            "rate_per_minute": round(rate * 60, 1),
            "elapsed_s": int(elapsed),
            "eta_s": eta,
            "workers_total": len(self.workers),
            "workers_active": sum(1 for w in self.workers if w.busy),
            "workers": [
                {
                    "id": w.worker_id,
                    "busy": w.busy,
                    "business": w.business_name,
                    "business_id": w.business_id,
                    "stage": w.stage,
                    "stage_label": STAGE_LABELS.get(w.stage, w.stage),
                    "seconds_on_lead": int(time.monotonic() - w.started_at) if w.started_at else 0,
                }
                for w in self.workers
            ],
        }


class JobControl:
    def __init__(self) -> None:
        self.cancel = asyncio.Event()
        self.pause = asyncio.Event()

    async def wait_if_paused(self) -> None:
        while self.pause.is_set() and not self.cancel.is_set():
            await asyncio.sleep(0.25)


# --------------------------------------------------------------------------


class JobManager:
    """Process-wide registry of running jobs."""

    def __init__(self) -> None:
        self._tasks: Dict[int, asyncio.Task] = {}
        self._controls: Dict[int, JobControl] = {}
        self._progress: Dict[int, JobProgress] = {}
        self._lock = asyncio.Lock()

    def is_running(self, job_id: int) -> bool:
        t = self._tasks.get(job_id)
        return bool(t and not t.done())

    @property
    def running_job_ids(self) -> List[int]:
        return [jid for jid, t in self._tasks.items() if not t.done()]

    def progress(self, job_id: int) -> Optional[Dict[str, Any]]:
        p = self._progress.get(job_id)
        return p.snapshot() if p else None

    def all_progress(self) -> Dict[int, Dict[str, Any]]:
        return {jid: p.snapshot() for jid, p in self._progress.items() if self.is_running(jid)}

    async def start(self, job_id: int) -> Dict[str, Any]:
        async with self._lock:
            if self.is_running(job_id):
                return {"started": False, "reason": "This job is already running."}
            control = JobControl()
            self._controls[job_id] = control
            runner = JobRunner(job_id, control, self)
            task = asyncio.create_task(runner.run(), name=f"job-{job_id}")
            self._tasks[job_id] = task
            return {"started": True}

    async def pause(self, job_id: int) -> bool:
        c = self._controls.get(job_id)
        if not c or not self.is_running(job_id):
            return False
        c.pause.set()
        await run_db(lambda s: _set_job_status(s, job_id, "paused"))
        bus.emit(type="job", job_id=job_id, message="Job paused", data={"status": "paused"})
        return True

    async def resume_paused(self, job_id: int) -> bool:
        c = self._controls.get(job_id)
        if not c or not self.is_running(job_id):
            return False
        c.pause.clear()
        await run_db(lambda s: _set_job_status(s, job_id, "running"))
        bus.emit(type="job", job_id=job_id, message="Job resumed", data={"status": "running"})
        return True

    async def cancel(self, job_id: int) -> bool:
        c = self._controls.get(job_id)
        if not c or not self.is_running(job_id):
            return False
        c.cancel.set()
        c.pause.clear()
        return True

    async def shutdown(self) -> None:
        for c in self._controls.values():
            c.cancel.set()
            c.pause.clear()
        tasks = [t for t in self._tasks.values() if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def register_progress(self, job_id: int, p: JobProgress) -> None:
        self._progress[job_id] = p


manager = JobManager()


def _set_job_status(s, job_id: int, status: str) -> None:
    job = s.get(Job, job_id)
    if job:
        job.status = status


# --------------------------------------------------------------------------


class JobRunner:
    def __init__(self, job_id: int, control: JobControl, mgr: JobManager) -> None:
        self.job_id = job_id
        self.control = control
        self.manager = mgr
        self.engine_cfg: Dict[str, Any] = get_engine()
        self.weights_cfg: Dict[str, Any] = get_weights()
        self.profile: Dict[str, Any] = get_profile()
        self.progress = JobProgress(job_id=job_id)
        self.fetcher: Optional[Fetcher] = None
        self.source_kind: str = "csv"

    # ---- lifecycle ------------------------------------------------------

    async def run(self) -> None:
        self.manager.register_progress(self.job_id, self.progress)
        try:
            pending = await run_db(lambda s: self._load_pending(s), write=True)
        except Exception as exc:
            await self._fail_job(f"Could not load the job: {exc}")
            return

        if not pending:
            await self._finish_job("completed")
            return

        self.progress.total = await run_db(
            lambda s: s.query(func.count(JobItem.id)).filter(JobItem.job_id == self.job_id).scalar() or 0,
            write=False,
        )
        already = await run_db(
            lambda s: s.query(func.count(JobItem.id))
            .filter(JobItem.job_id == self.job_id, JobItem.status.in_(("completed", "skipped")))
            .scalar() or 0,
            write=False,
        )
        self.progress.processed = already
        self.progress.succeeded = already

        workers = max(1, min(20, int(self.engine_cfg.get("workers", 5))))
        self.progress.workers = [WorkerState(worker_id=i + 1) for i in range(workers)]

        activity(
            "", f"Job started with {workers} worker(s) — {len(pending)} lead(s) to process "
                f"({already} already complete)",
            job_id=self.job_id, stage="job",
        )
        bus.emit(type="job", job_id=self.job_id, message="Job running", data={"status": "running"})

        self.fetcher = Fetcher(
            user_agent=self.engine_cfg["user_agent"],
            timeout_s=float(self.engine_cfg["request_timeout_s"]),
            per_domain_concurrency=int(self.engine_cfg["per_domain_concurrency"]),
            per_domain_delay_ms=int(self.engine_cfg["per_domain_delay_ms"]),
            max_bytes=int(self.engine_cfg["max_page_bytes"]),
            max_retries=int(self.engine_cfg["max_retries"]),
            backoff_base_s=float(self.engine_cfg["backoff_base_s"]),
            respect_robots=bool(self.engine_cfg["respect_robots"]),
            verify_ssl=bool(self.engine_cfg["verify_ssl"]),
            global_connections=max(20, workers * 8),
        )

        queue: asyncio.Queue = asyncio.Queue()
        for bid in pending:
            queue.put_nowait(bid)

        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            await asyncio.gather(
                *(self._worker(w, queue) for w in self.progress.workers),
                return_exceptions=True,
            )
        finally:
            heartbeat.cancel()
            if self.fetcher:
                await self.fetcher.aclose()

        status = "cancelled" if self.control.cancel.is_set() else "completed"
        await self._finish_job(status)

    def _load_pending(self, s) -> List[int]:
        job = s.get(Job, self.job_id)
        if not job:
            raise ValueError(f"Job {self.job_id} does not exist.")
        self.source_kind = job.source_kind or "csv"
        job.status = "running"
        if job.started_at is None:
            job.started_at = utcnow()

        # Anything left 'running' from a previous process is picked back up.
        stale = (
            s.query(JobItem)
            .filter(JobItem.job_id == self.job_id, JobItem.status == "running")
            .all()
        )
        for item in stale:
            item.status = "pending"

        rows = (
            s.query(JobItem.business_id)
            .filter(
                JobItem.job_id == self.job_id,
                JobItem.status.in_(("pending", "failed")),
            )
            .order_by(JobItem.id)
            .all()
        )
        return [r[0] for r in rows]

    async def _heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                bus.emit(
                    type="progress", job_id=self.job_id,
                    data=self.progress.snapshot(), persist=False,
                )
        except asyncio.CancelledError:
            pass

    async def _finish_job(self, status: str) -> None:
        def _work(s):
            job = s.get(Job, self.job_id)
            if job:
                job.status = status
                job.finished_at = utcnow()

        await run_db(_work)
        snap = self.progress.snapshot()
        activity(
            "",
            f"Job {status}: {snap['succeeded']} succeeded, {snap['failed']} failed, "
            f"{snap['skipped']} skipped",
            job_id=self.job_id, stage="job",
            level="info" if status == "completed" else "warn",
        )
        bus.emit(type="job", job_id=self.job_id, message=f"Job {status}",
                 data={"status": status, **snap})

    async def _fail_job(self, message: str) -> None:
        def _work(s):
            job = s.get(Job, self.job_id)
            if job:
                job.status = "failed"
                job.last_error = message[:2000]
                job.finished_at = utcnow()

        await run_db(_work)
        activity("", f"Job failed: {message}", job_id=self.job_id, stage="job", level="error")
        bus.emit(type="job", job_id=self.job_id, message="Job failed", data={"status": "failed"})

    # ---- worker ---------------------------------------------------------

    async def _worker(self, state: WorkerState, queue: asyncio.Queue) -> None:
        while True:
            if self.control.cancel.is_set():
                return
            await self.control.wait_if_paused()
            if self.control.cancel.is_set():
                return
            try:
                business_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            state.busy = True
            state.business_id = business_id
            state.started_at = time.monotonic()
            try:
                await self._process_lead(business_id, state)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                tb = traceback.format_exc(limit=6)
                await self._record_failure(business_id, state.stage or "unknown", "unhandled",
                                           f"{type(exc).__name__}: {exc}", retryable=True, tb=tb)
                self.progress.failed += 1
                self.progress.processed += 1
            finally:
                state.busy = False
                state.stage = "idle"
                state.business_id = None
                state.business_name = ""
                state.started_at = None
                queue.task_done()

    # ---- per-lead pipeline ---------------------------------------------

    async def _process_lead(self, business_id: int, state: WorkerState) -> None:
        biz = await run_db(lambda s: _business_dto(s, business_id), write=False)
        if biz is None:
            return

        state.business_name = biz["name"]
        name = biz["name"]

        def stage(stage_name: str) -> None:
            state.stage = stage_name
            _mark_stage(self.job_id, business_id, stage_name)

        await run_db(lambda s: _start_item(s, business_id))
        activity(name, "Processing started", job_id=self.job_id, business_id=business_id,
                 stage="start")

        # ---------------- 1. normalize ----------------
        stage("normalize")
        region = resolve_region(
            country=biz["country"], state=biz["state"], address=biz["address"]
        )
        phone = normalize_phone(biz["phone_raw"], region_hint=region, source="csv")
        if phone["validation_status"] == "valid":
            activity(name, f"Phone normalized to {phone['phone_normalized']} "
                           f"({phone['phone_country'] or 'unknown region'}, {phone['phone_type']})",
                     job_id=self.job_id, business_id=business_id, stage="normalize")
        elif biz["phone_raw"]:
            activity(name, f"Phone could not be normalized: {phone['validation_status']}",
                     job_id=self.job_id, business_id=business_id, stage="normalize", level="warn")

        phone_digits = [phone["phone_normalized"]] if phone["phone_normalized"] else []
        if biz["phone_raw"]:
            phone_digits.append(biz["phone_raw"])

        # ---------------- 2. website discovery ----------------
        stage("discovery")
        try:
            if self.source_kind == "url":
                # A direct-URL audit: the user explicitly supplied this exact
                # URL to be audited, so there is no business identity to
                # match it against - see verify_direct_website's docstring.
                disc = await verify_direct_website(self.fetcher, biz["website_original"])
            else:
                disc = await discover_website(
                    self.fetcher,
                    business_name=name,
                    website_raw=biz["website_original"],
                    phone_digits=phone_digits,
                    city=biz["city"], state=biz["state"], postal_code=biz["postal_code"],
                    address=biz["address"], category=biz["category"], region=region,
                    enable_guessing=bool(self.engine_cfg.get("enable_website_discovery", True)),
                    min_confidence=float(self.engine_cfg.get("min_identity_confidence", 0.55)),
                )
        except Exception as exc:
            await self._record_failure(business_id, "discovery", "discovery_failed",
                                       f"{type(exc).__name__}: {exc}", retryable=True)
            disc = None

        if disc is None:
            self.progress.failed += 1
            self.progress.processed += 1
            return

        if disc.has_website:
            activity(name, f"Website {'confirmed' if disc.source == 'csv' else 'discovered'}: "
                           f"{disc.website_final}"
                           + (f" (identity {int((disc.identity_confidence or 0) * 100)}%)"
                              if disc.identity_confidence is not None else ""),
                     job_id=self.job_id, business_id=business_id, stage="discovery")
        else:
            activity(name, f"No usable website ({disc.status})",
                     job_id=self.job_id, business_id=business_id, stage="discovery", level="warn")
            for note in disc.notes[:2]:
                activity(name, note, job_id=self.job_id, business_id=business_id,
                         stage="discovery", level="warn")

        for err_note in ([disc.error_message] if disc.error_code else []):
            await self._record_error(business_id, "discovery", disc.error_code, err_note,
                                     retryable=disc.error_code in ("timeout", "connection_error"),
                                     url=disc.website_original)

        # ---------------- website required ----------------
        # A valid, identity-confirmed website (disc.has_website) is required for
        # any further processing. Leads without one - none supplied, none
        # discoverable, or the supplied one unreachable/blocked/mismatched/not
        # actually a website - are excluded outright: no crawl, no audit, no
        # score, no drafts. See _skip_no_website.
        if not disc.has_website:
            await self._skip_no_website(business_id, name, disc)
            return

        # ---------------- 3-5. crawl / extract / validate ----------------
        crawl = None
        extracted = ExtractionResult()
        validations = []
        site_domain = registrable_domain(disc.website_final) if disc.website_final else ""

        if disc.has_website:
            stage("crawl")
            try:
                crawl = await crawl_site(
                    self.fetcher,
                    disc.website_final,
                    max_pages=int(self.engine_cfg["max_pages_per_site"]),
                    max_depth=int(self.engine_cfg["max_crawl_depth"]),
                    total_budget_s=float(self.engine_cfg["total_site_budget_s"]),
                    on_event=lambda msg, lvl="info": activity(
                        name, msg, job_id=self.job_id, business_id=business_id,
                        stage="crawl", level=lvl,
                    ),
                )
            except Exception as exc:
                await self._record_failure(business_id, "crawl", "crawl_failed",
                                           f"{type(exc).__name__}: {exc}", retryable=True)
                crawl = None

            if crawl and crawl.ok:
                activity(name, f"Crawled {len(crawl.pages)} page(s): "
                               f"{', '.join(sorted(crawl.types_found()))}",
                         job_id=self.job_id, business_id=business_id, stage="crawl")
                for ce in crawl.errors[:4]:
                    await self._record_error(business_id, "crawl", ce.code, ce.message,
                                             retryable=ce.retryable, url=ce.url)

                stage("extract")
                try:
                    extracted = extract_contacts(crawl, site_domain)
                except Exception as exc:
                    await self._record_error(business_id, "extract", "extract_failed",
                                             f"{type(exc).__name__}: {exc}", retryable=False)
                    extracted = ExtractionResult()

                if extracted.emails:
                    activity(name, f"Found {len(extracted.emails)} public email address(es); "
                                   f"best: {extracted.emails[0].email} "
                                   f"(from {extracted.emails[0].page_type} page)",
                             job_id=self.job_id, business_id=business_id, stage="extract")
                else:
                    activity(name, "No public email address published on the website",
                             job_id=self.job_id, business_id=business_id, stage="extract",
                             level="warn")

                stage("validate_emails")
                try:
                    validations = await validate_all(
                        extracted.emails, site_domain=site_domain,
                        enable_mx=bool(self.engine_cfg.get("enable_mx_lookup", True)),
                        dns_timeout=float(self.engine_cfg.get("dns_timeout_s", 4.0)),
                    )
                except Exception as exc:
                    await self._record_error(business_id, "validate_emails", "validation_failed",
                                             f"{type(exc).__name__}: {exc}", retryable=True)
                    validations = []
                if validations:
                    activity(name, f"Email validation: " + ", ".join(
                        f"{v.email} = {v.status}" for v in validations[:2]),
                             job_id=self.job_id, business_id=business_id, stage="validate_emails")
            elif crawl:
                for ce in crawl.errors[:3]:
                    await self._record_error(business_id, "crawl", ce.code, ce.message,
                                             retryable=ce.retryable, url=ce.url)
                activity(name, f"Website could not be crawled: "
                               f"{crawl.errors[0].message if crawl.errors else 'unknown error'}",
                         job_id=self.job_id, business_id=business_id, stage="crawl", level="error")

        # ---------------- 6. audit ----------------
        stage("audit")
        perf = None
        if (
            self.engine_cfg.get("pagespeed_enabled")
            and self.engine_cfg.get("pagespeed_api_key")
            and crawl and crawl.ok
        ):
            try:
                perf = await ps.measure(
                    crawl.final_url,
                    self.engine_cfg["pagespeed_api_key"],
                    self.engine_cfg.get("pagespeed_strategy", "mobile"),
                )
                if perf.get("measured"):
                    activity(name, f"PageSpeed {perf['strategy']}: {perf['performance_score']}/100",
                             job_id=self.job_id, business_id=business_id, stage="audit")
                else:
                    await self._record_error(business_id, "audit", "pagespeed_unavailable",
                                             perf.get("error_message", "PageSpeed unavailable"),
                                             retryable=True, url=crawl.final_url)
            except Exception as exc:
                await self._record_error(business_id, "audit", "pagespeed_error",
                                         f"{type(exc).__name__}: {exc}", retryable=True)

        findings: List[Finding] = []
        facts: Dict[str, Dict[str, Any]] = {}
        extra_facts: Dict[str, Dict[str, Any]] = {}
        extra_findings: List[Finding] = []
        scorecard: Dict[str, Any] = {}
        audit_kind = "website"
        audit_status = "completed"
        audit_error = ""

        if crawl and crawl.ok:
            facts, findings = run_all_checks(
                crawl, extracted=extracted, perf=perf, category_hint=biz["category"]
            )
            # Premium audit scorecard: additive checks (security, accessibility,
            # on-page extras, off-page/authority, performance extras) layered on
            # top of the same findings, never altering the opportunity score above.
            extra_facts, extra_findings = run_extra_checks(crawl)
            scorecard = build_scorecard(findings + extra_findings)
            activity(name, f"Premium audit scorecard: {scorecard['overall_score']}/100 overall "
                           f"({scorecard['pass_fail']['passed_count']}/{scorecard['pass_fail']['total_checked']} checks passed)",
                     job_id=self.job_id, business_id=business_id, stage="audit")
        elif disc.status == STATUS_NOT_A_WEBSITE:
            audit_kind = "no_website"
            findings = no_website_findings(
                "The listed web address is a third-party profile, not a website the business owns.",
                social_url=disc.social_profile_url,
            )
        elif disc.status == STATUS_NO_WEBSITE:
            audit_kind = "no_website"
            findings = no_website_findings(
                disc.notes[0] if disc.notes else "No website was found for this business."
            )
        elif disc.status == "mismatch":
            audit_status = "failed"
            audit_error = (
                "The site listed for this business shows no sign of belonging to it "
                f"(identity confidence {int((disc.identity_confidence or 0) * 100)}%). "
                "It was not audited, because auditing someone else's website would produce "
                "findings that are useless for outreach."
            )
        else:
            audit_status = "failed"
            audit_error = (
                disc.error_message
                or (crawl.errors[0].message if crawl and crawl.errors else "")
                or f"The website could not be audited (status: {disc.status})."
            )

        # ---------------- 7. score ----------------
        stage("score")
        score_result = None
        problems: List[Dict[str, Any]] = []
        recommendations: List[Dict[str, Any]] = []
        opp_tier = ""
        score_val: Optional[int] = None

        if audit_status == "completed" and audit_kind == "website":
            score_result = compute_score(findings, self.weights_cfg["weights"])
            score_val = score_result["score"]
            opp_tier, _ = tier_for_score(score_val, self.weights_cfg["tiers"])
            problems = select_problems(findings, int(self.weights_cfg.get("max_problems", 7)))
            recommendations = build_recommendations(problems, findings)
            activity(name, f"Website opportunity score: {score_val}/100 ({opp_tier}) — "
                           f"{len(problems)} problem(s) detected",
                     job_id=self.job_id, business_id=business_id, stage="score")
        elif audit_kind == "no_website":
            problems = [
                {
                    "rank": 1, "code": f.code, "category": f.display_category,
                    "category_label": CATEGORY_LABELS.get(f.display_category, f.display_category),
                    "severity": f.severity, "title": f.title, "detail": f.detail,
                    "evidence": f.evidence, "impact_points": 0, "is_strong_signal": True,
                }
                for f in findings
            ]
            recommendations = [
                {"rank": 1, "problem_code": f.code, "problem": f.title,
                 "recommendation": f.recommendation, "category": f.display_category,
                 "severity": f.severity}
                for f in findings if f.recommendation
            ]
            # No score: nothing was audited. The tier names the situation
            # instead, so these leads stay visible rather than looking unscored.
            opp_tier = "No website"
            activity(name, "Classified as a no-website opportunity",
                     job_id=self.job_id, business_id=business_id, stage="score")
        else:
            activity(name, f"Audit could not be completed: {audit_error}",
                     job_id=self.job_id, business_id=business_id, stage="audit", level="error")

        clear, no_opp_reason = has_clear_opportunity(
            problems, score_val if audit_kind == "website" else 50,
            int(self.weights_cfg.get("min_problems_for_outreach", 1)),
        )

        # ---------------- 8. WhatsApp check (strict) ----------------
        # A phone number being a WhatsApp-capable mobile is NOT, by itself,
        # evidence WhatsApp is usable - only a link actually published on the
        # business's own website counts. See choose_channel().
        stage("whatsapp_check")
        wa = assess_whatsapp(phone, extracted.whatsapp_numbers)
        wa_confirmed = wa["whatsapp_status"] == "confirmed_on_website"
        activity(
            name,
            "WhatsApp confirmed via a link on the business website"
            if wa_confirmed else f"WhatsApp not confirmed ({wa['whatsapp_status']}) — moving on",
            job_id=self.job_id, business_id=business_id, stage="whatsapp_check",
            level="info" if wa_confirmed else "warn",
        )

        # ---------------- 9. email discovery ----------------
        # Short-circuited once WhatsApp is confirmed (spec: do not spend time
        # on channels ranked below one already usable, unless the operator
        # explicitly asked for full contact discovery on every lead).
        stage("email_discovery")
        full_discovery = bool(self.engine_cfg.get("full_contact_discovery"))
        best_email = None
        best_email_status = ""
        if not wa_confirmed or full_discovery:
            for v in validations:
                if is_usable_for_outreach(v.status):
                    best_email = v.email
                    best_email_status = v.status
                    break
            if best_email is None and validations:
                best_email_status = validations[0].status
            activity(
                name,
                f"Public email found: {best_email}" if best_email else "No usable public email found",
                job_id=self.job_id, business_id=business_id, stage="email_discovery",
                level="info" if best_email else "warn",
            )
        else:
            activity(name, "Email discovery skipped — WhatsApp already confirmed",
                     job_id=self.job_id, business_id=business_id, stage="email_discovery")

        # ---------------- 10. LinkedIn discovery ----------------
        # Only ever the business's own published link (found during the same
        # crawl already done for the audit - no separate LinkedIn crawl is
        # ever attempted), and only looked for once WhatsApp and email have
        # both come up empty, unless full contact discovery is enabled.
        stage("linkedin_discovery")
        linkedin_url = ""
        linkedin_status = "not_checked"
        if full_discovery or not (wa_confirmed or best_email):
            linkedin_url = extracted.linkedin_urls[0] if extracted.linkedin_urls else ""
            linkedin_status = "found" if linkedin_url else "not_found"
            activity(
                name,
                f"LinkedIn company page found: {linkedin_url}" if linkedin_url
                else "No LinkedIn company page found on the website",
                job_id=self.job_id, business_id=business_id, stage="linkedin_discovery",
                level="info" if linkedin_url else "warn",
            )
        else:
            activity(name, "LinkedIn discovery skipped — WhatsApp/email already usable",
                     job_id=self.job_id, business_id=business_id, stage="linkedin_discovery")

        channel = choose_channel(
            whatsapp_status=wa["whatsapp_status"],
            whatsapp_number=phone["phone_normalized"],
            usable_email=best_email,
            email_status=best_email_status or "none_found",
            linkedin_url=linkedin_url,
            phone_normalized=phone["phone_normalized"],
            phone_status=phone["validation_status"],
        )
        activity(
            name,
            f"Contact channel: {channel['channel'] or 'skip'} — {channel['reason']}",
            job_id=self.job_id, business_id=business_id, stage="linkedin_discovery",
            level="info" if channel["channel"] != "none" else "warn",
        )

        # ---------------- 11. message generation ----------------
        stage("message_generation")
        contact_name = extracted.contact_names[0] if extracted.contact_names else ""
        ctx = OutreachContext(
            business_id=business_id, business_name=name, category=biz["category"],
            city=biz["city"], state=biz["state"], country=biz["country"],
            website=disc.website_final, contact_name=contact_name,
            problems=problems, score=score_val, audit_kind=audit_kind,
            report_available=bool(problems),
        )

        drafts: List[Draft] = []
        prof_status = profile_status()
        if channel["channel"] == "none":
            activity(name, "No contact channel — nothing to draft (SKIP)",
                     job_id=self.job_id, business_id=business_id, stage="message_generation")
        elif not clear:
            activity(name, f"No outreach generated — {no_opp_reason}",
                     job_id=self.job_id, business_id=business_id, stage="message_generation", level="warn")
        elif not prof_status["configured"]:
            await self._record_error(
                business_id, "outreach", "profile_incomplete",
                "Outreach was not generated because your identity is not configured in Settings "
                f"(missing: {', '.join(prof_status['missing_core'])}).",
                retryable=True,
            )
            activity(name, "Outreach skipped — your profile is not configured in Settings",
                     job_id=self.job_id, business_id=business_id, stage="message_generation", level="warn")
        else:
            drafts = await self._build_drafts(ctx, channel["channel"], wa, phone, best_email,
                                              business_id, name, linkedin_url=linkedin_url)

        # ---------------- 10. report ----------------
        stage("report")
        report_path = ""
        if audit_status == "completed" or audit_kind == "no_website":
            try:
                report_path = self._write_report(
                    biz, disc, crawl, facts, score_result, problems, recommendations,
                    audit_kind, phone, wa, validations, extracted, business_id, name,
                    legacy_findings=findings,
                    extra_facts=extra_facts, extra_findings=extra_findings, scorecard=scorecard,
                )
                activity(name, "Audit report generated",
                         job_id=self.job_id, business_id=business_id, stage="report")
            except Exception as exc:
                await self._record_error(business_id, "report", "report_failed",
                                         f"{type(exc).__name__}: {exc}", retryable=False)

        # ---------------- persist ----------------
        tier_info = lead_tier(
            score=score_val if audit_kind == "website" else (50 if audit_kind == "no_website" else None),
            website_status=disc.status,
            has_usable_contact=channel["channel"] not in ("none",),
            strong_problem_count=sum(1 for p in problems if p.get("is_strong_signal")),
            problem_count=len(problems),
            audit_kind=audit_kind,
            review_count=biz["review_count"],
            rating=biz["rating"],
        )

        payload = {
            "disc": disc, "phone": phone, "wa": wa, "extracted": extracted,
            "validations": validations, "facts": facts, "score_result": score_result,
            "problems": problems, "recommendations": recommendations, "drafts": drafts,
            "channel": channel, "tier": tier_info, "audit_kind": audit_kind,
            "audit_status": audit_status, "audit_error": audit_error,
            "report_path": report_path, "crawl": crawl, "score": score_val,
            "opp_tier": opp_tier, "clear": clear, "no_opp_reason": no_opp_reason,
            "extra_facts": extra_facts, "extra_findings": extra_findings, "scorecard": scorecard,
            "linkedin_url": linkedin_url, "linkedin_status": linkedin_status,
        }
        await run_db(lambda s: self._persist(s, business_id, payload))

        stage("done")
        await run_db(lambda s: _complete_item(s, business_id))
        self.progress.processed += 1
        self.progress.succeeded += 1
        if channel["channel"] == "whatsapp":
            self.progress.whatsapp_found += 1
        elif channel["channel"] == "email":
            self.progress.email_found += 1
        elif channel["channel"] == "linkedin":
            self.progress.linkedin_found += 1
        elif channel["channel"] == "phone":
            self.progress.phone_found += 1
        else:
            self.progress.no_channel += 1
        activity(name, f"Complete — lead tier {tier_info['tier']}, channel {channel['channel'] or 'skip'}",
                 job_id=self.job_id, business_id=business_id, stage="done")

    # ---- website-required gate -------------------------------------------

    async def _skip_no_website(self, business_id: int, name: str, disc) -> None:
        """
        No valid, identity-confirmed website exists for this business - none was
        supplied and none could be discovered, or the supplied one was
        unreachable, blocked, mismatched, or not actually a website
        (disc.has_website is False). Such leads are excluded outright: no
        crawl, no audit, no score, no drafts. The row stays in the job (and
        the export, per spec 11) so the reason is visible, but nothing about
        it is invented or pitched.
        """

        def _work(s):
            biz: Business = s.get(Business, business_id)
            if biz is not None:
                biz.website_original = disc.website_original
                biz.website_final = disc.website_final
                biz.website_status = disc.status
                biz.website_identity_confidence = disc.identity_confidence
                biz.website_source = disc.source
                biz.best_channel = "none"
                biz.channel_reason = (
                    "No valid website could be confirmed for this business "
                    f"(status: {disc.status}), so it was excluded from audit, "
                    "scoring and outreach."
                )
                biz.processed_at = utcnow()

            item = s.query(JobItem).filter(JobItem.business_id == business_id).first()
            if item:
                item.status = "skipped"
                item.stage = "no_website"
                item.error_message = (
                    f"Skipped — no valid website (status: {disc.status}). Leads without a "
                    "confirmed website are not audited, scored or drafted."
                )
                item.error_stage = "discovery"
                item.finished_at = utcnow()
                stages = list(item.completed_stages or [])
                if "no_website" not in stages:
                    stages.append("no_website")
                item.completed_stages = stages

        await run_db(_work)
        self.progress.processed += 1
        self.progress.skipped += 1
        activity(
            name,
            f"Skipped — no valid website (status: {disc.status}); not audited, scored or drafted.",
            job_id=self.job_id, business_id=business_id, stage="discovery", level="warn",
        )

    # ---- drafts ---------------------------------------------------------

    async def _build_drafts(
        self, ctx: OutreachContext, channel: str, wa: Dict[str, str],
        phone: Dict[str, Any], best_email: Optional[str], business_id: int, name: str,
        linkedin_url: str = "",
    ) -> List[Draft]:
        drafts: List[Draft] = []
        try:
            if channel == "whatsapp":
                for variant in ("initial", "followup_1", "followup_2"):
                    d = build_whatsapp_message(ctx, self.profile, variant)
                    if d.ok:
                        d.draft_url = whatsapp_url(phone["phone_normalized"], d.message)
                        drafts.append(d)
                if drafts:
                    activity(name, "WhatsApp draft generated from measured findings",
                             job_id=self.job_id, business_id=business_id, stage="message_generation")

            elif channel == "email":
                for variant in ("initial", "followup_1", "followup_2"):
                    d = build_email_message(ctx, self.profile, variant)
                    if d.ok:
                        d.draft_url = mailto_url(best_email or "", d.subject, d.message)
                        drafts.append(d)
                if drafts:
                    activity(name, "Email draft generated from measured findings",
                             job_id=self.job_id, business_id=business_id, stage="message_generation")

            elif channel == "linkedin":
                d = build_linkedin_message(ctx, self.profile, "initial")
                if d.ok:
                    # LinkedIn has no URL scheme to pre-fill a DM, so the draft
                    # opens the company page itself; the message is copied
                    # manually (spec: "Open LinkedIn" + "Copy LinkedIn Message").
                    d.draft_url = linkedin_url
                    drafts.append(d)
                    activity(name, "LinkedIn draft generated from measured findings",
                             job_id=self.job_id, business_id=business_id, stage="message_generation")

            elif channel == "phone":
                d = build_call_notes(ctx, self.profile)
                if d.ok:
                    drafts.append(d)
                    activity(name, "Added to the call list with a prepared opener",
                             job_id=self.job_id, business_id=business_id, stage="message_generation")
        except ProfileIncomplete as exc:
            await self._record_error(business_id, "outreach", "profile_incomplete", str(exc),
                                     retryable=True)
        except Exception as exc:
            await self._record_error(business_id, "outreach", "outreach_failed",
                                     f"{type(exc).__name__}: {exc}", retryable=False)
        return drafts

    # ---- report ---------------------------------------------------------

    def _write_report(
        self, biz, disc, crawl, facts, score_result, problems, recommendations,
        audit_kind, phone, wa, validations, extracted, business_id, name,
        *, legacy_findings: Optional[List[Finding]] = None,
        extra_facts: Optional[Dict[str, Any]] = None,
        extra_findings: Optional[List[Finding]] = None,
        scorecard: Optional[Dict[str, Any]] = None,
    ) -> str:
        location = ", ".join(p for p in (biz["city"], biz["state"], biz["country"]) if p)
        contacts: List[Dict[str, Any]] = []
        if phone["phone_normalized"]:
            contacts.append({
                "label": "Phone", "value": phone["phone_normalized"],
                "status": phone["validation_status"],
                "pill": "ok" if phone["validation_status"] == "valid" else "warn",
            })
        elif biz["phone_raw"]:
            contacts.append({"label": "Phone (raw)", "value": biz["phone_raw"],
                             "status": phone["validation_status"], "pill": "warn"})
        contacts.append({
            "label": "WhatsApp", "value": wa["whatsapp_reason"],
            "status": wa["whatsapp_status"],
            "pill": "ok" if wa["whatsapp_status"] in ("confirmed_on_website", "usable_unverified") else "neutral",
        })
        for v in validations[:3]:
            contacts.append({
                "label": "Email", "value": v.email, "status": v.status,
                "pill": "ok" if v.status in ("valid_public", "mx_valid") else "warn",
            })
        if not validations:
            contacts.append({"label": "Email", "value": "None published on the website",
                             "status": "", "pill": "neutral"})
        for u in extracted.contact_form_urls[:1]:
            contacts.append({"label": "Contact form", "value": u, "status": "found", "pill": "ok"})

        pages = []
        if crawl:
            for p in crawl.pages:
                pages.append({"type": p.page_type, "url": p.final_url or p.url,
                              "status": p.status or "—"})

        audit_dict = {
            "website": disc.website_final or disc.website_original,
            "score": score_result["score"] if score_result else None,
            "opportunity_tier": "" if not score_result else
                tier_for_score(score_result["score"], self.weights_cfg["tiers"])[0],
            "technical": facts.get("technical", {}),
            "mobile": facts.get("mobile", {}),
            "conversion": facts.get("conversion", {}),
        }
        html = render_report(
            business={
                "name": name, "location": location, "category": biz["category"],
                "lead_tier": "",
            },
            audit=audit_dict,
            problems=problems,
            recommendations=recommendations,
            explanation=score_result["explanation"] if score_result else [],
            contacts=contacts,
            pages=pages,
            generator=self.profile.get("company_name", ""),
            scorecard=scorecard or {},
            legacy_findings=legacy_findings or [],
            extra_findings=extra_findings or [],
            extra_facts=extra_facts or {},
        )
        return write_report(self.job_id, business_id, name, html)

    # ---- persistence ----------------------------------------------------

    def _persist(self, s, business_id: int, p: Dict[str, Any]) -> None:
        biz: Business = s.get(Business, business_id)
        if biz is None:
            return
        disc = p["disc"]

        biz.website_original = disc.website_original
        biz.website_final = disc.website_final
        biz.website_status = disc.status
        biz.website_identity_confidence = disc.identity_confidence
        biz.website_source = disc.source
        biz.score = p["score"]
        biz.opportunity_tier = p["opp_tier"]
        biz.lead_tier = p["tier"]["tier"]
        biz.audit_kind = p["audit_kind"]
        biz.best_channel = p["channel"]["channel"]
        biz.channel_reason = p["channel"]["reason"][:500]
        biz.linkedin_url = p["linkedin_url"]
        biz.linkedin_status = p["linkedin_status"]
        biz.processed_at = utcnow()

        # phone
        s.query(ContactPhone).filter(ContactPhone.business_id == business_id).delete()
        ph = p["phone"]
        if ph["phone_raw"]:
            s.add(ContactPhone(
                business_id=business_id,
                phone_raw=ph["phone_raw"], phone_normalized=ph["phone_normalized"],
                phone_national=ph["phone_national"], phone_country=ph["phone_country"],
                phone_country_name=ph["phone_country_name"],
                phone_calling_code=ph["phone_calling_code"], phone_type=ph["phone_type"],
                validation_status=ph["validation_status"], source=ph["source"],
                whatsapp_status=p["wa"]["whatsapp_status"],
                whatsapp_reason=p["wa"]["whatsapp_reason"][:500],
                # Only ever the drafted link, which always carries the full
                # personalized message (?text=...). A bare wa.me/NUMBER link
                # with no message is never stored - a lead is either drafted
                # with a message or has no WhatsApp link at all, so a click
                # can never open an empty chat.
                whatsapp_url=next(
                    (d.draft_url for d in p["drafts"]
                     if d.channel == "whatsapp" and d.variant == "initial"), ""
                ),
                rank=0,
            ))

        # emails
        s.query(ContactEmail).filter(ContactEmail.business_id == business_id).delete()
        found_by_email = {f.email: f for f in p["extracted"].emails}
        for i, v in enumerate(p["validations"]):
            f = found_by_email.get(v.email)
            s.add(ContactEmail(
                business_id=business_id, email=v.email,
                source_url=f.source_url if f else "", source_type=f.source_type if f else "",
                page_type=f.page_type if f else "", status=v.status,
                confidence=v.confidence, is_role=v.is_role, is_disposable=v.is_disposable,
                domain_matches_site=v.domain_matches_site, mx_records=v.mx_records,
                validation_notes=v.notes, rank=i,
            ))

        # audit
        s.query(WebsiteAudit).filter(WebsiteAudit.business_id == business_id).delete()
        crawl = p["crawl"]
        sr = p["score_result"]
        s.add(WebsiteAudit(
            business_id=business_id,
            website=disc.website_final or disc.website_original,
            audit_kind=p["audit_kind"],
            http_status=disc.http_status if not crawl else crawl.home_status,
            is_https=crawl.is_https if crawl else None,
            redirect_chain=(crawl.redirect_chain if crawl else disc.redirect_chain) or [],
            response_ms=crawl.home_response_ms if crawl else disc.response_ms,
            pages_crawled=len(crawl.pages) if crawl else 0,
            pages=[
                {"type": pg.page_type, "url": pg.final_url or pg.url, "status": pg.status,
                 "words": pg.word_count, "elapsed_ms": pg.elapsed_ms}
                for pg in (crawl.pages if crawl else [])
            ],
            technical=p["facts"].get("technical", {}),
            conversion=p["facts"].get("conversion", {}),
            mobile=p["facts"].get("mobile", {}),
            trust=p["facts"].get("trust", {}),
            content=p["facts"].get("content", {}),
            performance=(p["facts"].get("technical", {}) or {}).get("pagespeed", {}),
            subscores=sr["subscores"] if sr else {},
            score=p["score"],
            opportunity_tier=p["opp_tier"],
            score_explanation=sr["explanation"] if sr else [],
            problems=p["problems"],
            recommendations=p["recommendations"],
            extra={
                "facts": p.get("extra_facts") or {},
                "findings": [f.to_dict() for f in (p.get("extra_findings") or [])],
                "scorecard": p.get("scorecard") or {},
            },
            report_path=p["report_path"],
            audit_status=p["audit_status"] if p["clear"] else (
                p["audit_status"] if p["audit_status"] != "completed" else "no_clear_opportunity"
            ),
            audit_error=p["audit_error"] or ("" if p["clear"] else p["no_opp_reason"]),
        ))

        # drafts
        s.query(OutreachDraft).filter(OutreachDraft.business_id == business_id).delete()
        for d in p["drafts"]:
            s.add(OutreachDraft(
                business_id=business_id, channel=d.channel, variant=d.variant,
                subject=d.subject, message=d.message, draft_url=d.draft_url,
                based_on=d.based_on, generator=d.generator,
            ))

    # ---- error helpers --------------------------------------------------

    async def _record_error(
        self, business_id: int, stage: str, code: str, message: str,
        retryable: bool = False, url: str = "",
    ) -> None:
        def _work(s):
            s.add(AuditError(
                job_id=self.job_id, business_id=business_id, stage=stage, code=code,
                message=(message or "")[:2000], retryable=retryable, url=(url or "")[:1000],
            ))

        try:
            await run_db(_work)
        except Exception:
            pass

    async def _record_failure(
        self, business_id: int, stage: str, code: str, message: str,
        retryable: bool = False, tb: str = "",
    ) -> None:
        await self._record_error(business_id, stage, code, message + ("\n" + tb if tb else ""),
                                 retryable)

        def _work(s):
            item = s.query(JobItem).filter(JobItem.business_id == business_id).first()
            if item:
                item.status = "failed"
                item.error_message = (message or "")[:2000]
                item.error_stage = stage
                item.retryable = retryable
                item.finished_at = utcnow()
                item.attempts = (item.attempts or 0) + 1

        try:
            await run_db(_work)
        except Exception:
            pass

        biz_name = await run_db(
            lambda s: (s.get(Business, business_id).name if s.get(Business, business_id) else ""),
            write=False,
        )
        activity(biz_name or f"#{business_id}", f"Failed at {stage}: {message[:200]}",
                 job_id=self.job_id, business_id=business_id, stage=stage, level="error")


# --------------------------------------------------------------------------
# small DB helpers
# --------------------------------------------------------------------------


def _business_dto(s, business_id: int) -> Optional[Dict[str, Any]]:
    b: Optional[Business] = s.get(Business, business_id)
    if b is None:
        return None
    return {
        "id": b.id, "name": b.name, "category": b.category, "address": b.address,
        "city": b.city, "state": b.state, "country": b.country,
        "postal_code": b.postal_code, "phone_raw": b.phone_raw,
        "website_original": b.website_original, "rating": b.rating,
        "review_count": b.review_count,
    }


def _start_item(s, business_id: int) -> None:
    item = s.query(JobItem).filter(JobItem.business_id == business_id).first()
    if item:
        item.status = "running"
        item.stage = "normalize"
        item.attempts = (item.attempts or 0) + 1
        if item.started_at is None:
            item.started_at = utcnow()
        item.error_message = ""
        item.error_stage = ""


def _complete_item(s, business_id: int) -> None:
    item = s.query(JobItem).filter(JobItem.business_id == business_id).first()
    if item:
        item.status = "completed"
        item.stage = "done"
        item.finished_at = utcnow()
        stages = list(item.completed_stages or [])
        if "done" not in stages:
            stages.append("done")
        item.completed_stages = stages


def _mark_stage(job_id: int, business_id: int, stage: str) -> None:
    """Fire-and-forget stage checkpoint; never blocks the pipeline."""

    def _work(s):
        item = s.query(JobItem).filter(JobItem.business_id == business_id).first()
        if item:
            item.stage = stage
            stages = list(item.completed_stages or [])
            if stage not in stages:
                stages.append(stage)
                item.completed_stages = stages

    try:
        with session_scope() as s:
            _work(s)
    except Exception:
        pass
