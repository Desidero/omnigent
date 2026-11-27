# claude-native-coordinator-messages

Needs: none
Covers: 55d0a9904c677d11

A parent agent's follow-ups to a running Claude sub-agent appear in the
sub-agent's chat as "Message from parent agent".

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/claude-native-coordinator-messages`.

## Must hold

- A hidden (`isMeta`) record in a sub-agent's transcript with `origin: {"kind": "coordinator"}` is kept as a hidden (`is_meta`) user message; other hidden context that is not a completion is still dropped.
- The web UI shows that message in the sub-agent's chat as a `[System: Message from parent agent]` marker followed by the parent's text, without Claude's framing prefix and trailing guidance line, both in loaded history and for live events.
- A live marker does not consume a queued web message, and every other hidden message stays hidden.
- The same text typed by a human (not hidden) renders as an ordinary user message.

## Key code

- `omnigent/harnesses/claude_native/bridge.py`: `_is_coordinator_origin`, `_user_transcript_items_from_entry`
- `web/src/lib/systemMessage.ts`: `coordinatorMessageMarkerContent`, `COORDINATOR_MESSAGE_PREFIX`
- `web/src/lib/itemsToBlocks.ts`: `itemToBlock`, `coordinatorMessageMarkerContent`
- `web/src/store/chatStore.ts`: `userContentFromEvent`

## Tests

- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_parent_follow_up_reaches_the_child_as_hidden_context`
- `web/src/lib/itemsToBlocks.test.ts`
- `web/src/store/chatStore.test.ts`
