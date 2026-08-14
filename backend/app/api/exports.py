"""CSV / XLSX / report exports (spec 33)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ..core.exporter import COLUMN_DOCS, ENRICHMENT_COLUMNS, export_csv, export_xlsx
from ..db import session_scope
from ..models import Business, Job, WebsiteAudit
from ..settings import EXPORT_DIR, REPORT_DIR

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/columns")
def enrichment_columns() -> Dict[str, Any]:
    return {
        "columns": ENRICHMENT_COLUMNS,
        "documentation": COLUMN_DOCS,
        "note": "These are appended after every original column from your CSV. Original columns "
                "and row order are preserved exactly, and one input business remains one output row.",
    }


@router.get("/{job_id}/csv")
def download_csv(job_id: int):
    with session_scope(write=False) as s:
        if not s.get(Job, job_id):
            raise HTTPException(status_code=404, detail="Job not found.")
        path = export_csv(s, job_id)
    return FileResponse(path, media_type="text/csv", filename=path.name)


@router.get("/{job_id}/xlsx")
def download_xlsx(job_id: int):
    with session_scope(write=False) as s:
        if not s.get(Job, job_id):
            raise HTTPException(status_code=404, detail="Job not found.")
        path = export_xlsx(s, job_id)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@router.get("/{job_id}/reports.zip")
def download_reports(job_id: int):
    with session_scope(write=False) as s:
        job = s.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        rows = (
            s.query(WebsiteAudit.report_path, Business.name)
            .join(Business, Business.id == WebsiteAudit.business_id)
            .filter(Business.job_id == job_id, WebsiteAudit.report_path != "")
            .all()
        )

    paths: List[Path] = []
    for report_path, _name in rows:
        p = Path(report_path).resolve()
        if REPORT_DIR.resolve() in p.parents and p.exists():
            paths.append(p)

    if not paths:
        raise HTTPException(status_code=404, detail="No audit reports have been generated yet.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="job{job_id}-audit-reports.zip"'},
    )


@router.get("/history")
def export_history(limit: int = 30) -> Dict[str, Any]:
    files = sorted(
        (p for p in EXPORT_DIR.glob("*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[: max(1, min(200, limit))]
    return {
        "files": [
            {
                "name": p.name,
                "size_bytes": p.stat().st_size,
                "modified": p.stat().st_mtime,
                "kind": p.suffix.lstrip("."),
            }
            for p in files
        ],
        "folder": str(EXPORT_DIR),
    }
