#!/usr/bin/env bash
# Refresh the series onto a newer upstream commit, one series at a time, as a
# branch for a pull request.
#
#   custom/scripts/refresh.sh [--upstream <ref>] [--remote <name>] [--no-fetch] [<checks>]
#   custom/scripts/refresh.sh --continue [--park <series>]... [<checks>]
#   custom/scripts/refresh.sh --rehearse [--upstream <ref>] [--no-fetch] [<checks>]
#
# Run it in a clean worktree on a new branch cut from patches, e.g.
#   git switch -c refresh/$(date -u +%F) origin/patches
# It never rewrites history: the branch gets a merge of upstream and one
# commit with the regenerated custom/ files, ready for a pull request into
# patches. Steps:
#   1. fetch <remote> (default upstream; --no-fetch skips it) and merge <ref>
#      (default <remote>/main) into the branch; only upstream paths change,
#      so this merge does not conflict; write the new commit to custom/BASE;
#   2. move every series onto its new foundation, each on its own and in
#      build order (serieslib.py refresh). One line per series:
#        unchanged  its patches still apply exactly
#        refreshed  cherry-picked onto the new foundation and rewritten; a
#                   patch that came out empty landed upstream and is dropped
#        landed     no patch left: the series is removed with its note, its
#                   glue, and the needs and set lines that name it
#        conflict   stale: its files are left alone, with the commands to
#                   move it by hand
#        waits      it needs a stale series
#      Glue follows its two series: its patches are moved, a join the pair no
#      longer needs is taken off, and glue with nothing left is removed;
#   3. when nothing is stale: check.sh, commit custom/ as "Refresh the series
#      onto upstream <sha>", and check-tree.sh.
# A stale series does not hold up the others. Finish it by hand (the commands
# are printed), or park it, then run --continue:
#   --park S   move series S to custom/parked/S/ as it is, with "Base: <old
#              BASE>" in its note, so that the refresh can land without it.
#              Its glue goes with it and set files stop listing it; a series
#              that needs S must be parked too. To bring it back later, move
#              the directory to custom/patches/, take the Base line out and
#              run serieslib.py recut --from <the commit before it was parked> S.
# --rehearse does step 2 on a copy of custom/ in a temporary folder and prints
# the result: nothing is merged, written or committed.
#
# <checks>: for a series whose note links an upstream pull request that
# GitHub (gh, read only) says is merged, the note's tests that exist on bare
# BASE are named: if they pass there, the series landed in another shape and
# can go.
#   --no-upstream-check     do not ask GitHub (offline)
#   --landed-test-cmd CMD   run those tests with CMD in a worktree of BASE,
#                           e.g. "uv run pytest -q"; a test file the series
#                           changes is run in the series' own copy
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
top="$(git -C "$here" rev-parse --show-toplevel)"
remote=upstream
upstream_ref=""
resume=0
rehearse=0
fetch=1
park=()
checks=()

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upstream) upstream_ref="$2"; shift 2 ;;
    --remote) remote="$2"; shift 2 ;;
    --no-fetch) fetch=0; shift ;;
    --continue) resume=1; shift ;;
    --rehearse) rehearse=1; shift ;;
    --park) [[ $# -ge 2 ]] || usage 2; park+=("$2"); resume=1; shift 2 ;;
    --no-upstream-check) checks+=(--no-upstream-check); shift ;;
    --landed-test-cmd) [[ $# -ge 2 ]] || usage 2; checks+=(--landed-test-cmd "$2"); shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done
g() { git -C "$top" "$@"; }
die() { echo "error: $*" >&2; exit 1; }
lib=(python3 -I "$here/scripts/serieslib.py")
state="$(g rev-parse --git-path custom-refresh.env)"
[[ "$state" = /* ]] || state="$top/$state"

if [[ "$rehearse" == 1 ]]; then
  [[ "$fetch" == 0 ]] || g fetch --quiet "$remote"
  new_base="$(g rev-parse --verify "${upstream_ref:-$remote/main}^{commit}")"
  [[ -z "$(g status --porcelain -- custom/BASE custom/patches custom/glue)" ]] \
    || die "the series have local changes; a rehearsal reads them as committed"
  copy="$(mktemp -d)"
  trap 'rm -rf "$copy"' EXIT
  mkdir "$copy/custom"
  for part in patches glue parked sets index-intro.md; do
    [[ ! -e "$here/$part" ]] || cp -R "$here/$part" "$copy/custom/$part"
  done
  echo "$new_base" > "$copy/custom/BASE"
  echo "rehearsal: $(tr -d '[:space:]' < "$here/BASE" | cut -c1-12) -> ${new_base:0:12}; nothing is written"
  "${lib[@]}" --custom "$copy/custom" refresh --repo "$top" --from HEAD "${checks[@]}" || true
  exit 0
fi

branch="$(g symbolic-ref --quiet --short HEAD)" || die "check out a branch cut from patches first"
[[ "$branch" != patches ]] || die "don't refresh on patches itself: git switch -c refresh/$(date -u +%F)"

if [[ "$resume" == 0 ]]; then
  [[ -z "$(g status --porcelain)" ]] || die "the worktree has local changes"
  [[ "$fetch" == 0 ]] || g fetch --quiet "$remote"
  upstream_ref="${upstream_ref:-$remote/main}"
  new_base="$(g rev-parse --verify "$upstream_ref^{commit}")"
  old_base="$(tr -d '[:space:]' < "$here/BASE")"
  [[ "$new_base" != "$old_base" ]] || { echo "custom/BASE is already ${new_base:0:12}"; exit 0; }
  g merge-base --is-ancestor "$old_base" "$new_base" \
    || die "$upstream_ref (${new_base:0:12}) does not contain BASE ${old_base:0:12}"

  # 1. Bring upstream in, never by rebasing patches.
  if ! g merge-base --is-ancestor "$new_base" HEAD; then
    g merge --quiet --no-ff --no-edit -m "Merge upstream ${new_base:0:12} into patches" "$new_base" \
      || die "merging upstream conflicted: upstream now has a path under custom/ or a custom-* workflow; resolve by renaming ours"
  fi
  # The series as they were, cut from the old BASE, stay readable at this commit.
  source_commit="$(g rev-parse HEAD)"
  printf 'new_base=%s\nold_base=%s\nsource_commit=%s\n' "$new_base" "$old_base" "$source_commit" > "$state"
  echo "$new_base" > "$here/BASE"
else
  [[ -f "$state" ]] || die "no refresh in progress ($state is missing)"
  # shellcheck disable=SC1090
  . "$state"
fi

# shellcheck disable=SC2154 # set above or by the state file
if [[ ${#park[@]} -gt 0 ]]; then
  "${lib[@]}" park --repo "$top" --from "$source_commit" "${park[@]}"
fi

# 2. Every series onto its new foundation, on its own.
if ! "${lib[@]}" refresh --repo "$top" --from "$source_commit" "${checks[@]}"; then
  {
    echo
    echo "Some series are stale. For each: finish it by hand with the commands above, or park it:"
    echo "  $here/scripts/refresh.sh --continue --park <series>"
    echo "Then run:"
    echo "  $here/scripts/refresh.sh --continue"
  } >&2
  exit 1
fi

# 3. Check, commit, then confirm the branch is still upstream plus custom/ only.
"$here/scripts/check.sh" --repo "$top"
g add -A -- custom
g commit --quiet --no-verify -m "Refresh the series onto upstream ${new_base:0:12}" \
  -m "Moved each series from ${old_base:0:12} onto its new foundation with custom/scripts/refresh.sh."
"$here/scripts/check-tree.sh" --repo "$top" HEAD
rm -f "$state"
fork="$(g remote get-url origin 2>/dev/null | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##' || true)"
echo
echo "Refreshed onto ${new_base:0:12}. Review the notes of the series that changed."
echo "Next: push $branch and open a pull request into patches, e.g."
echo "  git push origin $branch"
echo "  gh pr create -R ${fork:-<owner>/<repo>} --base patches --head $branch"
