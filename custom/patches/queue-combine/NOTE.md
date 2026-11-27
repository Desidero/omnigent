# queue-combine

Needs: chat-item-comments
Covers: ba3bf8c897b5ec5a

When two or more adjacent queued messages can merge, the queue strip offers
**Combine** (one message: texts joined by a blank line, attachments kept) and,
where rows can be steered, **Send all** (combine, then steer the queue). Side
chats have the same actions.

- **Turn on:** on by default.
- **Docs:** [Queue and steer design](../QUEUE_STEER_DESIGN.md) ("Queue-wide actions") and [Composer](../../feature-map/composer.md) (`queue-combine`).
- **Upstream:** not proposed upstream yet.

## Must hold

- Combine merges each run of adjacent combinable messages of one conversation in queue order, in the first message's place; other conversations' entries keep their places.
- `!` shell commands, `/`-led messages, Codex `$` skills, failed sends awaiting retry and item-comment messages are never merged and nothing moves across them; a change of agent starts a new run.
- A merged message is a new submission: it gets a new idempotency id, is sent once under it, and the record kept for a reload holds it instead of the originals, so a reconnect or reload hands neither original back to the composer, and a reconnect after it was sent settles its one bubble from the item stored under the new id.
- A merged message waits for the host if any part did, and a side chat's merged message stays out of the reload record.
- Reply quotes stay editable when the merged text still reproduces them.
- Send all is disabled while the queue waits for an offline host; Combine still works.
- The item-comment rule is the only use of `chat-item-comments`: such a message's comment tracking matches the exact text it was sent with.

## Key code

- `web/src/lib/messageQueue.ts`: `combinedQueue`, `canCombineQueue`, `keepsQueuedMessageSeparate`, `mergeQueuedRun`
- `web/src/store/chatStore.ts`: `combineQueuedMessages`
- `web/src/pages/QueuedMessagesStrip.tsx`: `onCombine`, `onSendAll`, `showCombine`
- `web/src/pages/ChatPage.tsx`: `combineQueuedMessages`
- `web/src/components/chat/SideChatPane.tsx`: `combineQueuedMessages`

## Tests

- `web/src/lib/messageQueue.test.ts`
- `web/src/pages/QueuedMessagesStrip.test.tsx`
- `web/src/store/chatStore.test.ts`: the `combineQueuedMessages` tests, "keeps one record of a combined message, so a reconnect or reload hands nothing back" and "acks a combined message sent with Send all when reconnect backfills its item"
