#!/bin/bash
# Read-only drift check of this host's Omnigent service. Changes nothing.
#
#   check-host.sh [--host <name>] [--release DIR] [--server URL]
#
# Compares against ~/omnigent-deploy/current unless --release names another
# release folder (e.g. one about to be installed). Secret values are never
# printed. Exits 1 if any check FAILs. Works with macOS bash 3.2 and BSD tools.
# shellcheck disable=SC2015 # ok, bad, note and info always succeed
set -u
. "$(cd "$(dirname "$0")" && pwd -P)/host-common.sh"

host="" release="" server=""
while [ $# -gt 0 ]; do
  case $1 in
    --host | --release | --server)
      [ $# -ge 2 ] || die "$1 needs a value"
      case $1 in --host) host=$2 ;; --release) release=$2 ;; --server) server=$2 ;; esac
      shift 2 ;;
    -h | --help) sed -n '2,8p' "$here/check-host.sh" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument $1" ;;
  esac
done
[ -n "$host" ] || host=$(hostname -s | tr '[:upper:]' '[:lower:]')
[ -n "$release" ] || release=$deploy_root/current

fails=0 warns=0
ok() { say "OK    $*"; }
bad() { say "FAIL  $*"; fails=$((fails + 1)); }
note() { say "WARN  $*"; warns=$((warns + 1)); }
info() { say "      $*"; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

say "== $host"
if [ "$os" = Darwin ]; then
  info "macOS $(sw_vers -productVersion) $(uname -m), $(($(sysctl -n hw.memsize) / 1073741824)) GB RAM"
else
  info "$(. /etc/os-release && echo "$PRETTY_NAME") $(uname -m), $(awk '/^MemTotal/ { printf "%.0f", $2 / 1048576 }' /proc/meminfo) GB RAM"
fi

# ------------------------------------------------------------ service and binary

svc_py=$(service_python)
main_pid=""
if [ "$os" = Darwin ]; then
  [ -f "$plist" ] || bad "no $plist (run 'omnigent host enable --server <url>')"
  state=$(launchctl print "gui/$(id -u)/$label" 2>/dev/null | awk '$1 == "state" { print $3; exit }')
  [ "$state" = running ] && ok "service $label running" || bad "service $label is ${state:-not loaded}"
  if [ "$(lib plist-get "$plist" ProgramArguments.4 2>/dev/null)" = --server ]; then
    args_text=$(lib plist-get "$plist" ProgramArguments.5 2>/dev/null)
  else
    args_text=""
  fi
else
  if [ ! -f "$unit_dir/$unit_name" ]; then bad "no $unit_dir/$unit_name (run 'omnigent host enable --server <url>')"; fi
  state=$(systemctl --user is-active "$unit_name" 2>/dev/null)
  [ "$state" = active ] && ok "service $unit_name active" || bad "service $unit_name is $state"
  linger=$(loginctl show-user "${USER:-$(id -un)}" -p Linger --value 2>/dev/null)
  [ "$linger" = yes ] && ok "lingering enabled" || note "linger is '${linger:-unknown}': the host stops when you log out (loginctl enable-linger)"
  main_pid=$(systemctl --user show -p MainPID --value "$unit_name" 2>/dev/null)
  args_text=$(sed -n 's/^ExecStart=//p' "$unit_dir/$unit_name" 2>/dev/null | head -n 1)
fi
# The server URL is the argument after --server (unit or plist).
[ -n "$server" ] || server=$(printf '%s\n' "$args_text" | grep -o 'https\{0,1\}://[^" ]*' | head -n 1)

running=$(omnigent_short "$svc_py")
info "service binary: $svc_py: $(omnigent_version "$svc_py" || echo 'no omnigent')"
[ "$svc_py" = "$tool_py" ] || note "the service runs $svc_py, not the uv tool at $tool_py"
if [ -f "$release/manifest.json" ]; then
  want=$(lib json-get "$release/manifest.json" short_commit)
  info "release: $(lib json-get "$release/manifest.json" tag) ($want, $(cd "$release" && pwd -P))"
  [ "$running" = "$want" ] && ok "service binary is $want" || bad "service binary reports ${running:-no commit}, release is $want"
else
  note "no $release/manifest.json: no release installed with upgrade-host.sh yet"
fi
if [ -n "$main_pid" ] && [ "$main_pid" != 0 ] && [ -r "/proc/$main_pid/exe" ]; then
  case $(readlink "/proc/$main_pid/exe") in *"(deleted)") note "the running host's python was replaced on disk: restart pending" ;; esac
