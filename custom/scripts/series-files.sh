#!/usr/bin/env bash
# Print the patch files of one or more series, in apply order.
#
#   custom/scripts/series-files.sh [--needs] <series>...
#   custom/scripts/series-files.sh --only <series>[,<series>...] [--names]
#   custom/scripts/series-files.sh --all
#
# Paths are absolute, one per line, in the order custom/series lists them.
# --needs also takes every series named on the "# needs:" lines, recursively.
# Use it to apply part of the series to your own checkout:
#
#   git am -3 $(custom/scripts/series-files.sh --needs toast-safe-area)
#
# --only picks a set of features to build: the named series (comma- or
# space-separated, the option may repeat), every series they need, and always
# custom-docs-index. It prints each series it added, and why, on stderr.
# --names prints the chosen series' names instead of their files.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INDEX_SERIES=custom-docs-index
needs=0
all=0
only=0
names=0
wanted=()

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --needs) needs=1; shift ;;
    --all) all=1; shift ;;
    --only)
      [[ $# -ge 2 ]] || usage 2
      only=1; needs=1
      read -r -a listed <<< "${2//,/ }"
      wanted+=("${listed[@]}")
      shift 2 ;;
    --names) names=1; shift ;;
    -h|--help) usage 0 ;;
    -*) echo "unknown option: $1" >&2; usage 2 ;;
    *) wanted+=("$1"); shift ;;
  esac
done
[[ "$all" == 1 || ${#wanted[@]} -gt 0 ]] || usage 2
always=""
if [[ "$only" == 1 ]] && ! grep -qxF -- "$INDEX_SERIES" <<< "$(printf '%s\n' "${wanted[@]}")"; then
  always="$INDEX_SERIES"
fi

awk -v all="$all" -v needs="$needs" -v wanted="${wanted[*]:-}" -v always="$always" \
    -v names="$names" -v dir="$here/patches" '
  /^#[[:space:]]*series:/ {
    current = $0
    sub(/^#[[:space:]]*series:[[:space:]]*/, "", current)
    sub(/[[:space:]].*$/, "", current)
    if (!(current in known)) order[++series_count] = current
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
    split(wanted, list, " ")
    for (i in list) {
      if (!(list[i] in known)) { print "error: no series named " list[i] > "/dev/stderr"; exit 2 }
      take[list[i]] = 1
    }
    if (always != "") {
      if (!(always in known)) { print "error: no series named " always > "/dev/stderr"; exit 2 }
      take[always] = 1
      why[always] = "always included"
    }
    # Follow "# needs:" lines until nothing new is added.
    changed = needs
    while (changed) {
      changed = 0
      for (name in take) {
        n = split(deps[name], dep, " ")
        for (j = 1; j <= n; j++) {
          if (!(dep[j] in known)) { print "error: " name " needs unknown series " dep[j] > "/dev/stderr"; exit 2 }
          if (!(dep[j] in take)) { take[dep[j]] = 1; why[dep[j]] = "needed by " name; changed = 1 }
        }
      }
    }
    for (i = 1; i <= series_count; i++) {
      if (order[i] in why) print "added " order[i] " (" why[order[i]] ")" > "/dev/stderr"
    }
    for (i = 1; i <= series_count; i++) {
      if (names == 1 && (all == 1 || order[i] in take)) print order[i]
    }
    if (names == 1) exit 0
    for (i = 1; i <= count; i++) {
      if (all == 1 || owner[i] in take) print dir "/" file[i]
    }
  }
' "$here/series"
