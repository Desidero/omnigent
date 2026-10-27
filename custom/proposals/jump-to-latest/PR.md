<!-- Title: feat(web): offer a jump to the latest message with a new-reply signal -->
<!-- Branch: feat/transcript-jump-to-latest (cut from upstream/main @ 65be0f2468) -->
## Related issue

Closes #<to be filed> (jump back to the latest message with a signal when new content lands while scrolled up)

## Summary

ELI5: when you scroll up in a chat, the page stops following new messages. Now a small pill at the bottom edge tells you when something new arrived below ("New reply", "3 new messages") and takes you back there with one click.

- Scrolling up releases `use-stick-to-bottom`'s follow-tail, as it should, but the only way back was the stock `ConversationScrollButton`: an unlabeled arrow icon rendered 16px inside the scroll container, inside the 32px scroll fade, with no notification state and no accessible name (`evidence/before-phone-1-streaming-scrolled-up.png`).
- New `JumpToLatestButton` (`web/src/components/chat/JumpToLatestButton.tsx`) replaces it in `Transcript.tsx`. It reads the library's `isAtBottom` from `useStickToBottomContext` (the same state that drives follow-tail, so no scroll math of its own) and renders through a portal into the conversation wrapper, as the Jump-to-top pill does, so the fade mask does not touch it. Labels: "Jump to latest" while merely away; "New reply" while a turn streams below the reader; "N new messages" once distinct user/assistant messages have been appended after the last complete message the reader saw at the bottom. A reply still streaming when they scrolled away counts once it completes; older history paged in above never counts; a conversation switch re-baselines instead of reporting everything as new. The attention state uses the filled primary button, the idle state the outline pill of the top edge.
- Click (or Enter on the focused pill) scrolls to the bottom instantly, pins again a frame later for the rows that mount, and clears `escapedFromLock` so the next resize keeps following. Always visible while away on desktop and touch alike: a phone has nothing to hover, and on desktop the pill is the only visible sign that follow is off; it sits over the faded band, not over readable text. It appears only after a 300ms settle, so the mount pin, a deep-link scroll or a momentum bounce never flash it.
- `transcriptMessageKeys`, `lastSettledMessageKey`, `countNewMessages` and `jumpToLatestLabel` are pure helpers next to the component.

## Test Plan

Unit tests (new, `web/src/components/chat/JumpToLatestButton.test.tsx`): the message keys (one per user turn and per assistant response, system markers skipped), the settled baseline (a streaming reply is not seen), the count (suffix after the baseline, prepends ignored, missing baseline asks for a re-baseline), the labels, and the pill itself inside the real `Conversation` context with a simulated scroll-away: hidden at the bottom and before the settle, shown after it, "New reply" then "1 new message" then "3 new messages", no count for a prepend or a replaced conversation, click and Enter return to the bottom and hide it.

```sh
cd web && pnpm exec vitest run src/components/chat/JumpToLatestButton.test.tsx
cd web && pnpm exec vitest run src/components/chat src/pages src/components/ai-elements   # 56 files, 1744 tests
cd web && pnpm exec tsc -b
pre-commit run --from-ref upstream/main --to-ref HEAD
```

Manual (any model, or the mock model from `tests/e2e_ui`):

1. Open a session long enough to scroll. Send a prompt that gets a long reply; while it streams, scroll up two screens. A filled "New reply" pill appears centered just above the composer within half a second; the stock arrow is gone.
2. Let the reply finish: the pill reads "1 new message". From another tab on the same session send a message: the pill reads "3 new messages" once the reply lands.
3. Click the pill: the view lands at the bottom and the pill fades out. Send another prompt from the other tab: the view follows the new reply (follow-tail re-engaged).
4. Scroll up a little and stop: an outline "Jump to latest" pill; Tab reaches it, Enter jumps.
5. Open a session via a `?message=` deep link and switch between sessions: no pill flashes during the landing scroll.
6. Phone (DevTools device emulation or the shell): same pill, always visible while away.

Benchmark (`bench/jump.py`: a `scrollTop` spy on the scroll container while the reader is two screens up through a streamed reply and another client's turn; same drive before and after):

| Measure | Before desktop | After desktop | Before phone | After phone |
| --- | --- | --- | --- | --- |
| programmatic scroll writes while away | 0 | 0 | 0 | 0 |
| scrollTop drift while away | 0px | 0px | 0px | 0px |
| affordance shown while away | arrow, no label, in the fade | "New reply" → "1 new message" → "3 new messages" | same | same |
| distance from the bottom after the affordance | 1px | 1px | 1px | 1px |

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- `evidence/before-desktop-1-streaming-scrolled-up.png`, `evidence/before-phone-1-streaming-scrolled-up.png`: `main`, reader scrolled up while a reply streams; only the faded unlabeled arrow.
- `evidence/before-desktop-3-new-messages.png`, `evidence/before-phone-3-new-messages.png`: `main`, three messages landed below, nothing changed.
- `evidence/after-desktop-1-streaming-scrolled-up.png`, `evidence/after-phone-1-streaming-scrolled-up.png`: the "New reply" pill.
- `evidence/after-desktop-2-after-stream.png`: "1 new message"; `evidence/after-desktop-3-new-messages.png`, `evidence/after-phone-3-new-messages.png`: "3 new messages".
- `evidence/after-desktop-4-after-return.png`, `evidence/after-phone-4-after-return.png`: after the click, at the bottom, pill hidden; `evidence/after-desktop-5-follow-tail.png`, `evidence/after-phone-5-follow-tail.png`: a later streamed turn is followed.
- `evidence/before-desktop.webm`, `evidence/after-desktop.webm`, `evidence/after-phone.webm`: recordings of the drives.

## Type of change

- [ ] Bug fix
- [x] Feature
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

The counting, labelling and the pill's show/hide/click behaviour are unit-tested against the real StickToBottom context with a simulated scroll container. The browser behaviour (the library's scroll handlers, the virtualized rows mounting during the jump, the portal placement relative to the fade and the composer) was verified with the recorded Playwright drives on desktop and the iPhone 14 viewport in Chromium; the Playwright WebKit build could not be launched on the capture host, so iOS Safari is covered by the same code path rather than a recording. The existing transcript tests (`Transcript.*.test.ts(x)`, `chatBubbleParts.test.tsx`, `src/pages`) pass unchanged.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

A "Jump to latest" pill shows when you scroll up in a chat and tells you when a new reply or new messages arrive below

🤖 Generated with [Claude Code](https://claude.com/claude-code)
