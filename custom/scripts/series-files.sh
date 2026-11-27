#!/usr/bin/env bash
# Print the patch files of one or more series, in apply order.
#
#   custom/scripts/series-files.sh [--needs] <series>...
#   custom/scripts/series-files.sh --only <series>[,<series>...] [--names]
#   custom/scripts/series-files.sh --set <name> [--names]
#   custom/scripts/series-files.sh --all
#
# Paths are absolute, one per line: each series' files
# (custom/patches/<series>/NN-<slug>.patch) in name order, the series in
# build order (a series after the ones it needs, otherwise by name).
# --needs also takes every series a NOTE.md "Needs:" line names, recursively.
# A series is cut from BASE plus the series it needs, so this is the list to
# apply one to your own checkout:
#
#   git am -3 $(custom/scripts/series-files.sh --needs link-rules)
#
# Several series that do not need each other are each cut from BASE: apply
# them one after the other with -3, or let build-custom.sh --only combine them.
#
# --only picks a set of features to build: the named series (comma- or
# space-separated, the option may repeat) and every series they need. It
# prints each series it added, and why, on stderr.
# --names prints the chosen series' names instead of their files.
# --set is --only with the series a set file lists: custom/sets/<name>.txt,
# one series per line, '#' starts a comment. A set name is lowercase letters
# and digits, starting with a letter, at most 20 characters, and not "dirty":
# it becomes part of a build's version and tags.
#
# The work is done by serieslib.py, which every script reads the series through.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
  ""|-h|--help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
    [[ -n "${1:-}" ]] || exit 2
    exit 0 ;;
esac
exec python3 -I "$here/serieslib.py" files "$@"
