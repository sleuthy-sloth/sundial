#!/usr/bin/env bash
# Boot sundial: build the SPA once if it is missing, then serve API + UI on one port.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f backend/static/index.html ]; then
  echo "building frontend..."
  (cd frontend && npm install && npm run build)
fi

exec backend/.venv/bin/uvicorn app:app --app-dir backend \
  --host 127.0.0.1 --port "${PORT:-6770}"
