#!/bin/bash
# Install a release on this host, apply the service environment, restart the
# host service detached from its own process tree, and verify it.
#
#   upgrade-host.sh --host <name> [options] <release-folder>
#   upgrade-host.sh --host <name> [options] --release <tag> [--repo <owner/name>]
#   upgrade-host.sh --host <name> [options] --rollback
#
# Options:
#   --release TAG   download that GitHub release (gh if logged in, else HTTPS)
#   --repo REPO     repository the release is on (default $RELEASE_REPO or
#                   Desidero/omnigent)
#   --dry-run       print every action without changing anything
#   --no-restart    install and configure, but leave the running service alone
#                   (Linux: no daemon-reload either; the next restart does it)
#   --reinstall     reinstall the wheels even if the installed commit matches
#   --node-dir DIR  put DIR first on the service PATH instead of resolving node
#   --hosts-dir DIR host configs (<DIR>/<host>/); copied into the installed
#                   release so later runs and --rollback find them. Default:
#                   the release's hosts/, else the current release's.
#
# Idempotent: rerunning with the same release only reapplies what drifted.
# Works with macOS bash 3.2 and BSD tools.
set -eu
. "$(cd "$(dirname "$0")" && pwd -P)/host-common.sh"

usage() { sed -n '2,23p' "$here/upgrade-host.sh" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

host="" dry_run="" no_restart="" reinstall="" rollback="" node_dir="" hosts_dir="" src="" phase=""
expect="" action="" tag="" release_tag="" release_repo=${RELEASE_REPO:-Desidero/omnigent}
rel_tag="" rel_short="" rel_version="" rel_name="" rel_has_manifest="" # set by release-info
while [ $# -gt 0 ]; do
  case $1 in
    --host | --node-dir | --hosts-dir | --expect | --action | --tag | --release | --repo)
      [ $# -ge 2 ] || die "$1 needs a value"
      case $1 in
        --host) host=$2 ;; --node-dir) node_dir=$2 ;; --hosts-dir) hosts_dir=$2 ;;
        --expect) expect=$2 ;; --action) action=$2 ;; --tag) tag=$2 ;;
        --release) release_tag=$2 ;; --repo) release_repo=$2 ;;
      esac
      shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --no-restart) no_restart=1; shift ;;
    --reinstall) reinstall=1; shift ;;
    --rollback) rollback=1; shift ;;
    --restart-phase) phase=1; shift ;;
    -h | --help) usage 0 ;;
    -*) die "unknown option $1" ;;
    *) [ -z "$src" ] || die "give one release folder"; src=$1; shift ;;
  esac
done
[ -n "$host" ] || host=$(hostname -s | tr '[:upper:]' '[:lower:]')
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir=$deploy_root/backups/$stamp
status_file=$deploy_root/last-restart.status
upgrade_log=$deploy_root/upgrade.log

run() {
  say "+ $*"
  [ -n "$dry_run" ] || "$@"
}

rollout_line() { # result connected
  printf '%s host=%s action=%s tag=%s commit=%s result=%s connected=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$host" "$action" "${tag:-none}" "$expect" "$1" "$2" \
    >>"$deploy_root/rollout.log"
}

# ------------------------------------------------------------ restart phase
# Runs detached (systemd-run / setsid) so restarting the host cannot kill it.

host_connected_since() { # start-epoch log-offset
  if [ "$os" = Darwin ]; then
    local log
    log=$(lib plist-get "$plist" StandardErrorPath 2>/dev/null) || return 1
    [ -f "$log" ] || return 1
    if [ "$(wc -c <"$log")" -lt "$2" ]; then cat "$log"; else tail -c "+$(($2 + 1))" "$log"; fi \
      | grep -q "Connected as"
  else
    journalctl --user -u "$unit_name" --since "@$1" --no-pager -o cat 2>/dev/null | grep -q "Connected as"
  fi
}

