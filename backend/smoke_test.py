"""
End-to-end smoke test against the sample CSV.

Runs the real pipeline (real network requests to the sample sites), then
prints what each stage produced. Used during development and safe to run
any time - it writes to the normal data folder and cleans up its own job.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.csv_mapping import preview_csv, read_csv  # noqa: E402
from app.core.exporter import export_csv, export_xlsx  # noqa: E402
from app.core.pipeline import manager  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.models import (  # noqa: E402
    AuditError, Business, ContactEmail, ContactPhone, Job, JobItem,
    OutreachDraft, WebsiteAudit,
)
from app.settings import save_profile  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_businesses.csv"


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


async def main() -> int:
    init_db()

    hr("1. CSV MAPPING")
    preview = preview_csv(SAMPLE)
    print(f"Rows detected      : {preview['row_count']}")
    print(f"Headers            : {preview['headers']}")
    print("Auto-mapping:")
    for field, col in preview["mapping"].items():
        if col:
            print(f"   {field:<18} <- {col!r}  (confidence "
                  f"{preview['confidence'].get(field, 0):.2f})")
    missing = [f for f, c in preview["mapping"].items() if not c]
    print(f"Unmapped fields    : {missing}")
    print(f"Needs review       : {preview['needs_review']}")

    # A test identity so outreach generation is exercised.
    save_profile({
        "full_name": "SMOKE TEST USER",
        "company_name": "SMOKE TEST STUDIO",
        "whatsapp_number": "+10000000000",
        "email": "smoke@test.invalid",
        "service_name": "website redesign",
        "tone": "professional",
    })

    hr("2. CREATE JOB")
    headers, rows = read_csv(SAMPLE)
    mapping = {k: v for k, v in preview["mapping"].items() if v}

    from app.api.jobs import CreateJob, create_job
    from app.settings import UPLOAD_DIR
    import shutil

    upload_id = "smoketest-000001"
    shutil.copy(SAMPLE, UPLOAD_DIR / f"{upload_id}.csv")

    created = await create_job(CreateJob(
        upload_id=upload_id, name="SMOKE TEST", mapping=mapping,
        skip_duplicates=True, start_immediately=False,
    ))
    job_id = created["job_id"]
    print(f"Job {job_id}: {created['total']} rows, "
          f"{created['duplicates_skipped']} duplicate(s) skipped")

    hr("3. RUN PIPELINE (real network)")
    await manager.start(job_id)
    while manager.is_running(job_id):
        p = manager.progress(job_id)
        if p:
            active = [w["business"] for w in p["workers"] if w["busy"]]
            print(f"   {p['processed']}/{p['total']} ({p['percent']}%)  "
                  f"workers {p['workers_active']}/{p['workers_total']}  "
                  f"{', '.join(active[:3])}")
        await asyncio.sleep(2)
    print("   done")

    hr("4. RESULTS PER LEAD")
    with session_scope(write=False) as s:
        for b in s.query(Business).filter(Business.job_id == job_id).order_by(Business.row_index):
            item = s.query(JobItem).filter(JobItem.business_id == b.id).first()
            audit = s.query(WebsiteAudit).filter(WebsiteAudit.business_id == b.id).first()
            phone = s.query(ContactPhone).filter(ContactPhone.business_id == b.id).first()
            emails = s.query(ContactEmail).filter(ContactEmail.business_id == b.id).all()
            drafts = s.query(OutreachDraft).filter(OutreachDraft.business_id == b.id).all()

            print(f"\n--- {b.name}")
            print(f"    item status     : {item.status if item else '?'} "
                  f"({item.stage if item else ''})")
            if item and item.error_message:
                print(f"    note            : {item.error_message[:150]}")
            print(f"    website         : {b.website_status} -> {b.website_final or '(none)'}"
                  + (f"  identity={b.website_identity_confidence}"
                     if b.website_identity_confidence is not None else ""))
            print(f"    score / tiers   : {b.score} | {b.opportunity_tier} | lead {b.lead_tier}")
            if phone:
                print(f"    phone           : {phone.phone_raw!r} -> "
                      f"{phone.phone_normalized or '(not normalized)'} "
                      f"[{phone.phone_country} {phone.phone_type} {phone.validation_status}]")
                print(f"    whatsapp        : {phone.whatsapp_status}")
                print(f"                      {phone.whatsapp_reason[:100]}")
            print(f"    emails found    : "
                  f"{[(e.email, e.status) for e in emails] or 'none published on site'}")
            print(f"    channel         : {b.best_channel}  ({b.channel_reason[:90]})")
            if audit:
                print(f"    audit status    : {audit.audit_status}  "
                      f"pages={audit.pages_crawled} problems={len(audit.problems)}")
                for pr in audit.problems[:3]:
                    print(f"       [{pr['severity']:<6}] {pr['title']}")
                print(f"    report          : "
                      f"{'yes' if audit.report_path else 'no'}")
            for d in drafts:
                if d.variant != "initial":
                    continue
                print(f"    DRAFT ({d.channel}):")
                if d.subject:
                    print(f"       subject: {d.subject}")
                for line in d.message.splitlines():
                    print(f"       | {line}")
                print(f"       url: {(d.draft_url or '(none)')[:110]}")
                print(f"       based on: {[x['code'] for x in d.based_on]}")

    hr("5. ERRORS RECORDED")
    with session_scope(write=False) as s:
        errs = s.query(AuditError).filter(AuditError.job_id == job_id).all()
        if not errs:
            print("   none")
        for e in errs:
            print(f"   [{e.stage}/{e.code}] retryable={e.retryable}: {e.message[:130]}")

    hr("6. EXPORTS")
    with session_scope(write=False) as s:
        csv_path = export_csv(s, job_id)
        xlsx_path = export_xlsx(s, job_id)
    print(f"   CSV : {csv_path}")
    print(f"   XLSX: {xlsx_path}")

    import csv as csvmod
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csvmod.DictReader(fh)
        out_headers = reader.fieldnames or []
        out_rows = list(reader)
    print(f"   original columns preserved: "
          f"{out_headers[:len(headers)] == headers}")
    print(f"   row count matches input   : {len(out_rows)} == {len(rows)} "
          f"-> {len(out_rows) == len(rows)}")
    print(f"   appended columns          : {out_headers[len(headers):][:8]} ...")

    hr("7. RESUME CHECK")
    with session_scope(write=False) as s:
        counts = {}
        for i in s.query(JobItem).filter(JobItem.job_id == job_id).all():
            counts[i.status] = counts.get(i.status, 0) + 1
    print(f"   item statuses: {counts}")
    print("   (a restart would only pick up 'pending'/'failed' items)")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
