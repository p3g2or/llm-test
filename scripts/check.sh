#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
benchmark_python="$(uv python find --offline 3.12)"

# Benchmark tooling is checked independently of scenario dependencies.
bash -n benchmark.sh evaluate.sh scripts/check.sh
"$benchmark_python" -m unittest discover -s tests -v -b
uv tool run --from ruff==0.16.8 ruff check --config ruff.toml scripts/benchmark tests scenarios/field-notes/checks
uv tool run --from ruff==0.16.8 ruff format --check --config ruff.toml scripts/benchmark tests scenarios/field-notes/checks

# Validate the preserved application, then its private defect/control check.
bash scenarios/field-notes/baseline/scripts/check.sh
"$benchmark_python" scenarios/field-notes/checks/verify_defect.py