restart_phase() {
  exec >>"$upgrade_log" 2>&1
  say "== $(date -u +%FT%TZ) $action ${tag:-} on $host: restarting the host service"
  local start offset=0 connected=no result=ok tries=0 log running
  start=$(date +%s)
  if [ "$os" = Darwin ]; then
    local domain
    domain=gui/$(id -u)
    log=$(lib plist-get "$plist" StandardErrorPath 2>/dev/null || true)
    if [ -n "$log" ] && [ -f "$log" ]; then offset=$(wc -c <"$log" | tr -d ' '); fi
    launchctl bootout "$domain/$label" 2>/dev/null || true
    # bootout returns before the job is gone; bootstrap fails until it is.
    while launchctl print "$domain/$label" >/dev/null 2>&1 && [ $tries -lt 30 ]; do
      sleep 0.5; tries=$((tries + 1))
    done
    launchctl bootstrap "$domain" "$plist"
  else
    systemctl --user daemon-reload
    systemctl --user restart "$unit_name"
  fi
  tries=0
  while [ $tries -lt 20 ]; do
    sleep 2
    if host_connected_since "$start" "$offset"; then connected=yes; break; fi
    tries=$((tries + 1))
  done
  running=$(omnigent_short "$(service_python)")
  say "service binary reports ${running:-nothing}, expected $expect; connected: $connected"
  [ "$running" = "$expect" ] || result=fail
  [ $connected = yes ] || result=fail
  rollout_line "$result" "$connected"
  say "== $(date -u +%FT%TZ) $result"
  echo "$result" >"$status_file"
  [ $result = ok ]
}

if [ -n "$phase" ]; then
  restart_phase
  exit
fi

# ------------------------------------------------------------ helpers

backup() { # file
  if [ -z "$dry_run" ]; then
    mkdir -p "$backup_dir"
    chmod 700 "$deploy_root/backups" "$backup_dir"
  fi
  run cp -p "$1" "$backup_dir/"
}

changed=""
install_file() { # source destination
  if [ -f "$2" ] && cmp -s "$1" "$2"; then return 0; fi
  if [ -f "$2" ]; then
    say "update $2:"
    diff -u "$2" "$1" | sed '1,2d; s/^/    /' || true
    backup "$2"
  else
    say "add $2:"
    sed 's/^/    /' "$1"
  fi
  run cp "$1" "$2"
  changed=1
}

