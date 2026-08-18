# =============================================================================
# Production image for the Advanced Website Auditor.
#
# The app is a SINGLE process: the Python backend serves the built dashboard
# itself, so frontend and backend deploy together as one service on one port.
# There is no separate frontend host to configure and no cross-origin traffic
# in normal use.
#
# Stage 1 builds the dashboard with Node. Stage 2 is the runtime and contains
# no Node at all - only Python plus the built static files.
# =============================================================================

# ---- stage 1: build the dashboard ------------------------------------------
FROM node:20-slim AS dashboard

WORKDIR /build

# Copy manifests first so this layer is cached until dependencies change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY frontend/ ./
RUN npm run build && test -f dist/index.html


# ---- stage 2: runtime -------------------------------------------------------
FROM python:3.12-slim AS runtime

# PYTHONUNBUFFERED keeps logs flowing to the platform's log viewer in real
# time instead of sitting in a buffer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# curl is used by the container HEALTHCHECK below. --no-install-recommends and
# the apt list cleanup keep the image small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/

# The built dashboard must land where settings.FRONTEND_DIST expects it
# (<project root>/frontend/dist), so the same code path serves it in
# production and locally with no conditional logic.
COPY --from=dashboard /build/dist ./frontend/dist

# Persistent data lives outside the image so a redeploy never destroys the
# database, generated reports or exports. The hosting platform mounts its
# volume here; WAE_DATA_DIR is what settings.py reads.
ENV WAE_DATA_DIR=/data
RUN mkdir -p /data

# Bind to every interface: inside a container 127.0.0.1 is unreachable from
# the platform's router, which is a very common cause of "deployed but 502".
ENV WAE_BACKEND_HOST=0.0.0.0
ENV PORT=8021
EXPOSE 8021

# Run as a non-root user. /data is chowned so the volume stays writable.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /app /data
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# ${PORT} is expanded by the shell at runtime: Render, Railway, Fly and Cloud
# Run all inject their own port and the app must honour it, falling back to
# 8021 when nothing is injected.
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --app-dir /app/backend --host 0.0.0.0 --port ${PORT:-8021} --log-level info --proxy-headers --forwarded-allow-ips='*'"]
