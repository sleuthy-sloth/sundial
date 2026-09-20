#!/usr/bin/env bash
# Install Playwright for the UI check, pinned to the version whose Chromium is
# already in ~/.cache/ms-playwright so nothing large gets downloaded.
set -euo pipefail
cd "$(dirname "$0")/../frontend"

npm install --no-fund --no-audit --save-dev playwright@1.62.1
echo "playwright installed; browser cache already present:"
ls ~/.cache/ms-playwright/
