#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

cd "$ROOT/backend"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 &
API_PID=$!

cd "$ROOT/frontend"
npm run dev -- --host 127.0.0.1 --port 5173 &
UI_PID=$!

trap 'kill $API_PID $UI_PID 2>/dev/null || true' EXIT
echo "API  http://127.0.0.1:8000/docs"
echo "UI   http://127.0.0.1:5173"
wait
