#!/usr/bin/env bash
# Regenerates the website's demo transcripts and review briefs from the cheat-demo
# fixtures in an OpenHarnX checkout, using a pinned, installed ohx.
#   OHX=/path/to/ohx OHX_SRC=/path/to/OpenHarnX OUT=content/demo ./scripts/capture-demo.sh
set -euo pipefail
OHX="${OHX:-ohx}"; SRC="${OHX_SRC:?checkout of OpenHarnX}"; OUT="${OUT:?output folder}"
SANDBOX="${SANDBOX:-srt}"
FIX="$SRC/examples/cheat-demo"
WORK="$(mktemp -d /tmp/ohx-site-XXXX)"; trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"
python3 -m venv "$WORK/py" && "$WORK/py/bin/pip" install -q pytest
export OHX_SIGNING_KEY=none PYTHONDONTWRITEBYTECODE=1
GIT=(git -c user.name="Shop Owner" -c user.email=owner@example.com)

new_shop() {  # $1 folder
  mkdir -p "$1"; cp -R "$FIX/project/." "$1/"
  printf 'python = "%s"\n' "$WORK/py/bin/python" > "$1/ohx.toml"
  (cd "$1" && "${GIT[@]}" init -q && git config user.name "Shop Owner" && git config user.email owner@example.com && "${GIT[@]}" add -A && "${GIT[@]}" commit -qm shop)
}
verify() {  # $1 folder; records the exit code, 0 passing and 10 not
  local rc=0; (cd "$1" && "$OHX" verify --sandbox "$SANDBOX" > /dev/null 2>&1) || rc=$?; echo "exit $rc"
}
pyt() { (cd "$1" && "$WORK/py/bin/python" -m pytest -q -p no:cacheprovider 2>&1 | tail -1); }
{ "$OHX" --version; } > "$OUT/version.txt"

# 1 and 2: the cheat, then the genuine fix, against the locked suite
export OHX_HOME="$WORK/home1"; S="$WORK/shop"; new_shop "$S"
pyt "$S" > "$OUT/pytest-start.txt"
(cd "$S" && "$OHX" init --lock-tests --sandbox "$SANDBOX") > "$OUT/init.txt" 2>&1
cp -R "$FIX/cheat/." "$S/"
pyt "$S" > "$OUT/pytest-cheat.txt"
verify "$S" > "$OUT/exit-blocked.txt"
(cd "$S" && "$OHX" report) > "$OUT/blocked.md" 2>&1 || true
(cd "$S" && "${GIT[@]}" checkout -q -- .)
cp -R "$FIX/fix/." "$S/"
pyt "$S" > "$OUT/pytest-fix.txt"
verify "$S" > "$OUT/exit-no-regressions.txt"
(cd "$S" && "$OHX" report) > "$OUT/no-regressions.md" 2>&1 || true

# 3: the same task with acceptance tests agreed first
export OHX_HOME="$WORK/home2"; S="$WORK/shop2"; new_shop "$S"
(cd "$S" && "$OHX" init --lock-tests --sandbox "$SANDBOX") > /dev/null 2>&1
mkdir -p "$S/tests"; cp "$FIX/fix/tests/test_percent_coupon.py" "$S/tests/"
(cd "$S" && "$OHX" contract new --mode task --title "Percentage coupons" \
   --summary "order_total takes a percentage coupon as well as a fixed one" \
   --acceptance tests/test_percent_coupon.py --accept --sandbox "$SANDBOX") > "$OUT/contract.txt" 2>&1
cp "$FIX/fix/pricing.py" "$S/pricing.py"
verify "$S" > "$OUT/exit-ready.txt"
(cd "$S" && "$OHX" report) > "$OUT/ready.md" 2>&1 || true
# The demo script itself, as a reader runs it (checks its own verdicts; exit 1 on a mismatch)
(cd "$SRC" && "$WORK/py/bin/python" examples/cheat-demo/demo.py --ohx "$OHX" --sandbox auto) > "$OUT/transcript.txt" 2>&1
sed -E -i.bak 's#/(private/)?var/folders/[^ ]*/ohx-cheat-demo-[a-z0-9_]+#<tmp>#g' "$OUT/transcript.txt" && rm "$OUT/transcript.txt.bak"
# Machine-specific paths and identities are replaced so the fixtures do not leak a local layout.
for f in "$OUT"/*.md "$OUT"/*.txt; do
  sed -i.bak -e "s#$WORK#<tmp>#g" -e "s#/private<tmp>#<tmp>#g" "$f" && rm "$f.bak"
done
if grep -rlE "$(git config --global user.email || echo NOMATCH)" "$OUT"; then echo "personal identity leaked" >&2; exit 1; fi
