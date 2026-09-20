#!/usr/bin/env bash
# Install frontend dependencies at the registry's current versions and build the
# SPA into backend/static. Safe to re-run; npm is idempotent.
set -euo pipefail
cd "$(dirname "$0")/../frontend"

npm install --no-fund --no-audit react react-dom
npm install --no-fund --no-audit --save-dev vite @vitejs/plugin-react
npm run build
