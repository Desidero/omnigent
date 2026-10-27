<!-- posted 2026-10-23: https://github.com/omnigent-ai/omnigent/issues/10986 (body) -->
Add to the issue body, after "Alternatives considered" (or as a short "Notes" section):

### Why the queue left the server, and why this doesn't undo that

Before July, a sent message went straight to the server and waited in the runner, where it couldn't be touched. #1911 was closed ("going to redesign this") and the client-side design in #1999 followed so that queued messages could be edited, deleted and reordered. A server-owned queue keeps that: the server holds the message *before* it reaches the runner, so edit, delete and reorder stay available until the message is dispatched. Only the place it waits changes.

### The design doc is out of date

`docs/QUEUE_STEER_DESIGN.md` says the queue is persisted in `localStorage` and survives a hard refresh. The web app has no such persistence today (nothing in `chatStore.ts` or `messageQueue.ts` writes the queue to storage), which is why #10951 exists. Worth knowing before anyone replies that reload is already covered.
