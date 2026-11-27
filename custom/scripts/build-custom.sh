#!/usr/bin/env bash
# Build Omnigent with the series applied: BASE, one commit per patch, then
# the index (docs/custom/README.md, written from the notes of the series built).
#
#   custom/scripts/build-custom.sh [--repo <clone>] [--fetch <url>] [<selection>] [--force] <branch>
#   custom/scripts/build-custom.sh [--repo <clone>] [--fetch <url>] [<selection>] --worktree <dir>
#
# <branch>     create (or with --force, reset) this branch in the clone to the
#              built result, e.g. a local working branch to develop on.
# --worktree   leave the result checked out (detached) in a new worktree <dir>.
# --repo       the Omnigent clone to build in (default: $OMNIGENT_REPO, else
#              the clone this script is checked out in).
# --fetch URL  fetch BASE from URL first if the clone does not have it
#              (default: https://github.com/omnigent-ai/omnigent.git).
#
# <selection>, default every series:
# --only LIST  build only these series (comma-separated, may repeat), plus
#              every series they need (series-files.sh --only prints what it
#              adds). The index lists the series that were built.
# --set NAME   --only with the series custom/sets/NAME.txt lists: a named
#              build set, which check.sh, select-tests.py and custom/release/
#              take with the same option.
# --series S   one series as its own branch: the series it needs, then its
#              patches, nothing else. This is the branch to change the series
#              on and to hand to export.sh.
# --no-index   leave the index commit out (with --only or --set, to start the
#              branch of a new series on the series it will need).
#
# Each series is cut from BASE plus the series it needs. The build applies
# every chosen series exactly on that foundation and then combines them by
# cherry-pick, a series after the ones it needs and otherwise by name
# (custom/scripts/serieslib.py holds the engine). It is reproducible: fixed
# committer ($CUSTOM_COMMITTER_NAME / $CUSTOM_COMMITTER_EMAIL, default the
# GitHub Actions bot), committer date = author date and pinned merge settings,
# so the same BASE, patch files and selection give the same commit ids here
# and in CI. Prints the tip commit on the last line.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${OMNIGENT_REPO:-}"
branch=""
worktree=""
force=0
fetch_url="https://github.com/omnigent-ai/omnigent.git"
selection=()

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --worktree) worktree="$2"; shift 2 ;;
    --fetch) fetch_url="$2"; shift 2 ;;
    --force) force=1; shift ;;
    --only|--set|--series) [[ $# -ge 2 ]] || usage 2; selection+=("$1" "$2"); shift 2 ;;
    --no-index) selection+=(--no-index); shift ;;
    -h|--help) usage 0 ;;
    -*) echo "unknown option: $1" >&2; usage 2 ;;
    *) [[ -z "$branch" ]] || usage 2; branch="$1"; shift ;;
  esac
done
[[ -n "$repo" ]] || repo="$(git -C "$here" rev-parse --show-toplevel)"
[[ -n "$branch" || -n "$worktree" ]] || usage 2
[[ -z "$branch" || -z "$worktree" ]] || { echo "error: give a branch or --worktree, not both" >&2; exit 2; }
repo="$(cd "$repo" && pwd)"

if [[ -n "$branch" ]] && git -C "$repo" rev-parse --verify --quiet "refs/heads/$branch" >/dev/null; then
  if [[ "$force" != 1 ]]; then
    echo "error: branch $branch exists; pass --force to reset it to a fresh build" >&2
    exit 2
  fi
  if git -C "$repo" worktree list --porcelain | grep -qx "branch refs/heads/$branch"; then
    echo "error: $branch is checked out in a worktree; switch it away first" >&2
    exit 2
  fi
fi

base="$(tr -d '[:space:]' < "$here/BASE")"
if ! git -C "$repo" rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
  echo "fetching BASE ${base:0:12} from $fetch_url" >&2
  git -C "$repo" fetch --quiet --no-tags --depth=1 "$fetch_url" "$base"
fi

# The engine works on git objects only; its summary and what --only added go to stderr.
tip="$(python3 -I "$here/scripts/serieslib.py" build --repo "$repo" "${selection[@]}")"

if [[ -n "$branch" ]]; then
  git -C "$repo" branch --force --no-track "$branch" "$tip" >/dev/null
  echo "built $branch at ${tip:0:12}" >&2
else
  git -C "$repo" worktree add --quiet --detach "$worktree" "$tip"
  echo "built $worktree at ${tip:0:12}" >&2
fi
echo "$tip"