fi
[ -f "$deploy_root/rollout.log" ] && info "last rollout: $(tail -n 1 "$deploy_root/rollout.log")"

# ------------------------------------------------------------ service environment

env_file=$work/env
configured=$env_file # what the unit or plist sets, as opposed to what the host runs with
if [ "$os" = Darwin ]; then
  [ -f "$plist" ] && lib env-report --plist "$plist" >"$env_file"
  env_source="plist EnvironmentVariables"
elif [ -n "$main_pid" ] && [ "$main_pid" != 0 ] && [ -r "/proc/$main_pid/environ" ]; then
  lib env-report --proc "/proc/$main_pid/environ" >"$env_file"
  env_source="running host (pid $main_pid)"
  systemctl --user show -p Environment --value "$unit_name" | lib env-report --systemd \
    --unset "$(systemctl --user show -p UnsetEnvironment --value "$unit_name")" >"$work/configured"
  configured=$work/configured
  for key in PATH OMNIGENT_FEATURES OMNIGENT_NO_UPDATE_CHECK NODE_OPTIONS \
    OMNIGENT_NATIVE_PANE_IDLE_TIMEOUT_S OMNIGENT_HARNESS_IDLE_TIMEOUT_S; do
    [ "$(grep "^$key=" "$env_file")" = "$(grep "^$key=" "$configured")" ] \
      || note "$key in the unit differs from the running host's: restart pending"
  done
else
  systemctl --user show -p Environment --value "$unit_name" 2>/dev/null | lib env-report --systemd \
    --unset "$(systemctl --user show -p UnsetEnvironment --value "$unit_name" 2>/dev/null)" >"$env_file"
  env_source="unit configuration (host not running)"
fi
touch "$env_file"
info "environment from the $env_source:"
sed 's/^/        /' "$env_file"

grep -qx 'OMNIGENT_NO_UPDATE_CHECK=1' "$env_file" && ok "OMNIGENT_NO_UPDATE_CHECK=1" \
  || bad "OMNIGENT_NO_UPDATE_CHECK=1 is not set (upgrade-host.sh sets it)"
# On Linux the user manager adds its own variables (SSH_AUTH_SOCK, DBUS_*); only the unit's count.
lib leftovers <"$configured" >"$work/leftovers"
if [ -s "$work/leftovers" ]; then
  while IFS= read -r line; do
    if [ "$os" = Darwin ]; then bad "shell leftover in the plist: $line"; else note "shell leftover in the service env: $line"; fi
  done <"$work/leftovers"
else
  ok "no shell leftovers in the service environment"
fi
for file in "$env_file" "$configured"; do
  grep -o '^OMNIGENT_[A-Z_]*IDLE_TIMEOUT_S=[^ ]*' "$file"
done | sort -u | while IFS= read -r line; do
  note "$line overrides an idle timeout (upstream defaults are wanted)"
done
grep -q '^DISABLE_AUTOUPDATER=' "$env_file" && note "DISABLE_AUTOUPDATER is set: Claude Code auto-updates should stay on"
grep -hqs '"autoUpdates": *false' "$HOME/.claude.json" "$HOME/.claude/settings.json" \
  && note "Claude Code autoUpdates is false: it should stay on"

# ------------------------------------------------------------ CLIs on the service PATH

svc_path=$(sed -n 's/^PATH=//p' "$env_file")
[ -n "$svc_path" ] || { bad "the service environment has no PATH"; svc_path=/usr/bin:/bin; }
for cli in $required_clis; do
  version=$(cli_version "$cli" "$svc_path")
  [ "$version" = missing ] && bad "$cli is missing on the service PATH: $(install_hint)" || ok "$cli: $version"
