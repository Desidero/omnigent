# Does our Run button overlap the #10519 stack? (reviewed 2026-10-21)

Read-only research. Nothing on any branch was touched. `upstream/main` is at
`eced2859d` (#10826); our `feat/run-suggested-commands` forks from `d7783c381`
(#11088), 24 upstream commits behind.

## 1. The four PRs (all by andresgarciaf, all opened 2026-10-19, all from fork `andresgarciaf/omnigent`)

| PR | Title | State | Draft | Mergeable | Size | Files | Labels | Reviews / comments | CI |
|---|---|---|---|---|---|---|---|---|---|
| #10837 | feat(db): add code_run conversation item and migration (1/4) | OPEN | no | UNKNOWN | +1466 / -4 | 14 | size/XL, waiting-for-review | **none** (0 reviews, 0 issue comments, 0 inline comments) | 79 success, 7 skipped, 1 failure = "Maintainer Approval" (the fork gate) |
| #10840 | feat(server): run chat code blocks on the runner with streamed output (2/4) | OPEN | **yes** | UNKNOWN | +5816 / -33 (includes part 1) | 37 | size/XL | none | 36 success, 30 skipped, Maintainer Approval failure |
| #10856 | feat: deliver code-block runs to the agent's next turn (3/4) | OPEN | **yes** | UNKNOWN | +7280 / -75 (includes 1-2) | 60 | size/XL | none | 35 success, 34 skipped, Maintainer Approval failure |
| #10857 | feat(web): run chat code blocks with notebook-style inline output (4/4) | OPEN | **yes** | UNKNOWN | +11326 / -100 (includes 1-3; 76 commits) | 88 | size/XL, P2-medium | none | 45 success, 38 skipped, Maintainer Approval failure |

Maintainer engagement: **zero humans so far.** On #10837 the author
requested the four `CODEOWNERS` for `omnigent/db/migrations/` (Edwinhe03,
aravind-segu, dbczumar, bbqiu, all `CONTRIBUTOR` association) and the bot
assigned/review-requested daniellok-db (`CONTRIBUTOR`). Parts 2-4 have no
assignee or reviewer. Issue #10519 was labelled and assigned to dhruv0811
(`MEMBER`) by the triage bot only; the only comment is the bot's P2 triage.
No maintainer has answered the issue's three explicit "questions for
maintainers" (streaming endpoint acceptable? owner-only? confirm every run?).
The author built all four parts anyway.

## 2. The author

- `andresgarciaf`, "Andres Garcia", GitHub `company: Databricks`, account since 2017.
- Merged PRs in omnigent-ai/omnigent: **0**. Open PRs: these 4. `author_association` on #10857: **NONE**.
- All 39 commits carry `Signed-off-by: Andres Garcia <andres.garcia@databricks.com>`, 33 of them `Co-authored-by: Isaac <no-reply@databricks.com>`, every PR body ends "This pull request and its description were written by Isaac." That is the same Databricks-internal agent that co-authors yaoharry's commits (#10667). PR bodies use the repo's superpowers spec/plan docs under `docs/superpowers/`.
- Verdict: **a Databricks employee using the maintainers' internal tooling, but not a repo maintainer** (no merge rights, no prior merged PRs, "Maintainer Approval" fails as for any fork). Not a random drive-by either: the work is in the house style and will very likely get looked at eventually.

## 3. What #10857 does vs our branch

| | #10857 stack | ours (`feat/run-suggested-commands`) |
|---|---|---|
| Gate | server feature flag `code_block_run` (off by default, `OMNIGENT_FEATURES`, exposed in `/v1/info`); all new routes 404 when off | per-session "chat feature" `run_commands` stored in session_overrides, user default via new `GET/PUT /v1/preferences/chat-features`, toggles in new-chat dialog / configure menu / Settings; also injects a system-prompt instruction ("tag shell blocks as bash, one command per line") into every session |
| Which fences | `bash`, `sh`, `shell`, `zsh`, `console`, untagged blocks where every line starts with `$ `, plus `python`, `javascript`/`node`. Whole block = one run; `$ `/`% ` prompts stripped; `console` keeps only prompt lines | `bash`, `sh`, `shell`, `zsh`, `console`, `shell-session`; one command per logical line (backslash continuations joined), max 10, heredocs refused; prompt-only lines kept when a transcript is shown. No python/node |
| `!` handling | **None.** No `!`-prefix logic anywhere in the diff (grep for bang / `startsWith("!")` / `lstrip("!")` is empty). The design doc mentions #7840 only as an alternative rejected as "specific to one harness, and typed rather than run from the agent's code block" | `!`-prefixed lines win over the fence language (each becomes a command, other lines are commentary); inline `` `! cmd` `` spans also get Run |
| Execution path | new `POST /v1/sessions/{id}/code-runs` -> runner `code_runs.py` -> own sandbox helper process per run (max 4), process-group kill on Stop/timeout (120 s default), policy check as `sys_os_shell` with ASK/approval, audit, 100 kB output cap, new `code_run` DB item (type code 12, migration) | queues `!command` through the existing composer send path: claude-native types it into Claude Code's shell mode; codex-native (our 2nd commit) routes a lone `!cmd` to `thread/shellCommand` and mirrors `userShell` items as `terminal_command`. No server endpoint, no new item type, no policy pass, runs in the agent's own terminal |
| Output | inline notebook panel under the block (`CodeRunPanel.tsx`, new `codeRunStore`), streamed via new SSE events `code_run.started/output/finished/snapshot`, saved with the session, visible to all viewers, earlier runs collapsed, Expand, ANSI; summary delivered to the agent's next turn (part 3) | whatever the existing `terminal_command` input/output cards already render for a `!cmd`; agent sees it because it ran in its own shell |
| Who can run | session owner only, finished messages only, needs a bound runner, not during sandbox relaunch | anyone with the composer, gated by harness in {claude-native, codex-native} and the session's chat-feature set |
| Confirmation | first run per session per device (localStorage), plus every policy ASK | every click, lists the `!cmd` lines |

Files changed by both (#10857 vs ours, 17 overlaps): `omnigent/entities/conversation.py`,
`omnigent/harnesses/codex_native/forwarder.py`, `omnigent/inner/codex_native_executor.py`,
`omnigent/runner/app.py`, `omnigent/server/app.py`, `omnigent/server/routes/_sessions/{helpers,orchestration}.py`,
`omnigent/server/schemas.py`, `openapi.json`, `tests/inner/test_codex_native_executor.py`,
`tests/runner/test_app_sessions_native_terminals_runtime.py`,
`web/src/components/ai-elements/message.tsx`, `web/src/components/blocks/BlockRenderer.tsx`,
`web/src/pages/ChatPage.tsx`, `web/src/pages/ChatPage.composer.test.tsx`,
`web/src/store/chatStore.{ts,test.ts}`.
The hot spot is `message.tsx`: both add a Run button in the same code-block
header slot (`CODE_BLOCK_OVERLAY_BUTTON_CLASS`), both parse the fence language
from the `<code>` className, both wrap the block. They cannot coexist as
written; one would have to be rebased onto the other.

## 4. #10667 and our branch's standing against upstream/main

- #10667 (merged 2026-10-21T00:40Z, `ee9dea822`, by yaoharry = `COLLABORATOR`,
  self-merged) only changes `_restore_occupied_input`/`_occupying_surface` in
  `omnigent/harnesses/claude_native/bridge.py`: when the TUI input box is in
  `!` shell mode *with a typed draft*, send Ctrl+U twice instead of Escape so a
  web message can reclaim the box. It does not change how a web `!cmd` is
  delivered or mirrored. **It does not touch the composer `!cmd` path our Run
  button relies on.**
- `ee9dea822` is already an ancestor of `feat/run-suggested-commands`; our
  bridge.py diff (`_merge_append_system_prompt`, 835862568 -> f63dd949b) sits
  on top of it cleanly.
- Dry-run merge (`git merge-tree --write-tree upstream/main feat/run-suggested-commands`): **4 conflicts**, none from #10667 or #10857:
  - `omnigent/server/routes/preferences.py` add/add: we created this file for
    `/v1/preferences/chat-features`; #10826 (merged 2026-10-20) created the
    same path for `/preferences/shared`.
  - `tests/stores/test_preference_store.py` add/add (same cause).
  - `omnigent/cli.py` and `omnigent/server/app.py`: #10826 changed how the
    preference store is constructed (`SqlAlchemyPreferenceStore(db_uri, authority_id=...)`
    behind an `authority_id` guard, `PreferenceStore` import, `create_preferences_router(store, auth_provider)` signature).
  - All four are mechanical; the chat-features router would become a second
    router or a second set of routes in the same module.
- Recent upstream commits on the shared paths since our fork point: `d92a735ff` (#11052 compaction context), `966e5e0a1` (#10485), `baf4bbfa2` (#10410); all auto-merge.

## 5. `fix/web-reconnect-settles-shell-inputs` vs #10667 / #10649

- Our fix: `web/src/store/chatStore.ts` only (+140/-21). Factors the live
  `terminal_command` input handler's bubble settlement into `settleShellInput`
  and calls it from both reconnect paths (`reconcileOnReconnect` and
  `rehydrateWindowOnReconnect`), so a `!cmd` bubble whose item event fired
  into a dead socket is cleared from the backfill instead of sticking to the
  bottom until reload. Builds on `settledShellInputs` from #9493.
- #10667: claude-native bridge, TUI shell-mode draft blocking web input.
  **Different bug, different layer.** Not superseded.
- #10649 (open, yaoharry): server re-announces idle `session.status` when a
  reconnecting runner defers an idle session, so the tab stops saying
  "Working..." (#8541 nightly). It is about the status edge, not pending
  bubbles. **Different bug.** Not superseded, though both are "stuck UI after
  reconnect" and it would be reasonable to reference it.
- #7840 (open since Sept, bot-authored, last activity 2026-10-08 bot review,
  unmerged): gives a composer `!cmd` its own user message in claude-native.
  Its chatStore diff does not touch `settledShellInputs`/`isShellCommandBubble`
  or the reconnect paths, so no overlap, but if it lands, a `!cmd` would get a
  real user message and the FIFO `session.input.consumed` acknowledgement,
  which would make shell-bubble settlement partly redundant. Low risk; it has
  been stalled for a month.
- Merge dry-run against upstream/main: **clean** (forks from `efabd5cb2`, before #10667; #10667 doesn't touch chatStore).
- Verdict for this branch: still valid, independent, small, worth proposing on
  its own. Cite #9493 as the origin of the settlement logic and #10649 as the
  neighbouring reconnect fix.

## 6. Verdict on the Run button: (a), with a narrow (b)

**Drop it upstream-wise; keep it local only, and expect to retire it.**

Reasoning:

1. It is the same feature, filed first by them, with a design doc, four PRs,
   E2E tests, screenshots, and a fully-built notebook-output path. Their
   version is strictly more capable (inline output, persistence, viewers,
   policy/audit, Stop, agent delivery, python/node) and works for every
   harness, where ours works only for claude-native and codex-native because
   it rides the `!` composer hack. A maintainer choosing between them will not
   pick ours, and the issue's own "alternatives considered" already names the
   `!`-composer approach and rejects it as harness-specific.
2. Their stack has had zero maintainer response in two days, but it is in the
   house style (Isaac co-author, superpowers spec) from a Databricks employee.
   The likelier outcome is slow review and merge, not abandonment. Opening a
   competing 80-file PR now would read as duplicating active work.
3. Our branch's distinctive part is not the Run button; it is the
   **per-session "chat features" mechanism** (instruction + UI toggle, stored
   in session_overrides, user default in preferences, runner wire). That is
   broader than this feature and conflicts with #10826's preferences work.
   If we want anything upstream from this branch, it would be that mechanism
   as its own issue, decoupled from Run, and only after checking whether
   maintainers want prompt-affecting per-session toggles at all. Not urgent.
4. The codex-native `!cmd -> thread/shellCommand` commit (`cf80ba71c`) is
   independent of the Run button and of #10519 (their runner executes in its
   own helper process, never through the agent's shell). It is a candidate for
   its own small PR: "codex-native: run web `!command` inputs via
   `thread/shellCommand` instead of sending them as prompts", if that is
   indeed a bug today on upstream/main. Verify first that upstream still sends
   `!cmd` to Codex as a prompt; if so, that is a real fix worth proposing.

What to say on #10519 / #10857, if anything (the "narrow (b)"): one short
comment on #10857, not a review, since nobody has reviewed yet and it is a
draft:

- Suggest honouring `!`-prefixed lines inside a fence (and `` `! cmd` ``
  inline spans) as "one command each, the rest is commentary", since agents
  routinely write ``!cmd`` for claude-native users and the stack currently
  ignores the prefix entirely (it would try to run `!pip install x` literally
  in a `bash` block). This is a concrete gap in `codeRunLanguage` /
  `deriveCodeRunCommand` / `derive_code_run_command`.
- Optionally: a per-line Run for shell blocks (their model runs the whole
  block as one script; ours runs each line as its own input), as a question
  rather than a demand.
- Do not propose the no-endpoint `!`-composer fallback; they already
  considered and rejected it in the issue, and it only serves two harnesses.

Keep `feat/run-suggested-commands` as a local `custom` patch only if it is
actually used now; otherwise shelve it, because the 17-file
overlap with #10857 (especially `message.tsx`, `chatStore.ts`,
`routes/_sessions/*`, `schemas.py`, `openapi.json`) means every future
`custom` rebase will fight that stack once it merges.

## Data sources

- PR JSON: `<scratch>/pr{10837,10840,10856,10857}.json`
- PR bodies: `.../scratchpad/pr-bodies.md`; #10857 diff: `.../scratchpad/pr10857.diff` (13,253 lines); #7840 diff: `.../scratchpad/pr7840.diff`
- Merge dry-run output: `.../scratchpad/mt-feat.txt` (tree `05a941ed6`)
