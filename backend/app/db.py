"""
Database access.

SQLite + WAL. Writes are serialized through a single lock because SQLite
allows only one writer; reads stay concurrent thanks to WAL. Async callers
go through `run_db()` which hops to a worker thread, so the event loop is
never blocked by disk I/O.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base
from .settings import DB_PATH

T = TypeVar("T")

_engine: Engine = create_engine(
    f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
    pool_pre_ping=True,
)


@event.listens_for(_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)

# Single writer lock. Cheap, and removes every "database is locked" class of bug.
_write_lock = threading.RLock()


def init_db() -> None:
    Base.metadata.create_all(_engine)
    _migrate_add_columns()


# `create_all` only creates missing tables - it never alters an existing one,
# so columns added to models.py after a database already exists (this app's
# own data/app.db, or an upgraded install) need a tiny explicit migration.
# Each entry is (table, column, DDL type); already-present columns are
# skipped, so this is safe to run on every startup.
_NEW_COLUMNS = [
    ("jobs", "source_kind", "VARCHAR(16) DEFAULT 'csv'"),
    ("website_audits", "extra", "JSON"),
    ("businesses", "linkedin_url", "VARCHAR(1024) DEFAULT ''"),
    ("businesses", "linkedin_status", "VARCHAR(32) DEFAULT 'not_checked'"),
]


def _migrate_add_columns() -> None:
    with _engine.connect() as conn:
        for table, column, ddl_type in _NEW_COLUMNS:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
        conn.commit()


@contextmanager
def session_scope(write: bool = True) -> Iterator[Session]:
    """Transactional session. `write=False` skips the writer lock."""
    lock = _write_lock if write else None
    if lock:
        lock.acquire()
    session = SessionLocal()
    try:
        yield session
        if write:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        if lock:
            lock.release()


async def run_db(fn: Callable[[Session], T], write: bool = True) -> T:
    """Run a DB unit of work off the event loop."""

    def _work() -> T:
        with session_scope(write=write) as s:
            return fn(s)

    return await asyncio.to_thread(_work)


def healthcheck() -> dict[str, Any]:
    try:
        with session_scope(write=False) as s:
            s.execute(text("SELECT 1"))
            mode = s.execute(text("PRAGMA journal_mode")).scalar()
        size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
        return {
            "status": "healthy",
            "path": str(DB_PATH),
            "journal_mode": mode,
            "size_bytes": size,
        }
    except Exception as exc:  # pragma: no cover - only on real disk failure
        return {"status": "error", "path": str(DB_PATH), "detail": str(exc)}
