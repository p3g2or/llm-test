#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
node -e 'const fs = require("node:fs"); const expected = fs.readFileSync(".node-version", "utf8").trim(); if (process.versions.node !== expected) { console.error(`Node ${expected} required; found ${process.versions.node}`); process.exit(1); } console.log(`Validation Node: ${process.version}`);'

bash -n scripts/check.sh scripts/check-infra.sh scripts/dev.sh
uv sync --project backend --locked --python "$(cat .python-version)"
uv run --project backend --locked ruff check --config backend/pyproject.toml backend scripts
uv run --project backend --locked ruff format --check --config backend/pyproject.toml backend scripts
(cd backend && uv run --locked mypy && uv run --locked pytest)
npm ci --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
bash scripts/check-infra.sh
python3 scripts/build_release.py
uv run --project backend --locked python scripts/smoke.py dist/fieldnotes.zip
