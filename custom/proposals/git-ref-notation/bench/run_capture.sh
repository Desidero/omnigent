#!/bin/sh
# Capture the git-reference evidence for one revision of the checkout.
#
#   usage: run_capture.sh <label> <evidence-dir>     (from the checkout root)
#
# Needs the web UI built for that revision (cd web && pnpm run build) and the
# test extras installed (uv sync --frozen --extra all --group test). Copies the
# capture test next to the Pull Requests panel tests so their fixtures apply,
# runs it, and removes the copy again.
set -eu
label=$1
out=$2
here=$(cd "$(dirname "$0")" && pwd)
target=tests/e2e_ui/github/_git_refs_capture_test.py
cp "$here/capture_test.py" "$target"
trap 'rm -f "$target"' EXIT
GIT_REFS_LABEL="$label" GIT_REFS_EVIDENCE="$out" \
  .venv/bin/python -m pytest "$target" --ui-skip-build -p no:cacheprovider -q -x
