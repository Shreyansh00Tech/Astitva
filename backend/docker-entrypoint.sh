#!/bin/sh
# Apply migrations, seed the fictional demo data once, then start the API.
set -e
alembic upgrade head
if [ "${SEED_DEMO:-true}" = "true" ]; then
  python -m app.seed
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
