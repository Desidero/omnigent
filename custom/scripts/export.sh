#!/usr/bin/env bash
# Rewrite one series' patch files from its branch.
#
#   custom/scripts/export.sh [--repo <clone>] [--needs <series>,...] <series> <branch>
#   custom/scripts/export.sh [--repo <clone>] --glue <first>+<second> <branch>
#
# <branch> holds the series' commits on top of its foundation: BASE plus the
# series it needs, as build-custom.sh --series <series> builds it. Each commit
# after the foundation becomes custom/patches/<series>/NN-<subject-slug>.patch,
# numbered in branch order; files of commits that are gone are removed. Only
# this series' directory is written, and custom/BASE never moves here.
#
# --needs LIST  the series this one needs (comma-separated, or "none"), when
#               it is new or its needs change; the default is the "Needs:"
#               line of its NOTE.md. The branch must sit on the foundation
#               those give: start a new series with
#                 build-custom.sh --only <needs> --no-index <branch>
#               or, with no needs, on the commit in custom/BASE.
# --glue        export the patches of a glue pair, custom/glue/<first>+<second>/,
#               instead: <branch> holds them on top of the two series combined
#               (build-custom.sh --only <first>,<second> --no-index builds
#               that, with the pair's present patches already on it).
# --repo        defaults to $OMNIGENT_REPO, else the clone this script is in.
#
# A new series gets a NOTE.md to fill in. The export then rebuilds the series
# from the files it wrote and requires the branch's tree, and names the series
# cut on top of this one that no longer apply exactly (re-cut those with
# serieslib.py recut).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${OMNIGENT_REPO:-}"
options=()

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --needs) [[ $# -ge 2 ]] || usage 2; options+=(--needs "$2"); shift 2 ;;
    --glue) options+=(--glue); shift ;;
    -h|--help) usage 0 ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; usage 2 ;;
    *) break ;;
  esac
done
[[ $# -eq 2 ]] || usage 2
[[ -n "$repo" ]] || repo="$(git -C "$here" rev-parse --show-toplevel)"

exec python3 -I "$here/scripts/serieslib.py" export --repo "$repo" "${options[@]}" "$1" "$2"
