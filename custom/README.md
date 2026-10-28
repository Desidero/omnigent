# Omnigent with the patch series

This folder is the reason the `patches` branch exists. The branch is
[Omnigent](https://github.com/omnigent-ai/omnigent) exactly as upstream has
it at `custom/BASE`, plus this folder and one workflow. The patch series it
holds is a set of candidate contributions to Omnigent, kept as patch files
until they land upstream, and the workflow builds and releases Omnigent with
them.

> This layout replaced the separate `Desidero/omnigent-patches` repository
> (now archived), whose content was imported here in one commit. It is live
> since 2026-10-28: the first release is `custom/2026-10-28.1`. How it was set
> up is in [Cutover](#cutover).

Each change here is meant to go upstream. Until it does, it lives here as a
plain patch file, so you can read it, apply it to your own Omnigent checkout,
or take just the pieces you want. When a change merges upstream, its patches
are dropped from the series.

## Layout

| Path | What |
| --- | --- |
| `custom/BASE` | The upstream commit the series applies to. The branch merges upstream up to exactly this commit. |
| `custom/series` | The patches in apply order, grouped into named series (`# series: <name>`). A `# needs: <name>` line means that series expects another one first. |
| `custom/patches/*.patch` | `git format-patch` files, one per commit, named `<series>--<subject>.patch`. |
| `custom/proposals/<series>/` | The draft upstream PR description (`PR.md`), a draft issue where useful (`issue.md`), and `evidence/` (screenshots and logs to attach). `_reviews/` and `_watch/` hold review notes and drafts for upstream threads we only follow. |
| `custom/scripts/` | Build, export, check, refresh and the upstream-workflow switch (below). |
| `custom/release/` | Install set, server image, release publishing, host install scripts ([`release/README.md`](release/README.md)). |
| `custom/tracker.yaml` | Upstream links and relationships per series, for `scripts/tracker.py`. |
| `.github/workflows/custom-release.yml` | The only workflow of ours. |
| `.github/actions/custom-build-tree/` | Its composite action: build the series into a worktree. |

Upstream already uses a top-level `patches/` (npm patch-package), which is
why everything of ours is under `custom/` and the two `.github` paths start
with `custom-`.

### The tree rule

**Nothing else on `patches` may differ from upstream.** The branch's tree,
minus `custom/`, `.github/workflows/custom-*` and `.github/actions/custom-*/`,
must equal the tree of the commit in `custom/BASE`, and `custom/BASE` must be
an ancestor of the branch (and, in CI, of upstream's `main`).
`scripts/check-tree.sh` checks it and CI runs it on every pull request, so a
change to an upstream file can only arrive as a patch under
`custom/patches/`. An explicit `BASE` plus this check is clearer than
deriving the base from history: the merge of upstream and the `BASE` bump
travel together in one pull request and the check proves they agree.

## How a change gets in

```
develop on a working branch  ->  export to patch files  ->  pull request into patches
  (build-custom.sh)               (export.sh, check.sh,     (CI: tree rule, apply, docs,
                                   check-tree.sh)            tsc, tests, install set)
        -> merge  ->  CI: tag custom/<date>.<n>, GHCR image, pre-release
                      with the install set, then move custom to it
```

Merging a pull request into `patches` is the only way the series changes.
`patches` is never rebased or force-pushed; an upstream refresh is a pull
request too (a merge of upstream plus the refreshed patches). `custom` and
the `custom/*` tags are written only by the workflow.

## Developing a change

Work in a worktree of the `patches` branch (or a branch cut from it). The
scripts default to the clone they are checked out in; `--repo` or
`$OMNIGENT_REPO` points them elsewhere. The clone needs upstream as a remote
(`upstream` below). Upstream's top-level `patches/` folder makes a bare
`patches` ambiguous to git commands that take a revision: write
`refs/heads/patches` or `origin/patches`, or end the arguments with `--`.

1. **Build a working branch** from the series:
   `custom/scripts/build-custom.sh work/<topic>`. The commits are
   reproducible: the same `BASE` and patch files give the same commit ids
   everywhere (fixed committer, committer date = author date), so the branch
   matches what CI builds and what `custom` holds.
2. **Change it** like any branch: add commits, amend or `git rebase -i` the
   patch you are fixing (keep fixups squashed into the patch they fix), drop
   a patch that landed upstream. Develop a fix headed upstream on a
   contribution branch cut from `upstream/main`, never from `custom`, and
   cherry-pick it here. Try it with the repo's tests, or install the pull
   request's build (below).
3. **Export**, on a branch cut from `patches`:
   `custom/scripts/export.sh work/<topic> upstream/main` rewrites
   `custom/BASE`, `custom/series` and `custom/patches/`. Series are matched by
   each commit's subject; a new commit joins the previous commit's series
   with a warning, so move it in `custom/series` if it belongs elsewhere and
   run the export again. `# needs:` lines and other comments in a series are
   kept. `BASE` must not move here; moving it is a [refresh](#refreshing-the-base).
4. **Check**: `custom/scripts/check.sh --custom work/<topic>` applies the
   series in a throwaway worktree, runs the [docs rule](#docs-rule), a quick
   sanity check (no conflict markers, changed Python and JSON parse) and
   confirms the result has exactly your branch's tree. After committing,
   `custom/scripts/check-tree.sh` confirms the [tree rule](#the-tree-rule).
5. **Open a pull request into `patches`**, from a branch named
   `series/<topic>` (`refresh/<date>` for a refresh), with the regenerated files, plus
   `custom/proposals/<series>/PR.md` for a new series and a fixup to the
   index (`docs/custom/README.md`, series `custom-docs-index`).

Commit on `patches` branches without upstream's pre-commit hooks
(`git commit --no-verify` if you installed them): they would rewrite
whitespace in the patch files, which must stay byte for byte as exported.

To try a pull request before it merges, download its `install-set-<build>`
artifact from the PR's `custom-release` run (`gh run download <run-id> -R
Desidero/omnigent -n install-set-<build> -D /tmp/set`). It unpacks to
`release/` (the assets), `image/`, `notes.md` and `build.env`; install the
`release/` folder like a release
(`bash /tmp/set/release/upgrade-host.sh --host <name> --hosts-dir <dir> /tmp/set/release`,
see [`release/README.md`](release/README.md)).

### Refreshing the base

`custom/scripts/refresh.sh` does the whole refresh on a branch cut from
`patches`:

```bash
git fetch origin upstream
git switch -c refresh/$(date -u +%F) origin/patches
custom/scripts/refresh.sh                 # merges upstream/main, rebases the series
# on a conflict: resolve in the worktree it names, `git rebase --continue`, then
custom/scripts/refresh.sh --continue
git push origin refresh/$(date -u +%F)    # and open the pull request into patches
```

It merges `upstream/main` into the branch (only upstream paths change, so the
merge does not conflict), builds the old series as `work/refresh-<sha>`,
rebases it onto the new upstream commit (`rerere` remembers resolutions;
patches that landed upstream drop out as empty), exports, runs `check.sh` and
`check-tree.sh`, and commits `custom/`. Remove dropped series from the index
patch in the same pull request. The pull request moves `BASE`, so CI runs
the tests of every patch.

The merge brings upstream's workflow changes onto the branch, so pushing it
needs a credential that may write workflow files (`gh auth login` asks for
the `workflow` scope). There is no scheduled job that opens refresh pull
requests: a pull request the workflow token opens gets no CI runs without an
approval ([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)),
its pushes of upstream's workflow files would be refused, and a conflict
needs a person anyway.

### Applying a series to your own checkout

```bash
git am -3 $(custom/scripts/series-files.sh --needs toast-safe-area)
```

`series-files.sh` prints a series' files in apply order (a `(continued)`
fixup after the patch it fixes, which a shell glob gets wrong) and, with
`--needs`, the series it needs first; `--all` prints the whole series. If
your branch is ahead of `BASE` and a patch conflicts, `-3` falls back to a
three-way merge; resolve it and `git am --continue`. `git config
rerere.enabled true` means you resolve each conflict only once.

## What CI does

`.github/workflows/custom-release.yml`, on this fork only:

| Event | Jobs |
| --- | --- |
| Pull request into `patches` | `apply` (the required check: tree rule, build with `build-custom.sh`, `check.sh --tree`, unit tests of `scripts/` and `release/`, test selection), `web` (`tsc -b` and the selected vitest files), `python` (the selected pytest files), `package` (the install set as an artifact, the server image built and smoke-tested but not pushed; the notes go to the job summary), `upstream-workflows` (below) |
| Push to `patches` that changes `custom/BASE`, `custom/series`, `custom/patches/**`, `custom/release/**`, `custom/scripts/build-custom.sh`, `check.sh`, `check-tree.sh` or `select-tests.py`, the workflow, or its action | The same, then `publish`: tags the build, pushes the image to GHCR, creates the pre-release and then moves `custom` to it. A merge that only changes docs, proposals or the tracker makes no release. |
| Manual run (`workflow_dispatch`) | Inputs: `dry_run` (default true: everything, with `publish` printing the pushes, tag, image push and release instead of doing them; a run on any ref other than `patches` is always dry), `prerelease` (default true; false marks a real run's release as the latest full release), `all_tests` (default false; true runs the tests of every patch) |
| Daily schedule | Only `upstream-workflows`. Schedules run from the default branch only, so this needs `patches` to be the default branch. |

Test selection (`scripts/select-tests.py`): for each patch whose content
changed (by `git patch-id`, so a refresh that only moves line numbers doesn't
count), the touched test files, plus `tests/**/test_<module>.py` and
`test_<module>_*.py` for each touched Python module, and for the web UI the
touched `*.test.ts(x)` files and `vitest related` on the touched sources. A
pull request compares with its base; a release compares with the patches
commit of the previous `custom/*` tag. A moved `BASE`, no previous release
(the first one), or `all_tests` selects every patch. Browser, live-server and
benchmark lanes stay with upstream's CI.

Repository variables `UPSTREAM_REPO` and `IMAGE_NAME` override
`omnigent-ai/omnigent` and `ghcr.io/desidero/omnigent-server`. The fork is
always the repository the workflow runs in.

### Upstream's workflows

This branch carries upstream's `.github/workflows/` (92 workflow files at
`BASE` 65be0f2468, plus their scripts), and `main` mirrors upstream. Once
Actions is on, they would run here: at that `BASE`, 32 run on `pull_request`
and 13 on `pull_request_target` with no branch filter, so every pull request
into `patches` would start them, and `pull_request_target` runs with the
default branch's code and a write token; 18 run on a schedule; 12 run on
`push`, all limited to `main`, `release/v*` or `v*` tags, so pushes of
`patches`, `custom`, `custom/*` tags and contribution branches match none,
but a push of `main` does. Our workflow uses none of them.

- `scripts/disable-upstream-workflows.sh` lists the repository's workflows
  through the API and disables every one whose file is not
  `.github/workflows/custom-*` (`--cancel-runs` also cancels their queued and
  running runs; `--dry-run` prints). GitHub-managed workflows (`dynamic/…`)
  are left alone. Disabling is per workflow file, across all branches, and
  survives later pushes.
- The `upstream-workflows` job runs it on every run of ours and daily, so a
  workflow a refresh brings in is switched off soon after it appears.
- **Residual risk:** GitHub can only disable a workflow it has registered,
  and a new file is registered by the event that first runs it. A brand-new
  upstream workflow can therefore run once: a `pull_request` one on the
  refresh pull request that adds it, a `push` one on the fast-forward of
  `main` that adds it. Run the script right after either (it also cancels
  such runs). The exposure is small: default workflow permissions on this
  fork are read-only, workflows triggered by the workflow token start nothing,
  and the repository has no Actions secrets unless you add the fallbacks
  below, kept in an environment that only `publish` names.
- Scheduled workflows run only on the default branch, are disabled by
  default when a public repository is forked, and are disabled after 60 days
  without repository activity
  ([events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
  [disabling workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)).
  Whatever the default branch, upstream's schedules are on it, so they are
  disabled like the rest rather than relied on to stay off.

### Tokens

The workflow tries to do everything with the built-in workflow token:
`actions: write` to switch workflows off, `packages: write` for GHCR,
`contents: write` for the tag, the `custom` update and the release. What the
docs say, and the fallbacks for what may not work:

- The workflow token can never be granted the `workflows` permission: it is
  not among the
  [`permissions` keys](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions).
- **Releases:** creating one is refused without that permission "if the
  commit identified by target_commitish … adds or modifies any file under
  .github/workflows/ relative to the repository's default branch"
  ([create a release](https://docs.github.com/en/rest/releases/releases#create-a-release)).
  No patch touches `.github/`, so a built commit adds or modifies no workflow
  relative to `patches`; with `patches` as the default branch this should
  pass. With `main` as the default branch it would fail whenever `main` has
  moved past `BASE`.
- **Branch and tag pushes:** the same check applies, but the docs describe
  only the App permission (Workflows write for `git/refs`,
  [App permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps)).
  Community reports say the comparison is with the default branch or with
  existing branch tips, not whether the commits already exist in the
  repository ([#35410](https://github.com/orgs/community/discussions/35410),
  [#151442](https://github.com/orgs/community/discussions/151442), where a tag
  on a commit already on `main` was refused). Built commits match `patches`'
  workflows except for lacking ours, so the push should pass. Untested: this
  fork pushes with the deploy key instead (next point).
- **Rulesets:** a ruleset can name bypass actors by repository role, team,
  GitHub App, deploy key or (since 2026-05) user
  ([creating rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository),
  [REST](https://docs.github.com/en/rest/repos/rules),
  [changelog](https://github.blog/changelog/2026-05-07-repository-rulesets-user-bypass-and-branch-renaming/)).
  Adding the GitHub Actions app (actor type `Integration`) is refused with a
  422 on a repository a user owns ("must be part of the ruleset source or
  owner organization"; confirmed on this fork), and nothing in the docs says
  workflow-token pushes bypass rulesets. So this fork's `custom` and
  `custom/**` rulesets name deploy keys as the bypass, and the pushes use
  `CUSTOM_DEPLOY_KEY`.
- **Fallbacks**, as secrets of the `custom-release` environment (limit it to
  the `patches` branch); `publish` uses them only when they are set:
  `CUSTOM_DEPLOY_KEY`, the private half of a deploy key with write access,
  listed as a `DeployKey` bypass actor on the ruleset, used for the `custom`
  and tag pushes over SSH; `CUSTOM_PUBLISH_TOKEN`, a fine-grained token
  (this repository only; Contents and Workflows read and write) or a GitHub
  App token, used for the pushes (when there is no deploy key) and the
  release. GHCR always uses the workflow token: fine-grained tokens cannot
  push packages.

Pushes and releases made with the workflow token start no workflow runs
([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token));
with a fallback they do, but no workflow of ours or upstream's (once
disabled) listens for `custom`, `custom/*` tags or releases.

## Cutover

Done on 2026-10-28, in this order:

1. Pushed the `patches` branch and made it the default branch, so the manual
   run button and the daily job work, and built commits add or modify no
   workflow relative to the default branch.
2. Disabled upstream's 92 workflows with
   `custom/scripts/disable-upstream-workflows.sh` while Actions was still off
   (the API allows it), turned Actions on, and ran the script again with
   `--cancel-runs`. Nothing of upstream's ran.
3. Rulesets: `patches` takes pull requests only (the `apply` check, merge
   commits only, so a refresh keeps its upstream parent; no force push or
   deletion); `custom` and tags `custom/**` allow updates, creations and
   deletions only by repository admins and deploy keys. Naming the GitHub
   Actions integration as a bypass actor is refused on a user-owned
   repository ("must be part of the ruleset source or owner organization"),
   so the pushes use the `CUSTOM_DEPLOY_KEY` fallback: a write deploy key
   whose private half is a secret of the `custom-release` environment, which
   only the `patches` branch may use.
4. A dry run, then the first real release by a manual run with
   `dry_run=false`. The tag and `custom` went out over the deploy key; the
   release was created with the workflow token, and the image pushed with it
   to `ghcr.io/desidero/omnigent-server`.
5. Closed the old repository's pull request and archived it.

## Releases

- **Tag** `custom/<YYYY-MM-DD>.<n>` on this fork, an annotated tag on the
  built commit, `n` counting from 1 per UTC day. Tags are never moved or
  reused: a re-run of the same build resumes its tag, anything else gets the
  next number. The date says how old a build is and sorts; the `custom/`
  prefix keeps it apart from upstream's version tags.
- **Version** `<upstream version>+oss<BASE:8>.p<patches commit:7>`, a PEP 440
  local version, where the patches commit is the `patches` branch commit the
  build is from, e.g. `0.20.0.dev0+oss65be0f24.p0123abc` (illustrative). It
  is stamped at build time with upstream's `scripts/update_versions.py`, so
  the built tree keeps upstream's version files. `omnigent --version` prints
  it with the built commit:
  `omnigent 0.20.0.dev0+oss65be0f24.p0123abc (37f5c6e0, built …)`.
- **`custom`** points at the latest release's built commit: upstream at
  `BASE` plus one commit per patch, without `custom/` or our workflow.
- **Release** on this fork, a pre-release by default; mark the one that goes
  to production as the full release later. Assets: the `omnigent`,
  `omnigent-client` and `omnigent-ui-sdk` wheels, `constraints.txt` (every
  dependency pinned to the build's `uv.lock`), the host scripts,
  `manifest.json` (commits, version, image, sha256 of every file, the series
  with patch ids) and `custom-docs.md`.
- **Image** `ghcr.io/desidero/omnigent-server:custom-<date>.<n>` (the tag
  with `/` replaced by `-`, linux/amd64), built by
  `release/server.Dockerfile` from the same wheels and constraints, labelled
  with the version and the three commits.
- **Notes**: version, OSS base, patches commit, built commit and image; the
  changes since the previous release (series added, changed or dropped, base
  moved), from the two manifests; and the series index with its links pinned
  to the tag. `custom-docs.md` bundles, per series, the doc sections its
  patches add or change.

### Docs rule

Every patch ships its own usage docs in the same commit, in upstream's places
(`docs/`, the matching `feature-map/` recipe, or for API and telemetry details
`omnigent/server/API.md` and `designs/`). A patch with nothing to document,
such as an internal fix or a refactor, says why in a `Docs: none (<reason>)`
trailer. The last commit, series `custom-docs-index`, is
`docs/custom/README.md`: one `## <series>` section per series saying what it
changes, how to turn it on and where its docs are; adding, changing or
dropping a patch includes a fixup to it. `scripts/check.sh` enforces all
three: docs or the trailer on every patch, a section for every series, and
`custom-docs-index` last. The release notes carry that index, and
`custom-docs.md` the docs themselves.

## Tracker

`tracker.yaml` records, per series and per upstream change we only watch, the
upstream issue and PR links plus relationships (`carries`, `blocked_by`,
`superseded_by`, `related`, `conflicts`). `scripts/tracker.py OUT.html` joins
it with `series` and live GitHub state to produce a page with a drop list
(patches to remove on the next refresh), what waits on us, what waits on
maintainers, and a dependency graph. The table below is the hand-written
summary; the generated page is the live view.

## Patch index

Status is one of: **proposed** (not yet filed upstream; see `custom/proposals/`),
**issue open** (an upstream issue tracks it), or **PR open** (an upstream pull
request carries it, and the series holds a copy until it merges).

| Series | What it does | Status |
|---|---|---|
| `claude-config-dir` | claude-native and claude-sdk follow `CLAUDE_CONFIG_DIR` instead of assuming `~/.claude`. | PR open ([#9617](https://github.com/omnigent-ai/omnigent/pull/9617), carried copy) |
| `subscription-accounts` | Several Claude or Codex subscription logins per host: pick the account for a new session, switch a running session's account from the harness menu, accounts that share sessions through account tokens, and agents can start a child session on another account. Docs in `docs/providers.md`. Needs `claude-config-dir`. | issue open ([#503](https://github.com/omnigent-ai/omnigent/issues/503)) |
| `toast-safe-area` | Toasts stay below the iOS status bar and Dynamic Island. | PR open ([#11390](https://github.com/omnigent-ai/omnigent/pull/11390)) |
| `session-history-paging` | Agents can page through a session's history and list recently updated sessions. | proposed |
| `terminal-touch` | The terminal on phones and tablets: a Termux-style extra-keys row, long-press select, copy and paste, and native iOS clipboard reads for Paste. | PR open for the extra-keys row ([#6136](https://github.com/omnigent-ai/omnigent/pull/6136), carried copy with two iOS fixes); the rest proposed |
| `telemetry-attribution` | Exported spans carry the acting user (opt-in), the runner and the host. | PR open ([#11380](https://github.com/omnigent-ai/omnigent/pull/11380); issue [#10794](https://github.com/omnigent-ai/omnigent/issues/10794)) |
| `session-telemetry` | Every span of a turn carries the session's metadata (labels, project, agent, git, workspace, host) and the model and reasoning effort the turn ran with. | PR open ([#11384](https://github.com/omnigent-ai/omnigent/pull/11384), then [#11434](https://github.com/omnigent-ai/omnigent/pull/11434) stacked on it, draft) |
| `sidebar-attention-filter` | Sidebar filters for sessions that need you or changed recently. | proposed |
| `claude-sdk-web-tools` | claude-sdk agents can opt into Claude Code's WebSearch and WebFetch. | proposed |
| `run-suggested-commands` | A Run button on shell commands an agent suggests in chat. | proposed |
| `codex-native-shell-input` | A web `!command` runs as a Codex shell command instead of reaching the model as a prompt. Rides on `run-suggested-commands`, which carried the first version. | PR open ([#11396](https://github.com/omnigent-ai/omnigent/pull/11396)) |
| `claude-native-teammates` | Claude Code agent-team teammates show up as child sessions, and their deliveries no longer appear as raw `<teammate-message>` bubbles. | PR open ([#11388](https://github.com/omnigent-ai/omnigent/pull/11388) for the child sessions, [#11389](https://github.com/omnigent-ai/omnigent/pull/11389) for the deliveries; issue [#10745](https://github.com/omnigent-ai/omnigent/issues/10745)) |
| `claude-native-subagent-status` | Quiet sub-agents stay "running" until their turn actually ends. | proposed |
| `claude-native-coordinator-messages` | A parent agent's follow-ups appear in the sub-agent's chat. | proposed |
| `skip-gzip-binary-files` | Images and PDFs load in the file viewer again instead of failing with a 500. | PR open ([#10585](https://github.com/omnigent-ai/omnigent/pull/10585), carried copy) |
| `codex-native-mode-instructions` | Codex keeps its own Plan and Default mode instructions instead of having them replaced by the session's developer instructions. | proposed |
| `chat-item-labels` | Bracketed labels like `[Q2]` in chat become chips that preview the item they refer to; `~~[Q2]~~` closes it, and an Open items panel lists what is still open. Adds the labelling rules to agents' instructions. Needs `run-suggested-commands` and `codex-native-mode-instructions`. | proposed |
| `web-reconnect-shell-inputs` | A queued `!command` no longer stays stuck at the bottom of the chat after the connection drops. | PR open ([#11395](https://github.com/omnigent-ai/omnigent/pull/11395)) |
| `chat-item-comments` | Comment on labelled items and send the comments together as one structured message. Needs `chat-item-labels`. | proposed |
| `palette-new-chat-in-project` | The command palette can start a new chat in a chosen project. | PR open ([#11394](https://github.com/omnigent-ai/omnigent/pull/11394), draft; issue [#4409](https://github.com/omnigent-ai/omnigent/issues/4409)) |
| `new-chat-project-prompt` | When projects exist, starting a new session first asks which project, with a setting to turn it off. Needs `palette-new-chat-in-project`. | PR open ([#11397](https://github.com/omnigent-ai/omnigent/pull/11397), stacked on #11394; issue [#11083](https://github.com/omnigent-ai/omnigent/issues/11083)) |
| `session-labels-ui` | View and edit a session's labels in the web UI, delete labels through the API, and default labels per project. Needs `subscription-accounts`. | PR open ([#11398](https://github.com/omnigent-ai/omnigent/pull/11398) for the server, [#11399](https://github.com/omnigent-ai/omnigent/pull/11399) for the web UI (draft)) |
| `gateway-request-tags` | Requests to a Databricks Unity Gateway carry the session id and labels as request tags. Needs `chat-item-labels`. | proposed (issue drafted) |
| `chat-features` | Per-session toggles for chat features that need both an agent instruction and a renderer, starting with Run suggested commands. Needs several of the series above. | proposed |
| `pr-watch` | Watch a session's pull requests and wake the agent on failed checks, conflicts and reviews until they are green. Behind the default-off `pr_watch` feature flag. Needs `subscription-accounts`. | proposed |
| `claude-native-delegate-idle` | A Claude session stops showing Working, and takes follow-ups without Steer, once its turn ends while a background agent or teammate keeps running. Covers the default OSC status path and agent-team teammates, including lead turns a teammate's message starts. Needs `claude-native-teammates`. | PR open for the status-file part ([#10849](https://github.com/omnigent-ai/omnigent/pull/10849), carried copy); OSC and teammate parts proposed |
| `delete-stops-runner` | Deleting a session stops its host-launched runner once no remaining session uses it, instead of leaving the process running until its idle timeout. | PR open ([#11391](https://github.com/omnigent-ai/omnigent/pull/11391)) |
| `app-error-boundary` | A rendering error shows the error, its stack and a Reload button instead of a blank window. | proposed |
| `jump-to-latest` | A labelled Jump-to-latest pill, outside the scroll fade, that counts new replies landing below a reader who scrolled up. | proposed |
| `custom-docs-index` | `docs/custom/README.md`, the index of the series: what each changes, how to turn it on, and where its docs are. | custom only |


## Deploying your own

The releases are meant to be installed as they are: keep what is specific to
your machines (per-host service settings, secrets, runbooks) in a separate
repository of deployment config, and install a release tag with
`upgrade-host.sh --release <tag> --hosts-dir <your hosts/>` and the image tag
on the server. Production should run a tag that has already run somewhere
safe; [`release/README.md`](release/README.md) covers install, check and
rollback.

If you need changes that will never go upstream, add them as their own series
in a fork of this branch rather than rebasing private commits onto the build.

## Contributing

- Changes here are headed upstream, so they follow
  [Omnigent's contributing guide](https://github.com/omnigent-ai/omnigent/blob/main/CONTRIBUTING.md):
  sign off every patch's commit (`git commit -s`, the
  [DCO](https://developercertificate.org/)), and add tests.
- For a fix that is ready for upstream, open the PR against
  `omnigent-ai/omnigent` directly; it only needs to come here if it should be
  usable before it merges.
- To add or change a patch, follow [Developing a change](#developing-a-change)
  and send a pull request into `patches` with the regenerated files.
- Screenshots and logs in `proposals/*/evidence/` must come from a throwaway
  server with dummy data. Never include credentials, real user data or
  private hostnames.

## License

Omnigent is licensed under the Apache License 2.0 (the repository's
`LICENSE`), and the patches here are contributions to it under the same
license.
