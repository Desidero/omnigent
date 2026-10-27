# fix(web): settle queued !cmd bubbles a reconnect recovers

## Related issue

Closes #<to be filed>

## Summary

ELI5: when you send `!cmd` from the web chat and your connection blips while it runs, the chat gets the command's result back but keeps showing your message as still queued until you reload. Now the reconnect clears it too.

- **Cause.** A `!cmd` sent to a claude-native or codex-native session gets no `session.input.consumed` receipt; its queued bubble clears only when the live `terminal_command` item event arrives. If the stream drops while the command waits or runs, that event fires into the dead socket. The reconnect backfill splices the committed item into the transcript, but it only acknowledges recovered user messages, so the bubble stays pinned to the bottom of the chat until a full reload.
- **Fix.** `chatStore.ts` now settles the bubbles of recovered shell inputs on both reconnect paths (the incremental backfill and the fresh-window fallback), using the same command match and per-item dedupe as the live handler, which now shares the `settleShellInput` helper. Shell bubbles are settled before the user-message FIFO acknowledgement, so that count no longer lands on a shell bubble.

## Test Plan

- New unit test in `web/src/store/chatStore.test.ts`: "settles a queued !cmd bubble whose shell input the reconnect recovers through $path", parameterised over both reconnect paths. Fails on `main`, passes here.
- `web/`: `vitest run src/store/chatStore.test.ts`: 1 file, 718 passed.
- `web/`: `tsc -b` (the `web-tsc` pre-commit hook) passes; `web-prettier`, `web-oxlint`, `custom-lint` and the generic hooks pass on the changed files.

```sh
cd web && pnpm vitest run src/store/chatStore.test.ts && node_modules/.bin/tsc -b
```

Manual: in a claude-native web session send `!sleep 20 && echo done`, go offline in DevTools for ~5 s while it runs, go back online. After the reconnect the terminal command and its output render and the queued bubble is gone, without a reload.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Store-only change with no new visual elements; the parameterised unit test above reproduces the stuck bubble on `main` and its removal here.

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

The store test drives the real reconnect reducers with a recovered `terminal_command` input on each path; no browser boundary is involved, so no e2e was added.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
