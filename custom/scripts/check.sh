#!/usr/bin/env bash
# Apply the series onto BASE and check the result.
#
#   custom/scripts/check.sh [--repo <clone>] [--tree <dir>] [--custom <ref>]
#
# Besides applying cleanly, every patch must carry usage docs (touch a path in
# DOC_PATHS) or a "Docs: none (<reason>)" trailer, every "# series:" needs a
# "## <series>" section in docs/custom/README.md of the applied tree, and the
# last series must be custom-docs-index, the commit that holds that index.
# Each series must be one block that comes after every series it "# needs:".
#
# --repo     Omnigent clone that has (or can fetch) the BASE commit
#            (default: $OMNIGENT_REPO, else the clone this script is in).
# --tree     Check a tree build-custom.sh already built in <dir>
#            instead of applying the series again.
# --custom   Also require the applied tree to equal <ref>'s tree, e.g. the
#            working branch you exported from.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${OMNIGENT_REPO:-}"
custom_ref=""
tree_dir=""

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --tree) tree_dir="$2"; shift 2 ;;
    --custom) custom_ref="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done
if [[ -z "$repo" && -z "$tree_dir" ]]; then
  repo="$(git -C "$here" rev-parse --show-toplevel)"
fi

# Paths that count as usage docs: upstream's user and agent docs, feature-map
# recipes, design docs (the telemetry variable table) and the server API reference.
DOC_PATHS_RE='^(docs/|feature-map/|designs/|omnigent/server/API\.md$)'
INDEX_SERIES=custom-docs-index
INDEX_PATH=docs/custom/README.md

base="$(tr -d '[:space:]' < "$here/BASE")"
mapfile -t patches < <(grep -v -e '^#' -e '^[[:space:]]*$' "$here/series")

fail() { echo "$1"; exit 1; }

# Docs rule, per patch file: it touches a doc path or says why it needs none.
patch_message() {
  # The commit message: after the mail headers, up to the diffstat separator.
  awk 'body && /^---$/ {exit} body {print} !body && /^$/ {body=1}' "$1"
}
problems=()
for patch in "${patches[@]}"; do
  file="$here/patches/$patch"
  [[ -f "$file" ]] || { problems+=("$patch is listed in custom/series but missing"); continue; }
  # grep -q on a pipe can SIGPIPE the writer, which pipefail reports; use strings.
  touched="$(grep -E '^diff --git a/' "$file" | sed -E 's|^diff --git a/(.*) b/.*$|\1|')"
  if grep -qE "$DOC_PATHS_RE" <<< "$touched"; then
    continue
  fi
  if grep -q '^Docs: none (' <<< "$(patch_message "$file" | git interpret-trailers --parse)"; then
    continue
  fi
  problems+=("$patch has no usage docs and no 'Docs: none (<reason>)' trailer")
done
shopt -s nullglob
for file in "$here"/patches/*.patch; do
  name="$(basename "$file")"
  grep -qxF -- "$name" <<< "$(printf '%s\n' "${patches[@]}")" || problems+=("$name is not listed in custom/series")
done
mapfile -t series_names < <(sed -nE 's/^#[[:space:]]*series:[[:space:]]*([^[:space:]]+).*$/\1/p' \
  "$here/series" | awk '!seen[$0]++')
last_series="$(sed -nE 's/^#[[:space:]]*series:[[:space:]]*([^[:space:]]+).*$/\1/p' \
  "$here/series" | tail -n 1)"
if [[ "$last_series" != "$INDEX_SERIES" ]]; then
  problems+=("the last series is ${last_series:-missing}, not $INDEX_SERIES")
fi
# Each series is one block, after every series it needs, so any set of
# series (series-files.sh --only) applies in custom/series order.
mapfile -t -O "${#problems[@]}" problems < <(awk '
  /^#[[:space:]]*series:/ {
    current = $0
    sub(/^#[[:space:]]*series:[[:space:]]*/, "", current)
    sub(/[[:space:]].*$/, "", current)
    if (current in seen) print "series " current " is split into several blocks; keep its patches together"
    seen[current] = 1
    next
  }
  /^#[[:space:]]*needs:/ {
    need = $0
    sub(/^#[[:space:]]*needs:[[:space:]]*/, "", need)
    sub(/[[:space:]].*$/, "", need)
    if (!(need in seen)) print "series " current " needs " need ", which does not come before it"
  }
