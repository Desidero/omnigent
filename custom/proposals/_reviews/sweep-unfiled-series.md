# Sweep: unfiled patch series vs upstream (2026-10-23)

Read-only research on `omnigent-ai/omnigent` for the series in
`~/repos/Desidero/omnigent-patches` that have nothing filed upstream. Nothing was
posted, pushed or changed.

Method per series: the patch diff and commit message, `proposals/<series>/`,
3 `gh search issues` + 2 `gh search prs` (both states), `gh issue/pr view` on
every hit (state, `closedByPullRequestsReferences`, author), `gh pr list
--author` for the authors of related open issues, and
`git log --since=2026-09-15 upstream/main -- <source files>` for churn.
"Churn" below = upstream commits since 2026-09-15 touching the series' non-test
source files (upstream/main at 39611f812, 2026-10-23). Lines are the whole
patch including tests; "source" is the non-test part.

Patches base: `patches/BASE` = 449d608; upstream/main is ~40 commits ahead,
and two of those (#8584, #11118's sibling #11226) touch files below.

---

## 1. gateway-request-tags

**Carry cost:** 1 patch, +586/-22 (source ~+305 across 11 files incl.
`databricks_ai_gateway.py`, `claude_native/main.py`, `claude_sdk_executor.py`,
`codex_executor.py`, `pi_executor.py`, `runner/app.py`). Churn **266** (the
hottest files in the repo: runner/app.py, the three executors, claude_native/main.py).

**Prior art:**
- #10410 merged 2026-10-20: static Unity Gateway attribution headers
  (`Databricks-Custom-Coding-Agent`). Our builder sits next to its helpers.
- #11118 **open** (yaoharry, maintainer, 2026-10-21): "preserve Unity Gateway
  attribution across config layers". Touches `databricks_ai_gateway.py`,
  `claude_native/main.py`, `claude_gateway_shim.py`, `claude_sdk_executor.py`,
  `codex_executor.py`, `model_signing.py` — the same code our patch edits. Direct
  rebase conflict when it lands.
- #11099 open (yaoharry): attribute signer-backed Codex requests to the gateway.
- #11226 merged 2026-10-22: route native Codex's gateway/auth through ucode state
  (touches `codex_native/app_server.py`, which we also edit).
- #10794 (span attribution, referenced by our telemetry series), #11000 (per-launch
  Codex header from a session label).
- No issue or PR mentions `Databricks-Ai-Gateway-Request-Tags` or per-session
  request tags. Terms: "request tags", "Databricks-Ai-Gateway-Request-Tags",
  "gateway usage attribution session", "attribution", "Unity Gateway".

**Maintainer fit:** Good. Databricks is the maintainers' own platform and a
maintainer is actively working this exact header block this week, so the
timing is right and the pattern (one canonical builder, thin per-harness
transport) matches #10410. Two things they will push on: it is on by default
and ships user labels to the gateway (they may want opt-in rather than
`OMNIGENT_GATEWAY_REQUEST_TAGS=0`), and the Codex/pi transport paths are
being reshuffled by #11118/#11226, so the PR must be rebased on #11118 or it
will not apply.

**Route:** File the drafted `proposals/gateway-request-tags/issue.md` now,
referencing #10410/#11118/#11099 and asking yaoharry whether to stack on
#11118. Open the PR once #11118 merges (rebase first). Highest carry cost
saved of the plausible merges.

---

## 2. session-history-paging

**Carry cost:** 1 patch, +772/-77 (source +340: `runner/tool_dispatch.py`
+151/-43, `tools/builtins/spawn.py` +174/-34, store/route +15, openapi +18).
Churn **121** (tool_dispatch.py and routes_core.py are hot).

**Prior art:**
- #4601 merged 2026-08-11: "let sys_session_get_history request longer items" —
  same tool, shows maintainers accept additive parameters here.
- #11108 open issue (andrewreid) / #11109 open PR: make runner session-metadata
  reads cheap on both ends — same session-read path in tool_dispatch; rebase
  hazard, not overlap.
