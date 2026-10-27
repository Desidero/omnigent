<!-- Title: fix(web): hold the reader's row while a streaming turn re-keys or re-measures rows -->
<!-- Branch: fix/transcript-hold-position (cut from upstream/main @ 65be0f2468) -->
## Related issue

Closes #<to be filed> (transcript jumps to the bottom while re-reading a reply that is still streaming)

## Summary

ELI5: when you scroll up a little to re-read a reply that is still being written, the page could suddenly jump to the end of the reply. Now the text you were reading stays put, whatever the model does below it.

- The virtualized transcript keeps native scroll anchoring off and relied on the virtualizer's own per-row scroll adjustment for in-list height changes. That heuristic misreads one common case: a streaming assistant bubble is keyed `responseId:0` until its first item gets a store-assigned id (when a tool call closes the streamed text), then remounts under the new key at the 280px size estimate. Its first measurement finds a row starting above the viewport top and the library scrolls by (height − 280px) although nothing moved: a reader inside the reply is thrown to its end (−1927px on a 1280×800 desktop, −7164px on an iPhone 14 viewport in the benchmark). The same heuristic also skips rows that merely span the viewport top and defers on iOS WebKit.
- Fix: the history-prepend hold becomes the one in-list hold. On every virtualizer change (its `onChange` fires once per measurement batch, synchronously before paint) and after every commit, the list compares the mounted rows with their list-relative offsets from the previous hold and moves `scrollTop` by how far the row that was first fully visible shifted (a row a history page renamed is still held by its bottom edge). The library's own adjustment is turned off for good, so nothing is counted twice; offsets are list-relative, so the existing list-offset compensation (content above the list) stays disjoint; a re-keyed row with the same content holds nothing, which is what happened on screen. The prepend path keeps its lock release and its synchronous measurement of the page's rows; follow-tail at the bottom and the native-find mode (`disableVirtualization`) are untouched.
- `holdAnchorRow` / `holdScrollDelta` are small pure helpers next to the existing snapshot helpers.

## Test Plan

Unit tests (new):

- `web/src/components/chat/Transcript.scrollRestore.test.ts`: anchor choice (first fully visible row, the row crossing the viewport top inside a tall reply, nothing after a long jump) and the delta (both directions, renamed row held by its end, gone row holds nothing).
- `web/src/components/chat/Transcript.virtualList.test.tsx`: through a mocked virtualizer, a row above the reader growing and shrinking moves `scrollTop` by the same amount via StickToBottom's state, a re-keyed row leaves it alone, and the library's own adjustment is off.

```sh
cd web && pnpm exec vitest run src/components/chat/Transcript.virtualList.test.tsx src/components/chat/Transcript.scrollRestore.test.ts
cd web && pnpm exec vitest run src/components/chat src/pages   # 45 files, 1592 tests
cd web && pnpm exec tsc -b
pre-commit run --from-ref upstream/main --to-ref HEAD
uv run --no-sync pytest tests/e2e_ui/chat/test_transcript_scroll_stability.py --ui-skip-build
```

Manual (mock model or any model that answers at length and then calls a tool):

1. Open a session with a few dozen messages. Send a prompt that gets a long reply followed by a tool call.
2. While the reply streams and is taller than the viewport, scroll up ~240px and stop. Before: when the tool call starts, the view jumps to the end of the reply. After: the lines you were reading stay where they are through the tool call and the rest of the stream.
3. Scroll up three screens into earlier turns while a turn with several tool calls streams: nothing moves (unchanged).
4. Scroll back to the bottom and send another prompt: the view follows the new reply (follow-tail re-engages).
5. Scroll up through older history so pages load: the read position holds as before (covered by `test_transcript_scroll_stability.py`).

Benchmark (Playwright script sampling a visible paragraph's `getBoundingClientRect().top` every frame while logging every programmatic `scrollTop` write; drift is its on-screen move by the end of the turn):

| Scenario | Before (drift / scroll writes) | After (drift / scroll writes) |
| --- | --- | --- |
| desktop 1280×800, inside the streaming reply, tool call lands | −1927px / 2 | 0px / 0 |
| iPhone 14 viewport, same | −7164px / 2 | 0px / 0 |
| desktop, three screens up in earlier turns, 8 tool calls + stream | 0px / 0 | 0px / 0 |
| iPhone 14 viewport, same | 0px / 0 | 0px / 0 |

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- `evidence/before-desktop-reread.webm`: the jump on `main` (desktop); stills `evidence/before-desktop-reread-1-scrolled-up.png` and `evidence/before-desktop-reread-2-after-turn.png`.
- `evidence/before-phone-reread.webm`: the same on the iPhone 14 viewport; stills `evidence/before-phone-reread-1-scrolled-up.png`, `evidence/before-phone-reread-2-after-turn.png`.
- `evidence/after-desktop-reread.webm`, `evidence/after-phone-reread.webm`: the same drive on this branch, the reply's start stays under the reader; stills `evidence/after-*-reread-2-after-turn.png`, and `evidence/after-*-reread-3-back-at-bottom.png` for follow-tail re-engaging.
- `evidence/after-desktop-3up-2-after-turn.png`, `evidence/after-phone-3up-2-after-turn.png`: reader parked in earlier turns, unchanged.

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
- [x] Manual verification completed
- [x] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The hold's decisions are unit-tested through pure helpers and a mocked virtualizer. The browser behaviour (a real remount, ResizeObserver batches, StickToBottom's lock) was verified with the recorded Playwright drives above on desktop and phone viewports in Chromium; the Playwright WebKit build could not be launched on the capture host, so iOS Safari is covered by the same code path rather than a recording. The existing `test_transcript_scroll_stability.py` E2E covers the history-prepend hold and streaming at the bottom, which this change reroutes through the same hold.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

The transcript no longer jumps while you re-read a reply that is still streaming

🤖 Generated with [Claude Code](https://claude.com/claude-code)