done
for cli in $optional_clis; do info "$cli: $(cli_version "$cli" "$svc_path")"; done
login_node=$(login_cli_dirs | grep '/\.nvm/versions/node/' | head -n 1)
case $svc_path in
  */.nvm/versions/node/*)
    pinned=$(printf '%s\n' "$svc_path" | tr ':' '\n' | grep '/\.nvm/versions/node/' | head -n 1)
    [ -z "$login_node" ] || [ "$pinned" = "$login_node" ] \
      || note "the service PATH has $pinned but a login shell uses $login_node: rerun upgrade-host.sh" ;;
esac

# ------------------------------------------------------------ feature flags

flags=$(sed -n 's/^OMNIGENT_FEATURES=//p' "$env_file" | tr ',' '\n' | sed 's/^ *-\{0,1\}//; s/ *$//' | grep -v '^$')
if [ -z "$flags" ]; then
  info "OMNIGENT_FEATURES is not set (feature defaults)"
else
  "$svc_py" -I -c 'from omnigent.server.feature_flags import Feature
for feature in Feature: print(feature.value)' >"$work/known" 2>/dev/null || true
  server_flags=""
  if [ -n "$server" ] && command -v curl >/dev/null; then
    curl -fsS --max-time 10 "$server/v1/info" 2>/dev/null | lib json-keys features >"$work/server" 2>/dev/null \
      && server_flags=1
  fi
  [ -n "$server_flags" ] || note "could not read ${server:-the server}/v1/info"
  for flag in $flags; do
    if [ -s "$work/known" ] && ! grep -qx "$flag" "$work/known"; then
      bad "OMNIGENT_FEATURES names '$flag', unknown to this binary: host processes refuse to start"
    elif [ -n "$server_flags" ] && ! grep -qx "$flag" "$work/server"; then
      note "OMNIGENT_FEATURES names '$flag', which $server/v1/info does not list (it lists only UI-visible flags)"
    else
      ok "feature flag '$flag' is known"
    fi
  done
fi

# ------------------------------------------------------------ secrets file

if [ -f "$secrets" ]; then
  case $(ls -l "$secrets") in -rw-------*) ok "$secrets is mode 600" ;; *) bad "$secrets is not mode 600 (chmod 600 it)" ;; esac
  info "$secrets sets: $(lib secret-names "$secrets" | tr '\n' ' ')"
  if lib secret-names "$secrets" | grep -qx CLAUDE_CODE_OAUTH_TOKEN; then
    age=$(lib token-age "$secrets")
    if [ "$age" = none ]; then
      note "$secrets has no '# created: YYYY-MM-DD' comment for its Claude setup-token"
    elif [ "$age" -gt 365 ]; then
      bad "the Claude setup-token is $age days old and has expired: run 'claude setup-token'"
    elif [ "$age" -gt 335 ]; then
      note "the Claude setup-token is $age days old; it expires after a year: run 'claude setup-token'"
    else
      ok "Claude setup-token is $age days old"
    fi
  fi
  grep -q '^ *export ' "$secrets" && note "$secrets uses 'export'; systemd's EnvironmentFile wants plain KEY=VALUE"
fi
if grep -q '^CLAUDE_CODE_OAUTH_TOKEN=' "$env_file" \
  && ! { [ -f "$secrets" ] && lib secret-names "$secrets" | grep -qx CLAUDE_CODE_OAUTH_TOKEN; }; then
  note "CLAUDE_CODE_OAUTH_TOKEN is in the service env but not in $secrets: move it there and out of the host config"
fi

# ------------------------------------------------------------ systemd drop-ins

if [ "$os" = Linux ] && [ -d "$dropin_dir" ]; then
  want_dir=$release/hosts/$host/systemd
  for file in "$dropin_dir"/*.conf; do
    [ -f "$file" ] || continue
    name=$(basename "$file")
    if [ "$name" = "$generated_dropin" ]; then
      ok "drop-in $name (generated)"
    elif [ -f "$want_dir/$name" ]; then
      cmp -s "$file" "$want_dir/$name" && ok "drop-in $name matches the release" \
        || note "drop-in $name differs from $want_dir/$name"
    else
      note "drop-in $name is not in ${want_dir}: upgrade-host.sh will move it aside"
    fi
    grep -q 'IDLE_TIMEOUT_S' "$file" && note "drop-in $name overrides idle timeouts (upstream defaults are wanted)"
  done
  [ -f "$dropin_dir/$generated_dropin" ] || note "no generated $generated_dropin yet"
fi

say "== $fails failed, $warns warnings"
[ "$fails" -eq 0 ]
