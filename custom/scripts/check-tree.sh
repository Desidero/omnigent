#!/usr/bin/env bash
# Check that a commit on the patches branch is upstream's tree plus only our paths.
#
#   custom/scripts/check-tree.sh [--repo <clone>] [--upstream <ref>] [<commit>]
#
# <commit> (default HEAD) must hold custom/BASE, an upstream commit that is an
# ancestor of <commit>, and its tree minus OWNED_PATHS must equal BASE's tree:
# every difference from upstream lives under custom/ or in our workflow and
# composite action. BASE itself must not have any of those paths.
# --upstream REF  also require BASE to be an ancestor of REF (e.g. upstream/main).
# --repo          defaults to $OMNIGENT_REPO, else the clone this script is in.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${OMNIGENT_REPO:-}"
upstream_ref=""
commit=HEAD
# Everything the patches branch may add to upstream's tree.
OWNED_PATHS=(custom ':(glob).github/workflows/custom-*' ':(glob).github/actions/custom-*/**')

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --upstream) upstream_ref="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    -*) echo "unknown option: $1" >&2; usage 2 ;;
    *) commit="$1"; shift ;;
  esac
done
[[ -n "$repo" ]] || repo="$(git -C "$here" rev-parse --show-toplevel)"
g() { git -C "$repo" "$@"; }
fail() { echo "tree check failed: $*" >&2; exit 1; }

commit="$(g rev-parse --verify "$commit^{commit}")"
base="$(g show "$commit:custom/BASE" 2>/dev/null | tr -d '[:space:]')" \
  || fail "${commit:0:12} has no custom/BASE"
[[ "$base" =~ ^[0-9a-f]{40}$ ]] || fail "custom/BASE is '$base', not a full commit id"
g rev-parse --verify --quiet "$base^{commit}" >/dev/null \
  || fail "BASE ${base:0:12} is not in this clone; fetch upstream"
g merge-base --is-ancestor "$base" "$commit" \
  || fail "BASE ${base:0:12} is not an ancestor of ${commit:0:12}; merge upstream into the branch"
if [[ -n "$upstream_ref" ]]; then
  g merge-base --is-ancestor "$base" "$upstream_ref" \
    || fail "BASE ${base:0:12} is not on $upstream_ref"
fi

# Each tree minus our paths, written through a throwaway index.
index="$(mktemp)"
trap 'rm -f "$index"' EXIT
stripped_tree() {
  rm -f "$index"
  GIT_INDEX_FILE="$index" g read-tree "$1"
  GIT_INDEX_FILE="$index" g rm -r -q -f --cached --ignore-unmatch -- "${OWNED_PATHS[@]}" >/dev/null
  GIT_INDEX_FILE="$index" g write-tree
}
base_tree="$(g rev-parse "$base^{tree}")"
[[ "$(stripped_tree "$base")" == "$base_tree" ]] \
  || fail "upstream BASE ${base:0:12} has paths the patches branch owns (${OWNED_PATHS[*]}); rename ours"
ours="$(stripped_tree "$commit")"
if [[ "$ours" != "$base_tree" ]]; then
  differences="$(g diff-tree -r --name-status "$base_tree" "$ours")"
  count="$(wc -l <<< "$differences")"
  echo "paths outside custom/ and our workflow that differ from BASE ${base:0:12}:" >&2
  sed -n '1,50p' <<< "$differences" >&2
  [[ "$count" -le 50 ]] || echo "... and $((count - 50)) more" >&2
  fail "${commit:0:12} changes $count upstream paths; such changes belong in a patch under custom/patches/, or in a merge of upstream that also moves custom/BASE"
fi
echo "${commit:0:12} is upstream ${base:0:12} plus custom/ and the custom workflow only"
