#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete. Starting server..."

# WEB_CONCURRENCY controls the number of uvicorn worker processes.
# Default: 2. Override by setting WEB_CONCURRENCY in the environment.
WORKERS="${WEB_CONCURRENCY:-2}"
echo "Starting uvicorn with ${WORKERS} worker(s)..."

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WORKERS}"
