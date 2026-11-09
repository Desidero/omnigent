<!-- Draft PR body for the queue-combine series; title: feat(web): combine queued messages into one -->
## Related issue

Related to #10986 (server-owned queue: the merge is a pure function so it can move there), #4426 and #8326 (other steering ergonomics).

## Summary

Depends on: chat-item-comments (the strip's comment-message summary); would be rebased onto upstream's strip for upstream.

When several messages wait behind a running turn, steering sends each one as its own message, so the agent gets several partial steers instead of one combined instruction. This adds two queue-wide actions to the queue strip's header:

- **Combine** (shown when two or more adjacent messages can merge): each run of adjacent combinable messages becomes one message in its first message's place, texts joined by a blank line, attachments concatenated, reply quotes kept when they still match the joined text. The merged message gets a fresh idempotency id.
- **Send all** (shown with Combine where rows can be steered; disabled while a message waits for its host): Combine, then the existing steer-all, so the queue reaches the running turn in order.

Messages that must be sent as they are stay separate and in place: `!` shell commands, `/`-led commands, skills and paths (the harness reads the first text, see #11651), Codex `$` skills, failed sends that the server may already hold, and item-comment messages, whose drafts are tracked by their exact text. Nothing moves across such a message, so the runs on either side combine separately, and a change of agent starts a new run.

The merge is `combinedQueue(messages, { skillPrefix })` in `web/src/lib/messageQueue.ts`, a pure function over `QueuedMessage[]`; the store action `combineQueuedMessages` applies it to one conversation's slots of the flat queue. The header is one compact row ("N queued", Combine, Send all) whose buttons are 32px tall on phones with a 44px hit area.

Follow-up, not in this PR: drag one row onto another to merge just those two. It would be ambiguous with drag-to-reorder, especially on touch.

Docs: `docs/QUEUE_STEER_DESIGN.md` (Queue-wide actions), `feature-map/composer.md` (`queue-combine`).

## Test Plan

- `web/src/lib/messageQueue.test.ts`: order and blank-line join, attachments and empty texts, `!`, `/`, `$`, failed and item-comment messages kept in place, agent changes, host holds, reply quotes, the fewer-than-two case.
- `web/src/store/chatStore.test.ts`: the action merges one conversation's slots of an interleaved queue, assigns a fresh stableId and no-ops when nothing merges.
- `web/src/pages/QueuedMessagesStrip.test.tsx`: when the actions show and hide, Send all only with steering and disabled while waiting for the host, focus kept in the strip, touch sizing.
- New story `CombineAndSendAll`; its visual baseline still has to be generated.
- `tsc -b`.
