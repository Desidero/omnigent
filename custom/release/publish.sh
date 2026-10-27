#!/usr/bin/env bash
# Publish a build: push an immutable tag, push the server image, create the
# GitHub release on the fork, then point the fork's custom branch at it.
#
#   custom/release/publish.sh <out-dir> <built-commit>
#
# <out-dir> is the install set custom/release/build.sh wrote (with plan.env
# from plan.py); <built-commit> is the tip build-custom.sh just rebuilt in the
# clone, which must equal the install set's commit. Environment:
#   DRY_RUN=true          print the pushes, tag, image push and release instead
#   PRERELEASE            true (default) marks the release as a pre-release
#   OMNIGENT_CLONE        the clone that holds the built commits (default: the
#                         checkout this script is in)
#   FORK_REPO             the repository to publish to (default Desidero/omnigent)
#   UPSTREAM_REPO         named in the tag message (default omnigent-ai/omnigent)
#   PUSH_SSH_KEY          a write deploy key for the custom and tag pushes, used
#                         instead of PUSH_TOKEN when set (see README)
#   PUSH_TOKEN            token for the custom and tag pushes (in CI the
#                         workflow token, or a fallback secret; see README)
#   GH_TOKEN              token gh uses to create the release (contents: write)
#   GHCR_TOKEN, GHCR_USER login for ghcr.io (packages: write)
#   CUSTOM_COMMITTER_NAME, CUSTOM_COMMITTER_EMAIL
#                         tagger identity (default the GitHub Actions bot)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # custom/
out="$1" built="$2"
repo="${OMNIGENT_CLONE:-$(git -C "$here" rev-parse --show-toplevel)}"
dry_run="${DRY_RUN:-true}"
prerelease="${PRERELEASE:-true}"
fork="${FORK_REPO:-Desidero/omnigent}"

# shellcheck disable=SC1091
. "$out/build.env"
resume=""
# shellcheck disable=SC1091
[[ ! -f "$out/plan.env" ]] || . "$out/plan.env"

summary() { echo "$*"; [[ -z "${GITHUB_STEP_SUMMARY:-}" ]] || echo "$*" >> "$GITHUB_STEP_SUMMARY"; }
run() {
  if [[ "$dry_run" == true ]]; then
    summary "- dry run, would run: \`$*\`"
  else
    "$@"
  fi
}
die() { echo "::error::$*" >&2; exit 1; }

[[ "$built" == "$CUSTOM_COMMIT" ]] \
  || die "rebuilt custom $built differs from the install set's $CUSTOM_COMMIT"
[[ "$TAG" == custom/* ]] || die "$TAG is not a release tag; was the plan step skipped?"
mode=""
[[ "$dry_run" != true ]] || mode=", dry run"
summary "### Publish $TAG ($VERSION)${resume:+, resuming}$mode"
summary ""

export GIT_COMMITTER_NAME="${CUSTOM_COMMITTER_NAME:-github-actions[bot]}"
export GIT_COMMITTER_EMAIL="${CUSTOM_COMMITTER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
fork_url="https://github.com/$fork.git"
push_url="$fork_url"
auth=()
if [[ -n "${PUSH_SSH_KEY:-}" ]]; then
  # A write deploy key: a ruleset can list deploy keys as bypass actors.
  ssh_dir="$(mktemp -d)"
  trap 'rm -rf "$ssh_dir"' EXIT
  printf '%s\n' "$PUSH_SSH_KEY" > "$ssh_dir/key"
  chmod 600 "$ssh_dir/key"
  # GitHub's host keys from its API over TLS, not from an unauthenticated keyscan.
  curl -fsS https://api.github.com/meta \
    | python3 -c 'import json, sys; [print("github.com", key) for key in json.load(sys.stdin)["ssh_keys"]]' \
    > "$ssh_dir/known_hosts"
  export GIT_SSH_COMMAND="ssh -i $ssh_dir/key -o IdentitiesOnly=yes -o UserKnownHostsFile=$ssh_dir/known_hosts -o StrictHostKeyChecking=yes"
  push_url="git@github.com:$fork.git"
elif [[ -n "${PUSH_TOKEN:-}" ]]; then
  basic="$(printf 'x-access-token:%s' "$PUSH_TOKEN" | base64 -w0)"
  echo "::add-mask::$basic"
  auth=(-c "http.https://github.com/.extraheader=AUTHORIZATION: basic $basic")
fi

# 1. The tag: annotated, never moved. plan.py recognises a re-run by Patches-Commit.
if [[ -n "$resume" ]]; then
  summary "- tag $TAG already exists for this build"
else
  message="Omnigent $VERSION

Built from $fork@$PATCHES_COMMIT (the patches branch) onto ${UPSTREAM_REPO:-omnigent-ai/omnigent}@$OSS_COMMIT.

Build-Id: $BUILD_ID
OSS-Commit: $OSS_COMMIT
Patches-Commit: $PATCHES_COMMIT
Image: $IMAGE"
  git -C "$repo" tag -a "$TAG" "$CUSTOM_COMMIT" -m "$message"
  summary "- tag $TAG on ${CUSTOM_COMMIT:0:12}"
  run git "${auth[@]}" -C "$repo" push --quiet "$push_url" "refs/tags/$TAG"
fi

# 2. The server image on GHCR.
if [[ "$dry_run" == true ]]; then
  summary "- dry run, would push the image \`$IMAGE\`"
else
  printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null
  if [[ -n "$resume" ]] && digest="$(docker buildx imagetools inspect "$IMAGE" --format '{{.Manifest.Digest}}' 2>/dev/null)"; then
    summary "- image $IMAGE already pushed ($digest)"
  else
    "$here/release/build-image.sh" "$out" --push --digest-file "$out/digest"
    digest="$(cat "$out/digest")"
    summary "- pushed $IMAGE ($digest)"
  fi
  python3 -I "$here/release/notes.py" set-digest --manifest "$out/release/manifest.json" \
    --notes "$out/notes.md" --digest "$digest"
fi

# 3. The GitHub release with the install set.
args=(release create "$TAG" -R "$fork" --verify-tag --title "$TAG ($VERSION)" --notes-file "$out/notes.md")
if [[ "$prerelease" == true ]]; then args+=(--prerelease); else args+=(--latest); fi
mapfile -t assets < <(find "$out/release" -maxdepth 1 -type f ! -name '.*' | sort)
if [[ "$dry_run" != true ]] && gh release view "$TAG" -R "$fork" >/dev/null 2>&1; then
  summary "- release $TAG already exists; not changing it"
else
  summary "- release $TAG with ${#assets[@]} assets$([[ "$prerelease" == true ]] && echo ", pre-release")"
  if [[ "$dry_run" == true ]]; then
    run gh "${args[@]}" "${assets[@]##*/}"
  else
    gh "${args[@]}" "${assets[@]}"
    summary "- https://github.com/$fork/releases/tag/$TAG"
  fi
fi

# 4. The fork's custom branch, last, so it only ever points at a released build.
#    Written only by this script; it moves sideways on every refresh.
old_custom="$(git ls-remote "$fork_url" refs/heads/custom | cut -f1)"
if [[ "$old_custom" == "$CUSTOM_COMMIT" ]]; then
  summary "- custom is already ${CUSTOM_COMMIT:0:12}"
else
  summary "- custom: ${old_custom:0:12} -> ${CUSTOM_COMMIT:0:12}"
  run git "${auth[@]}" -C "$repo" push --quiet \
    "--force-with-lease=refs/heads/custom:$old_custom" "$push_url" "$CUSTOM_COMMIT:refs/heads/custom"
fi
