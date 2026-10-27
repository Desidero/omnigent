#!/usr/bin/env bash
# Run the full scroll-up benchmark for one build label.
# Usage: run-all.sh <worktree> <base_url> <session_id> <label> <out_dir>
# Produces per device: a continuous run (fetches, stalls, long tasks), a paused
# run (prepend hold quality, stall screenshot) and a video run (evidence).
set -euo pipefail
WT=$1; URL=$2; SID=$3; LABEL=$4; OUT=$5
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$WT"
UNSET=$(env | grep -E '^(OMNIGENT_|RUNNER_SERVER_URL)' | cut -d= -f1 | sed 's/^/-u /' || true)
for d in desktop phone; do
  env $UNSET uv run --no-sync python "$HERE/scroll_bench.py" "$URL" "$SID" "$LABEL" "$OUT" --device $d --max-seconds 150
  env $UNSET uv run --no-sync python "$HERE/scroll_bench.py" "$URL" "$SID" "$LABEL" "$OUT" --device $d --max-seconds 150 --pause-on-loading
done
