# ── Stage 1: builder ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Copy uv binary from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# System deps needed to compile PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    mupdf-tools \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files first — Docker cache means deps only
# reinstall when pyproject.toml changes, not on every code change
COPY pyproject.toml .
COPY uv.lock .
COPY .python-version .

# Install all dependencies into /app/.venv
RUN uv sync --frozen --no-dev

# Copy application source
COPY . .

# ── Stage 2: runtime ──────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Runtime-only system deps (no gcc, no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the pre-built venv and app source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app ./app
COPY --from=builder /app/alembic ./alembic
COPY --from=builder /app/alembic.ini ./alembic.ini
COPY --from=builder /app/pyproject.toml ./pyproject.toml
COPY --from=builder /app/start.sh ./start.sh

# Put venv binaries on PATH so uvicorn is found directly
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Run as non-root for security
RUN useradd --create-home --shell /bin/bash appuser && chmod +x start.sh
USER appuser

EXPOSE 8000
CMD ["./start.sh"]
