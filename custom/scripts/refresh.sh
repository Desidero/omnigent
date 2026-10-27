#!/usr/bin/env bash
# Refresh the series onto a newer upstream commit, as a branch for a pull request.
#
#   custom/scripts/refresh.sh [--upstream <ref>] [--remote <name>] [--work-dir <dir>]
#   custom/scripts/refresh.sh --continue
#
# Run it in a clean worktree on a new branch cut from patches, e.g.
#   git switch -c refresh/$(date -u +%F) origin/patches
# It never rewrites history: the branch gets a merge of upstream and one
# commit with the regenerated custom/ files, ready for a pull request into
# patches. Steps:
#   1. fetch <remote> (default upstream) and merge <ref> (default
#      <remote>/main) into the branch; only upstream paths change, so this
#      merge does not conflict;
#   2. build the old series as work/refresh-<sha> (build-custom.sh) and rebase
#      it onto the new upstream commit in --work-dir (default
#      $TMPDIR/custom-refresh-<sha>). On a conflict it stops: resolve it there
#      (rerere remembers), `git rebase --continue`, then run this again with
#      --continue. Patches that landed upstream drop out as empty commits;
#   3. export the rebased branch (export.sh), so custom/BASE becomes the
#      merged upstream commit, then check.sh --custom and check-tree.sh;
#   4. commit custom/ as "Refresh the series onto upstream <sha>".
# Then push the branch and open the pull request into patches; CI runs the
# tests of every patch because BASE moved.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
top="$(git -C "$here" rev-parse --show-toplevel)"
remote=upstream
upstream_ref=""
work_dir=""
resume=0

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upstream) upstream_ref="$2"; shift 2 ;;
    --remote) remote="$2"; shift 2 ;;
    --work-dir) work_dir="$2"; shift 2 ;;
    --continue) resume=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done
g() { git -C "$top" "$@"; }
die() { echo "error: $*" >&2; exit 1; }
state="$(g rev-parse --git-path custom-refresh.env)"
[[ "$state" = /* ]] || state="$top/$state"

branch="$(g symbolic-ref --quiet --short HEAD)" || die "check out a branch cut from patches first"
[[ "$branch" != patches ]] || die "don't refresh on patches itself: git switch -c refresh/$(date -u +%F)"

if [[ "$resume" == 0 ]]; then
  [[ -z "$(g status --porcelain)" ]] || die "the worktree has local changes"
  g fetch --quiet "$remote"
  upstream_ref="${upstream_ref:-$remote/main}"
  new_base="$(g rev-parse --verify "$upstream_ref^{commit}")"
  old_base="$(tr -d '[:space:]' < "$here/BASE")"
  [[ "$new_base" != "$old_base" ]] || { echo "custom/BASE is already ${new_base:0:12}"; exit 0; }
  g merge-base --is-ancestor "$old_base" "$new_base" \
    || die "$upstream_ref (${new_base:0:12}) does not contain BASE ${old_base:0:12}"
  work_branch="work/refresh-${new_base:0:12}"
  work_dir="${work_dir:-${TMPDIR:-/tmp}/custom-refresh-${new_base:0:12}}"

  # 1. Bring upstream in, never by rebasing patches.
  if ! g merge-base --is-ancestor "$new_base" HEAD; then
    g merge --quiet --no-ff --no-edit -m "Merge upstream ${new_base:0:12} into patches" "$new_base" \
      || die "merging upstream conflicted: upstream now has a path under custom/ or a custom-* workflow; resolve by renaming ours"
  fi

  # 2. The old series, rebased onto the new base in its own worktree.
  "$here/scripts/build-custom.sh" --repo "$top" --force "$work_branch" >/dev/null
  printf 'new_base=%s\nold_base=%s\nwork_branch=%s\nwork_dir=%s\n' \
    "$new_base" "$old_base" "$work_branch" "$work_dir" > "$state"
  [[ ! -e "$work_dir" ]] || die "$work_dir exists; remove it or pass --work-dir"
  g worktree add --quiet "$work_dir" "$work_branch"
  if ! git -C "$work_dir" rebase --onto "$new_base" "$old_base"; then
    cat >&2 <<EOF

The rebase stopped on a conflict. Resolve it in
  $work_dir
then \`git -C $work_dir rebase --continue\` until it finishes, and run
  $here/scripts/refresh.sh --continue
EOF
    exit 1
  fi
else
  [[ -f "$state" ]] || die "no refresh in progress ($state is missing)"
  # shellcheck disable=SC1090
  . "$state"
fi

# shellcheck disable=SC2154 # set above or by the state file
if [[ -d "$(git -C "$work_dir" rev-parse --git-path rebase-merge)" ]] \
    || [[ -d "$(git -C "$work_dir" rev-parse --git-path rebase-apply)" ]]; then
  die "the rebase in $work_dir is not finished"
fi
g merge-base --is-ancestor "$new_base" "$work_branch" || die "$work_branch is not on ${new_base:0:12}"

# 3. Export and check.
"$here/scripts/export.sh" --repo "$top" "$work_branch" "$new_base"
[[ "$(tr -d '[:space:]' < "$here/BASE")" == "$new_base" ]] || die "export did not set BASE to ${new_base:0:12}"
"$here/scripts/check.sh" --repo "$top" --custom "$work_branch"

# 4. Commit, then confirm the branch is still upstream plus custom/ only.
g add -A -- custom
g commit --quiet -m "Refresh the series onto upstream ${new_base:0:12}" \
  -m "Rebased $(git -C "$top" rev-list --count "$new_base..$work_branch") patches from ${old_base:0:12} with custom/scripts/refresh.sh."
"$here/scripts/check-tree.sh" --repo "$top" HEAD
g worktree remove "$work_dir"
rm -f "$state"
fork="$(g remote get-url origin 2>/dev/null | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##')"
cat <<EOF

Refreshed onto ${new_base:0:12}. The rebased series stays as $work_branch.
Next: push $branch and open a pull request into patches, e.g.
  git push origin $branch
  gh pr create -R ${fork:-<owner>/<repo>} --base patches --head $branch
EOF
