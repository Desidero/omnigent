# Pre-PR review: claude-native teammate branches

Reviewed 2026-10-21 against `upstream/main` = eced2859d. Report only; no branch was modified.

Evidence used beyond the diffs:
- Real Claude Code 2.1.304 agent-teams transcripts on this machine:
  `<session transcripts>/de891190-c9ad-42fa-b847-5758f89bf966.jsonl` (+ `subagents/agent-ateammate-hello-2e27e88623a466c6.{jsonl,meta.json}`)
  and `<session transcripts>/174876f7-4385-4a2f-a073-d9bef2626a71.jsonl` (+ `subagents/agent-abuddy-8c42f4e0af3e69a1.*`).
  These are the only true in-process teammates on disk (`taskKind: "in_process_teammate"`, no `toolUseId`). The
  `teams-probe` session (2.1.303) is a *background subagent* (meta has `toolUseId`, `spawnDepth: 1`), not a teammate.
- Observed record shapes:
  - Teammate delivery to the lead (2.1.304): `type: user`, `version`, `entrypoint: cli`, **no `isMeta`, no `origin`,
    no `promptSource`**; text = `Another Claude session sent a message:\n<teammate-message teammate_id="…" color="blue">\n{"type":"idle_notification",…}\n</teammate-message>\n\nThat "other Claude session" is an agent working inside this same session — …permission laundering.`
  - Typed prompt (2.1.303/304/306): `origin: {"kind":"human"}`, `promptSource: "typed"`, `turnOrigin: "human"`.
  - Queued human prompt (`attachment.type == queued_command`, `commandMode: prompt`) on 2.1.303/304/306: `origin: {"kind":"human"}` (3 of 3 samples).
  - Background-subagent hand-back via SendMessage (2.1.303–2.1.306): `isMeta: true` + `origin.kind: "peer"` (already hidden upstream).
  - Records Omnigent itself re-materialises into the transcript (`omnigent/harnesses/claude_native/main.py`,
    `_claude_transcript_record_from_session_item`, ~L5840) carry **no `origin`, no `isMeta`, no `version`** (Python-style
    microsecond timestamps; e.g. sessions dd222afe, ea0cfec7). Both human prompts and peer deliveries lose provenance there.
- Dry-run merges onto `upstream/main` (`git merge-tree --write-tree --merge-base <base> upstream/main <branch>`): both clean.
- Tests run (OMNIGENT_*/RUNNER_SERVER_URL unset, `uv run --no-sync`):
  - children: `tests/harnesses/claude_native/forwarder/test_subagent_discovery.py test_subagent_status.py` -> 42 passed.
  - delivery: `tests/harnesses/claude_native/test_claude_native_bridge.py` (full module) -> 566 passed (worktree venv created with `uv sync --frozen --extra all --group test`).
  - Real 2.1.304 lead transcript through the delivery parser: teammate delivery -> `is_meta=True`, candidate False; typed prompt visible; hand-back + task-notification `is_meta`.
  - Real 2.1.304 teammate meta through the children reader: `{'agentType': 'teammate-hello', 'description': 'teammate-hello: Teammate says hello', 'toolUseId': ''}`; `_subagent_own_spawn_tool_use_id` -> `None`.

---

# Branch 1: `fix/claude-native-teammate-children` @ 49a4cd1f2

Base d7783c381 (2 commits behind upstream/main). One commit, forwarder only, +79 test LOC. Targets issue #10745.

## Verdict
**Ready after fixes** (small). The mechanism is correct on the real 2.1.304 fixture; the fixes are message/test completeness, not logic.

## Must fix
None blocking. Closest to one:

