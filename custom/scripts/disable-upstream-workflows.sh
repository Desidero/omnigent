#!/usr/bin/env bash
# Switch off every GitHub Actions workflow on the fork except ours.
#
#   custom/scripts/disable-upstream-workflows.sh [--repo <owner/name>] [--dry-run] [--cancel-runs]
#
# The patches branch carries upstream's .github/workflows/, and main mirrors
# upstream, so upstream's CI would otherwise run on our pull requests, pushes
# and schedules. This lists the repository's workflows through the API and
# disables each one whose file is not .github/workflows/custom-*. Workflows
# GitHub manages itself (paths under dynamic/, such as Dependabot or CodeQL
# default setup) are listed but left alone. Idempotent.
#
# --repo         default: $GITHUB_REPOSITORY, else Desidero/omnigent
# --dry-run      print what it would disable or cancel
# --cancel-runs  also cancel queued and running runs of those workflows
# --branch REF   warn about upstream workflow files on REF that GitHub has not
#                registered yet, so cannot be disabled (default: patches)
#
# Needs gh with a token that may write Actions on the repository: the workflow
# token with `actions: write`, a fine-grained token with Actions read and
# write, or a classic token with `repo`.
set -euo pipefail

repo="${GITHUB_REPOSITORY:-Desidero/omnigent}"
dry_run=0
cancel_runs=0
branch=patches
OURS_RE='^\.github/workflows/custom-[^/]*$'

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --cancel-runs) cancel_runs=1; shift ;;
    --branch) branch="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done

act() {
  if [[ "$dry_run" == 1 ]]; then echo "  would: $*"; else "$@"; fi
}

# id <TAB> state <TAB> path <TAB> name, one line per registered workflow.
listing="$(gh api --paginate "repos/$repo/actions/workflows?per_page=100" \
  --jq '.workflows[] | [.id, .state, .path, .name] | @tsv')"

disabled=0 kept=0 already=0 failed=0
upstream_ids=()
while IFS=$'\t' read -r id state path name; do
  [[ -n "$id" ]] || continue
  if [[ "$path" =~ $OURS_RE ]]; then
    echo "keep     $path ($state)"
    kept=$((kept + 1))
    continue
  fi
  if [[ "$path" != .github/workflows/* ]]; then
    echo "managed  $path ($name, $state): left alone"
    continue
  fi
  upstream_ids+=("$id")
  case "$state" in
    disabled_manually|deleted) already=$((already + 1)); continue ;;
  esac
  echo "disable  $path ($state)"
  if act gh api -X PUT "repos/$repo/actions/workflows/$id/disable" --silent </dev/null; then
    disabled=$((disabled + 1))
  else
    echo "  failed to disable $path" >&2
    failed=$((failed + 1))
  fi
done <<< "$listing"

if [[ "$cancel_runs" == 1 && ${#upstream_ids[@]} -gt 0 ]]; then
  for status in queued in_progress waiting pending requested; do
    gh api --paginate "repos/$repo/actions/runs?status=$status&per_page=100" \
      --jq '.workflow_runs[] | [.id, .workflow_id, .path, .head_branch] | @tsv' 2>/dev/null
  done | sort -u | while IFS=$'\t' read -r run_id workflow_id path head; do
    [[ -n "$run_id" ]] || continue
    [[ " ${upstream_ids[*]} " == *" $workflow_id "* ]] || continue
    echo "cancel   run $run_id of $path on $head"
    act gh api -X POST "repos/$repo/actions/runs/$run_id/cancel" --silent </dev/null \
      || echo "  could not cancel run $run_id" >&2
  done
fi

# Upstream workflow files on the branch that GitHub has not registered yet:
# they cannot be disabled until they exist, so their first event may run them.
unregistered=0
if files="$(gh api "repos/$repo/contents/.github/workflows?ref=$branch" \
    --jq '.[] | select(.type == "file") | .path' 2>/dev/null)"; then
  registered="$(cut -f3 <<< "$listing")"
  while read -r path; do
    [[ "$path" == *.yml || "$path" == *.yaml ]] || continue
    [[ ! "$path" =~ $OURS_RE ]] || continue
    if ! grep -qxF -- "$path" <<< "$registered"; then
      echo "WARN     $path on $branch is not registered yet; disable it once it shows up" >&2
      unregistered=$((unregistered + 1))
    fi
  done <<< "$files"
fi

verb=disabled
[[ "$dry_run" == 0 ]] || verb="to disable"
echo "$disabled $verb, $already already off, $kept ours kept, $unregistered not registered yet, $failed failed"
[[ "$failed" == 0 ]]
