#!/bin/sh
# Inside the ohx-linux image: copy the read-only source, install, run the suite with
# the real srt sandbox, then a sandboxed gate on a throwaway repository.
set -eu
mkdir -p "$HOME/OpenHarnX"
tar -C /src --exclude=./.venv --exclude=./.mypy_cache --exclude=./.ruff_cache \
    --exclude=__pycache__ -cf - . | tar -C "$HOME/OpenHarnX" -xf -
cd "$HOME/OpenHarnX"
uv sync --quiet
export OHX_SRT="$(command -v srt)" OHX_SIGNING_KEY=none
srt --version
uv run pytest -q -p no:cacheprovider -rs
uv run python ci/linux/gate_probe.py
