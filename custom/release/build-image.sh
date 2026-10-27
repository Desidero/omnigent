#!/usr/bin/env bash
# Build the server image from a folder custom/release/build.sh wrote.
#
#   custom/release/build-image.sh <out-dir> [--push] [--digest-file FILE]
#
# Tags the image with build.env's IMAGE (linux/amd64) and labels it with the
# OSS, patches-branch and custom commits; the source label links the GHCR
# package to the fork. Without --push it is loaded into the local
# Docker; with --push it goes to the registry and its digest is written to
# --digest-file. Needs docker with buildx.
set -euo pipefail

out="" push=0 digest_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --push) push=1; shift ;;
    --digest-file) digest_file="$2"; shift 2 ;;
    -h|--help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) [[ -z "$out" ]] || { echo "unexpected argument: $1" >&2; exit 2; }; out="$1"; shift ;;
  esac
done
[[ -n "$out" && -f "$out/build.env" ]] || { echo "usage: build-image.sh <out-dir> [--push]" >&2; exit 2; }
# shellcheck disable=SC1091
. "$out/build.env"

fork="${FORK_REPO:-Desidero/omnigent}"
metadata="$(mktemp)"
trap 'rm -f "$metadata"' EXIT
args=(--platform linux/amd64 -f "$out/image/server.Dockerfile" -t "$IMAGE"
  --label "org.opencontainers.image.title=omnigent-server"
  --label "org.opencontainers.image.description=Omnigent server with the patch series"
  --label "org.opencontainers.image.source=https://github.com/$fork"
  --label "org.opencontainers.image.url=https://github.com/$fork"
  --label "org.opencontainers.image.licenses=Apache-2.0"
  --label "org.opencontainers.image.version=$VERSION"
  --label "org.opencontainers.image.revision=$CUSTOM_COMMIT"
  --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  --label "io.github.desidero.omnigent.build-id=$BUILD_ID"
  --label "io.github.desidero.omnigent.oss-commit=$OSS_COMMIT"
  --label "io.github.desidero.omnigent.patches-commit=$PATCHES_COMMIT"
  --label "io.github.desidero.omnigent.release-tag=$TAG"
  --metadata-file "$metadata")
if [[ "$push" == 1 ]]; then
  args+=(--push)
else
  args+=(--load)
fi
docker buildx build "${args[@]}" "$out"
digest="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("containerimage.digest", ""))' "$metadata")"
echo "built $IMAGE${digest:+ ($digest)}"
if [[ -n "$digest_file" ]]; then
  echo "$digest" > "$digest_file"
fi
