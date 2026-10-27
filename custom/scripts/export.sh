#!/usr/bin/env bash
# Regenerate custom/BASE, custom/series and custom/patches/*.patch from a working branch.
#
#   custom/scripts/export.sh [--repo <clone>] <branch> [<base-ref>]
#
# <branch> is a branch built with build-custom.sh and then edited.
# <base-ref> defaults to upstream/main; BASE becomes merge-base(<branch>, <base-ref>).
# --repo defaults to $OMNIGENT_REPO, else the clone this script is checked out in.
# Each commit in BASE..<branch> becomes custom/patches/<series>--<subject-slug>.patch.
# A commit's series is looked up by its subject slug in the existing custom/series;
# a commit with an unknown slug joins the previous commit's series (with a warning),
# so edit custom/series and re-run to file it elsewhere. Comment lines kept per
# series ("# needs: ...", notes) and the header above the first series survive.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${OMNIGENT_REPO:-}"

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; usage 2 ;;
    *) break ;;
  esac
done
[[ $# -ge 1 && $# -le 2 ]] || usage 2
custom_ref="$1"
base_ref="${2:-upstream/main}"

[[ -n "$repo" ]] || repo="$(git -C "$here" rev-parse --show-toplevel)"
git -C "$repo" rev-parse --verify --quiet "$custom_ref^{commit}" >/dev/null \
  || { echo "error: $custom_ref is not a commit in $repo" >&2; exit 2; }
git -C "$repo" rev-parse --verify --quiet "$base_ref^{commit}" >/dev/null \
  || { echo "error: $base_ref is not a commit in $repo" >&2; exit 2; }

base="$(git -C "$repo" merge-base "$custom_ref" "$base_ref")"
mapfile -t commits < <(git -C "$repo" rev-list --reverse --no-merges "$base..$custom_ref")
if [[ "$(git -C "$repo" rev-list --count --merges "$base..$custom_ref")" != 0 ]]; then
  echo "error: $base..$custom_ref contains merge commits; rebase it instead" >&2
  exit 1
fi

out="$here/patches"
series_file="$here/series"
mkdir -p "$out"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# One "sha<TAB>subject" line per commit, in apply order.
for sha in "${commits[@]}"; do
  printf '%s\t%s\n' "$sha" "$(git -C "$repo" log -1 --format=%s "$sha")"
done > "$tmp/commits.tsv"

touch "$series_file"
python3 - "$series_file" "$tmp/commits.tsv" "$tmp/plan.tsv" "$tmp/series.new" <<'PY'
import re
import sys

series_path, commits_path, plan_path, new_series_path = sys.argv[1:5]

def slug(subject: str) -> str:
    text = re.sub(r"^[a-z]+(\([^)]*\))?!?:\s*", "", subject.strip())
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > 64:
        text = text[:64].rsplit("-", 1)[0]
    return text or "patch"

# Parse the existing series: header, per-series comment lines, slug -> series.
header, comments, slug_series = [], {}, {}
current = None
for raw in open(series_path, encoding="utf-8").read().splitlines():
    line = raw.rstrip()
    match = re.match(r"^#\s*series:\s*(\S+)", line)
    if match:
        current = match.group(1)
        comments.setdefault(current, [])
        continue
    if current is None:
        header.append(line)
    elif line.startswith("#"):
        if line not in comments[current]:
            comments[current].append(line)
    elif line.endswith(".patch") and "--" in line:
        series, _, rest = line.partition("--")
        slug_series[rest[: -len(".patch")]] = series

while header and header[-1] == "":
    header.pop()
if not header:
    header = [
        "# Apply order for the files in custom/patches/, onto the commit in custom/BASE:",
        "#   git am -3 $(custom/scripts/series-files.sh --all)",
        "# '# series: <name>' starts a series; '# needs: <name>' names a series",
        "# that has to be applied first if you take this one on its own.",
    ]

plan, lines, previous, seen, used = [], list(header), None, set(), set()
for raw in open(commits_path, encoding="utf-8").read().splitlines():
    sha, subject = raw.split("\t", 1)
    name = slug(subject)
    series = slug_series.get(name)
    if series is None:
        series = previous or "unsorted"
        print(f"warning: new patch '{subject}' filed under series '{series}'", file=sys.stderr)
    filename = f"{series}--{name}.patch"
    if filename in used:
        sys.exit(f"error: two commits map to {filename}; reword one subject")
    used.add(filename)
    if series != previous:
        lines.append("")
        if series in seen:
            lines.append(f"# series: {series} (continued)")
        else:
            lines.append(f"# series: {series}")
            lines.extend(comments.get(series, []))
        seen.add(series)
    lines.append(filename)
    plan.append(f"{sha}\t{filename}")
    previous = series

for series in comments:
    if series not in seen:
        print(f"note: series '{series}' has no patches left (landed upstream?)", file=sys.stderr)

open(plan_path, "w", encoding="utf-8").write("\n".join(plan) + "\n")
open(new_series_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY

# Write the patches, then drop any that the custom branch no longer carries.
declare -A keep=()
while IFS=$'\t' read -r sha filename; do
  git -C "$repo" format-patch -1 --stdout --zero-commit --no-signature --no-numbered \
    --full-index --no-color --encode-email-headers "$sha" > "$tmp/$filename"
  if ! cmp -s "$tmp/$filename" "$out/$filename"; then
    mv "$tmp/$filename" "$out/$filename"
  fi
  keep["$filename"]=1
done < "$tmp/plan.tsv"

shopt -s nullglob
for old in "$out"/*.patch; do
  name="$(basename "$old")"
  if [[ -z "${keep[$name]:-}" ]]; then
    echo "removed: $name"
    rm -f "$old"
  fi
done

mv "$tmp/series.new" "$series_file"
echo "$base" > "$here/BASE"
echo "exported ${#commits[@]} patches onto $base"
