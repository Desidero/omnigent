# fix(claude-native): hide teammate deliveries Claude records without an origin

## Related issue

Closes #<to be filed> (issue draft: `issue-teammate-delivery.md`; the chat half of #7690, which #8588 fixed only for origin-stamped records and #8779 fixed together with the rail half before it was closed unmerged)

## Summary

When an agent-team teammate messages the lead, Claude Code writes the delivery to the lead's transcript as a plain `role=user` record: `Another Claude session sent a message:` (or the `while you were working:` variant when it is queued mid-turn), one or more `<teammate-message>` / `<agent-message>` envelopes, and Claude's own guidance paragraph, with no `origin` field at all. The bridge only trusted explicit provenance (`origin.kind == "peer"`, or a `<task-notification>`; #8588), so each delivery was persisted `user_authored` and rendered in the lead's chat as a raw user bubble full of markup and `{"type":"idle_notification",...}` JSON.

The fix is bridge-parser-only (`omnigent/harnesses/claude_native/bridge.py`):

- Claude Code 2.1.303 through 2.1.306 stamp typed and pasted prompts `origin: {"kind": "human"}`, both as user records and as `queued_command` prompts queued mid-turn. So a record (or queued prompt) with **no `origin` key** whose text is **entirely Claude's framing** (an optional delivery prefix, envelopes, optionally the trailing guidance, nothing else) is now treated as internal and mirrored `is_meta`, like other peer traffic. The agent still receives everything; this only affects the transcript mirror.
- Everything else keeps today's behaviour: a human-origin record renders as the user's message even if it contains the framing; an explicit `origin: null` is treated as attributed (visible); framing followed by extra text (a user who pasted a teammate message and asked about it) renders; a `<pasted_content>`-wrapped paste never matches because the check runs on the raw text.
- `_is_internal_agent_text(text, record=...)` is the single predicate the three mirror paths (queued prompt, user string, user text blocks) share, so the policy has one home. `_teammate_envelope_shape` classifies envelope text as `bare` / `framed` / `None`; `_is_unattributed_teammate_delivery` applies the no-`origin` rule.

On an older Claude Code build that omits `origin` everywhere, only a verbatim paste of the complete wrapper would be hidden, and that text renders as a raw markup bubble today anyway. A future build that stamps teammate deliveries `origin.kind == "peer"` (as it already does for SendMessage hand-backs) makes this rule dormant, not wrong. `<system-reminder>`-wrapped deliveries start differently and are not matched.

Known follow-ups, deliberately out of scope:

- The lead's first `<teammate-message>` in the teammate's own child chat (reachable once the companion forwarder PR for #10745 lands) still renders raw. That record is `bare` (no prefix, no guidance), so it stays a candidate; the right fix is presentation (render the envelope as the task card), a web change.
- Teammates never get a Completed notice (companion PR explains why).

## Test Plan

Unit tests in `tests/harnesses/claude_native/test_claude_native_bridge.py` via the existing `_read_native_user` parser helper:

- `test_claude_framed_delivery_without_origin_is_internal` (str and blocks): framed with guidance -> `is_meta`, not a candidate; framed without guidance -> `is_meta`; bare envelope -> visible; framed plus extra text -> visible.
- `test_real_claude_2_1_304_teammate_delivery_is_internal`: the verbatim `type: user` record Claude Code 2.1.304 writes for a teammate `idle_notification` (`userType: external`, `entrypoint: cli`, no `origin`/`isMeta`/`promptSource`, full guidance paragraph) -> `is_meta`, response id kept.
- `test_explicit_null_origin_keeps_framed_delivery_visible`: `origin: null` is attributed -> visible, candidate.
- `test_framed_delivery_block_beside_human_text_hides_only_the_delivery`: text blocks `[framed delivery, "What now?"]` -> the delivery is `is_meta`, the question renders as the user's message and ends the turn.
- `test_queued_framed_delivery_from_a_human_stays_visible`: a queued prompt with human origin and the framing -> visible, candidate.
- `test_internal_scaffolding_does_not_split_parent_response`: a queued framed delivery with no origin is dropped from the mirror and the active response id is kept.
- `test_team_markup_needs_provenance` now passes `origin: human` explicitly, so every shape stays visible when attributed.

Commands (OMNIGENT_* / RUNNER_SERVER_URL unset):

- `uv run python -m pytest tests/harnesses/claude_native/test_claude_native_bridge.py tests/server/routes/test_native_message_authorship.py -q` — 624 passed
- `pre-commit run --files omnigent/harnesses/claude_native/bridge.py tests/harnesses/claude_native/test_claude_native_bridge.py` — all hooks pass
- Manual: this change has run in our production deployment (0.18-based) since 2026-10-20. In a lead session with an agent team, teammate idle notifications and replies no longer appear as user bubbles in the lead's chat; typed prompts, pasted content and queued prompts render as before. The real 2.1.304 lead transcript was also run through the parser: the teammate delivery mirrors `is_meta`, the typed prompt stays visible, and the SendMessage hand-back and task notifications stay `is_meta`.

To reproduce by hand: start a Claude-native session with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, ask Claude to create a team with one in-process teammate and have it report back (or just go idle). Before: the lead's chat shows a user bubble with `<teammate-message ...>` markup and `idle_notification` JSON. After: no such bubble; the teammate's text still reaches Claude (its next assistant turn reacts to it). Send a message while a teammate is reporting to cover the queued (`while you were working`) variant, and paste a teammate message yourself with a question after it to see that it still renders as yours.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

N/A for media: no frontend code changes. The hidden/visible decision is asserted in the parser unit tests above, including the real 2.1.304 record.

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

The parser unit tests pin both sides of the rule (unattributed complete framing hidden; attributed, null-origin, bare and extra-text shapes visible) on the user-string, text-block and queued-prompt paths, with the real Claude Code 2.1.304 record as a fixture. Manual verification covered the lead's chat with a live agent team. No E2E: no new process, transport or browser boundary; items with `is_meta` already flow through the server unchanged (`tests/server/routes/test_native_message_authorship.py` passes untouched).

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Claude Code agent-team teammate messages no longer show up as raw user bubbles in the lead session's chat

🤖 Generated with [Claude Code](https://claude.com/claude-code)
