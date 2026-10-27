# Codex review: web-reconnect-shell-inputs

Command: `codex exec -C <worktree> --sandbox read-only -` with the maintainer-review prompt, the repo's CLAUDE.md and `git diff -U40 <base>...HEAD` piped on stdin (`codex review --base` rejects a custom prompt, and the bundled bubblewrap sandbox cannot run commands in this environment, so the diff was supplied inline). Model: gpt-6.1-sol (codex-cli 0.159.2). Reviewed at the rebase onto upstream/main 3f2ccf56e.

## Disposition

1. [P1] Fresh-window fallback only settles shell inputs inside the newest `INITIAL_WINDOW_ITEMS` (100) items — **not fixed, documented**: the fallback runs only when `RECONNECT_BACKFILL_MAX_PAGES` (4) pages of `SESSION_HISTORY_PAGE_SIZE` (20) items did not reach the pre-gap transcript, and it then fetches exactly the newest 100 items, so the backfill pages are a subset of that window and carrying them over adds no coverage. A `!cmd` followed by more than 100 committed items in one disconnect is beyond any fetch that path makes, as it already is for the recovered user messages that path also never FIFO-acknowledges; settling it needs the server's pending queue in the snapshot, a separate change. Recorded under Coverage notes in the PR.

## Raw output

```
I’ll review the supplied diff for correctness and test gaps, using the included CLAUDE.md conventions. I won’t run shell commands. I’m Codex, based on GPT-6.
I’m Codex, based on GPT-6.

- **[P1] Fresh-window fallback still leaves gap-committed shell bubbles pending** — [web/src/store/chatStore.ts:5557](web/src/store/chatStore.ts:5557). Settlement only examines `freshBlocks`, which contains the newest `INITIAL_WINDOW_ITEMS`. If a shell input commits early during a long disconnect and enough output follows it, that input falls outside the replacement window. Its optimistic `!cmd` bubble remains pending indefinitely because its live acknowledgement was missed. The backfill can even have fetched that input before falling back, but those items are discarded without settlement. Carry recovered shell inputs into fallback settlement, including those outside the displayed window.

  The new fallback test misses this because it always places `shellInput` **last**. Add a case with the shell input early in the gap, followed by enough items to exclude it from the fresh window; assert that its pending bubble disappears and an identical second command stays pending.

Review is limited to the supplied diff; tests were not run. To verify manually, submit `!cmd`, disconnect before its acknowledgement, let enough subsequent output accumulate to exceed the reconnect window, then reconnect and check that the queued command bubble disappears.
```