# Release folder in $deploy_root whose wheel was built from the given short commit.
find_release_for() {
  local wheel
  for wheel in "$deploy_root"/*/omnigent-[0-9]*.whl "$deploy_root"/omnigent-[0-9]*.whl; do
    [ -f "$wheel" ] || continue
    [ ! -L "$(dirname "$wheel")" ] || continue # skip current/previous
    case $(lib wheel-commit "$wheel") in "$1"*) dirname "$wheel"; return 0 ;; esac
  done
}

# ------------------------------------------------------------ which release

# Download a release's assets into a temporary folder, which then installs like
# a local one. gh handles private repositories; plain HTTPS needs a public one.
download_release() { # tag repo dest
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh release download "$1" -R "$2" -D "$3" >/dev/null || return 1
  else
    command -v curl >/dev/null || die "need gh or curl to download a release"
    local api name url
    api=https://api.github.com/repos/$2/releases/tags/$(lib urlquote "$1")
    curl -fsSL -H 'Accept: application/vnd.github+json' "$api" | lib release-assets >"$3/.assets" \
      || return 1
    while read -r name url; do
      curl -fsSL -o "$3/$name" "$url" || return 1
    done <"$3/.assets"
    rm -f "$3/.assets"
  fi
}

if [ -n "$release_tag" ]; then
  [ -z "$src" ] && [ -z "$rollback" ] || die "--release replaces the release folder and --rollback"
  download_dir=$(mktemp -d)
  trap 'rm -rf "$download_dir"' EXIT
  say "downloading $release_repo release $release_tag"
  download_release "$release_tag" "$release_repo" "$download_dir" \
    || die "could not download release $release_tag from $release_repo"
  src=$download_dir
fi

if [ -n "$rollback" ]; then
  [ -z "$src" ] || die "--rollback takes no release folder"
  [ -L "$deploy_root/previous" ] || die "no $deploy_root/previous release to roll back to"
  rel=$(cd "$deploy_root/previous" && pwd -P)
  info=$(lib release-info --verify "$rel") || die "cannot use the previous release $rel"
  eval "$info"
  action=rollback
else
  [ -n "$src" ] || usage 2
  src=$(cd "$src" && pwd -P)
  info=$(lib release-info --verify "$src") || die "cannot use the release in $src"
  eval "$info"
  [ -n "$rel_has_manifest" ] || die "$src has no manifest.json; build it with release/build.sh"
  rel=$deploy_root/$rel_name
  action=upgrade
fi
tag=$rel_tag expect=$rel_short
say "== $action to ${rel_tag:-$(basename "$rel")} (omnigent $rel_version, $rel_short) on $host ($os)${dry_run:+, dry run}"

if [ -z "$hosts_dir" ]; then
  hosts_dir=${src:-$rel}/hosts
  [ -d "$hosts_dir" ] || hosts_dir=$deploy_root/current/hosts
fi
[ -d "$hosts_dir" ] || die "no host configs: pass --hosts-dir DIR (a folder holding <host>/; see release/README.md)"
# Resolve now: a rollback repoints current/ before the drop-ins are applied.
hosts_dir=$(cd "$hosts_dir" && pwd -P)
host_cfg=$hosts_dir/$host
# shellcheck disable=SC2012
[ -d "$host_cfg" ] || die "no host config $host_cfg; pass --host (known: $(ls -1 "$hosts_dir" 2>/dev/null | tr '\n' ' '))"
todo=$(grep -l 'TODO(user)' "$host_cfg"/host.env "$host_cfg"/systemd/*.conf 2>/dev/null || true)
[ -z "$todo" ] || die "fill in the TODO(user) values first: $todo"

# ------------------------------------------------------------ service PATH and CLIs

path_args=()
[ -z "$node_dir" ] || path_args+=(--first "$node_dir")
while IFS= read -r dir; do path_args+=(--first "$dir"); done <<EOF
$(login_cli_dirs)
$HOME/.local/bin
EOF
while IFS= read -r dir; do path_args+=(--default "$dir"); done <<EOF
$(default_path_dirs)
EOF
env_args=()
[ ! -f "$host_cfg/host.env" ] || env_args+=(--env-file "$host_cfg/host.env")
svc_path=$(lib service-path "${path_args[@]}" ${env_args[@]+"${env_args[@]}"})
say "service PATH: $svc_path"
if [ -z "$node_dir" ] && ! PATH=$svc_path command -v node >/dev/null; then
  warn "no node found from a login shell; pass --node-dir if a harness needs it"
fi
for cli in $required_clis; do
  PATH=$svc_path command -v "$cli" >/dev/null || die "$cli is required on the service PATH: $(install_hint)"
done
for cli in $optional_clis; do say "  $cli: $(cli_version "$cli" "$svc_path")"; done

# ------------------------------------------------------------ stage and install

before=$(omnigent_short "$tool_py")
if [ "$action" = upgrade ]; then
  if [ "$src" = "$rel" ]; then
    say "release already in $rel"
  elif [ -e "$rel" ]; then
    cmp -s "$src/manifest.json" "$rel/manifest.json" 2>/dev/null \
      || die "$rel exists and holds a different release; move it aside"
    say "release already copied to $rel"
  else
    run mkdir -p "$deploy_root"
    run cp -R "$src" "$rel.partial"
    run mv "$rel.partial" "$rel"
  fi
fi
read_from=$rel
[ -d "$rel" ] || read_from=$src # dry run before the copy

# Keep the host configs this run applies with the installed release.
if [ "$hosts_dir" != "$(cd "$rel" 2>/dev/null && pwd -P)/hosts" ]; then
  run rm -rf "$rel/hosts"
  run cp -R "$hosts_dir" "$rel/hosts"
fi

if [ -z "$reinstall" ] && [ "$before" = "$rel_short" ]; then
  say "omnigent $rel_short is already installed"
else
  say "installing omnigent $rel_version ($rel_short) over ${before:-nothing}"
  run sh "$read_from/install-host.sh"
fi

current=$(readlink "$deploy_root/current" 2>/dev/null || true)
name=$(basename "$rel")
if [ "$current" != "$name" ]; then
  previous=$current
  if [ -z "$previous" ] && [ -n "$before" ] && [ "$before" != "$rel_short" ]; then
    found=$(find_release_for "$before")
    if [ "$found" = "$deploy_root" ]; then # old flat layout: keep a copy for rollback
      previous=legacy-$before
      run mkdir -p "$deploy_root/$previous"
      run cp -p "$deploy_root"/*.whl "$deploy_root/$previous/"
      # Older flat installs may lack these; the rollback copy needs both.
      if [ -f "$deploy_root/install-host.sh" ]; then
        run cp -p "$deploy_root/install-host.sh" "$deploy_root/$previous/"
      else
        run cp -p "$read_from/install-host.sh" "$deploy_root/$previous/"
      fi
      if [ -f "$deploy_root/constraints.txt" ]; then
        run cp -p "$deploy_root/constraints.txt" "$deploy_root/$previous/"
      else
        warn "the old install has no constraints.txt; a rollback to it resolves dependencies afresh"
        run touch "$deploy_root/$previous/constraints.txt"
      fi
    elif [ -n "$found" ]; then
      previous=$(basename "$found")
    else
      warn "no release folder holds the installed $before; --rollback will not be available"
    fi
  fi
  [ -z "$previous" ] || run ln -sfn "$previous" "$deploy_root/previous"
  run ln -sfn "$name" "$deploy_root/current"
fi

# ------------------------------------------------------------ service environment

common_env=(--set OMNIGENT_NO_UPDATE_CHECK=1 "${path_args[@]}" ${env_args[@]+"${env_args[@]}"})
if [ "$os" = Darwin ]; then
  [ -f "$plist" ] || die "$plist is missing: run 'omnigent host enable --server <url>' once"
  if [ -f "$secrets" ]; then
    case $(ls -l "$secrets") in -rw-------*) ;; *) run chmod 600 "$secrets" ;; esac
    case $(ls -ld "$(dirname "$secrets")") in drwx------*) ;; *) run chmod 700 "$(dirname "$secrets")" ;; esac
  else
    warn "no $secrets; the plist keeps whatever credentials it already has"
  fi
  merge_out=$(lib plist-merge --plist "$plist" --secrets-file "$secrets" --backup-dir "$backup_dir" \
    ${dry_run:+--dry-run} "${common_env[@]}")
  printf '%s\n' "$merge_out" | grep -v '^CHANGED$' || true
  case $merge_out in *CHANGED* | "would update"*) changed=1 ;; esac
else
  [ -f "$unit_dir/$unit_name" ] || die "$unit_dir/$unit_name is missing: run 'omnigent host enable --server <url>' once"
  [ -d "$dropin_dir" ] || run mkdir -p "$dropin_dir"
  managed=" $generated_dropin "
  for file in "$host_cfg"/systemd/*.conf; do
    [ -f "$file" ] || continue
    managed="$managed$(basename "$file") "
    install_file "$file" "$dropin_dir/$(basename "$file")"
  done
  generated=$(mktemp)
  lib systemd-dropin --unit "$unit_dir/$unit_name" --secrets '%h/.omnigent/secrets/host.env' \
    "${common_env[@]}" >"$generated"
  install_file "$generated" "$dropin_dir/$generated_dropin"
  rm -f "$generated"
  for file in "$dropin_dir"/*.conf; do
    [ -f "$file" ] || continue
    case $managed in *" $(basename "$file") "*) continue ;; esac
    warn "$(basename "$file") is not in $host_cfg/systemd; moving it to $backup_dir"
    backup "$file"
    run rm -f "$file"
    changed=1
  done
fi
[ -n "$changed" ] || say "service environment already up to date"

# ------------------------------------------------------------ verify and restart

svc_py=$(service_python)
[ "$svc_py" = "$tool_py" ] || warn "the service runs $svc_py, not the tool this script installs ($tool_py)"
if [ -z "$dry_run" ]; then
  installed=$(omnigent_short "$svc_py")
  [ "$installed" = "$rel_short" ] || die "$svc_py reports ${installed:-no commit}, expected $rel_short"
  say "service binary reports $installed"
else
  say "service binary currently reports $(omnigent_short "$svc_py"), will report $rel_short"
fi

if [ -n "$no_restart" ]; then
  say "not restarting (--no-restart); the running host keeps its old code and environment"
  [ -n "$dry_run" ] || rollout_line restart-skipped no
  exit 0
fi

# Is this shell inside the host service's process tree (e.g. an Omnigent session)?
inside_host=""
if [ "$os" = Darwin ]; then
  host_pid=$(launchctl print "gui/$(id -u)/$label" 2>/dev/null | awk '$1 == "pid" { print $3; exit }')
  pid=$$
  while [ -n "$host_pid" ] && [ -n "$pid" ] && [ "$pid" -gt 1 ]; do
    if [ "$pid" = "$host_pid" ]; then inside_host=1; break; fi
    pid=$(ps -o ppid= -p "$pid" | tr -d ' ')
  done
else
  cgroup=$(systemctl --user show -p ControlGroup --value "$unit_name" 2>/dev/null || true)
  case $(sed -n 's/^0:://p' /proc/self/cgroup) in "$cgroup" | "$cgroup"/*) [ -z "$cgroup" ] || inside_host=1 ;; esac
fi

phase_args=(--restart-phase --host "$host" --action "$action" --expect "$rel_short" --tag "${rel_tag:-none}")
[ -n "$dry_run" ] || rm -f "$status_file"
log_offset=0
if [ -f "$upgrade_log" ]; then log_offset=$(wc -c <"$upgrade_log" | tr -d ' '); fi
if [ "$os" = Darwin ]; then
  # setsid: launchd's bootout kills the job's process group, not a new session.
  say "+ restart detached: bootout + bootstrap $label"
  if [ -z "$dry_run" ]; then
    nohup "$svc_py" -I -c 'import os, sys; os.setsid(); os.execv(sys.argv[1], sys.argv[1:])' \
      /bin/bash "$here/upgrade-host.sh" "${phase_args[@]}" </dev/null >/dev/null 2>&1 &
  fi
else
  run systemd-run --user --quiet --collect --unit "omnigent-upgrade-$stamp" \
    /bin/bash "$here/upgrade-host.sh" "${phase_args[@]}"
fi
[ -z "$dry_run" ] || exit 0

if [ -n "$inside_host" ]; then
  say "This shell runs under the host service and ends with the restart."
  say "Result: tail -n 1 $deploy_root/rollout.log (details in $upgrade_log)"
  exit 0
fi
waited=0
while [ ! -f "$status_file" ] && [ $waited -lt 120 ]; do sleep 2; waited=$((waited + 2)); done
tail -c "+$((log_offset + 1))" "$upgrade_log" 2>/dev/null || true
[ -f "$status_file" ] || die "the restart has not finished after ${waited}s; see $upgrade_log"
[ "$(cat "$status_file")" = ok ] || die "restart verification failed; roll back with: $here/upgrade-host.sh --host $host --rollback"
say "done: $(tail -n 1 "$deploy_root/rollout.log")"
