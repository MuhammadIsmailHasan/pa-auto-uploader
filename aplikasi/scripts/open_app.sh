#!/usr/bin/env bash
set -e

URL="http://127.0.0.1:8000"

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
else
  echo "Buka di browser: $URL"
fi
