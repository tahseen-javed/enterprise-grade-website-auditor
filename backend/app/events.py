"""
In-process event bus feeding the live dashboard over SSE.

Subscribers get bounded queues: a slow browser tab drops its own oldest
events rather than back-pressuring the pipeline. Events are also persisted
(trimmed) so the activity log survives a page reload.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set

from .db import session_scope
from .models import EventLog

MAX_QUEUE = 500
MEMORY_RING = 400
PERSIST_LIMIT = 5000


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._recent: Deque[Dict[str, Any]] = deque(maxlen=MEMORY_RING)
        self._lock = asyncio.Lock()
        self._persist_counter = 0

    # -- subscription -----------------------------------------------------

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        items = list(self._recent)
        return items[-limit:][::-1]

    # -- publishing -------------------------------------------------------

    def emit(
        self,
        *,
        type: str,
        job_id: int = 0,
        business_id: Optional[int] = None,
        business_name: str = "",
        stage: str = "",
        message: str = "",
        level: str = "info",
        data: Optional[Dict[str, Any]] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        evt = {
            "type": type,
            "job_id": job_id,
            "business_id": business_id,
            "business_name": business_name,
            "stage": stage,
            "message": message,
            "level": level,
            "data": data or {},
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

        if type == "activity":
            self._recent.append(evt)

        for q in list(self._subscribers):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                # Drop this subscriber's oldest event, keep the newest.
                try:
                    q.get_nowait()
                    q.put_nowait(evt)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

        if persist and type == "activity":
            self._persist(evt)
        return evt

    def _persist(self, evt: Dict[str, Any]) -> None:
        try:
            with session_scope() as s:
                s.add(
                    EventLog(
                        job_id=evt["job_id"] or 0,
                        business_id=evt["business_id"],
                        business_name=evt["business_name"][:500],
                        level=evt["level"],
                        stage=evt["stage"],
                        message=evt["message"][:2000],
                    )
                )
            self._persist_counter += 1
            if self._persist_counter % 500 == 0:
                self._trim()
        except Exception:
            # The event log must never break the pipeline.
            pass

    def _trim(self) -> None:
        try:
            with session_scope() as s:
                total = s.query(EventLog).count()
                if total <= PERSIST_LIMIT:
                    return
                cutoff = (
                    s.query(EventLog.id)
                    .order_by(EventLog.id.desc())
                    .offset(PERSIST_LIMIT)
                    .limit(1)
                    .scalar()
                )
                if cutoff:
                    s.query(EventLog).filter(EventLog.id <= cutoff).delete(
                        synchronize_session=False
                    )
        except Exception:
            pass


bus = EventBus()


def activity(
    business_name: str,
    message: str,
    *,
    job_id: int = 0,
    business_id: Optional[int] = None,
    stage: str = "",
    level: str = "info",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Shorthand for the timestamped activity-log line the dashboard renders."""
    bus.emit(
        type="activity",
        job_id=job_id,
        business_id=business_id,
        business_name=business_name,
        stage=stage,
        message=message,
        level=level,
        data=data,
    )
