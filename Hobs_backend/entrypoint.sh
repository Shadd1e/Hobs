#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Starting..."

# Run migrations with retry logic to handle concurrent startup race conditions.
# Railway can start multiple instances simultaneously — only one should win the
# migration lock, the others retry and find nothing to do.
echo "[entrypoint] Running database migrations..."
for attempt in 1 2 3; do
    if alembic upgrade head; then
        echo "[entrypoint] Migrations complete."
        break
    else
        if [ $attempt -eq 3 ]; then
            echo "[entrypoint] Migration failed after 3 attempts. Aborting."
            exit 1
        fi
        echo "[entrypoint] Migration attempt $attempt failed, retrying in 3s..."
        sleep 3
    fi
done

PORT=${PORT:-8080}

echo "[entrypoint] Starting FastAPI..."

exec gunicorn \
  --bind "0.0.0.0:$PORT" \
  --workers 1 \
  --worker-class uvicorn.workers.UvicornWorker \
  main:app
