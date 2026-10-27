#!/usr/bin/env bash
# Start an isolated Omnigent server for the history-prefetch bench.
# Usage: start-server.sh <worktree> <env-dir> [port]
# Serves the SPA built into <worktree>/omnigent/server/static/web-ui.
set -euo pipefail
WT=${1:?worktree}; ENVDIR=${2:?env dir}; PORT=${3:-18802}
mkdir -p "$ENVDIR/config" "$ENVDIR/data" "$ENVDIR/artifacts"
cat > "$ENVDIR/hello_world.yaml" <<'YAML'
name: hello_world
prompt: You are a friendly assistant. Say hello and answer questions.

executor:
  model: gpt-4o-mini
  harness: openai-agents
YAML
cd "$WT"
# Strip the runner env of the session this runs inside.
UNSET=$(env | grep -E '^(OMNIGENT_|RUNNER_SERVER_URL)' | cut -d= -f1 | sed 's/^/-u /' || true)
exec env $UNSET \
  OMNIGENT_CONFIG_HOME="$ENVDIR/config" OMNIGENT_DATA_DIR="$ENVDIR/data" \
  OMNIGENT_WEB_UI_DIST="${DIST:-$WT/omnigent/server/static/web-ui}" \
  OPENAI_API_KEY=mock-key ANTHROPIC_API_KEY= \
  uv run --no-sync python -m omnigent server --host 127.0.0.1 --port "$PORT" \
    --database-uri "sqlite:///$ENVDIR/sessions.db" \
    --artifact-location "$ENVDIR/artifacts" \
    --agent "$ENVDIR/hello_world.yaml"
