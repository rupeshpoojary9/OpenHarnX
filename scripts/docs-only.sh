#!/bin/sh
# Does a change touch only documentation? (T102)
#
#   scripts/docs-only.sh <base> <head> <repository>
#
# Prints the changed files and exits 0 when every one is documentation: a Markdown file,
# or a file under docs/assets/, but nothing under tests/, src/ or contracts/ (tests read
# files there). Exits 1 otherwise, and for an empty change, so anything else, the CI
# examples in docs/ci/ included, runs the full gate. CI runs the base branch's copy of
# this script, never the pull request's.
set -eu

base="$1"
head="$2"
repo="$3"

files="$(git -C "$repo" diff --name-only "$base...$head")"
if [ -z "$files" ]; then
    echo "no changed files"
    exit 1
fi
echo "$files"

not_docs="$(printf '%s\n' "$files" \
    | grep -Ev '^(tests|src|contracts)/' \
    | grep -Ev '\.md$|^docs/assets/' || true)"
excluded="$(printf '%s\n' "$files" | grep -E '^(tests|src|contracts)/' || true)"
if [ -n "$not_docs" ] || [ -n "$excluded" ]; then
    exit 1
fi
exit 0