1. `omnigent/harnesses/claude_native/forwarder.py:1962-1967` — `_read_subagent_meta` now bakes presentation (`"<name>: <description>"`) into what is documented as the raw meta reader, and the function is also used by `_subagent_own_spawn_tool_use_id` (L2668) purely for correlation. Keep the reader pure (return `name` as its own key, like #8779 did) and build the display description next to the placeholder in `_forward_available_subagents` (L2802-2807), where the teammate special-casing already lives. Why: one place decides "this is a teammate", and a future server-side `name`/`task_kind` field (as #8779 proposed) slots in without re-reading metas. Suggested: `meta["name"] = name or ""`; in the loop `description = f"{name}: {desc}" if name and desc else name or desc`.

## Should fix
1. **PR text: state the parent assumption.** The issue's open question is "teamName or lead?". The branch always parents a teammate to the session that owns the transcript (`parent_subagent_id=None`, L2807) and ignores `teamName`. That is right for Claude's flat teams (teammates cannot form sub-teams; `spawnDepth: 0` in both real metas), but say so explicitly in the commit/PR so maintainers see it was decided, and mention `teamName` is left unread.
2. **PR text: no "Completed" notice for a teammate.** The server's `record_claude_subagent_return` / `_recorded_completion_status` (`omnigent/server/subagent_activity.py:124-135, 338-349`) match a child by its `omnigent.claude_native.tool_use_id` label against parent tool results. The placeholder `teammate:<id>` never matches, so a teammate only ever reaches *idle* via the 5 s quiet observation (`_SUBAGENT_IDLE_THRESHOLD_S`, forwarder L2496-2512), never *returned*. Same as #8779; acceptable, but document it, and note the placeholder is persisted as a label on the child row (no server change strips it, unlike #8779).
3. **Tests (forwarder layer, same file):**
   - nested: a teammate whose transcript contains an `Agent`/`Task` tool_use, plus a child meta with that `toolUseId` -> child registers under the teammate's `child_conversation_id` (exercises `_subagent_own_spawn_tool_use_id` returning `None` for the teammate, L2669, and the deferral loop ordering). Nothing covers the `or None` change today.
   - restart: a teammate already in `subagent_forwarder.json` is not re-posted (parametrize `test_subagent_watcher_skips_subagents_already_in_state` or add a teammate entry to it).
   - `_read_subagent_meta` unit cases: teammate with blank/missing `name` (description unchanged), empty description (name alone), and a meta with `taskKind: in_process_teammate` **and** a `toolUseId` (goes through normal correlation; a future Claude that stamps both would fall back to the old never-resolves behaviour — worth a test that pins the current intent either way).
   - the dead-letter payload for a teammate carries the placeholder (L2899 uses `meta["toolUseId"]` from the rewritten meta, which is right, but untested).
4. `forwarder.py:2796` — `any(meta["toolUseId"] for _, meta in candidate_metas)`: correct, and the test proves correlation is skipped. Behaviour change worth one sentence in the message: a poll whose only candidates are *unreadable* metas (mid-write) now also skips the scan; previously `candidate_meta_paths` being non-empty triggered it. Harmless (memoised stat-only since #10485).

## Nits
- `forwarder.py:1966` computes `name.strip()` three times; bind once.
- Test docstring says "a meta missing toolUseId for any other reason stays unregistered" — good; also assert that `fail_correlation` would have been called had a Task meta been present (a second parametrized case with one Task meta + one teammate meta, correlation runs once) to lock the "only teammates -> skip" rule from both sides.
- Commit trailer: this *is* the contribution branch, so no `Not upstream yet:` line is needed here; the `custom` cherry-pick copy will need it.
- Log line L2812-2820 still says "sub-agent"; fine, but consider `teammate` in the registration debug/log paths for grepability.

## Tests
- Layer is right (forwarder unit with `httpx.MockTransport`, per `tests/harnesses/claude_native/forwarder/README`); no E2E needed (no new process/transport boundary). The nightly e2e in #8779 (`tests/e2e_ui/agents/test_claude_native_teammates.py`) needed a `--settings` merge fix to enable teams per session; not required for this PR.
- 42/42 pass in the two relevant modules; 964 passed earlier today per the caller.

## Upstream drift
- Base d7783c381 -> upstream/main eced2859d: only 7c15cc683 (claude-native API-error keep) and eced2859d (preferences); no forwarder overlap. `merge-tree` clean (tree c8249f4e2). No rebase needed before opening the PR, but rebase anyway so CI runs on current main.

---

# Branch 2: `fix/claude-native-teammate-delivery` @ 9c4a266fd

Base f2b1006d8 (102 commits behind upstream/main). One commit, bridge only, +44 test LOC.

## Verdict
**Ready after fixes.** The rule is narrow and verified against a real 2.1.304 teammate record; the fixes are a small helper fold, a docstring accuracy tweak, and a real-fixture test.

## Must fix
None. Things I tried to break and could not:
- **Human text hidden?** Requires: record has no `origin` key at all, and text == one of the three prefixes + >=1 envelope + (optionally) Claude's guidance paragraph, nothing else (leading/trailing whitespace tolerated; `.startswith` on the guidance, so a trailing newline is fine). Claude 2.1.303+ stamps `origin.kind=human` on typed *and* queued prompts (verified), so a human pasting the exact wrapper stays visible there. On a build that omits `origin`, only a verbatim paste of the whole wrapper is hidden — and today that text renders as a raw markup bubble anyway. Acceptable.
- **`origin: null`**: `"origin" not in entry` treats an explicit null as attributed -> visible (safe direction).
- **Pasted content**: the check runs on the raw text before `_unwrap_pasted_content_markers` (L9193 vs L9262), so a `<pasted_content>`-wrapped paste never matches.
- **Quoted inner message with newlines / `summary="a > b"`**: `_TEAMMATE_MESSAGE_RE` is DOTALL and `[^>]*` stops at the first `>`, so `summary="a > b"` breaks the open-tag match -> visible (pre-existing limitation of the #8588 regex, not new; the real 2.1.304 attrs are `teammate_id`, `color`, `summary` without `>`).
- **Agent still receives everything**: this is the transcript *mirror*; hidden user records are still posted as `is_meta` items (user path) or dropped from the mirror like peer-origin queued prompts (attachment path, L8468-8471). Nothing feeds back into Claude.
- **Regex cost** (measured with the branch's `_peer_message_shape`): 1 MB envelope body 19 ms; 240 KB open tag with 40k attrs and no `teammate_id` 3 ms; 20k unterminated opens 7 ms; 200 envelopes + junk 0.2 ms. `.match` is anchored and the loop consumes, so it is linear; no catastrophic backtracking.
- **Turn boundary**: a hidden framed delivery keeps `current_response_id` (L9205-9209), unlike `<task-notification>` which returns `None`. When the lead was idle, the assistant output that follows still gets a fresh id + wake marker through `settled_response_id` (`_assistant_transcript_items_from_entry`, L9394-9421); mid-turn it continues the turn. #8779's explicit `_wakes_parent_turn` is therefore not needed; cosmetic difference: the web shows the generic scheduled-wake marker, not a "teammate delivered" marker.

## Should fix
1. `bridge.py:8468-8471, 9191-9195, 9286-9290` — the same two-predicate disjunction is written three times: `_is_trusted_agent_notification_text(text, origin=entry.get("origin")) or _is_unattributed_peer_delivery(text, entry=entry)`. Fold into one predicate that takes the record, e.g. `_is_internal_agent_text(text, entry)` (or give `_is_trusted_agent_notification_text` an `entry=` keyword and derive `origin`), so the policy has one home and the attachment/user/blocks paths cannot drift. Repo CLAUDE.md: reuse over repetition.
2. `bridge.py:8914-8917` docstring and the commit body claim "Claude Code stamps typed and pasted prompts `origin: {"kind": "human"}`". True for 2.1.303–2.1.306 (verified) but version-dependent; say "Claude Code 2.1.303+ stamps…; an older build that omits `origin` is protected only by the exact-framing rule". Also mention that `<system-reminder id=…>`-wrapped "while you were working" deliveries (seen in 2.1.306 transcripts, re-materialised without `isMeta`) are *not* matched (text starts with `<system-reminder`), so they still render raw if they are ever re-mirrored.
3. `bridge.py:8921-8923` — `_is_agent_notification_text` now reads `_peer_message_shape(text) is not None`; name the helper for what it returns (`_teammate_envelope_shape`?) since "peer" elsewhere in this file means the `origin.kind == "peer"` provenance, which this function explicitly does *not* check. Minor naming clash with `_is_unattributed_peer_delivery` too.
4. **Tests — add a real fixture** (unit layer, same module): the 2.1.304 idle_notification record from `de891190` (`<teammate-message teammate_id="teammate-hello" color="blue">` + JSON body + the second guidance variant `That "other Claude session" is an agent working inside this same session —`). Today every case uses the first guidance variant and a one-word envelope, so the variant actually emitted by current Claude Code is untested at the unit level (I only verified it ad hoc). Also add: blocks path with `[framed delivery, human text]` (first hidden, second visible — current behaviour, worth pinning), and `origin: None` explicit.
5. Rebase before opening: base is 102 commits behind. `bridge.py` has since changed in ee9dea822 (#10667), 60cec4b51 (#10965), 591a2b8c7 (#9880) — composer/injection code, not this region; merge-tree is clean (tree 5356d1a0c). Re-run the bridge module after the rebase.

## Nits
- `Literal["bare", "framed"]` is fine; a tiny `enum`/constants would avoid stringly return values, but it is internal.
- `test_team_markup_needs_provenance` now passes `origin={"kind": "human"}` for every case, so it no longer pins "framed + guidance *without* origin is a candidate" — that is intentional (it is now `is_meta`), but the new test only checks `_FRAMED_TEAMMATE_DELIVERY`; keep a comment on why the human origin was added.
- Commit message: "Typed and pasted prompts carry origin … both as user records and as prompts queued mid-turn" — add the Claude Code versions you observed (2.1.303–2.1.306) since the premise is empirical.
- Note for the PR: a future Claude Code that stamps teammate deliveries `origin.kind == "peer"` (as it already does for SendMessage hand-backs) makes this rule dormant, not wrong.

## Tests
- Right layer: parser unit tests via `_read_native_user`; no process/transport boundary, so no E2E. 566/566 pass on the branch.
- Covered: framed with/without guidance (str and blocks) -> `is_meta`, bare -> visible, framed + extra text -> visible, queued framed no-origin -> dropped and response id kept, queued framed with human origin -> visible + candidate, non-queued framed with human origin -> candidate (existing parametrized case).
- Missing: real-record fixture (above); blocks path mix; `origin: null`; server-side nothing new (items with `is_meta` already flow).

## Known gap: the teammate's own chat
Confirmed on the real teammate transcript `subagents/agent-ateammate-hello-2e27e88623a466c6.jsonl`: first record is
`{"type":"user","isSidechain":true,"agentId":"ateammate-hello-…","version":"2.1.304"}` with content
`<teammate-message teammate_id="team-lead" summary="Teammate says hello">\n…\n</teammate-message>` — no `origin`, no prefix,
no guidance. The branch classifies it `bare` -> `agent_message_candidate=True`; the server then stamps `user_authored: True`
(`omnigent/server/routes/_sessions/orchestration.py:3028-3031`, unconditional for candidates), and the web renders a user
bubble with raw markup (`web/src/lib/itemsToBlocks.ts:254`).

Cheap bridge-side fix exists but is the wrong shape: a sub-agent transcript has no TUI, so a record with `agentId`/`isSidechain`
can trust a bare envelope and mark it `is_meta` — but that *hides the teammate's task prompt entirely*, which is the one bubble
a reader wants in that chat (Task subagents show their task prompt the same way). The right fix is presentation: render the
envelope as the task card (use `summary=` as the title, inner text as the body), i.e. the web `teammateDeliveryMarker`-style
rendering #8779 added, or at minimum unwrap the envelope text for display. That is a web change plus possibly a bridge flag,
so **follow-up**, referenced from the children PR (which makes the teammate chat reachable and therefore makes this visible).

## Upstream drift
- `git log f2b1006d8..upstream/main -- omnigent/harnesses/claude_native/`: 966e5e0a1 (#10485 memoised spawn scan, forwarder),
  baf4bbfa2 (#10410 gateway attribution), d92a735ff (#11052 compaction context, forwarder/main), ee9dea822 (#10667 typed shell
  command, bridge), efabd5cb2 (#7854 model config), 60cec4b51 (#10965 injection refusal, bridge), 591a2b8c7 (#9880 composer
  clear, bridge), 9cfc94373 (#10259 OSC status). None touch `_is_agent_notification_text` / `_user_transcript_items_from_entry`.
  #10911 (initial prompt replay) is not in this range.
- `git merge-tree --write-tree --merge-base f2b1006d8 upstream/main fix/claude-native-teammate-delivery` -> clean, tree 5356d1a0c.

---

# One PR or two?

**Two PRs, cross-linked.**
- The children branch is forwarder-only, closes #10745 exactly as filed (rail + cost + polling), and needs no server/web change.
- The delivery branch is bridge-parser-only and fixes a different symptom (#7690's chat half, which #8588 fixed only for
  origin-stamped records). It should reference #7690/#8588 and #8779, and ideally a fresh issue with the 2.1.304 record shape.
- They do not touch the same files, so no ordering constraint; each is independently revertable and reviewable (#8779 bundled
  both plus a settings merge and web cards, and died in review budget — that is the cautionary tale).
- In each PR's "Known follow-ups": the teammate-chat raw first message, and the lack of a "Completed" notice for teammates.
