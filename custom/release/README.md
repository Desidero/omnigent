# Release tooling

> **Status: pending cutover.** The workflow below does not run yet; see
> [Cutover](../README.md#cutover).

The workflow (`.github/workflows/custom-release.yml` on the `patches` branch)
uses these scripts to turn a build of the series into a release on this fork;
the host scripts then install a release on a machine that runs the Omnigent
host service.

| File | What |
| --- | --- |
| `build.sh` | From a tree `scripts/build-custom.sh` built: stamp the version, build the three wheels (web UI bundled), export `constraints.txt` from `uv.lock`, copy the host scripts, write `manifest.json`, the notes and `custom-docs.md`, and the image context |
| `server.Dockerfile`, `build-image.sh` | The server image, from the same wheels and constraints |
| `plan.py` | Picks the release tag and finds the previous release |
| `notes.py` | Release notes, `custom-docs.md`, the series list for the manifest |
| `publish.sh` | Pushes the tag and the image, creates the release, then updates `custom` |
| `install-host.sh` | Installs a release folder's wheels as the `omnigent` uv tool |
| `upgrade-host.sh` | Installs a release on a host, applies the service environment, restarts and verifies; `--rollback` |
| `check-host.sh` | Read-only drift check of a host against its release |
| `host-common.sh`, `hostlib.py` | Shared shell helpers; stdlib Python helper (manifest, env files, systemd drop-ins, launchd plists) |
| `tests/` | `python3 -m unittest discover -s custom/release/tests` |

## Building one locally

From a worktree of the `patches` branch:

```bash
custom/scripts/build-custom.sh --worktree /tmp/custom-tree
custom/release/build.sh --tree /tmp/custom-tree --out /tmp/install-set
custom/release/build-image.sh /tmp/install-set     # optional: loads the image locally
```

Needs `uv`, Node 22 and pnpm (the web UI is built into the wheel), and Docker
with buildx for the image. A local build gets the tag `build/<build-id>`,
with the checkout's commit as the patches commit and a `.dirty` build id
when `custom/BASE`, `custom/series`, `custom/patches/` or `custom/release/`
has uncommitted changes. `/tmp/install-set/release/` is the folder to
install.

## Why the image has its own Dockerfile

Upstream's `deploy/docker/Dockerfile` installs the package editable with
`uv pip install -e .`, which resolves dependencies afresh and ignores
`uv.lock`; that once shipped a Starlette release that broke file previews.
`server.Dockerfile` installs the release's own wheels with `constraints.txt`
instead, so the server runs the same bytes and the same dependency versions
the hosts get, and no build tools or Node are needed in the image. It keeps
upstream's runtime contract (entrypoint copied from the build's
`deploy/docker/entrypoint.py`, port 8000, `/data/artifacts`, the `/health`
check), so upstream's `docker-compose.yaml` runs it with
`OMNIGENT_IMAGE=ghcr.io/desidero/omnigent-server` and
`OMNIGENT_IMAGE_TAG=custom-<date>.<n>`. When upstream changes its runtime
stage (new system packages, environment), mirror it here.

## Publishing

