<!-- Draft PR body for the claude-native-subagent-status series; title: fix(claude-native): settle a mirrored sub-agent when its parent records the result -->
> Status: not filed. The series was shrunk at the 2026-11-24 refresh: upstream fixed the other half (a sub-agent in a long tool call no longer flips to idle) in #13811, so only the server-side settle below is left. The open upstream PR #12411 (not ours) changes the same function; check it before filing.

## Related issue

Closes #TODO (issue to be opened)

Related: #13811 (merged; the forwarder now keeps an open turn running for up to 600 seconds), #12411 (open).

## Summary

A mirrored Claude sub-agent that is killed in the middle of a tool call never writes a turn end. Since #13811 the forwarder keeps such a child "running" until its 600-second mid-turn window runs out, although the parent already holds the child's result, so the Agents rail shows a finished child as Working for up to ten minutes.

- **Server-side settle.** When the parent records a child's result, the server settles a child that is still running or waiting: idle for a completed result, failed for a failed one (`failure_origin="claude_subagent_result"`).
- **Retries are skipped.** A deduplicated (retried) result may predate a resumed run of the same child, so it settles nothing and a resumed child is not cut short.
- **Nothing else changes.** A child that already reported idle or failed is left as it is; the forwarder's own idle rules are upstream's.

## Test Plan

Test changed:

- `tests/server/routes/test_subagent_activity.py::test_claude_completion_survives_retries_and_late_child_discovery`: a live result settles a running child once (idle, or failed for a failed result); a retry or a late-discovered child settles nothing.

```sh
uv run pytest tests/server/routes/test_subagent_activity.py
```

Manual:

1. In a claude-native session, ask: "Spawn a sub-agent that runs `sleep 600` with Bash."
2. While the child is Working, interrupt the parent so the child is killed mid-tool.
3. Once the parent records the child's result, the child leaves Working in the Agents rail (before this change it stayed Working until the forwarder's ten-minute window ended).

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: short recording or before/after screenshots of the Agents rail after a sub-agent is killed mid-tool (throwaway server, dummy task)
- [ ] TODO: attach the pytest output for the command above

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
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The settle path is tested through the external-item persistence route, with a live result, a retried result and a late-discovered child, for completed and failed results.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.
