<!-- Draft PR body for the claude-native-coordinator-messages series; title: fix(claude-native): show a parent agent's follow-ups in the sub-agent chat -->
## Related issue

Closes #TODO (issue to be opened)

## Summary

When a Claude parent agent sends a follow-up to a running sub-agent, the sub-agent's chat now shows that message, so you can see what the sub-agent is replying to.

When a parent messages a running sub-agent (`SendMessage` to a background agent or teammate), Claude records the message in the child's transcript as hidden context: `isMeta` with `origin: {"kind": "coordinator"}` and the text "The coordinator sent a message while you were working: ...". The bridge dropped every hidden record that was not a completion, so the child's chat showed the child answering a prompt nobody could see.

- **Bridge.** Coordinator-origin hidden records are kept as hidden (`is_meta`) messages instead of being dropped. Other hidden context is still dropped.
- **Web.** A hidden user message with Claude's coordinator framing renders as a muted `[System: Message from parent agent]` marker followed by the message body (Claude's trailing "Address this before completing your current task." is trimmed), the same treatment a background-task wake already gets. This applies both on history load (`itemsToBlocks`) and live (`session_input_consumed`), and the marker does not consume a queued web message.
- Messages in the parent's chat stay hidden, and a human typing the same text still gets an ordinary bubble.

## Test Plan

Tests added or changed:

- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_parent_follow_up_reaches_the_child_as_hidden_context`: coordinator-origin records are kept as `is_meta`, other hidden records are dropped (string and block content).
- `web/src/lib/itemsToBlocks.test.ts`: a hidden follow-up becomes the marker; a user-authored message with the same text stays verbatim.
- `web/src/store/chatStore.test.ts`: the existing background-task wake test is parameterized to cover the parent follow-up marker on the live path, without popping a pending message.

```sh
uv run pytest tests/harnesses/claude_native/test_claude_native_bridge.py
cd web && pnpm exec vitest run src/lib/itemsToBlocks.test.ts src/store/chatStore.test.ts
cd web && pnpm exec tsc -b
```

Manual:

1. In a claude-native session, ask: "Spawn a background sub-agent that runs `sleep 60` and then reports. While it runs, send it a message saying 'Also print the date when you finish.'"
2. Open the sub-agent from the Agents rail. Its chat shows a muted "Message from parent agent" marker with "Also print the date when you finish." just before its reply.
3. Reload the page: the marker is still there.
4. The parent's chat does not show the follow-up as a user bubble.

## Demo

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: before/after screenshots of a sub-agent chat, showing a reply with no visible prompt before and the "Message from parent agent" marker after (throwaway server, dummy task)

## Type of change

- [x] Bug fix
- [ ] Feature
- [x] UI / frontend change
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

The bridge test pins which hidden records survive; the web tests cover both the history and live rendering paths and confirm a human-typed copy of the text is not relabelled.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.
