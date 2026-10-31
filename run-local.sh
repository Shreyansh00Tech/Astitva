#!/usr/bin/env bash
# Run ASTITVA on macOS without Docker: Postgres + Redis (Homebrew), FastAPI backend, Next.js frontend.
#   ./run-local.sh            start (seeds the demo data the first time)
#   ./run-local.sh --reset    start with fresh demo data (deletes existing data)
#   ./run-local.sh --clean    start empty: only the 5 people, no old access or requests (deletes existing data)
# Stop with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'. Install with: $2"; exit 1; }; }
need brew   '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
need node   'brew install node'
PY="$(command -v python3.12 || command -v python3.13 || command -v python3 || true)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null \
  || { echo "Python 3.12+ needed. Install with: brew install python@3.12"; exit 1; }

# 1. Postgres + Redis
brew list postgresql@16 >/dev/null 2>&1 || brew install postgresql@16
brew list redis >/dev/null 2>&1 || brew install redis
brew services start postgresql@16 >/dev/null
brew services start redis >/dev/null
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
for i in {1..20}; do pg_isready -q -h localhost && break; sleep 0.5; done
createdb -h localhost astitva 2>/dev/null || true

# 2. Environment (local demo values only)
export APP_ENV=development
export DATABASE_URL="postgresql+psycopg://${USER}@localhost:5432/astitva"
export REDIS_URL="redis://localhost:6379/0"
export CORS_ORIGINS="http://localhost:3000"
export BACKEND_URL="http://localhost:8000"
# NamoID Hosted Auth settings come from the root .env (never committed)
if [ -f "$ROOT/.env" ]; then
  set -a; source <(grep -E '^(NAMOID_[A-Z_]+|FRONTEND_URL)=' "$ROOT/.env" || true); set +a
fi

# 3. Backend
cd "$ROOT/backend"
[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
alembic upgrade head
case "${1:-}" in
  --reset) python -m app.seed --reset ;;
  --clean) python -m app.seed --reset --clean ;;
  *)       python -m app.seed ;;
esac
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 &
BACK=$!

# 4. Frontend
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npm run dev &
FRONT=$!

trap 'echo; echo "Stopping..."; kill $BACK $FRONT 2>/dev/null; exit 0' INT TERM
echo
echo "ASTITVA running:  http://localhost:3000   (API http://localhost:8000)"
echo "Login: admin@nexora.example / Nexora@Demo2026 (OTP is shown in the Dev mailbox on the login page)"
echo "Ctrl+C to stop."
wait
