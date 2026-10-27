#!/usr/bin/env bash
# Build Omnigent with the series applied: BASE plus one commit per patch.
#
#   custom/scripts/build-custom.sh [--repo <clone>] [--fetch <url>] [--force] <branch>
#   custom/scripts/build-custom.sh [--repo <clone>] [--fetch <url>] --worktree <dir>
#
# <branch>     create (or with --force, reset) this branch in the clone to the
#              built result, e.g. a local working branch to develop on.
# --worktree   leave the result checked out (detached) in a new worktree <dir>.
# --repo       the Omnigent clone to build in (default: $OMNIGENT_REPO, else
#              the clone this script is checked out in).
# --fetch URL  fetch BASE from URL first if the clone does not have it
#              (default: https://github.com/omnigent-ai/omnigent.git).
#
# The build is reproducible: patches are applied with a fixed committer
# ($CUSTOM_COMMITTER_NAME / $CUSTOM_COMMITTER_EMAIL, default the GitHub Actions
# bot) and committer date = author date, so the same BASE and patch files give
# the same commit ids here and in CI. Prints the tip commit on the last line.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${OMNIGENT_REPO:-}"
branch=""
worktree=""
force=0
fetch_url="https://github.com/omnigent-ai/omnigent.git"

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --worktree) worktree="$2"; shift 2 ;;
    --fetch) fetch_url="$2"; shift 2 ;;
    --force) force=1; shift ;;
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
mapfile -t patches < <(grep -v -e '^#' -e '^[[:space:]]*$' "$here/series")

if ! git -C "$repo" rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
  echo "fetching BASE ${base:0:12} from $fetch_url" >&2
  git -C "$repo" fetch --quiet --no-tags --depth=1 "$fetch_url" "$base"
fi

# Fixed identity and settings, so the commit ids depend only on BASE and the patches.
export GIT_COMMITTER_NAME="${CUSTOM_COMMITTER_NAME:-github-actions[bot]}"
export GIT_COMMITTER_EMAIL="${CUSTOM_COMMITTER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
am_config=(-c commit.gpgSign=false -c core.autocrlf=false -c am.keepcr=false
  -c am.messageid=false -c mailinfo.scissors=false -c core.hooksPath=/dev/null)

if [[ -n "$worktree" ]]; then
  work="$worktree"
  cleanup() { :; }
else
  work="$(mktemp -d)/build"
  cleanup() {
    git -C "$repo" worktree remove --force "$work" >/dev/null 2>&1 || true
    rm -rf "$(dirname "$work")"
  }
fi
trap cleanup EXIT
git -C "$repo" worktree add --quiet --detach "$work" "$base"

applied=0
for patch in "${patches[@]}"; do
  if ! git "${am_config[@]}" -C "$work" am -3 --quiet --committer-date-is-author-date \
      "$here/patches/$patch" >/dev/null 2>"$work.err"; then
    cat "$work.err" >&2
    git -C "$work" am --abort >/dev/null 2>&1 || true
    echo "error: $patch did not apply after $applied of ${#patches[@]} patches" >&2
    exit 1
  fi
  applied=$((applied + 1))
done
rm -f "$work.err"
tip="$(git -C "$work" rev-parse HEAD)"

if [[ -n "$branch" ]]; then
  git -C "$repo" branch --force --no-track "$branch" "$tip" >/dev/null
  echo "built $branch: $applied patches on ${base:0:12}" >&2
else
  echo "built $work: $applied patches on ${base:0:12}" >&2
fi
echo "$tip"
