#!/usr/bin/env bash
# Start an isolated Omnigent server from a checkout for the items benchmark.
# Usage: start_server.sh <checkout-dir> <port> <env-dir>
set -euo pipefail
checkout=$1; port=$2; envdir=$3
mkdir -p "$envdir/config" "$envdir/data" "$envdir/artifacts"
cd "$checkout"
# Strip the runner env an Omnigent-hosted shell inherits.
for key in $(env | grep -E '^(OMNIGENT_|RUNNER_SERVER_URL)' | cut -d= -f1); do unset "$key"; done
export OMNIGENT_CONFIG_HOME="$envdir/config"
export OMNIGENT_DATA_DIR="$envdir/data"
export OMNIGENT_AUTH_PROVIDER=header
export OMNIGENT_LOCAL_SINGLE_USER=1
export OMNIGENT_DISABLE_CATALOG_LOOKUP=1
export OMNIGENT_WEB_UI_DIST="$checkout/omnigent/server/static/web-ui"
export NO_PROXY=localhost,127.0.0.1
exec uv run --frozen python -m omnigent server --host 127.0.0.1 --port "$port" \
  --database-uri "sqlite:///$envdir/sessions.db" --artifact-location "$envdir/artifacts"
