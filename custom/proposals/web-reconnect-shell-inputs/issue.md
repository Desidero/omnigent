# [Bug] web: a queued `!cmd` bubble stays pinned to the bottom of the chat when the stream drops while the command waits or runs

### Description

In a claude-native or codex-native session, a `!cmd` sent from the web composer shows as a queued user bubble. Unlike a normal message it never gets a `session.input.consumed` receipt: the bubble clears only when the live `terminal_command` input item event arrives on the SSE stream. If the stream drops while the command is queued or running (a phone locks, a laptop sleeps, a proxy recycles the connection), that event fires into the dead socket. On reconnect the backfill splices the committed `terminal_command` item into the transcript, so the command and its output render correctly, but the queued `!cmd` bubble is left behind, pinned to the bottom of the chat as if still pending, until a full page reload.

Cause: in `web/src/store/chatStore.ts`, both reconnect paths (the incremental backfill and the fresh-window fallback) acknowledge only recovered user `message` items against the pending FIFO. Recovered `terminal_command` inputs are not matched to their `!cmd` bubble, and the FIFO count can even land on a shell bubble and pop the wrong one. Only the live `item` handler knows how to settle shell bubbles.

Proposed fix: share the live handler's settle logic (command match + per-item-id dedupe via `settledShellInputs`) and run it over the recovered blocks on both reconnect paths, before the user-message FIFO acknowledgement so that count never lands on a shell bubble. Patch ready on `fix/web-reconnect-settles-shell-inputs`.

Prior art checked: #10667 (clear a typed shell command that blocks web input) fixes Claude Code's input box being stuck in shell mode on the runner side; #10649 (re-announce idle status for sessions a reconnecting runner defers) fixes a stale "Working" state after a runner restart. Neither touches the web store's reconnect backfill, which is where this bubble is left behind. #8104 and #6588 deal with pending user messages and steered messages, not with shell inputs that get no consumed receipt.

### Steps to reproduce

1. Open a claude-native (or codex-native) session in the web chat view.
2. Send `!sleep 20 && echo done` from the composer; the bubble shows as queued.
3. While it runs, drop the SSE stream: go offline in DevTools for a few seconds, lock the phone, or kill the proxy connection; then come back online.
4. The reconnect backfills the transcript: the `!sleep 20 && echo done` terminal command and its `done` output appear.

Expected: the queued `!sleep 20 && echo done` bubble is gone, replaced by the committed terminal command item.

Actual: the committed item is rendered and the queued bubble remains at the bottom of the chat as a pending message until the page is reloaded.

Automated: `web/src/store/chatStore.test.ts` "settles a queued !cmd bubble whose shell input the reconnect recovers through <path>" (both reconnect paths) fails on `main` and passes with the fix.

### Version

main @ 39611f812

### Harness

Claude

### Harness mode

Native

### Platform or device

Linux

### Observed impact

Some users or sessions

### Authentication type

Not authentication-related