- #11299 open (kzarzycki, 2026-10-22): server-side find in a long chat with a
  `before` cursor on `/v1/sessions/{id}/search` — adjacent precedent for
  cursor-paged item reads and bounded scans (`docs/DATABASE_BEST_PRACTICES.md`).
- #11003 open (bobbyhyam): rewrites session-tool descriptions in spawn.py.
- No issue asks for history paging or `updated_after`. Terms:
  "sys_session_get_history", "session history pagination cursor",
  "sys_session_list updated", "transcript agent read older", "session history
  paging".

**Maintainer fit:** Good. Harness-agnostic, all parameters optional, defaults
and caps unchanged, well tested at tool, store and endpoint layers. Two
reviewer asks are predictable: split it (list filters vs history cursor are
independent features in one commit) and justify the new `updated_after` query
param against the bounded-scan rules #11299 is being held to. Agent-facing
tool surface changes get a careful read but #4601 shows the path.

**Route:** Feature issue (short) + PR now, ideally as two PRs: (a)
`sys_session_list` filters/timestamps + `GET /v1/sessions?updated_after`, (b)
`sys_session_get_history` forward cursor. Note #11109 so the reviewer sees the
rebase relationship.

---

## 3. claude-native-coordinator-messages

**Carry cost:** 1 patch, +149/-53 (source +43: `claude_native/bridge.py` +8,
`web/src/lib/itemsToBlocks.ts` +7, `systemMessage.ts` +26, `chatStore.ts` +2).
Churn **112** (bridge.py and chatStore.ts are hot, but the hunks are tiny).

**Prior art:**
- #10740 **open** (resolve agent, 2026-10-19, "Resolves OMNI-13003"): "Fix
  agent-sent cross-session messages showing as user-typed" — adds a "From
  Claude" link on messages a parent sends via `sys_session_create/send`. Same
  UX problem, different channel (Omnigent child sessions vs Claude Code's
  in-process `SendMessage`/teammate records with `origin.kind == "coordinator"`).
  Not a duplicate, but the two presentations should agree.
- #7962 issue / #7965 PR (cross-session peer messaging, stale) — unrelated channel.
- Terms: "coordinator", "SendMessage sub-agent chat", "isMeta hidden message",
  "sub-agent chat missing prompt", "is_meta claude-native".

**Maintainer fit:** Good. Small bug fix with a clean reproduction (spawn a
background agent, message it, open its chat), reuses the existing
background-task-wake system marker rather than inventing a presentation, and
pins which `isMeta` records survive in a bridge test. The one likely ask is
to align with #10740's "From <agent>" treatment if that merges first.

**Route:** Bug issue + PR now; cite #10740 in the issue so a maintainer can
decide which presentation wins.

---

## 4. claude-native-subagent-status

**Carry cost:** 1 patch, +231/-3 (source +132: `claude_native/forwarder.py`
+113, `server/subagent_activity.py` +19). Churn **36**, but forwarder.py is a
9k-line file edited weekly (#10485 on 2026-10-21 changed the same
sub-agent-meta polling region), so conflicts are likely on every rebase.

**Prior art:**
- #4988 closed by #5834 (merged): "False 'sub-agent finished' notifications …
  5s transcript-quiescence heuristic". #5834 stopped the quiescence badge from
  driving *delivery*; `_SUBAGENT_IDLE_THRESHOLD_S = 5.0` still drives the
  Agents-rail status on upstream/main, which is exactly what our patch fixes.
