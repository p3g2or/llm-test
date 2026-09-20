#!/usr/bin/env bash
set -euo pipefail
benchmark_python="$(uv python find --offline 3.12)"
exec "$benchmark_python" "$(cd "$(dirname "$0")" && pwd)/scripts/benchmark/evaluate.py" "$@"
