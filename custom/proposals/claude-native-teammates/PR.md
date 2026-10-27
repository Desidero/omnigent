# fix(claude-native): register in-process teammates as child sessions

## Related issue

Closes #10745

## Summary

Claude Code agent-team teammates (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`) run inside the lead's process. Claude writes each one like any sub-agent, `subagents/agent-<id>.jsonl` plus `agent-<id>.meta.json`, but the meta carries `taskKind: "in_process_teammate"`, `name` and `teamName` and no `toolUseId`, because no tool call spawned it. `_read_subagent_meta` required a `toolUseId`, so the forwarder skipped every teammate on every poll. Teammates never appeared in the Agents rail, their transcripts were neither mirrored nor priced into the parent's real-time cost estimate, and each unregistered meta kept spawn correlation re-running for the life of the session (#10485 made that a stat per transcript instead of a full re-read, but the meta still never resolves).

The fix is forwarder-only:

- `_read_subagent_meta` accepts a meta without `toolUseId` when `taskKind` is `in_process_teammate`, returning an empty id, and returns the meta's `name` as its own field. Any other meta missing `toolUseId` is still rejected; a meta that carries both `taskKind: in_process_teammate` and a `toolUseId` goes through normal spawn correlation. The reader stays a plain reader: no presentation is baked into it.
- `_forward_available_subagents` registers a teammate under the lead session without spawn correlation. It builds the rail label there, leading with the teammate's `name` (the handle the lead messages it by), so the rail reads `differ: Version-diff pass on findings` rather than the bare task description. The server requires a non-empty `tool_use_id`, so the forwarder sends a stable `teammate:<subagent_id>` placeholder that no real spawn record can match. No server or schema change; existing servers accept it unchanged, and the placeholder is persisted as a label on the child row.
- Metas are read before correlation runs, so a poll with only teammate or unreadable metas skips the transcript scan entirely. (Previously a non-empty list of candidate meta *paths* triggered the scan; now only a candidate with a real `toolUseId` does. Harmless: the scan has been a memoised stat since #10485.)

On the issue's open question (which source to trust for the parent): a teammate is always parented to the lead session that owns the transcript, and `teamName` is not read. Claude's teams are flat (teammates cannot form sub-teams; `spawnDepth: 0` in every real meta), and the teammate's meta lives in the lead session's own `subagents/` directory, so the lead is the parent by construction. A Task sub-agent that a teammate spawns still registers under the teammate's child session through the normal correlation path.

A teammate never gets a "returned" / Completed notice: `record_claude_subagent_return` matches a child by its tool-use id against the parent's tool results, and the `teammate:<id>` placeholder never matches, so a teammate only reaches *idle* through the forwarder's 5 s quiet observation (`_SUBAGENT_IDLE_THRESHOLD_S`). That is the same behaviour #8779 had and is acceptable for teammates, which have no single completion event.

Known follow-ups, deliberately out of scope:

- Teammate messages Claude delivers to the lead (`Another Claude session sent a message:` + `<teammate-message>` + guidance) are recorded without an `origin` field and still render as raw user bubbles in the lead's chat. That is a bridge/authorship problem with its own fix (companion PR, filed separately).
- The lead's first `<teammate-message>` in the teammate's own child chat (now reachable thanks to this change) renders raw. The right fix is presentation, rendering the envelope as the task card the way Task sub-agents get one; web change, separate PR.
- No Completed notice for teammates, as described above.

## Test Plan

New and extended unit tests in `tests/harnesses/claude_native/forwarder/test_subagent_discovery.py` (forwarder layer with `httpx.MockTransport`, per `tests/harnesses/claude_native/forwarder/README`):

- `test_subagent_watcher_registers_an_in_process_teammate_under_the_lead` (parametrized): a teammate meta (no `toolUseId`, `taskKind: "in_process_teammate"`) is registered under the lead with `tool_use_id: "teammate:<id>"` and `parent_subagent_id: None`; spawn correlation is asserted not to run; a meta missing `toolUseId` for any other reason stays unregistered. The three cases pin the label: name and description -> `differ: Version-diff pass on findings`; blank name -> description alone; empty description -> name alone.
- `test_subagent_watcher_registers_a_teammate_spawned_subagent_under_the_teammate`: a teammate whose transcript holds a `Task` tool_use, plus a child meta with that `toolUseId`, registers the child under the teammate's child session (`/v1/sessions/conv_t-mate/events`, `parent_subagent_id == "t-mate"`); correlation runs exactly once, for the Task meta. Exercises `_subagent_own_spawn_tool_use_id` returning `None` for the teammate and the deferral ordering (child sorts before the teammate).
- `test_subagent_watcher_skips_subagents_already_in_state`: now also seeds a teammate in `subagent_forwarder.json` and asserts no second `external_subagent_start` for it on restart.
- `test_read_subagent_meta_returns_fields_as_written` (parametrized): teammate meta -> empty `toolUseId` plus `name`; blank name; empty description; teammate meta that also has a `toolUseId` keeps it (normal correlation); plain Task meta gets `name: ""`; missing `toolUseId` without the teammate `taskKind`, or with another `taskKind`, -> `None`.

Commands (OMNIGENT_* / RUNNER_SERVER_URL unset):

- `uv run python -m pytest tests/harnesses/claude_native/forwarder/ -q` — 376 passed
- `uv run python -m pytest tests/harnesses/claude_native/test_claude_native_bridge.py -q` — 578 passed
- `uv run python -m pytest tests/server/routes/test_native_message_authorship.py -q` — 20 passed
- `pre-commit run --files omnigent/harnesses/claude_native/forwarder.py tests/harnesses/claude_native/forwarder/test_subagent_discovery.py` — all hooks pass
- Manual: this change has run in our production deployment (0.18-based) since 2026-10-20. With an agent team running, each teammate appears in the Agents rail under its name, its chat opens, its id is present in the bridge directory's `subagent_forwarder.json` `subagents` map, and its transcript is included in the parent's real-time cost estimate. The mechanism was also checked against a real Claude Code 2.1.304 teammate meta (`taskKind: "in_process_teammate"`, `name`, `teamName`, no `toolUseId`): the reader returns the empty id and name, and `_subagent_own_spawn_tool_use_id` returns `None`.

To reproduce the fix by hand: start a Claude-native session with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, ask Claude to create a team with one in-process teammate and give it a task, then check the Agents rail (teammate listed under its name) and `~/.claude/projects/<project>/<session>/subagents/` (`agent-<id>.meta.json` has no `toolUseId`; its id is now in `subagent_forwarder.json`).

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

N/A for media: no frontend code changes. The registration event and resulting state are asserted in the unit tests above; the rail effect follows from the existing child-session rendering.

## Type of change

- [x] Bug fix
- [ ] Feature
- [ ] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [ ] E2E tests added / updated
- [x] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The unit tests cover the forwarder decision (teammate registered without correlation, placeholder tool-use id, name-led label and its edges, non-teammate meta without `toolUseId` still rejected), a teammate's own Task sub-agent nesting under it, restart idempotency for a teammate, and the meta reader's contract. Manual verification covered the end-to-end effect against a real Claude Code agent team: teammate rows in the Agents rail, openable child chats, and teammate transcripts counted in the parent's cost estimate. No E2E: no new process, transport or browser boundary.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Claude Code agent-team teammates now show up in the Agents rail as child sessions of the lead, and their spend counts toward the parent's real-time cost estimate

🤖 Generated with [Claude Code](https://claude.com/claude-code)
