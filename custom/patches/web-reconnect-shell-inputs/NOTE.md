# web-reconnect-shell-inputs

Needs: none
Covers: 43f25ad8bbf98a28

A queued `!command` no longer stays stuck at the bottom of the chat after the
connection drops and recovers.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/web-reconnect-settles-shell-inputs`.

## Must hold

- A queued `!cmd` bubble is settled when a reconnect recovers its `terminal_command` input item, on both reconnect paths: the incremental backfill and the fresh-window fallback.
- Each recovered item settles one bubble, matched by command, once per item id: a replay of the same item on the new stream does not settle a second, identical queued command.
- Shell bubbles are settled before the user-message FIFO acknowledgement, so that count does not land on a shell bubble, and other queued messages stay.
- The live `terminal_command` handler and both reconnect paths go through the same helper, so live settling behaves as before.

## Key code

- `web/src/store/chatStore.ts`: `settleRecoveredShellInputs`, `settleShellInput`, `reconcileOnReconnect`, `rehydrateWindowOnReconnect`

## Tests

- `web/src/store/chatStore.test.ts`
