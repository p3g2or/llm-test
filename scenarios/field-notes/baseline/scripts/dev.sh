#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export STORAGE_BACKEND=memory
uv run --project backend --locked uvicorn fieldnotes.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend/src &
api_pid=$!
npm run dev --prefix frontend &
web_pid=$!
cleanup() {
  kill "$api_pid" "$web_pid" 2>/dev/null || true
  wait "$api_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
exit 1
