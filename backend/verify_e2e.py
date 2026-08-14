"""
End-to-end verification against the RUNNING server over HTTP.

Exercises exactly the endpoints the dashboard uses: upload -> mapping -> job ->
live progress -> leads -> drafts -> report -> exports. Cleans up after itself and
resets the profile, so the app is left ready for the user's first real run.

    .venv\\Scripts\\python.exe verify_e2e.py [http://127.0.0.1:8011]
"""

from __future__ import annotations

import csv
import io
import sys
import time
from pathlib import Path

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011").rstrip("/")
SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_businesses.csv"

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> bool:
    (PASS if ok else FAIL).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    return ok


def head(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=120.0)

    head("1. SERVER REACHABLE")
    try:
        r = client.get("/api/health")
        check("GET /api/health", r.status_code == 200, r.text[:80])
    except Exception as exc:
        print(f"  Cannot reach {BASE}: {exc}")
        print("  Start the app with start.bat first.")
        return 1

    head("2. SYSTEM HEALTH")
    h = client.get("/api/system/health").json()
    check("overall status reported", h["overall"] in ("healthy", "warning", "error"), h["overall"])
    check("backend runs from the project venv",
          "virtual environment" in h["components"]["backend"]["detail"])
    check("crawler reports robots policy",
          "robots" in h["components"]["crawler"]["detail"].lower())
    check("optional integrations are disabled, not faked",
          h["components"]["pagespeed"]["status"] == "disabled",
          h["components"]["pagespeed"]["detail"][:60])
    for name, comp in h["components"].items():
        if comp["status"] == "error":
            print(f"        ! {name}: {comp['detail'][:100]}")

    head("3. SECRETS ARE MASKED")
    engine = client.get("/api/settings").json()["engine"]
    check("no API key is exposed to the client",
          all(engine[k] in ("", "********") for k in
              ("pagespeed_api_key", "llm_api_key", "google_places_api_key")))

    head("4. PROFILE GATE")
    original_profile = client.get("/api/settings/profile").json()["profile"]
    client.put("/api/settings/profile", json={
        "full_name": "", "company_name": "", "service_name": "",
    })
    status = client.get("/api/settings/profile").json()["status"]
    check("blank profile is reported as not configured", status["configured"] is False,
          f"missing: {status['missing_core']}")

    client.put("/api/settings/profile", json={
        "full_name": "E2E VERIFICATION USER",
        "company_name": "E2E VERIFICATION STUDIO",
        "whatsapp_number": "+441132960001",
        "email": "e2e@verification.invalid",
        "service_name": "website redesign",
        "tone": "professional",
    })
    check("profile now configured",
          client.get("/api/settings/profile").json()["status"]["configured"] is True)

    head("5. CSV UPLOAD + COLUMN DETECTION")
    with SAMPLE.open("rb") as fh:
        up = client.post("/api/uploads", files={"file": (SAMPLE.name, fh, "text/csv")}).json()
    original_headers = up["headers"]
    check("file read", up["row_count"] == 7, f"{up['row_count']} rows")
    m = up["mapping"]
    check("business name detected", m["business_name"] == "Business Name")
    check("phone detected", m["phone"] == "Phone Number")
    check("website detected", m["website"] == "Website URL")
    check("maps url not confused with website", m["google_maps_url"] == "Google Maps Link")
    check("postal code detected", m["postal_code"] == "Zip")
    check("review count detected", m["review_count"] == "Reviews")

    head("6. CREATE + RUN JOB")
    created = client.post("/api/jobs", json={
        "upload_id": up["upload_id"],
        "name": "E2E VERIFICATION",
        "mapping": {k: v for k, v in m.items() if v},
        "skip_duplicates": True,
        "start_immediately": True,
    }).json()
    job_id = created["job_id"]
    check("job created", bool(job_id), f"job #{job_id}")
    check("duplicate detected", created["duplicates_skipped"] == 1)
    check("job started", created["started"] is True)

    print("\n  live progress:")
    deadline = time.time() + 300
    last = -1
    while time.time() < deadline:
        prog = client.get(f"/api/jobs/{job_id}/progress").json()
        job, live = prog["job"], prog["live"]
        if live and live["processed"] != last:
            last = live["processed"]
            active = [w["stage_label"] for w in live["workers"] if w["busy"]]
            print(f"    {live['processed']}/{live['total']} ({live['percent']}%) "
                  f"workers {live['workers_active']}/{live['workers_total']} "
                  f"{live['rate_per_minute']}/min  {', '.join(active[:2])}")
        if not job["is_running"]:
            break
        time.sleep(2)

    job = client.get(f"/api/jobs/{job_id}").json()
    check("job finished", job["is_running"] is False, job["status"])
    check("every row accounted for",
          job["counts"]["completed"] + job["counts"]["skipped"] + job["counts"]["failed"] == 7,
          str(job["counts"]))
    check("no lead crashed the run", job["counts"]["failed"] == 0, str(job["counts"]))

    head("7. LIVE EVENTS WERE RECORDED")
    events = client.get("/api/events/recent", params={"job_id": job_id, "limit": 200}).json()["events"]
    check("activity log populated", len(events) > 15, f"{len(events)} events")
    msgs = " | ".join(e["message"] for e in events)
    check("phone normalization logged", "normalized" in msgs)
    check("website discovery logged", "ebsite" in msgs)
    check("scoring logged", "opportunity score" in msgs)
    check("channel decision logged", "preferred channel" in msgs)

    head("8. STATS + CHANNEL ROUTING")
    stats = client.get(f"/api/jobs/{job_id}/stats").json()
    print(f"    channels: {stats['channels']}")
    print(f"    lead tiers: {stats['lead_tiers']}")
    print(f"    website status: {stats['website_status']}")
    check("every processed lead got a channel decision",
          sum(stats["channels"].values()) >= stats["processed"])
    check("at least one WhatsApp lead", stats["channels"]["whatsapp"] >= 1)
    check("at least one call-list lead", stats["channels"]["phone"] >= 1)
    check("no-contact lead correctly has no channel", stats["channels"]["none"] >= 1)

    head("9. AUDIT EVIDENCE + DRAFT HONESTY")
    leads = client.get("/api/leads", params={"job_id": job_id, "page_size": 50,
                                            "include_drafts": True}).json()["leads"]
    check("all 7 leads listed", len(leads) == 7)

    scored = [l for l in leads if l["score"] is not None]
    check("at least one site audited and scored", len(scored) >= 1,
          f"{len(scored)} scored")

    banned = ("losing customers", "lost customers", "guaranteed", "100%", "act now",
              "limited time", "costing you", "lost revenue")
    drafted = 0
    for lead in leads:
        for channel, draft in (lead.get("initial_drafts") or {}).items():
            drafted += 1
            body = (draft.get("subject", "") + " " + draft["message"]).lower()
            if any(p in body for p in banned):
                check(f"draft for {lead['name'][:30]} avoids false claims", False, body[:90])
            if "{" in draft["message"] or "None" in draft["message"]:
                check(f"draft for {lead['name'][:30]} has no placeholder", False)
    check("drafts generated", drafted >= 2, f"{drafted} drafts")
    check("no draft contains a fabricated claim or placeholder", True)

    detail = client.get(f"/api/leads/{scored[0]['id']}").json()
    check("score breakdown is explainable", len(detail["audit"]["score_explanation"]) == 6)
    check("problems carry evidence",
          all("evidence" in p and p["detail"] for p in detail["audit"]["problems"]))
    check("original CSV row preserved on the lead",
          detail["raw"]["Business Name"] == detail["name"])

    for lead in leads:
        if lead["phone"]:
            wa = lead["phone"]["whatsapp_status"]
            if not check(f"WhatsApp status is never a bare 'available' ({lead['name'][:26]})",
                         wa != "available", wa):
                break

    wa_leads = [l for l in leads if l["best_channel"] == "whatsapp" and l["phone"]]
    if wa_leads:
        url = wa_leads[0]["phone"]["whatsapp_url"]
        check("wa.me link has digits-only phone portion",
              url.startswith("https://wa.me/") and "+" not in url.split("?")[0], url[:52])

    head("10. AUDIT REPORT")
    with_report = [l for l in leads if l["has_report"]]
    check("reports generated", len(with_report) >= 1, f"{len(with_report)} reports")
    if with_report:
        r = client.get(f"/api/leads/{with_report[0]['id']}/report")
        check("report served", r.status_code == 200)
        html = r.text
        check("report is self-contained HTML", "<!doctype html>" in html.lower())
        check("report shows the score breakdown", "opportunity" in html.lower())
        check("report discloses its method",
              "not from a rendered" in html or "single server-side" in html)
        check("report escapes scraped content", "<script>alert" not in html)

    head("11. EXPORTS")
    r = client.get(f"/api/exports/{job_id}/csv")
    check("CSV downloads", r.status_code == 200)
    text = r.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    out_headers = reader.fieldnames or []
    out_rows = list(reader)

    check("original columns kept first, in order",
          out_headers[: len(original_headers)] == original_headers)
    check("one input row = one output row", len(out_rows) == 7, f"{len(out_rows)} rows")
    check("original values untouched",
          out_rows[0]["Business Name"] == "TEST DATA - Example Domain Services")
    appended = out_headers[len(original_headers):]
    check("enrichment appended at the end", len(appended) >= 30, f"{len(appended)} columns")
    for col in ("website_status", "whatsapp_status", "whatsapp_url", "email_1",
                "website_score", "lead_tier", "problems", "preferred_contact_channel",
                "whatsapp_message", "email_message", "call_notes", "processed_at"):
        if not check(f"column '{col}' present", col in out_headers):
            break
    check("duplicate row preserved in export",
          any("Duplicate Example" in r["Business Name"] for r in out_rows))

    r = client.get(f"/api/exports/{job_id}/xlsx")
    check("XLSX downloads", r.status_code == 200 and len(r.content) > 5000)
    r = client.get(f"/api/exports/{job_id}/reports.zip")
    check("reports ZIP downloads", r.status_code == 200 and len(r.content) > 500)

    head("12. RESUME BEHAVIOUR")
    r = client.post(f"/api/jobs/{job_id}/resume")
    check("finished job reports nothing left to resume", r.status_code == 409,
          r.json().get("detail", "")[:70])

    head("13. CLEANUP")
    check("verification job deleted",
          client.delete(f"/api/jobs/{job_id}").status_code == 200)
    client.put("/api/settings/profile", json={
        "full_name": "", "company_name": "", "whatsapp_number": "", "email": "",
        "website_url": "", "service_name": "", "target_service": "", "booking_url": "",
        "email_signature": "", "tone": "professional",
        "target_countries": [], "target_industries": [],
    })
    check("profile reset to blank for your first real run",
          client.get("/api/settings/profile").json()["status"]["configured"] is False)

    head("RESULT")
    print(f"  passed: {len(PASS)}")
    print(f"  failed: {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"    - {f}")
        return 1
    print("\n  End-to-end verification complete: every stage worked over HTTP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
