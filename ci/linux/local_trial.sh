#!/bin/sh
# Inside the ohx-linux image: what a user does on a Linux machine, outside CI (T108).
# Install ohx as a tool, run `ohx doctor`, the cheat demo under srt, and OpenHarnX
# verifying its own unchanged tree under srt. Run it like check.sh:
#   docker run --rm --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
#     --security-opt systempaths=unconfined --tmpfs /home/ci:rw,exec,size=2g,uid=1000 \
#     -v "$PWD":/src:ro ohx-linux /src/ci/linux/local_trial.sh
set -eu
mkdir -p "$HOME/OpenHarnX"
tar -C /src --exclude=./.venv --exclude=./.mypy_cache --exclude=./.ruff_cache \
    --exclude=__pycache__ -cf - . | tar -C "$HOME/OpenHarnX" -xf -
cd "$HOME/OpenHarnX"
git config --global user.name trial
git config --global user.email trial@example.com
export PATH="$HOME/.local/bin:$PATH" OHX_HOME="$HOME/ohx-home" OHX_SIGNING_KEY=none

echo "== install"
uv tool install --quiet --from . openharnx
ohx --version

echo "== doctor"
ohx doctor

echo "== cheat demo under srt"
uv sync --quiet
uv run python examples/cheat-demo/demo.py --sandbox srt >"$HOME/demo.txt" 2>&1 || {
    cat "$HOME/demo.txt"
    exit 1
}
grep -E "OpenHarnX report:" "$HOME/demo.txt"

echo "== OpenHarnX verifies itself under srt"
if [ ! -d .git ]; then
    git init --quiet && git add -A && git commit --quiet -m trial
fi
ohx init --lock-tests --sandbox srt >/dev/null
start=$(date +%s)
code=0
ohx verify --sandbox srt >"$HOME/verify.txt" 2>&1 || code=$?
grep -m1 "OpenHarnX report:" "$HOME/verify.txt"
echo "exit $code in $(($(date +%s) - start))s"
[ "$code" -eq 0 ]
