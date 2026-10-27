# Shared by upgrade-host.sh and check-host.sh; sourced, not run.
# Keep to bash 3.2 and BSD tools: macOS runs these scripts.
# shellcheck shell=bash disable=SC2034 # variables are used by the sourcing scripts

here=$(cd "$(dirname "$0")" && pwd -P)
hostlib=$here/hostlib.py
os=$(uname -s)
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# The service never wants upstream's update notice: it offers stock PyPI wheels.
export OMNIGENT_NO_UPDATE_CHECK=1

deploy_root=${RELEASE_ROOT:-$HOME/omnigent-deploy}
tool_py=${UV_TOOL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools}/omnigent/bin/python
unit_name=omnigent-host.service
unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
dropin_dir=$unit_dir/$unit_name.d
generated_dropin=90-omnigent-release.conf
label=ai.omnigent.host
plist=$HOME/Library/LaunchAgents/$label.plist
secrets=$HOME/.omnigent/secrets/host.env
required_clis="rg"
optional_clis="claude codex opencode pi gemini agy node uv"

say() { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

case $os in Linux | Darwin) ;; *) die "unsupported OS $os" ;; esac

# Run hostlib.py with the omnigent tool's python, or python3 before the first install.
lib() {
  local py=$tool_py
  [ -x "$py" ] || py=$(command -v python3 || true)
  [ -n "$py" ] || die "need python3 or an installed omnigent uv tool"
  "$py" -I "$hostlib" "$@"
}

# The python the service starts: ExecStart's first word, or ProgramArguments[0].
service_python() {
  if [ "$os" = Darwin ]; then
    [ -f "$plist" ] && lib plist-get "$plist" ProgramArguments.0
  elif [ -f "$unit_dir/$unit_name" ]; then
    sed -n 's/^ExecStart=//p' "$unit_dir/$unit_name" | head -n 1 | sed -E 's/^"([^"]*)".*/\1/; s/^([^" ]+).*/\1/'
  fi
}

# `<python> -m omnigent --version` of the installed package. -I and cd / keep a
# checkout in the current directory from shadowing it.
omnigent_version() {
  [ -n "$1" ] && [ -x "$1" ] || return 1
  (cd / && "$1" -I -m omnigent --version 2>/dev/null)
}

# Short commit that omnigent_version reports, or nothing.
omnigent_short() {
  omnigent_version "$1" | sed -n 's/.*(\([0-9a-f]\{8\}\).*/\1/p'
}

# Directories of node and the harness CLIs, as a clean login shell resolves them.
# Run with a minimal environment so the caller's PATH (e.g. an ssh shell) is not inherited.
login_cli_dirs() {
  local shell_path found
  for shell_path in "${SHELL:-}" /bin/bash; do
    [ -n "$shell_path" ] && [ -x "$shell_path" ] || continue
    found=$(env -i HOME="$HOME" USER="${USER:-}" LOGNAME="${LOGNAME:-${USER:-}}" SHELL="$shell_path" \
      PATH=/usr/bin:/bin "$shell_path" -lc \
      "for c in node $required_clis $optional_clis; do command -v \"\$c\"; done" </dev/null 2>/dev/null || true)
    printf '%s\n' "$found" | while read -r bin; do
      case $bin in /*) dirname "$bin" ;; esac
    done
  done
}

# PATH dirs that end every service PATH.
default_path_dirs() {
  local dir
  if [ "$os" = Darwin ]; then
    for dir in /opt/homebrew/bin /opt/homebrew/sbin; do [ -d "$dir" ] && echo "$dir"; done
    printf '%s\n' /usr/local/bin /usr/bin /bin /usr/sbin /sbin
  else
    printf '%s\n' /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin
    if [ -d /snap/bin ]; then echo /snap/bin; fi
  fi
}

install_hint() {
  if [ "$os" = Darwin ]; then echo "brew install ripgrep"; else echo "sudo apt install ripgrep"; fi
}

# First line of `<cli> --version` found on the given PATH, or "missing".
cli_version() {
  local bin
  bin=$(PATH=$2 command -v "$1" 2>/dev/null) || { echo missing; return 0; }
  printf '%s (%s)\n' "$("$bin" --version </dev/null 2>&1 | head -n 1)" "$bin"
}
