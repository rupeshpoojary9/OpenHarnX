#!/usr/bin/env bash
# Run every required check. Exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== format";  uv run ruff format --check .
echo "== lint";    uv run ruff check .
echo "== types";   uv run mypy
echo "== layers";  uv run lint-imports
echo "== tests";   uv run pytest -n auto
echo "all checks passed"