- #9320 closed unmerged (dhruv0811, maintainer, 2026-10-06): "prevent false Done
  status during active work" — same symptom, closed by the stale bot after
  review blockers ("confirmed completion can leave a child marked Failed after
  a server restart"). Our server-side settle must not reintroduce that.
- #10485 merged 2026-10-21: stop re-reading unchanged transcripts while a
  sub-agent meta is unresolved — overlaps our mtime/size tail cache.
- #10318 open (kzarzycki, P1, assigned dbczumar): wake a sub-agent's parent
  however the child stops — touches the same status route; adjacent.
- #10396 open (codex pane reaping while a sub-agent works) — same class, other
  harness.
- Terms: "sub-agent idle", "subagent status running tool call", "Agents rail
  idle", "subagent idle", "sub-agent done while still working", "transcript idle
  sub-agent".

**Maintainer fit:** Good on substance: a reproducible bug (child runs `sleep
90`, rail shows idle), bounded tail reads, tests on each transcript shape.
Harness-specific but claude-native is the flagship. Risks: the closed #9320
shows a maintainer already tried and got blocked on restart semantics, so the
server-side settle in `subagent_activity.py` needs an explicit answer to that
review; and the forwarder change competes for the same lines as #10485.

**Route:** Bug issue + PR now, referencing #4988/#5834 (what was fixed, what
was not) and #9320 (why this differs). Consider landing the forwarder
classifier first and the server settle as a follow-up to keep review small.

---

## 5. codex-native-mode-instructions

**Carry cost:** 1 patch, +25/-106 (net negative; `runner/native_controls.py`
+4/-25, `codex_native/forwarder.py` +3/-1). Churn **28**.

**Prior art:**
- #8422 **open** (resolve agent, 2026-09-28, size/XL, `needs-demo`, no review
  decision): "offer Plan mode before launch and deliver Codex's Plan Mode
  instructions". Its body contains our fix verbatim: "Every collaboration-mode
  update now sends `developer_instructions: null`. The forwarder's tracking of
  that value and the bridge readers that fed it are gone." Bundled with a
  pre-launch Plan UI, server-side label checks and version gating across 29
  files; untouched for ~4 weeks.
- Upstream/main still sends the echoed value (`native_controls.py:814`).
- Terms: "codex plan mode developer_instructions", "codex collaboration mode
  instructions", "codex-native plan mode", "developer_instructions",
  "collaborationMode", "plan mode codex".

**Maintainer fit:** Excellent as a standalone: real bug, two-line cause,
removes code, cites the Codex app-server behaviour (`normalize_collaboration_mode`
since 0.129). The only question is etiquette: it is a slice of a stalled
resolve-agent PR, so say so and offer it as the small fix #8422 can rebase on.

**Route:** Bug issue + PR now (cheapest win on the list). Comment on #8422
linking it. Drop our copy if #8422 merges first.

---

## 6. session-labels-ui

**Carry cost:** 1 patch, +1853/-312 (source ~+1130 across 20 files;
`ProjectSettingsDialog.tsx` +302/-229 is a near-rewrite, `LabelEditor.tsx`
+323 new, server +80). Churn **246** (routes_core.py, schemas.py,
NewChatDialog.tsx, ProjectSettingsDialog.tsx all hot). Depends on
subscription-accounts in the series file, which blocks a clean PR cut unless
that dependency is only a merge-order artefact.

**Prior art:**
- #2117 / #2118 closed 2026-07 by btli (maintainer): session tags design —
  "Closing — keeping tags scoping internal for now; not soliciting upstream
  review yet." Signals an internal direction for tags that a labels UI could
  collide with.
- #8689 open (kadenbrooke, triaged, assigned TomeHirata) with two open
  resolve-agent PRs #8719 / #10418: Python client cannot update labels and the
  PATCH merge semantics are undocumented — our null-delete API change answers
  part of this.
- #10850 merged 2026-10-19: session validation refactor in routes_core (rebase).
- #5194 referenced in PR.md for the dialog height; not re-verified here.
- Nothing asks for a labels editor or project default labels. Terms: "session
  labels", "tags sessions", "project default labels", "labels editor", "labels
  web", "labels UI".

