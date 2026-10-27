#!/usr/bin/env bash
# Build the install set for one build of the series: host wheels, constraints,
# host scripts, manifest.json, release notes and custom-docs.md, plus the
# server image's build context.
#
#   custom/release/build.sh --tree <dir> --out <dir> [options]
#
# --tree DIR             a tree custom/scripts/build-custom.sh built (clean, at
#                        the series tip); its version files are stamped and restored
# --out DIR              output: DIR/release/ (the release assets), DIR/image/
#                        (server image context), DIR/notes.md, DIR/build.env
# --tag TAG              release tag (default build/<build-id>, not a release)
# --patches-commit SHA   patches-branch commit the build is from (default: HEAD
#                        of the checkout this script is in)
# --fork REPO            repository the patches branch, custom and the releases
#                        live on (default $FORK_REPO, else Desidero/omnigent)
# --image NAME           server image name (default $IMAGE_NAME, else
#                        ghcr.io/desidero/omnigent-server)
# --previous-manifest F  manifest.json of the previous release, for the notes
# --note TEXT            extra line for the notes header (e.g. the pull request)
#
# Version: <upstream version>+oss<BASE:8>.p<patches commit:7>, e.g.
# 0.20.0.dev0+oss65be0f24.p0123abc. Needs uv, node 22 and pnpm (web UI).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # custom/
tree="" out="" tag="" patches_commit="" previous="" note=""
fork="${FORK_REPO:-Desidero/omnigent}"
image_name="${IMAGE_NAME:-ghcr.io/desidero/omnigent-server}"
# Extras whose dependencies constraints.txt pins too (server: postgres).
constraint_extras=(postgres vault)

usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit "${1:-0}"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tree) tree="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --tag) tag="$2"; shift 2 ;;
    --patches-commit) patches_commit="$2"; shift 2 ;;
    --fork) fork="$2"; shift 2 ;;
    --image) image_name="$2"; shift 2 ;;
    --previous-manifest) previous="$2"; shift 2 ;;
    --note) note="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done
[[ -n "$tree" && -n "$out" ]] || usage 2
tree="$(cd "$tree" && pwd)"
mkdir -p "$out"
out="$(cd "$out" && pwd)"

base="$(tr -d '[:space:]' < "$here/BASE")"
custom="$(git -C "$tree" rev-parse HEAD)"
[[ "$(git -C "$tree" rev-list --count "$base..HEAD")" -gt 0 ]] \
  || { echo "error: $tree is not a build of the series on BASE ${base:0:12}" >&2; exit 2; }
[[ -z "$(git -C "$tree" status --porcelain --untracked-files=no)" ]] \
  || { echo "error: $tree has local changes; build from a clean tree" >&2; exit 2; }
dirty=""
if [[ -z "$patches_commit" ]]; then
  patches_commit="$(git -C "$here" rev-parse HEAD)"
  [[ -z "$(git -C "$here" status --porcelain -- BASE series patches release)" ]] || dirty=.dirty
fi

upstream_version="$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$tree/pyproject.toml")"
build_id="oss${base:0:8}.p${patches_commit:0:7}${dirty}"
version="${upstream_version}+${build_id}"
[[ -n "$tag" ]] || tag="build/$build_id"
image="$image_name:${tag//\//-}"
echo "building $version ($tag) from custom ${custom:0:12}" >&2

rel="$out/release"
rm -rf "$rel" "$out/image"
mkdir -p "$rel" "$out/image"

# Pinned dependencies from the tree's uv.lock, exported before the version stamp.
extra_args=()
for extra in "${constraint_extras[@]}"; do extra_args+=(--extra "$extra"); done
(cd "$tree" && uv export --frozen --no-dev --no-emit-project --no-hashes -q "${extra_args[@]}") \
  | grep -v '^-e ' > "$rel/constraints.txt"

# Stamp the build's version with upstream's own lockstep tool, build, restore.
restore() { git -C "$tree" checkout --quiet -- . ; }
trap restore EXIT
(cd "$tree" && uv run --quiet --no-project --with packaging python scripts/update_versions.py \
  pre-release --new-version "$version" >/dev/null 2>"$out/stamp.log") \
  || { cat "$out/stamp.log" >&2; exit 1; }
rm -f "$out/stamp.log"
grep -qxF "VERSION = \"$version\"" "$tree/omnigent/version.py" \
  || { echo "error: the version stamp did not reach omnigent/version.py" >&2; exit 1; }
OMNIGENT_BUILD_WEB_UI=1 uv build --wheel -q -o "$rel" "$tree"
uv build --wheel -q -o "$rel" "$tree/sdks/python-client"
uv build --wheel -q -o "$rel" "$tree/sdks/ui"
rm -f "$rel/.gitignore" # uv build marks its output folder ignored
restore
trap - EXIT

for file in install-host.sh upgrade-host.sh check-host.sh host-common.sh hostlib.py; do
  cp "$here/release/$file" "$rel/"
done
chmod +x "$rel"/*.sh

# Series list (with patch ids) for the manifest, then the manifest itself.
python3 -I "$here/release/notes.py" series --custom "$here" > "$out/series.json"
python3 -I "$here/release/hostlib.py" manifest --dir "$rel" --tag "$tag" --commit "$custom" \
  --image "$image" --build-id "$build_id" --oss-commit "$base" --patches-commit "$patches_commit" \
  --patches-repo "$fork" --fork-repo "$fork" --series-json "$out/series.json"

notes_args=(render --manifest "$rel/manifest.json" --tree "$tree" --custom "$here"
  --fork "$fork" --notes "$out/notes.md" --docs "$rel/custom-docs.md")
[[ -z "$previous" ]] || notes_args+=(--previous-manifest "$previous")
[[ -z "$note" ]] || notes_args+=(--note "$note")
python3 -I "$here/release/notes.py" "${notes_args[@]}"

# Server image context: the Dockerfile, the entrypoint from the tree, the wheels.
cp "$here/release/server.Dockerfile" "$out/image/"
cp "$tree/deploy/docker/entrypoint.py" "$out/image/"

cat > "$out/build.env" <<EOF
VERSION=$version
BUILD_ID=$build_id
TAG=$tag
IMAGE=$image
CUSTOM_COMMIT=$custom
OSS_COMMIT=$base
PATCHES_COMMIT=$patches_commit
FORK_REPO=$fork
EOF
echo "built $out: $(cd "$rel" && ls | tr '\n' ' ')" >&2
