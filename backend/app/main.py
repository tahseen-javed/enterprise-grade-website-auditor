"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import audits, events_api, exports, health, jobs, leads, settings_api, uploads
from .db import init_db
from .core.pipeline import manager
from .settings import FRONTEND_DIST, LOG_DIR, config

# When FRONTEND_DIST exists, the backend serves it directly so the packaged
# app is a single process on a single port: no Node process has to stay
# running, and there is nothing else to install or start at runtime. When
# absent (e.g. running the backend alone for development), "/" falls back to
# a small JSON pointer instead of a broken page.
FRONTEND_ASSETS = FRONTEND_DIST / "assets"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "backend.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("website-auditor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("Database ready")
    log.info("%s v%s listening on http://%s:%s",
             config.APP_NAME, config.VERSION, config.BACKEND_HOST, config.BACKEND_PORT)
    try:
        yield
    finally:
        log.info("Shutting down; stopping running jobs so they can be resumed later")
        try:
            await asyncio.wait_for(manager.shutdown(), timeout=20)
        except (asyncio.TimeoutError, TimeoutError):
            log.warning("Job shutdown timed out; state is checkpointed and resumable")


app = FastAPI(
    title=config.APP_NAME,
    version=config.VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": f"{type(exc).__name__}: {exc}",
            "path": request.url.path,
        },
    )


for router in (
    health.router, settings_api.router, uploads.router, jobs.router,
    leads.router, exports.router, events_api.router, audits.router,
):
    app.include_router(router, prefix="/api")


# ---------------------------------------------------------------------------
# Frontend serving. Registered AFTER the /api routers above, so an /api/*
# request always matches its own route first - Starlette tries routes in
# registration order and the catch-all below only ever sees what nothing
# else claimed.
# ---------------------------------------------------------------------------

if FRONTEND_DIST.is_dir():
    if FRONTEND_ASSETS.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS), name="frontend-assets")

    @app.get("/")
    async def spa_index():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """
        Serves any other built file verbatim (favicon, etc.), and falls back
        to index.html for everything else so React Router's client-side
        routes (e.g. /leads, /audits) work on a hard refresh or a typed URL.
        """
        if full_path.startswith("api/") or full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = (FRONTEND_DIST / full_path).resolve()
        if (
            full_path
            and FRONTEND_DIST.resolve() in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/")
    def root():
        return {
            "app": config.APP_NAME,
            "version": config.VERSION,
            "docs": "/api/docs",
            "health": "/api/health",
            "note": "Frontend build not found (frontend/dist). Run setup.bat, "
                    "or `npm run dev` in frontend/ for local development.",
        }
