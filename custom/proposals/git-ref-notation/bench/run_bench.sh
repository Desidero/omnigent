#!/bin/sh
# Time the git-reference autolink on a long message.
#
#   usage: run_bench.sh <results.json>     (from the checkout root, web deps installed)
#
# Copies the vitest timing file under web/src (vitest only discovers tests
# there), runs it, and removes the copy again.
set -eu
out=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
here=$(cd "$(dirname "$0")" && pwd)
target=$(pwd)/web/src/lib/_gitReferencesBench.test.tsx
cp "$here/autolink_bench.test.tsx" "$target"
trap 'rm -f "$target"' EXIT
cd web && GIT_REFS_BENCH_OUT="$out" pnpm exec vitest run src/lib/_gitReferencesBench.test.tsx
