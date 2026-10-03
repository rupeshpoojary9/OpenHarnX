#!/bin/sh
# Run the GitLab and Jenkins examples' command block on Linux under srt (T79).
#
# Inside the ohx-linux image, with the OpenHarnX repository mounted read-only at
# /src. The block is taken from each example file as written, so this tests the
# commands users copy, not GitLab or Jenkins. Four runs: each example gets a
# genuine change (must be READY) and a cheat that edits a test to match broken
# code (must be BLOCKED), once with the base branch in the checkout and once
# without it (the block must fetch it).
set -eu
git config --global --add safe.directory '*'
git config --global user.name probe
git config --global user.email probe@example.com
work="$HOME/probe"
rm -rf "$work"
mkdir -p "$work"

# The project's own test interpreter.
python3 -m venv "$work/proj-venv"
"$work/proj-venv/bin/pip" install -q pytest

# A base repository with a test suite, published as "origin".
mkdir "$work/seed"
cd "$work/seed"
git init -q -b main
mkdir tests
printf 'def add(a, b):\n    return a + b\n' > calc.py
printf 'from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n' > tests/test_calc.py
printf 'python = "%s"\n' "$work/proj-venv/bin/python" > ohx.toml
git add -A
git commit -qm base
git clone -q --bare "$work/seed" "$work/origin.git"

block() {
    python3 - "$1" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read()
body = text.split("# ohx-gate commands: start", 1)[1].split("# ohx-gate commands: end", 1)[0]
print("\n".join(line.strip() for line in body.strip().splitlines()))
PY
}

run() {  # example, change (genuine|cheat), base (present|absent), expected exit, file
    name="$1-$2-$3"
    clone="$work/$name"
    git clone -q "$work/origin.git" "$clone"
    cd "$clone"
    git checkout -qb change
    if [ "$2" = genuine ]; then
        printf '\n\ndef sub(a, b):\n    return a - b\n' >> calc.py
    else
        printf 'def add(a, b):\n    return a + b + 1\n' > calc.py
        sed -i 's/== 5/== 6/' tests/test_calc.py
    fi
    git commit -qam "$2"
    if [ "$3" = absent ]; then
        git branch -qD main
        git update-ref -d refs/remotes/origin/main
    fi
    block "/src/docs/ci/$5" > "$work/$name.sh"
    set +e
    OHX_BASE=main OHX_SOURCE="git+file:///src" OHX_VERSION="$(git -C /src rev-parse HEAD)" \
        sh -eu "$work/$name.sh" > "$work/$name.log" 2>&1
    code=$?
    set -e
    verdict=$(sed -n 's/^# OpenHarnX report: //p' "$work/$name.log" | head -1)
    protection=$(sed -n 's/^- Verifier protection: //p' "$work/$name.log" | head -1)
    echo "$name: exit $code, $verdict, $protection"
    if [ "$code" != "$4" ] || [ "${protection#enforced}" = "$protection" ]; then
        tail -20 "$work/$name.log"
        failed=1
    fi
}

failed=0
run gitlab genuine present 0 gitlab-ci.yml
run gitlab cheat absent 10 gitlab-ci.yml
run jenkins genuine absent 0 Jenkinsfile
run jenkins cheat present 10 Jenkinsfile
if [ "$failed" = 0 ]; then echo "examples probe: ok"; else echo "examples probe: FAILED"; exit 1; fi
