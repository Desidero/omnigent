#!/bin/sh
# Install this folder's omnigent build as the uv tool the host service runs.
# Dependencies are pinned to the release's uv.lock via constraints.txt.
# upgrade-host.sh runs this; on its own it does not touch the service.
set -eu
dir=$(cd "$(dirname "$0")" && pwd)
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
wheel=$(ls "$dir"/omnigent-[0-9]*.whl)
uv tool install --force --python 3.12 --find-links "$dir" -c "$dir/constraints.txt" "$wheel"
tools=${UV_TOOL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools}
OMNIGENT_NO_UPDATE_CHECK=1 "$tools/omnigent/bin/omnigent" --version
