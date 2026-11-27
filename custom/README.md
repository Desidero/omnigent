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
| `custom/BASE` | The upstream commit the series are cut from. The branch merges upstream up to exactly this commit. |
| `custom/patches/<series>/` | One directory per series: `NOTE.md` and its patches, `git format-patch` files named `NN-<subject>.patch`, one per commit, applied in name order. The patches are cut from the series' foundation: `BASE` plus the series it needs, nothing else. |
| `custom/patches/<series>/NOTE.md` | The series' [note](#notes): its name, a `Needs:` line (the series it is cut on top of, or `none`), a `Covers:` line, the text of its section in the index, and what must hold, the key code and the tests. |
| `custom/index-intro.md` | The text above the sections of the built index, `docs/custom/README.md`. |
| `custom/glue/<first>+<second>/` | [Glue](#glue) between two series that do not need each other: a `NOTE.md` with a `Joins:` line (the files where both insert at the same spot) and the reason, and optional patches that go on top of the two combined. Used only when both series are in a build. |
| `custom/parked/<series>/` | A series taken out of the build during a [refresh](#refreshing-the-base): its patches and note as they were, the note with a `Base:` line. Not built. |
| `custom/sets/<name>.txt` | Named [build sets](#named-build-sets): the series one kind of build holds, one per line. Without a set, a build is the whole series. |
| `custom/proposals/<series>/` | The draft upstream PR description (`PR.md`), a draft issue where useful (`issue.md`), and `evidence/` (screenshots and logs to attach). `_reviews/` and `_watch/` hold review notes and drafts for upstream threads we only follow. |
| `custom/scripts/` | Build, export, check, refresh and the upstream-workflow switch (below). `serieslib.py` is the one reader of the layout above and holds the build engine; the other scripts go through it. |
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

## How the series build

Each series is independent of the others except for the ones its `Needs:`
line names. Its patches are cut from its **foundation**, `BASE` plus the
series it needs (and what those need), so a series reads, applies and is
changed without the rest.

A build takes a selection of series (all of them, `--only`, or a
[set](#named-build-sets)) and

1. applies each chosen series **exactly** on its own foundation: no fuzz, no
   three-way fallback, and every file must come out with the blob id the
   patch recorded when it was exported;
2. **combines** the series by cherry-picking their commits onto `BASE` in a
   fixed order: a series after the series it needs, the second series of a
   [glue](#glue) pair after the first, otherwise by name;
3. adds one last commit, the **index**: `docs/custom/README.md`, written
   from the [notes](#notes) of the series in the build, one section each.

The combination is a three-way merge per commit, so two series that touch
the same file combine as long as they do not change the same or adjacent
lines. The committer, the dates (committer date = author date) and the merge
settings are pinned: the same `BASE`, patch files and selection give the same
commit ids on every machine with the same git. `check.sh` builds every series
alone on its foundation, every glue pair, and the whole build in two orders
(ties by name and by name reversed), which must give the same tree: nothing
may depend on the order of series that do not need each other.
`check.sh --pairs` also builds every two series that touch a common file, so
that any two of them are known to build together.

**Needs.** B needs A when B, written fresh against upstream, would import,
extend or rely at run time on what A adds; B is then cut on top of A, and a
build of B includes A. Touching the same file is not a need.

### Glue

Two series that do not need each other can still meet in a file. Where they
change lines that are apart, the build combines them and nothing has to be
said. Where they meet, `custom/glue/<first>+<second>/` says how they fit, and
it is used only in a build that holds both:

- **A join**, for insertions at the same spot (two rows at the end of one
  table, two helpers before the same function). `NOTE.md` lists the files on
  a `Joins:` line; in those files a conflict between the two is resolved by
  keeping both insertions whole, the first-named series' lines first. The
  name of the directory is therefore also an order: the second series is
  combined after the first. A join is declared per pair and per file, never
  assumed, and `check.sh` fails on a join the two series do not need.
- **A glue patch**, `NN-<subject>.patch` in the same directory, for what has
  to change when both are present. It is cut on top of the two series
  combined (joins made), applied exactly there, and cherry-picked after the
  second series. Export it with `export.sh --glue <first>+<second> <branch>`
  from a branch started with `build-custom.sh --only <first>,<second>
  --no-index`.

A join does not cover two series that edit the same lines: the build stops
and says so. Then one of them really needs the other, or one can leave those
lines alone (`session-labels-ui` no longer rewords a comment that
`subscription-accounts` rewords).

`NOTE.md` starts with `# <first>+<second>`, then the `Joins:` line if any,
then says what the two series add at that place and that neither uses the
other.

### Notes

`custom/patches/<series>/NOTE.md` is what a reader needs before the patches,
and what whoever rebases the series or resolves a conflict in it has to keep
true. At most 60 lines:

```markdown
# <series>

Needs: <series>, <series>        (or: none)
Covers: <hash>

One paragraph: what the series changes for the user.

- **Turn on:** how, or "on by default".
- **Docs:** where its usage docs are, or "none (<reason>)".
- **Upstream:** the branch it is proposed from, its issue or pull request as a full link.

## Must hold

- A behaviour the series guarantees, as a user or caller sees it.

## Key code

- `path/the/series/changes.py`: `symbol`, `another_symbol`

## Tests

- `tests/path/test_x.py::test_name`
```

- The part between `Covers:` and `## Must hold` is the series' section of
  the index, word for word. Links there are relative to `docs/custom/` in
  the built tree. Issues and pull requests are written as full links.
- **Must hold** lists behaviours, not code. A bullet that is a guess starts
  with `TODO(owner):`, so that it gets confirmed instead of trusted.
- **Key code** names files the series changes and symbols in them;
  **Tests** names test files, with `::<test name>` where it helps. `check.sh`
  looks each one up in the series' own build (its foundation plus its
  patches), so a rename shows up as a stale note. A series without code or
  tests says `- none (<reason>)`.
- **Covers** is a hash of the lines the patches add and remove (not of their
  context, so re-cutting a series on another foundation keeps it). When it
  no longer matches, the series does something else than the note was
  written for: read the note again, fix it, then
  `custom/scripts/serieslib.py covers --write <series>`. `export.sh` says
  when that is due and never updates the line itself.

`custom/scripts/serieslib.py index` prints the index a build would hold.

## How a change gets in

```
develop a series on its branch  ->  export it to patch files  ->  pull request into patches
  (build-custom.sh --series)        (export.sh, check.sh,          (CI: tree rule, build, docs,
                                     check-tree.sh)                 tsc, tests, install set)
        -> merge  ->  CI: tag custom/<date>.<n>, GHCR image, pre-release
                      with the install set, then move custom to it
```

Merging a pull request into `patches` is the only way the series changes.
`patches` is never rebased or force-pushed; an upstream refresh is a pull
request too (a merge of upstream plus the refreshed patches). `custom` and
the `custom/*` tags are written only by the workflow. A pull request that
changes one series touches one directory.

## Developing a change

Work in a worktree of the `patches` branch (or a branch cut from it). The
scripts default to the clone they are checked out in; `--repo` or
`$OMNIGENT_REPO` points them elsewhere. The clone needs upstream as a remote
(`upstream` below). Upstream's top-level `patches/` folder makes a bare
`patches` ambiguous to git commands that take a revision: write
`refs/heads/patches` or `origin/patches`, or end the arguments with `--`.

1. **Build the series' branch**:
   `custom/scripts/build-custom.sh --series <series> work/<series>` gives the
   series it needs and then its own commits, nothing else. For a new series,
   start on the foundation it will have: the commit in `custom/BASE`, or
   `build-custom.sh --only <needs> --no-index work/<series>` when it needs
   other series.
2. **Change it** like any branch: add commits, amend or `git rebase -i` the
   patch you are fixing (keep fixups squashed into the patch they fix; leave
   the foundation's commits alone). Develop a fix headed upstream on a
   contribution branch cut from `upstream/main`, never from `custom`, and
   cherry-pick it here. To try it with the other series, build them all with
   your working copy of the patch files (`build-custom.sh work/all` after the
   export), or install the pull request's build (below).
3. **Export**, on a branch cut from `patches`:
   `custom/scripts/export.sh <series> work/<series>` rewrites
   `custom/patches/<series>/` from the commits after the foundation, rebuilds
   the series from the files it wrote and requires the branch's tree.
   `--needs a,b` names the needs of a new series or changes them (the branch
   must sit on the foundation they give); a new series gets a `NOTE.md` to
   fill in. `BASE` does not move here; moving it is a
   [refresh](#refreshing-the-base).
4. **Re-cut what sits on top.** A series that needs the one you changed is cut
   from a foundation that just moved. `export.sh` names the ones that no
   longer apply exactly; `custom/scripts/serieslib.py recut <series>...`
   cherry-picks each (as committed at `HEAD`, or `--from <commit>`) onto its
   new foundation and rewrites its files, or stops on a conflict and prints
   the commands to finish by hand.
5. **Check**: `custom/scripts/check.sh` runs the rules that need no build
   (`serieslib.py lint`: layout, notes, the [docs rule](#docs-rule), needs,
   sets), applies every series exactly on its foundation, builds the whole in
   both tie orders, and runs a quick sanity check on the built tree (no
   conflict markers, changed Python and JSON parse). `--custom
   <ref>` also requires the build to have exactly `<ref>`'s tree, for a
   change that must not alter the result. After committing,
   `custom/scripts/check-tree.sh` confirms the [tree rule](#the-tree-rule).
6. **Open a pull request into `patches`**, from a branch named
   `series/<topic>` (`refresh/<date>` for a refresh), with the regenerated
   files and the series' `NOTE.md` (the index follows from it), plus
   `custom/proposals/<series>/PR.md` for a new series.

When two series that do not need each other change the same lines, the build
stops and names the series, the commit and the paths. If both only insert at
the same spot, declare a [join](#glue). Otherwise one really needs the other
(say so in `Needs:` and re-export it on that foundation), or one of them can
be written to keep clear of the other.

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

`custom/scripts/refresh.sh` does the refresh on a branch cut from `patches`,
one series at a time:

```bash
git fetch origin upstream
git switch -c refresh/$(date -u +%F) origin/patches
custom/scripts/refresh.sh --rehearse      # optional: what would happen, nothing written
custom/scripts/refresh.sh                 # merges upstream/main, moves BASE, moves each series
# if it stops on stale series: fix each by hand, or park it, then
custom/scripts/refresh.sh --continue [--park <series>]...
git push origin refresh/$(date -u +%F)    # and open the pull request into patches
```

It merges `upstream/main` into the branch (only upstream paths change, so the
merge does not conflict), writes the new commit to `custom/BASE`, and moves
every series onto its new foundation separately, in build order
(`serieslib.py refresh`). Each series ends as one of:

| Result | Meaning |
| --- | --- |
| `unchanged` | Its patches still apply exactly: upstream did not touch its files. |
| `refreshed` | Cherry-picked onto the new foundation and rewritten. A patch that came out empty landed upstream and is dropped. |
| `landed` | No patch is left. The series is removed with its note (and so its index section), its glue, and the `Needs:` and set lines that name it. |
| `conflict` | Stale. Its files are left as they were, and the commands to move it by hand are printed: a branch on the new foundation, `git cherry-pick` of the old commits, `export.sh`. |
| `waits` | It needs a stale series. |

A stale series does not hold up the others. Glue follows its two series: its
patches are moved, a join the pair no longer needs is taken off, and glue
with nothing left is removed. When nothing is stale the script runs
`check.sh`, commits `custom/`, and runs `check-tree.sh`; review the notes of
the series that changed (a dropped patch moves `Covers:`). The pull request
moves `BASE`, so CI runs the tests of every patch.

**Parking.** `refresh.sh --continue --park <series>` moves a stale series to
`custom/parked/<series>/` as it is, so the refresh can land without it. Its
note gains `Base: <commit>`, the `BASE` its patches are cut from; its glue
goes into the same directory; set files stop listing it; a series that needs
it has to be parked with it. Nothing under `custom/parked/` is built. To
bring one back, move its directory to `custom/patches/`, take the `Base:`
line out, and run `serieslib.py recut --from <the commit before it was
parked> <series>`, which moves it from where it was cut onto today's
foundation (or prints the commands to do it by hand).

**Landed in another shape.** A series can land upstream rewritten, so that
its patches conflict instead of coming out empty. For every series whose
note links an upstream pull request that GitHub says is merged, the refresh
names the note's tests that exist on bare `BASE`; with `--landed-test-cmd
"uv run pytest -q"` it runs them in a worktree of `BASE`. A test file the
series changes is run in the series' own copy, since `BASE`'s copy of a test
the series only extends passes without the series. If they pass there,
upstream has the behaviour and the series can be deleted. The question goes
to GitHub through `gh`, read only; `--no-upstream-check` skips it, and
without `gh` or a network it is skipped with a line saying so.

The merge brings upstream's workflow changes onto the branch, so pushing it
needs a credential that may write workflow files (`gh auth login` asks for
the `workflow` scope). There is no scheduled job that opens refresh pull
requests: a pull request the workflow token opens gets no CI runs without an
approval ([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)),
its pushes of upstream's workflow files would be refused, and a conflict
needs a person anyway.

### Applying a series to your own checkout

```bash
git am -3 $(custom/scripts/series-files.sh --needs link-rules)
```

`series-files.sh` prints a series' files in apply order and, with `--needs`,
the series it needs first; that list is cut as one stack from `BASE`, so on
`BASE` it applies exactly. If your branch is ahead of `BASE` and a patch
conflicts, `-3` falls back to a three-way merge; resolve it and `git am
--continue`. `git config rerere.enabled true` means you resolve each conflict
only once. Series that do not need each other are each cut from `BASE`: apply
them one after the other with `-3`, or let `build-custom.sh --only` combine
them and take the branch it builds.

### Building a set of features

Each series is one feature, and any set of them builds:

```bash
custom/scripts/build-custom.sh --only link-rules,app-error-boundary work/mine
custom/scripts/series-files.sh --only link-rules,app-error-boundary --names   # just list them
```

`--only` takes series names, comma-separated (or repeat the option), adds
every series they need, recursively; it prints each series it added and why.
In the built tree, the index (`docs/custom/README.md`) has the sections of
the series that were built. `series-files.sh --only ... --names` prints the
chosen series instead of their files.

A partial build is for building and running. A branch to export from is one
series on its foundation (`build-custom.sh --series`).

### Named build sets

When the same series feeds more than one kind of build, give each kind a set
file instead of repeating an `--only` list: `custom/sets/<name>.txt` lists the
series that build holds, one per line (`#` starts a comment). As with
`--only`, the series they need are added. [`sets/fixes.txt`](sets/fixes.txt), the
bug-fix series only, is an example.

```bash
custom/scripts/series-files.sh --set fixes --names     # what the set resolves to
custom/scripts/build-custom.sh --set fixes work/fixes   # build it
custom/scripts/check.sh --set fixes                     # apply and check just the set
custom/scripts/select-tests.py --set fixes --tree <dir> --out <dir> --all
custom/release/build.sh --set fixes --tree <dir> --out <dir>
```

Every command without `--set` works on the whole series, exactly as before,
and nothing about the whole series' builds, tags or `custom` changes when a
set exists.

- **Names.** A set name is lowercase letters and digits, starts with a
  letter, is at most 20 characters and is not `dirty`, because it becomes
  part of a version, a git tag and an image tag.
- **Checks.** `check.sh` (and so CI on every pull request) fails when a set
  file names a series that does not exist, so dropping a series means
  editing the sets that list it; CI also builds each set. `check.sh --set`
  checks that set's build: its series combine (the index of a set lists its
  series only).
- **Tests.** `select-tests.py --set` selects from the set's patches only; a
  change to the set file selects all of them.
- **Releases.** A set is released by a manual run of the workflow with the
  `set` input, never by a merge. Its names carry the set and cannot collide
  with the whole series' ([Releases](#releases)): version
  `<upstream version>+oss<BASE:8>.p<patches commit:7>.<set>`, tag
  `custom/<date>.<n>-<set>` (its own count per day), image tag
  `custom-<date>.<n>-<set>`. Its notes are compared with the same set's
  previous release. `custom` is not moved, since it stands for the whole
  series: the tag is what holds a set's built commit. A set release is never
  marked as the latest release.

## What CI does

`.github/workflows/custom-release.yml`, on this fork only:

| Event | Jobs |
| --- | --- |
| Pull request into `patches` | `apply` (the required check: tree rule, build with `build-custom.sh`, `check.sh --tree`, unit tests of `scripts/` and `release/`, test selection), `web` (`tsc -b` and the selected vitest files), `python` (the selected pytest files), `package` (the install set as an artifact, the server image built and smoke-tested but not pushed; the notes go to the job summary), `upstream-workflows` (below) |
| Push to `patches` that changes `custom/BASE`, `custom/patches/**`, `custom/glue/**`, `custom/release/**` (not its Markdown), `custom/scripts/build-custom.sh`, `check.sh`, `check-tree.sh`, `select-tests.py`, `serieslib.py` or `series-files.sh`, the workflow, or its action | The same, then `publish`: tags the build, pushes the image to GHCR, creates the pre-release and then moves `custom` to it. A merge that only changes docs, proposals or the tracker makes no release. |
| Manual run (`workflow_dispatch`) | Inputs: `dry_run` (default true: everything, with `publish` printing the pushes, tag, image push and release instead of doing them; a run on any ref other than `patches` is always dry), `prerelease` (default true; false marks a real run's release as the latest full release), `all_tests` (default false; true runs the tests of every patch), `set` (default empty: the whole series; a name builds, tests and releases that [build set](#named-build-sets) and leaves `custom` alone) |
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
  prefix keeps it apart from upstream's version tags. A
  [build set](#named-build-sets)'s tag ends in `-<set>` and has its own
  count; its version ends in `.<set>`.
- **Version** `<upstream version>+oss<BASE:8>.p<patches commit:7>`, a PEP 440
  local version, where the patches commit is the `patches` branch commit the
  build is from, e.g. `0.20.0.dev0+oss65be0f24.p0123abc` (illustrative). It
  is stamped at build time with upstream's `scripts/update_versions.py`, so
  the built tree keeps upstream's version files. `omnigent --version` prints
  it with the built commit:
  `omnigent 0.20.0.dev0+oss65be0f24.p0123abc (37f5c6e0, built …)`.
- **`custom`** points at the latest release's built commit: upstream at
  `BASE` plus one commit per patch (the series combined, in build order) and
  the index commit, without `custom/` or our workflow.
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
trailer. The last commit of a build is the index, `docs/custom/README.md`:
one `## <series>` section per series built, saying what it changes, how to
turn it on and where its docs are. The build writes it from each series'
[note](#notes), so adding, changing or dropping a series updates it with the
series' own directory, and no patch may touch that file. `scripts/check.sh`
enforces docs or the trailer on every patch and a complete note for every
series. The release notes carry that index, and `custom-docs.md` the docs
themselves.

## Tracker

`tracker.yaml` records, per series and per upstream change we only watch, the
upstream issue and PR links plus relationships (`carries`, `blocked_by`,
`superseded_by`, `related`, `conflicts`). `scripts/tracker.py OUT.html` joins
it with the series directories and live GitHub state to produce a page with a drop list
(patches to remove on the next refresh), what waits on us, what waits on
maintainers, and a dependency graph. The table below is the hand-written
summary; the generated page is the live view.

## Patch index

Status is one of: **proposed** (not yet filed upstream; see `custom/proposals/`),
**issue open** (an upstream issue tracks it), or **PR open** (an upstream pull
request carries it, and the series holds a copy until it merges).

| Series | What it does | Status |
|---|---|---|
| `claude-config-dir` | claude-native and claude-sdk follow `CLAUDE_CONFIG_DIR` instead of assuming `~/.claude`. | issue open ([#7124](https://github.com/omnigent-ai/omnigent/issues/7124); the PR this copied, [#9617](https://github.com/omnigent-ai/omnigent/pull/9617), was closed) |
| `subscription-accounts` | Several Claude or Codex subscription logins per host: pick the account for a new session, switch a running session's account from the harness menu, accounts that share sessions through account tokens, and agents can start a child session on another account. Docs in `docs/providers.md`. Needs `claude-config-dir`. | issue open ([#503](https://github.com/omnigent-ai/omnigent/issues/503)) |
| `session-history-paging` | Agents can page through a session's history and list recently updated sessions; `ownership` stays an alias of upstream's `visibility` until 0.24.0. | proposed |
| `telemetry-attribution` | Exported spans carry the acting user (opt-in), the runner and the host. | PR open ([#11380](https://github.com/omnigent-ai/omnigent/pull/11380); issue [#10794](https://github.com/omnigent-ai/omnigent/issues/10794)) |
| `session-telemetry` | Every span of a turn carries the session's metadata (labels, project, agent, git, workspace, host) and the model and reasoning effort the turn ran with. | PR open ([#11384](https://github.com/omnigent-ai/omnigent/pull/11384), then [#11434](https://github.com/omnigent-ai/omnigent/pull/11434) stacked on it, draft) |
| `claude-sdk-web-tools` | claude-sdk agents can opt into Claude Code's WebSearch and WebFetch. | proposed |
| `claude-native-teammates` | Claude Code agent-team teammates show up as child sessions, and their deliveries no longer appear as raw `<teammate-message>` bubbles. | PR open ([#11388](https://github.com/omnigent-ai/omnigent/pull/11388) for the child sessions, [#11389](https://github.com/omnigent-ai/omnigent/pull/11389) for the deliveries; issue [#10745](https://github.com/omnigent-ai/omnigent/issues/10745)) |
| `claude-native-subagent-status` | A sub-agent still shown as working when its parent records its result is settled then (idle, or failed for a failed result). | not filed; upstream fixed the other half (long tool calls) in [#13811](https://github.com/omnigent-ai/omnigent/pull/13811), and open PR [#12411](https://github.com/omnigent-ai/omnigent/pull/12411) (not ours) touches the same code |
| `claude-native-coordinator-messages` | A parent agent's follow-ups appear in the sub-agent's chat. | proposed |
| `codex-native-mode-instructions` | A Default-mode Codex turn keeps Codex's own Default mode instructions instead of having them replaced by the session's developer instructions (the Plan toggle is upstream since [#11570](https://github.com/omnigent-ai/omnigent/pull/11570)). | proposed |
| `chat-item-labels` | Bracketed labels like `[Q2]` in chat become chips that preview the item they refer to; `~~[Q2]~~` closes it, and an Open items panel lists what is still open. Adds the labelling rules to agents' instructions. Needs `codex-native-mode-instructions` and `session-labels-ui`. | proposed |
| `open-items-links-compact` | The Open items bar becomes a button in the session header with a count badge (a popover on desktop, a sheet on phones), and the panel also lists the session's links. Needs `chat-item-labels`. | proposed |
| `web-reconnect-shell-inputs` | A queued `!command` no longer stays stuck at the bottom of the chat after the connection drops. | PR open ([#11395](https://github.com/omnigent-ai/omnigent/pull/11395)) |
| `chat-item-comments` | Comment on labelled items and send the comments together as one structured message. Needs `chat-item-labels`. | proposed |
| `queue-combine` | The queue strip offers **Combine** for adjacent queued messages, and **Send all** where rows can be steered. Needs `chat-item-comments`. | proposed |
| `pr-watch` | A session watches its pull requests: while it is idle the server wakes it about failed checks, owners' comments and reviews, and conflicts, until each is green, merged or closed. Off by default (`OMNIGENT_FEATURES=pr_watch`). | proposed |
| `pr-refresh-main-checkout` | A session in a repository's main checkout keeps looking for pull requests at every turn end, so one opened later shows up. | carried from [#14515](https://github.com/omnigent-ai/omnigent/pull/14515) (not ours, open); drop when it merges |
| `session-labels-ui` | View and edit a session's labels in the web UI, delete labels through the API, and default labels per project. | PR open ([#11398](https://github.com/omnigent-ai/omnigent/pull/11398) for the server, [#11399](https://github.com/omnigent-ai/omnigent/pull/11399) for the web UI (draft)) |
| `palette-new-chat-in-project` | Typing in ⌘K lists a "New chat in <project>" row for every project, in both the classic and the QuickPick palette. | PR open ([#11394](https://github.com/omnigent-ai/omnigent/pull/11394), draft) |
| `new-chat-project-prompt` | Starting a new session asks which project it belongs to (a picker, a bottom sheet on phones); a setting turns it off. | PR open ([#11397](https://github.com/omnigent-ai/omnigent/pull/11397), draft; issue [#11083](https://github.com/omnigent-ai/omnigent/issues/11083)) |
| `terminal-touch` | On touch devices the terminal gets an extra-keys row (Esc, Tab, arrows, sticky Ctrl, Alt and Shift) and long-press select with Copy and Paste; the iOS app pastes natively. | the extra-keys row is carried from [#6136](https://github.com/omnigent-ai/omnigent/pull/6136) (not ours, open); the rest is proposed |
| `gateway-request-tags` | Requests to a Databricks Unity Gateway carry the session id and labels as request tags. | proposed (issue drafted) |
| `claude-native-delegate-idle` | A Claude lead stops showing Working, and takes follow-ups without Steer, once its turn ends while agent-team teammates keep running: teammates count as background agents for upstream's background-agent hold ([#12561](https://github.com/omnigent-ai/omnigent/pull/12561)). | proposed (the status-file and OSC parts landed upstream as #12561) |
| `delete-stops-runner` | Deleting a session stops its host-launched runner once no remaining session uses it, instead of leaving the process running until its idle timeout. | PR open ([#11391](https://github.com/omnigent-ai/omnigent/pull/11391)) |
| `app-error-boundary` | Upstream's render error fallback also shows the error, component stack and path, with Copy details and Reload. | proposed |
| `tolerate-retired-preferences` | A stored shared preference of a kind this build doesn't know (one a parked or newer series saved) is skipped on read instead of failing every preferences read with a 500; the row stays stored. | proposed |
| `link-rules` | Short references in chat (`BST-2135`, `#123`, `session:<id>`) render as links from per-user rules set in Settings → Chat links; agents can change them with `sys_link_rules`, each change approved, and are told the active syntaxes. A bare `#123` stays with upstream's built-in pull request links, which link it only to a pull request the session links ([#14978](https://github.com/omnigent-ai/omnigent/pull/14978)); while any rule is on, the rules replace the built-in `owner/repo#12` links ([#14191](https://github.com/omnigent-ai/omnigent/pull/14191)). Needs `chat-item-labels`. | proposed (related issue [#11176](https://github.com/omnigent-ai/omnigent/issues/11176)) |
| `antigravity-cooldown` | The `antigravity` extra locks `google-antigravity` 0.1.23 instead of 0.1.2 (the fixed-date cooldown exemption in `uv.toml` is gone), and the antigravity harness reads a turn's token usage from the conversation, where the newer SDK reports it. On a refresh conflict in `uv.lock`, re-lock with `uv lock --upgrade-package google-antigravity` instead of merging the hunk. | PR open ([#14704](https://github.com/omnigent-ai/omnigent/pull/14704), draft) |
| `mcp-registry-icons` | A service in the MCP registry file can set `icon`, an embedded SVG or PNG data URI, shown in the managed MCP picker in place of the plug. A build without the series rejects the field, so upgrade the server before adding it. Docs in `examples/mcp-registry/README.md`. | not proposed from here; upstream's own issue [#13294](https://github.com/omnigent-ai/omnigent/issues/13294) and draft PR [#13295](https://github.com/omnigent-ai/omnigent/pull/13295) (not ours) add the same field with a wider set of values, ours a subset: drop if it merges |
| `credential-local-key` | The credential store can use a key the operator keeps in a file (AES-256-GCM), an explicit opt-in for a trial or single-machine server with neither KMS nor Vault. | not proposed (upstream's design has no non-KMS fallback) |
| `mcp-registry-tool-patterns` | An MCP registry service's `tools` allowlist takes `*` patterns (`search_*`, or `"*"` for every tool), checked on every listing and call. Docs in `examples/mcp-registry/README.md`. | not proposed |
| `sandbox-connection-gate` | The New session host menu shows a sandbox provider that launches as the signed-in user as disabled, with a row to connect the account, until the user has connected it. | not proposed |
| `deploy-features-list` | `deploy/databricks/deploy.py --features a,b` deploys: the list goes to the bundle as `BUNDLE_VAR_features` instead of a `--var` pair, which the Databricks CLI splits on commas. | not filed (fork issue [#20](https://github.com/Desidero/omnigent/issues/20)) |
| `deploy-overlay` | `deploy.py --overlay <file>`: a Databricks Apps deployment's own workspace host, extras, env vars, secret-backed env vars and app-source files come from one untracked YAML file instead of hand edits to tracked files. | not filed (fork issue [#21](https://github.com/Desidero/omnigent/issues/21)) |
| `kms-uc-service-credential` | The credential store's KMS backend can sign with a Unity Catalog service credential (`OMNIGENT_CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL`), so a server with no AWS identity, such as a Databricks App, needs no static keys or helper files. | not filed (fork issue [#22](https://github.com/Desidero/omnigent/issues/22)) |
| `databricks-apps-docs` | Docs only: what a Databricks App needs after the first deploy (server config, smart routing, MCP registry, the per-user connection, sharing, hosts, telemetry). Needs `deploy-overlay` and `kms-uc-service-credential`. | not filed (fork issue [#17](https://github.com/Desidero/omnigent/issues/17)) |
| `subagent-only-routing` | A Claude Code or Codex session keeps the model the user picked and lets Smart Routing choose the model of each sub-agent it starts: "Route sub-agents" in the new-session and session model menus, or `subagent_routing_override: "on"` at create. The host installs the routing gate at launch, so hosts need the build too. | issue open ([#14897](https://github.com/omnigent-ai/omnigent/issues/14897)) |
| `side-schemas` | Infrastructure for other series: a feature can keep its own tables as a side store, with its own migrations outside the main Alembic chain. Docs in `docs/extending/side_schemas.md`. | not proposed (upstream adds tables through its own chain) |
| `open-items-store` | Open items become records of their session with server-allocated labels: agents raise, close and list them with `sys_open_items_*` tools, people through `/v1/sessions/{id}/open-items`. Needs `side-schemas` and `chat-item-labels`. | proposed (follows issue [#14639](https://github.com/omnigent-ai/omnigent/issues/14639)) |
| `open-items-panel` | The Open items panel, its badge and the label chips read the session's stored open items, live, with chat-only labels marked; editors close, reopen and retopic items and import the chat's own labels. Needs `open-items-store` and `open-items-links-compact`. | proposed (follows issue [#14639](https://github.com/omnigent-ai/omnigent/issues/14639)) |
| `transcript-hold-position` | Scrolled up in a transcript, the reader keeps their place while rows above change height (a reply streaming, a tool group settling, an image loading, rows measured during a scroll back): the transcript holds the row being read instead of leaving it to the virtual list's own correction. | proposed (the streaming re-key that first motivated it is fixed upstream by [#12923](https://github.com/omnigent-ai/omnigent/pull/12923)) |
| `history-prefetch` | The next older page of history is fetched as soon as a scroll-up comes near the top, ahead of its landing; one gesture pages in at most 600 items. | PR open ([#13257](https://github.com/omnigent-ai/omnigent/pull/13257), draft; issue [#13255](https://github.com/omnigent-ai/omnigent/issues/13255); the larger page landed as [#13247](https://github.com/omnigent-ai/omnigent/pull/13247)) |
| `lean-history-items` | History pages carry only the head of long tool outputs (`tool_output=preview`), and expanding a tool row fetches the full result from a per-item read; both reads are gzipped. Needs `history-prefetch`. | PR open ([#13259](https://github.com/omnigent-ai/omnigent/pull/13259), draft; issue [#13255](https://github.com/omnigent-ai/omnigent/issues/13255)) |
| `composer-send-tap` | On touch screens one tap on Send sends, even while the on-screen keyboard is up. | proposed |
| `mobile-settings-nav` | Phone Settings opens on a full-width list of pages (Back row, title, search, inset groups of 44px rows with a chevron, none highlighted), not on General; a page opens with the menu closed and its header goes Back to the list. | PR open ([#13484](https://github.com/omnigent-ai/omnigent/pull/13484), draft) |
| `mobile-landing-project-chip` | The phone new-session landing names its project in a chip whose menu switches it and keeps the draft. | PR open ([#13487](https://github.com/omnigent-ai/omnigent/pull/13487)) |
| `mobile-sidebar-nav-strip` | The phone drawer's New session, Automations, Workflows and Inbox rows fold into one strip of icon-over-label cells. | PR open ([#13488](https://github.com/omnigent-ai/omnigent/pull/13488), draft; issue [#13482](https://github.com/omnigent-ai/omnigent/issues/13482)) |
| `sidebar-updated-filter` | A sidebar filter for sessions updated in the last 24 hours, 3, 7 or 30 days, with a chip while it is on. | proposed |
| `sidebar-sticky-toolbar` | The sidebar's filter, Select sessions and bulk-action bar stay in view while the session list scrolls. | proposed |

### Parked series

A series parked by a refresh sits in `custom/parked/<series>/`
([Refreshing the base](#refreshing-the-base)). The ones below were taken out
before that directory existed. Their patch files (in the flat
`<series>--<subject>.patch` layout of the time, listed by that commit's
`custom/series`) and index sections are on the patches commit that release `custom/2026-11-09.1` was
built from (the tag's `Patches-Commit:` line); their proposals stay under
`proposals/`. "Optional" means kept out to keep the series small, not that
anything is wrong with it.

| Series | Why parked |
|---|---|
| `backport-sidebar-filter-submenus` | landed upstream (#13481) |
| `toast-safe-area` | superseded by upstream #13607 |
| `skip-gzip-binary-files` | landed upstream (#12362); dropped at the 2026-11-24 refresh |
| `chat-features` | optional |

To restore one, apply it from that commit onto the foundation it will have
now (`BASE`, or the series it needs: what its `# needs:` lines named, less
the ones that were only there to make it apply), then export it as a new
series and check it as in [Developing a change](#developing-a-change); a
conflict is resolved as in a refresh.

```bash
old=$(git tag -l --format='%(contents)' custom/2026-11-09.1 | sed -n 's/^Patches-Commit: //p')
git worktree add --detach /tmp/parked "$old"
git switch -c work/<series> "$(cat custom/BASE)"   # or build-custom.sh --only <needs> --no-index work/<series>
git am -3 $(/tmp/parked/custom/scripts/series-files.sh <series>)
custom/scripts/export.sh --needs <needs or none> <series> work/<series>
```

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
  and send a pull request into `patches` with the series' regenerated
  directory.
- Screenshots and logs in `proposals/*/evidence/` must come from a throwaway
  server with dummy data. Never include credentials, real user data or
  private hostnames.

## License

Omnigent is licensed under the Apache License 2.0 (the repository's
`LICENSE`), and the patches here are contributions to it under the same
license.
