# ── Build arguments for OCI labels ────────────────────────────────
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG VERSION=1.0.0

# ── Stage 1: builder ──────────────────────────────────────────────
FROM python:3.11.9-slim AS builder

# Pin uv to a specific release — uv:latest produces non-reproducible builds.
# 0.5.31 matches the lock file format revision (revision 3).
COPY --from=ghcr.io/astral-sh/uv:0.5.31 /uv /uvx /usr/local/bin/

# Don't let uv download a separate Python (base image provides 3.11.9).
# Use copy mode instead of hardlinks — safer on overlay2 filesystems.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency manifests first — Docker caches this layer until they change.
COPY pyproject.toml uv.lock .python-version ./

# Install production deps only, honouring the frozen lockfile.
# PyMuPDF 1.24+ ships via PyMuPDFb which bundles MuPDF as a manylinux
# wheel — no apt-get needed for compilation.
RUN uv sync --frozen --no-dev

# App source copied after the dependency layer is cached.
COPY . .

# ── Stage 2: runtime ──────────────────────────────────────────────
FROM python:3.11.9-slim AS runtime

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG VERSION=1.0.0

LABEL org.opencontainers.image.title="Edyrix Backend" \
      org.opencontainers.image.description="Edyrix EdTech Platform — FastAPI Backend" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="Proprietary"

WORKDIR /app

# No apt-get needed — PyMuPDFb bundles its own MuPDF binary in the wheel.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app ./app
COPY --from=builder /app/seed_data ./seed_data
COPY --from=builder /app/alembic ./alembic
COPY --from=builder /app/alembic.ini ./alembic.ini
COPY --from=builder /app/pyproject.toml ./pyproject.toml
COPY --from=builder /app/start.sh ./start.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --shell /bin/bash appuser \
    && chmod +x start.sh \
    && mkdir -p /app/logs \
    && chown appuser:appuser /app/logs

USER appuser

EXPOSE 8000

# start-period=40s gives alembic upgrade head time to complete before probing.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request, sys; \
        r = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8); \
        sys.exit(0 if r.status == 200 else 1)"

CMD ["./start.sh"]
