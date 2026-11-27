#!/usr/bin/env bash
# Build the series on BASE and check the result.
#
#   custom/scripts/check.sh [--repo <clone>] [--tree <dir>] [--custom <ref>] [--set <name>] [--pairs]
#
# Without a build (serieslib.py lint): every series is a directory
# custom/patches/<series>/ with NN-<slug>.patch files and a NOTE.md of at most
# 60 lines: its title, a "Needs:" line, a "Covers:" line that matches the
# lines its patches change, its index text (with "Turn on" and "Upstream",
# issues and pull requests as full links) and something under "Must hold",
# "Key code" and "Tests"; every patch carries usage docs (touches a path in
# DOC_PATHS) or a "Docs: none (<reason>)" trailer; needs name series that
# exist and do not form a circle; a glue directory (custom/glue/<a>+<b>/) is
# named after two series that do not need each other and says what it joins
# or patches, and why; every set file (custom/sets/<name>.txt) names series
# that exist.
# With the engine (serieslib.py verify): every series applies exactly on its
# own foundation, BASE plus the series it needs, so each builds alone, and
# the files, symbols and tests its note names exist in that build; every
# glue pair builds, its patches apply exactly on the two series combined and
# each path it joins really needs the join; and the whole build has the same
# tree whether series that do not need each other are combined by name or by
# name reversed.
# On the built tree: no conflict markers, and changed Python and JSON parse.
# The index, docs/custom/README.md, is the build's last commit, written from
# the notes of the series built, so it needs no check of its own.
#
# --repo     Omnigent clone that has (or can fetch) the BASE commit
#            (default: $OMNIGENT_REPO, else the clone this script is in).
# --tree     Check a tree build-custom.sh already built in <dir>: its HEAD
#            must be the commit the series build to.
# --custom   Also require the built tree to equal <ref>'s tree, e.g. the
#            build of an earlier commit when a change must not alter it.
# --set      Check the build of that set (build-custom.sh --set): the whole
#            series still passes the rules above, but only the set is built
#            (or expected in --tree).
# --pairs    Also build every two series that touch a common file and do not
#            need each other: any two must combine, cleanly or through glue.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${OMNIGENT_REPO:-}"
custom_ref=""
tree_dir=""
set_name=""
verify_args=()

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --tree) tree_dir="$2"; shift 2 ;;
    --custom) custom_ref="$2"; shift 2 ;;
    --set) set_name="$2"; shift 2 ;;
    --pairs) verify_args+=(--pairs); shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done
if [[ -z "$repo" && -z "$tree_dir" ]]; then
  repo="$(git -C "$here" rev-parse --show-toplevel)"
fi

base="$(tr -d '[:space:]' < "$here/BASE")"

fail() { echo "$1"; exit 1; }

lib=(python3 -I "$here/scripts/serieslib.py")

# The rules that need no build: layout, notes, the docs rule, needs, sets.
mapfile -t problems < <("${lib[@]}" lint || true)
if [[ ${#problems[@]} -gt 0 ]]; then
  printf '%s\n' "${problems[@]}" >&2
  fail "series check failed: ${problems[0]}"
fi
mapfile -t patches < <("$here/scripts/series-files.sh" --all)

set_args=()
if [[ -n "$set_name" ]]; then
  # From here on, only what the set builds: its series and what they need.
  set_args=(--set "$set_name")
  "$here/scripts/series-files.sh" "${set_args[@]}" --names >/dev/null 2>&1 \
    || { "$here/scripts/series-files.sh" "${set_args[@]}" --names >/dev/null || true; exit 2; }
  mapfile -t patches < <("$here/scripts/series-files.sh" "${set_args[@]}" 2>/dev/null)
fi

if [[ -n "$tree_dir" ]]; then
  work="$(cd "$tree_dir" && pwd)"
  engine_repo="${repo:-$work}"
else
  repo="$(cd "$repo" && pwd)"
  engine_repo="$repo"
fi

# Each series exactly on its own foundation, each glue pair, the whole build in both tie orders.
mapfile -t problems < <("${lib[@]}" verify --repo "$engine_repo" "${verify_args[@]}" 2>&1 || true)
if [[ ${#problems[@]} -gt 0 ]]; then
  printf '%s\n' "${problems[@]}" >&2
  fail "series check failed: ${problems[0]}"
fi

if [[ -n "$tree_dir" ]]; then
  expected="$("${lib[@]}" build --repo "$engine_repo" "${set_args[@]}" 2>/dev/null)" \
    || fail "the series${set_name:+ in set $set_name} does not build on ${base:0:12}"
  actual="$(git -C "$work" rev-parse HEAD)"
  [[ "$actual" == "$expected" ]] \
    || fail "$work is at ${actual:0:12}, the series${set_name:+ in set $set_name} builds ${expected:0:12}; rebuild it"
else
  work="$(mktemp -d)/check"
  cleanup() {
    git -C "$repo" worktree remove --force "$work" >/dev/null 2>&1 || true
    rm -rf "$(dirname "$work")"
  }
  trap cleanup EXIT
  "$here/scripts/build-custom.sh" --repo "$repo" "${set_args[@]}" --worktree "$work" >/dev/null 2>&1 \
    || fail "the series${set_name:+ in set $set_name} does not build on ${base:0:12}"
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

tip="$(git -C "$work" rev-parse HEAD)"
if [[ -n "$custom_ref" ]]; then
  ref_repo="${repo:-$work}"
  custom_tree="$(git -C "$ref_repo" rev-parse "$custom_ref^{tree}")"
  if [[ "$(git -C "$work" rev-parse 'HEAD^{tree}')" != "$custom_tree" ]]; then
    git -C "$ref_repo" diff --stat "$custom_ref" "$tip" >&2 || true
    fail "${#patches[@]} patches apply, but the tree differs from $custom_ref"
  fi
  echo "${#patches[@]} patches${set_name:+ of set $set_name} apply on ${base:0:12} as ${tip:0:12} and match $custom_ref"
else
  echo "${#patches[@]} patches${set_name:+ of set $set_name} apply on ${base:0:12} as ${tip:0:12}"
fi
