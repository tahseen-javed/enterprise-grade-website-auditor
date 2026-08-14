"""Live activity stream (SSE) and global statistics."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..core.pipeline import manager
from ..db import session_scope
from ..events import bus
from ..models import EventLog

router = APIRouter(tags=["events"])


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/events/stream")
async def stream(request: Request) -> StreamingResponse:
    queue = await bus.subscribe()

    async def generator() -> AsyncIterator[str]:
        try:
            yield _sse("hello", {
                "connected": True,
                "recent": bus.recent(60),
                "running_jobs": manager.running_job_ids,
                "progress": manager.all_progress(),
            })
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                except (asyncio.TimeoutError, TimeoutError):
                    # Keep-alive so proxies and browsers hold the connection.
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(evt.get("type", "activity"), evt)
        except asyncio.CancelledError:
            raise
        finally:
            await bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/events/recent")
def recent(job_id: Optional[int] = None, limit: int = 120) -> Dict[str, Any]:
    limit = max(1, min(1000, limit))
    with session_scope(write=False) as s:
        q = s.query(EventLog)
        if job_id is not None:
            q = q.filter(EventLog.job_id == job_id)
        rows = q.order_by(EventLog.id.desc()).limit(limit).all()
        return {
            "events": [
                {
                    "id": e.id, "job_id": e.job_id, "business_id": e.business_id,
                    "business_name": e.business_name, "level": e.level, "stage": e.stage,
                    "message": e.message,
                    "ts": e.created_at.isoformat() if e.created_at else None,
                }
                for e in rows
            ]
        }


@router.get("/stats")
def global_stats(job_id: Optional[int] = None) -> Dict[str, Any]:
    from .jobs import _stats_for

    with session_scope(write=False) as s:
        stats = _stats_for(s, job_id)
    stats["running_jobs"] = manager.running_job_ids
    stats["live"] = manager.all_progress()
    return stats