**Maintainer fit:** Mixed. The server half (delete a label with `null`,
project `config.labels` merged at create, `apply_project_labels`) is small,
harness-agnostic and fixes a documented gap (#8689). The web half is large,
rewrites a maintainer-owned dialog, and lands on top of a tags design the
maintainers deliberately kept internal. Expect "why not wait for tags" and
"split this".

**Route:** Feature issue first (use `proposals/session-labels-ui/issue.md`,
which already asks the #2117 question). Then PR the server parts alone
(~200 lines) as "labels can be deleted; projects can seed labels"; hold the
UI until the issue gets a direction. Big carry cost, so worth the ask.

---

## 7. claude-sdk-web-tools

**Carry cost:** 1 patch, +424/-5 (source +164 across 9 files: executor +54,
harness +44, datamodel +22, spec/parser/compat/loader +21, docs +19).
Churn **56**.

**Prior art:**
- #6529 **open** (resolve agent, 2026-09-05, "Resolves OMNI-4530"): withhold
  WebSearch on gateway-backed claude-native launches — confirms claude-native
  already exposes Claude's WebSearch and that the gateway gating our patch
  mirrors is a recognised concern. Unmerged after 7 weeks.
- #2071 closed by #5829 (merged): Omnigent's own `web_search` builtin now
  advertised to claude-sdk — the alternative a reviewer will raise ("use
  web_search"); our answer is that it needs a separate search backend/key.
- #8584 merged 2026-10-22: spec can opt out of framework-owned tool groups —
  touches `spec/omnigent.py`, `spec/parser.py`, `runtime/prompt.py` (rebase)
  and is the maintainers' precedent for a spec-level tool knob.
- #11137 merged 2026-10-21: claude-sdk `executor.config` system-prompt preset —
  precedent for new executor.config keys.
- Terms: "WebSearch WebFetch", "claude-sdk web search", "claude sdk built-in
  tools allowed", "WebFetch", "claude-sdk native tools".

**Maintainer fit:** Moderate. Opt-in, off by default, keeps the policy gate in
the loop, documented in AGENT_YAML_SPEC — all things they ask for. Against it:
harness-specific, adds a spec schema field (datamodel + compat + parser) for
two tool names, and the gateway heuristic (`ANTHROPIC_BASE_URL` not Anthropic
⇒ withhold) is the same open question #6529's author left "as a reviewer
decision".

**Route:** Feature issue first, short, citing #6529 and #5829 and asking
whether `executor.config.native_tools` or the #8584 tool-group mechanism is
the preferred shape. PR after a nod.

---

## 8. sidebar-attention-filter

**Carry cost:** 1 patch, +365/-18 (source +240: `Sidebar.tsx` +158/-18,
`sidebarNav.ts` +26, new preferences module +56). Churn **38**, all in
`Sidebar.tsx` (4.5k lines, edited ~weekly).

**Prior art:**
- `sidebar_grouping_ui` release flag (#9792 2026-10-12, #10433 2026-10-16,
  #10035, #10026): maintainers' own sidebar status grouping with a
  "Needs attention" bucket (`sidebarNav.ts:233`) and Created/Updated grouping.
  Our patch exists because that grouping is flagged and drops project
  folders; a maintainer will read it as a parallel mechanism for the same need.
- #9232 merged 2026-10-06 (TomeHirata): Inbox surfaces unread sessions with
  filter tabs — the maintainers' answer to "sessions that need me", on the
  Inbox surface, following a published UX prototype.
- #11079 open: sync read/unread across clients (same read-state we reuse).
- #1701 open: work items below Inbox.
- Terms: "sidebar filter needs attention", "sidebar unread sessions filter",
  "sidebar recently updated sessions", "sidebar filter", "needs attention
  sessions", "Inbox", "sidebar unread".

**Maintainer fit:** Weak. Clean and device-local, but it duplicates a flagged
feature the team is iterating toward a design, and `Sidebar.tsx` is their
most-touched UI file. Expect "fold this into the grouping flag" or "use the
Inbox".

**Route:** Keep local. Optionally one comment/issue asking whether the
grouping flag will keep project folders and add a time window; that is the
only path to dropping the patch.

---

## 9. pr-watch  (depends on subscription-accounts; prior art only)

**Carry cost:** 1 patch, +3398/-14 (source ~+2200: `server/pr_watch.py`
+974 new, routes +300, web +430, openapi +372). Churn **300**.

**Prior art:**
- #7717 / #7719 (dbczumar, merged 2026-09-18): Claude's own `Monitor`
  background tasks ("watching pull-request checks") are the expected way a
  claude-native session babysits CI; the composer indicator shows them.
- #5353 merged: resolve-agent drives its PR to a landable state (agent-side
  loop, not a server poller).
- #11161 / #11167 merged 2026-10-22 and #7746: the Pull Requests tab is being
  built out by maintainers right now (merge, reviewers, check pills), so
  `PullRequestPanel.tsx` churns.
- #11145 (automations v2 flag) and #11148 (scheduled-task dispatch) merged
  this week: a "poll until green, then wake the session" job is the kind of
  thing automations v2 may be meant to express.
- #10870 open (dhruv0811): keep PR details after workspace shutdown.
- No issue asks for a server-side PR watch. Terms: "watch pull request
  checks", "PR CI failing notify agent", "pull request review comments agent
  wake", "monitor pull request", "pr watch", "pull request checks poll".

**Maintainer fit:** Doubtful. Flagged off and harness-agnostic are in its
favour, and the trusted-author filter shows the prompt-injection risk was
considered. Against: a 1k-line server poller that autonomously messages
agents, state packed into reserved session labels instead of a table, and
overlap with Claude's Monitor and the new automations work.

**Route:** Feature issue first (problem statement, ask whether automations v2
is the intended home). Keep local; it is blocked on subscription-accounts
anyway.

---

## 10. chat-item-labels (+ chat-item-comments)

**Carry cost:** labels 1 patch +1975/-83 (source ~+1040, incl. `runtime/prompt.py`
+41 and native `--append-system-prompt` plumbing in `claude_native/main.py`,
`codex_native/main.py`, `runner/native/orchestration.py`); comments 1 patch
+4164/-153 (source ~+2650, web only + prompt.py +11). Churn **197** / **113**.
Also `gateway-request-tags` and `chat-features` are listed as needing it in
`patches/series` (merge-order dependency on the native instruction plumbing).

**Prior art:**
- None for bracketed item labels, chips, or a batched comment tray. Terms:
  "item labels chips", "refer back items long session", "open items panel",
  "chips chat markdown", "labelled items", "long conversation reference earlier
  message", "comment on items review", "inline comments chat message",
  "comments composer", "comment on agent message".
- Adjacent: #11299 open (kzarzycki, 2026-10-22) find-in-chat is the
  maintainers' answer to "finding the original detail in a long session".
  The existing review-comments feature (`entities/comment.py`, file-anchored
  comments with draft/addressed status, `list_comments`/`update_comment`
  tools, #8722 comment-only permission, #11171 thumbs feedback "modelled on
  review comments") is the comment primitive a maintainer would expect
  chat-item-comments to build on rather than localStorage drafts + a markdown
  convention.
- #8584 merged: `runtime/prompt.py` framework-instruction list was just
  refactored (rebase).

**Maintainer fit:** Poor. Invents a transcript convention (`[Q2]`, `~~[Q2]~~`)
with no existing standard, injects framework-owned prompt text into every
session on every harness by default with no flag (the flag is the blocked
chat-features series), reaches into both native harnesses' launch args, and
is 6k lines for a workflow most users will not recognise. Exactly the
"niche, prompt-text, bloat" trio the criteria warn about.

**Route:** Keep local. At most a feature issue describing the problem
(referring back to items raised earlier) to see if anyone bites, pointing at
#11299 as the partial answer. Do not open a PR.

---

## 11. chat-features  (depends on five blocked series; prior art only)

**Carry cost:** 1 patch, +3221/-86 across 75 files (source ~+1700 in 42
files). Churn **514** — the widest footprint of any series.

**Prior art:**
- #10519 open issue (andresgarciaf, triaged, assigned dhruv0811) with the
  4-PR stack #10837 → #10840 → #10856 → #10857 (open since 2026-10-19, behind
  a `code_block_run` flag): Run button on chat code blocks with streamed output
  and delivery to the agent's next turn. `proposals/run-suggested-commands/issue-retired.md`
  already records that this supersedes run-suggested-commands, which is the
  only feature chat-features toggles.
- #8584 merged 2026-10-22: per-spec opt-out of framework-owned tool groups —
  the maintainers' chosen shape for turning framework behaviour off is agent
  YAML, not a per-session UI toggle plus shared-preference default.
- Terms: "run suggested commands", "chat features toggle", "per-session
  instructions toggle", "chat features", "run code block", "code block run
  button", "system prompt per session setting".

**Maintainer fit:** Very poor: a generic toggle framework (server, runner,
native launch args, shared preferences, three UI surfaces) built for one
feature that upstream is replacing with a flagged implementation.

**Route:** Keep local. When the #10519 stack merges, drop
run-suggested-commands and chat-features together. If anything, a comment on
#10519 noting the "ask the agent to tag shell blocks as bash" instruction
angle, since #10857 only detects `$ `-prefixed untagged blocks.

---

## Ranked table

Rank = likelihood a maintainer merges × carry cost saved (patch size, churn,
conflict-prone files). The two cheap bug fixes (#5, #3) are the quickest to
land even though they save less.

| # | Series | Carry cost (patches / +lines / churn) | Fit | Route |
|---|--------|----------------------------------------|-----|-------|
| 1 | gateway-request-tags | 1 / +586 / 266 (hot executor + launch files) | Good; maintainer (yaoharry) is in the same code now; rebase on #11118 | File drafted issue now; PR after #11118 merges |
| 2 | session-history-paging | 1 / +772 / 121 | Good; additive, tested; split in two; note #11109 | Feature issue + PR(s) now |
| 3 | claude-native-coordinator-messages | 1 / +149 / 112 (tiny hunks) | Good; align with open #10740 | Bug issue + PR now |
| 4 | claude-native-subagent-status | 1 / +231 / 36 (forwarder.py conflicts) | Good; answer #9320's restart objection; cite #4988/#5834 | Bug issue + PR now |
| 5 | codex-native-mode-instructions | 1 / +25-106 / 28 | Excellent; is a slice of stalled #8422 | Bug issue + PR now; comment on #8422 |
| 6 | session-labels-ui | 1 / +1853 / 246 | Mixed; server half good, UI collides with internal tags (#2117) | Issue first (drafted); PR server parts only |
| 7 | claude-sdk-web-tools | 1 / +424 / 56 | Moderate; opt-in but harness-specific spec field; #6529 open on same gating | Feature issue first |
| 8 | sidebar-attention-filter | 1 / +365 / 38 (Sidebar.tsx) | Weak; duplicates flagged `sidebar_grouping_ui` + Inbox #9232 | Keep local; optional comment |
| 9 | pr-watch (blocked) | 1 / +3398 / 300 | Doubtful; competes with Monitor, PR tab work, automations v2 | Feature issue to test appetite; keep local |
| 10 | chat-item-labels + comments (blocked) | 2 / +6139 / 197+113 | Poor; unflagged prompt text, new convention, 6k lines | Keep local |
| 11 | chat-features (blocked) | 1 / +3221 / 514 | Very poor; superseded by #10519 stack | Keep local; drop when #10519 lands |

## Hazards spotted

- `upstream/main` moved past `patches/BASE` (449d608 → 39611f81): #8584
  touched `runtime/prompt.py`, `spec/parser.py`, `spec/omnigent.py` (hits
  claude-sdk-web-tools and chat-item-labels); #11226 touched
  `codex_native/app_server.py` (hits gateway-request-tags).
- Open resolve-agent PRs that contain pieces of our work and could land
  without warning: #8422 (codex plan mode), #6529 (WebSearch gating),
  #10740 (agent-sent message attribution), #10849 (delegate idle, already
  tracked by the claude-native-delegate-idle series).
- Open maintainer PRs that will conflict on rebase: #11118, #11099 (gateway),
  #10318 (sub-agent status route), #11109 (session-metadata reads), #11299
  (chat search; adjacent to history paging).
