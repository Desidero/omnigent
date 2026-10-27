<!-- Draft PR body for the claude-native-subagent-status series; title: fix(claude-native): keep quiet sub-agents running until their turn ends -->
## Related issue

Closes #TODO (issue to be opened)

## Summary

A Claude sub-agent running a long command (a build, a test suite, a sleep) writes nothing to its transcript until the command returns. Omnigent took that silence as "idle" after five seconds, so the Agents rail showed the child idle or done while it was still working. It now checks how the child's transcript ends before calling it idle.

- **Turn-phase check.** Before reporting a quiet child idle, the forwarder classifies the end of its transcript:
  - a pending tool call keeps it running however long the tool takes;
  - a turn awaiting a model reply counts as idle only after ten quiet minutes (a live model call keeps writing records well within that);
  - a final reply (a `stop_reason` other than `tool_use`/`pause_turn`), a `SubagentHandback` result, or a user interrupt ends the turn;
  - a transcript with no readable message record keeps the old lull rule.
- **Cheap polls.** The tail read starts at 64 KiB and grows (up to 8 MiB) until it holds a message record; the result is cached by file size and mtime, and the check is skipped once the child is already idle.
- **Server-side settle.** A child killed mid-tool never writes a turn end, so the server now also settles a running or waiting mirrored child to idle (or failed) when the parent records that child's result. Deduplicated (retried) results are skipped, so a resumed child is not cut short.

## Test Plan

Tests added or changed:

- `tests/harnesses/claude_native/forwarder/test_subagent_status.py::test_quiet_subagent_is_idle_only_once_its_turn_ends`: pending tool, final reply, streaming reply, stalled reply, awaiting model, large tool output (tail growth), handback, interrupt, no messages.
- `tests/server/routes/test_subagent_activity.py::test_claude_completion_survives_retries_and_late_child_discovery`: a live result settles a running child once; a retry or a late-discovered child does not.
- `tests/harnesses/claude_native/forwarder/test_subagent_status.py`, `tests/harnesses/claude_native/forwarder/test_subagent_delivery.py`, `tests/e2e/test_subagent_status_compat_e2e.py`: existing idle tests now write `stop_reason: "end_turn"` on the final reply, as Claude does.

```sh
uv run pytest tests/harnesses/claude_native/forwarder/test_subagent_status.py tests/harnesses/claude_native/forwarder/test_subagent_delivery.py tests/server/routes/test_subagent_activity.py
uv run pytest tests/e2e/test_subagent_status_compat_e2e.py
```

Manual:

1. In a claude-native session, ask: "Spawn a sub-agent that runs `sleep 90 && echo done` with Bash and reports the output."
2. Watch the Agents rail: the child stays Working for the whole 90 seconds (before this change it flipped to idle after about five seconds), then goes idle once it replies.
3. Spawn another sub-agent running `sleep 600`, then interrupt the parent so the child is killed mid-tool. Once the parent records the child's result, the child leaves Working.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: short recording or before/after screenshots of the Agents rail during a 90-second sub-agent `sleep` (throwaway server, dummy task)
- [ ] TODO: attach the pytest output for the commands above

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
- [x] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The phase classifier is tested directly against transcript files covering each turn-ending and non-ending shape; the server settle path is tested through the external-item persistence route with retries and late child discovery. The E2E change only adds the `stop_reason` Claude writes.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.
