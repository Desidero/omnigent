#!/usr/bin/env bash
# Print the patch files of one or more series, in apply order.
#
#   custom/scripts/series-files.sh [--needs] <series>...
#   custom/scripts/series-files.sh --all
#
# Paths are absolute, one per line, in the order custom/series lists them, so
# a series' "(continued)" fixups come after its first patches. --needs also
# takes every series named on the "# needs:" lines, recursively. Use it to
# apply part of the series to your own checkout:
#
#   git am -3 $(custom/scripts/series-files.sh --needs toast-safe-area)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
needs=0
all=0
wanted=()

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --needs) needs=1; shift ;;
    --all) all=1; shift ;;
    -h|--help) usage 0 ;;
    -*) echo "unknown option: $1" >&2; usage 2 ;;
    *) wanted+=("$1"); shift ;;
  esac
done
[[ "$all" == 1 || ${#wanted[@]} -gt 0 ]] || usage 2

awk -v all="$all" -v needs="$needs" -v wanted="${wanted[*]:-}" -v dir="$here/patches" '
  /^#[[:space:]]*series:/ {
    current = $0
    sub(/^#[[:space:]]*series:[[:space:]]*/, "", current)
    sub(/[[:space:]].*$/, "", current)
    known[current] = 1
    next
  }
  /^#[[:space:]]*needs:/ {
    need = $0
    sub(/^#[[:space:]]*needs:[[:space:]]*/, "", need)
    sub(/[[:space:]].*$/, "", need)
    if (current != "") deps[current] = deps[current] " " need
    next
  }
  /^#/ || /^[[:space:]]*$/ { next }
  { count++; file[count] = $1; owner[count] = current }
  END {
    split(wanted, names, " ")
    for (i in names) {
      if (!(names[i] in known)) { print "error: no series named " names[i] > "/dev/stderr"; exit 2 }
      take[names[i]] = 1
    }
    # Follow "# needs:" lines until nothing new is added.
    changed = needs
    while (changed) {
      changed = 0
      for (name in take) {
        n = split(deps[name], list, " ")
        for (j = 1; j <= n; j++) {
          if (!(list[j] in take)) { take[list[j]] = 1; changed = 1 }
        }
      }
    }
    for (i = 1; i <= count; i++) {
      if (all == 1 || owner[i] in take) print dir "/" file[i]
    }
  }
' "$here/series"