' "$here/series")
if [[ ${#problems[@]} -gt 0 ]]; then
  printf '%s\n' "${problems[@]}" >&2
  fail "series check failed: ${problems[0]}"
fi

if [[ -n "$tree_dir" ]]; then
  work="$(cd "$tree_dir" && pwd)"
  count="$(git -C "$work" rev-list --count "$base..HEAD")"
  [[ "$count" == "${#patches[@]}" ]] \
    || fail "$work has $count commits on BASE, the series has ${#patches[@]}; rebuild it"
else
  repo="$(cd "$repo" && pwd)"
  work="$(mktemp -d)/check"
  cleanup() {
    git -C "$repo" worktree remove --force "$work" >/dev/null 2>&1 || true
    rm -rf "$(dirname "$work")"
  }
  trap cleanup EXIT
  "$here/scripts/build-custom.sh" --repo "$repo" --worktree "$work" >/dev/null \
    || fail "the series does not apply on ${base:0:12}"
fi

# Quick sanity: no conflict markers, and changed Python and JSON files parse.
mapfile -t changed < <(git -C "$work" diff --name-only --diff-filter=AM "$base" HEAD)
for path in "${changed[@]}"; do
  file="$work/$path"
  if grep -qE '^(<<<<<<<|>>>>>>>) ' "$file"; then
    problems+=("conflict marker in $path")
  fi
  case "$path" in
    *.py) python3 -c 'import ast, sys; ast.parse(open(sys.argv[1], "rb").read(), sys.argv[1])' \
            "$file" 2>/dev/null || problems+=("Python syntax error in $path") ;;
    *.json) python3 -m json.tool "$file" >/dev/null 2>&1 || problems+=("invalid JSON in $path") ;;
  esac
done
if [[ ${#problems[@]} -gt 0 ]]; then
  printf '%s\n' "${problems[@]}" >&2
  fail "sanity check failed: ${problems[0]}"
fi

# Every series has a section in the index at the series tip.
indexed=()
if [[ -f "$work/$INDEX_PATH" ]]; then
  mapfile -t indexed < <(sed -nE 's/^##[[:space:]]+([^[:space:]]+)[[:space:]]*$/\1/p' "$work/$INDEX_PATH")
fi
for name in "${series_names[@]}"; do
  if ! grep -qxF -- "$name" <<< "$(printf '%s\n' "${indexed[@]}")"; then
    problems+=("series $name has no '## $name' section in $INDEX_PATH")
  fi
done
if [[ ${#problems[@]} -gt 0 ]]; then
  printf '%s\n' "${problems[@]}" >&2
  fail "index check failed: ${problems[0]}"
fi

tip="$(git -C "$work" rev-parse HEAD)"
if [[ -n "$custom_ref" ]]; then
  ref_repo="${repo:-$work}"
  custom_tree="$(git -C "$ref_repo" rev-parse "$custom_ref^{tree}")"
  if [[ "$(git -C "$work" rev-parse 'HEAD^{tree}')" != "$custom_tree" ]]; then
    git -C "$ref_repo" diff --stat "$custom_ref" "$tip" >&2 || true
    fail "${#patches[@]} patches apply, but the tree differs from $custom_ref; re-run export.sh"
  fi
  echo "${#patches[@]} patches apply on ${base:0:12} as ${tip:0:12} and match $custom_ref"
else
  echo "${#patches[@]} patches apply on ${base:0:12} as ${tip:0:12}"
fi
