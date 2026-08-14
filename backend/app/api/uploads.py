"""CSV upload + column-mapping preview (spec 2, 45)."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..core.csv_mapping import (
    CANONICAL_FIELDS,
    EXCEL_SUFFIXES,
    CsvReadError,
    excel_to_csv_text,
    preview_csv,
    suggest_mapping,
    read_csv,
)
from ..settings import UPLOAD_DIR, config

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_SUFFIXES = {".csv", ".txt", ".tsv", *EXCEL_SUFFIXES}


def _safe_name(name: str) -> str:
    """Strip any path component - uploads must never escape the upload folder."""
    base = Path(name or "upload.csv").name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base[:120] or "upload.csv"


def _resolve_upload(upload_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", upload_id or ""):
        raise HTTPException(status_code=400, detail="Invalid upload id.")
    path = (UPLOAD_DIR / f"{upload_id}.csv").resolve()
    if UPLOAD_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid upload path.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="That upload no longer exists.")
    return path


@router.post("")
async def upload_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
    original_name = _safe_name(file.filename or "upload.csv")
    suffix = Path(original_name).suffix.lower()
    if suffix and suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"'{suffix}' files are not supported. Upload a .csv, .tsv or .xlsx file.",
        )
    is_excel = suffix in EXCEL_SUFFIXES

    upload_id = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    # Every upload - CSV, TSV or Excel - is normalized to one stored .csv file,
    # so preview/remap/job-creation never need to know which format arrived.
    dest = UPLOAD_DIR / f"{upload_id}.csv"

    size = 0
    try:
        if is_excel:
            # Excel needs the whole file before it can be parsed, so it is
            # buffered in memory (bounded by the same size limit as CSV)
            # rather than streamed straight to disk.
            raw = bytearray()
            while chunk := await file.read(1024 * 1024):
                raw.extend(chunk)
                if len(raw) > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"The file is larger than the "
                               f"{config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
            size = len(raw)
            if size == 0:
                raise HTTPException(status_code=400, detail="The uploaded file is empty.")
            try:
                csv_text = excel_to_csv_text(bytes(raw))
            except CsvReadError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail=f"The Excel file could not be read: {exc}"
                ) from None
            dest.write_text(csv_text, encoding="utf-8", newline="")
        else:
            with dest.open("wb") as fh:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"The file is larger than the "
                                   f"{config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                        )
                    fh.write(chunk)
            if size == 0:
                raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    try:
        preview = preview_csv(dest)
    except CsvReadError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"The file could not be read as CSV: {exc}"
        ) from None

    return {
        "upload_id": upload_id,
        "filename": original_name,
        "size_bytes": size,
        "source_format": "excel" if is_excel else "csv",
        "canonical_fields": CANONICAL_FIELDS,
        **preview,
    }


@router.get("/{upload_id}/preview")
def preview(upload_id: str, sample: int = 25) -> Dict[str, Any]:
    path = _resolve_upload(upload_id)
    try:
        data = preview_csv(path, sample=max(1, min(200, sample)))
    except CsvReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"upload_id": upload_id, "canonical_fields": CANONICAL_FIELDS, **data}


@router.post("/{upload_id}/remap")
def remap(upload_id: str) -> Dict[str, Any]:
    """Re-run the mapping suggestion against a larger sample."""
    path = _resolve_upload(upload_id)
    try:
        headers, rows = read_csv(path, limit=200)
    except CsvReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"upload_id": upload_id, "headers": headers, **suggest_mapping(headers, rows)}