`publish` runs after a push to `patches` that changes the series or the
release tooling (the list is in [What CI does](../README.md#what-ci-does)),
or on a manual run with `dry_run=false` on `patches`. In order, it:

1. checks the rebuilt commit equals the install set's;
2. pushes the annotated tag `custom/<date>.<n>` (message: version, both
   commits, `Patches-Commit:`, image), unless `plan.py` found this build's
   tag already, which makes it a resume;
3. pushes the image to GHCR and records its digest in the manifest and notes;
4. creates the release with the install set, unless it exists;
5. last, updates `custom` to the built commit (`--force-with-lease`), so it
   only ever points at a released build. It moves sideways on every refresh,
   which is why it is CI-owned and never a base for work.

It never moves a tag or edits a published release.

Tokens: the workflow token by default; `CUSTOM_DEPLOY_KEY` or
`CUSTOM_PUBLISH_TOKEN` in the `custom-release` environment replace it for
the pushes and the release only if GitHub refuses it. Why, with the GitHub
docs, is in [Tokens](../README.md#tokens). To add the fallbacks:

- **Deploy key** (for the pushes, when the ruleset refuses the workflow
  token): `ssh-keygen -t ed25519 -N '' -f /tmp/custom-deploy`, add the public
  half as a deploy key with write access
  (`gh repo deploy-key add /tmp/custom-deploy.pub -R Desidero/omnigent -w -t custom-release`),
  add it as a `DeployKey` bypass actor on the `custom` and `custom/**`
  rulesets, store the private half
  (`gh secret set CUSTOM_DEPLOY_KEY -R Desidero/omnigent -e custom-release < /tmp/custom-deploy`)
  and delete both files.
- **Token** (for the release, or the pushes without a deploy key, when the
  workflow-file check refuses the workflow token): a fine-grained token,
  resource owner the fork's owner, repository access only this fork,
  permissions Contents and Workflows read and write; or a GitHub App's
  installation token. `gh secret set CUSTOM_PUBLISH_TOKEN -R Desidero/omnigent -e custom-release`.
  A token acts as its owner, so on the ruleset it bypasses as that user's
  role.

**GHCR:** the image is always pushed with the workflow token
(`packages: write`). The first push creates
`ghcr.io/desidero/omnigent-server`, linked to this repository; it starts
private: make it public in its package settings, or log the server in with
a token that has `read:packages`. If the package already exists and is not
linked here, grant this repository Write under "Manage Actions access" in
the package settings
([container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)).

**Try it with a dry run before anything merges**, because the first merge
into `patches` that touches the series publishes for real. A manual run is a
dry run unless you pass `dry_run=false` on `patches`, and a run on any other
ref is always dry:

```bash
gh workflow run custom-release.yml -R Desidero/omnigent --ref patches
gh workflow run custom-release.yml -R Desidero/omnigent --ref <branch>   # forced dry
```

A pull request's run shows the same build and notes without a publish step.
The manual run needs the workflow on the default branch (or one earlier run
of it) ([workflow_dispatch](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)).

## Releases

Each publish creates a **pre-release** unless the manual run sets
`prerelease=false`. When a release has run somewhere safe and goes to
production, mark it as the full release:

```bash
gh release edit custom/2026-10-27.1 -R Desidero/omnigent --prerelease=false --latest
```

Releases and tags stay; drop old pre-releases by hand if they pile up
(`gh release delete <tag> -R Desidero/omnigent`, keeping the tag).

## Installing a release on a host

The host scripts run with bash 3.2 and BSD tools (macOS) as well as Linux
(systemd user unit `omnigent-host.service`). Each host needs a host config
folder `<hosts-dir>/<host>/` (may be empty) from your own deployment config:

- `systemd/*.conf` (Linux): drop-ins installed into
  `~/.config/systemd/user/omnigent-host.service.d/`. The script owns that
  directory; any other `.conf` there is moved to
  `~/omnigent-deploy/backups/<time>/`.
- `host.env` (optional, non-secret): `KEY=VALUE` lines for the service
  environment; `~` and `$HOME` expand; `RELEASE_EXTRA_PATH=dir:dir` adds PATH
  entries (`PATH` itself is generated).
- A `TODO(user)` marker in either makes `upgrade-host.sh` refuse that host.

Secrets go in `~/.omnigent/secrets/host.env` on the host (mode 600, plain
`KEY=VALUE`), never in the config: systemd reads it with `EnvironmentFile=`,
and on macOS it is merged into the launchd plist.

```bash
# First time, or to bootstrap the scripts on a host:
gh release download custom/2026-10-27.1 -R Desidero/omnigent -D /tmp/rel   # or curl the assets
bash /tmp/rel/check-host.sh --host <name> --release /tmp/rel
bash /tmp/rel/upgrade-host.sh --host <name> --hosts-dir <hosts-dir> /tmp/rel

# Later releases, straight from GitHub (gh if logged in, else HTTPS):
bash ~/omnigent-deploy/current/upgrade-host.sh --host <name> --release custom/2026-11-02.1

# Check, roll back:
bash ~/omnigent-deploy/current/check-host.sh --host <name>
bash ~/omnigent-deploy/current/upgrade-host.sh --host <name> --rollback
```

A pull request's install set installs the same way from its `release/`
subfolder.

`--dry-run` prints every action first; `--no-restart` installs and
configures but leaves the running service alone. `upgrade-host.sh` is
idempotent. It:

1. verifies the release's sha256s against `manifest.json`, checks the host
   config for `TODO(user)`, and requires `rg` on the service PATH;
2. copies the release to `~/omnigent-deploy/<date>.<n>/` (the tag's last
   part) with the host configs it used, so later runs and `--rollback` find
   them, and installs the wheels with `install-host.sh` unless the installed
   tool already reports the release's commit (`--reinstall` forces it);
3. points `~/omnigent-deploy/current` at it and `previous` at the release it
   replaces;
4. applies the service environment (drop-ins plus a generated
   `90-omnigent-release.conf` on Linux; the plist's `EnvironmentVariables` on
   macOS), backing up what it replaces;
5. restarts detached from the host's own process tree (`systemd-run --user`
   on Linux, `bootout` + `bootstrap` in a new session on macOS), waits for
   `Connected as` in the host log, and checks the commit the service binary
   reports. Results go to `~/omnigent-deploy/rollout.log`, details to
   `upgrade.log`.

The installed version is always read with `python -I -m omnigent --version`
from `/`, so running the scripts from inside an Omnigent checkout cannot make
them report the checkout's version instead.

Every host also gets `OMNIGENT_NO_UPDATE_CHECK=1` (upstream's update notice
would offer stock PyPI wheels), a PATH resolved from a clean login shell, and
shell leftovers (`SSH_AUTH_SOCK`, `TERM*`, terminal-app variables) removed.
After `omnigent host enable`, which rewrites the service definition from the
current shell, rerun `upgrade-host.sh` with the current release.

## Installing the server

With upstream's Docker Compose setup (`deploy/docker/` from the release's
tag): back up the database, set `OMNIGENT_IMAGE=ghcr.io/desidero/omnigent-server`
and `OMNIGENT_IMAGE_TAG=custom-<date>.<n>` in `.env`, `docker compose pull
omnigent && docker compose up -d omnigent`, and check `/health` and that
`/v1/info` reports the release's `server_version`. Roll back by restoring the
previous tag in `.env` (and the database dump if the newer version migrated
it).
