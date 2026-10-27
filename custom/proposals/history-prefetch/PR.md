# perf(web): fetch scroll-up history ahead of its landing, in larger pages

Branch: `fix/history-prefetch` (cut from `upstream/main` @ 65be0f2468)

## Related issue

Closes #<issue from issue.md>

## Summary

Scrolling up through a long transcript stuttered, worst on a phone: history was paged 20 items at a time, the fetch only started once the pane was still, and every page cost a round trip plus a prepend hitch, so a reader paging back through a few hundred items hit the top and waited sixteen times over.

- The history loader now fetches the next older page as soon as a seeking gesture brings the pane within the load threshold, ahead of the landing decision (which on touch still waits for a fling to settle, so momentum is never interrupted). `loadMoreHistory` lands the prefetched page from memory. One page per cursor is ever in flight; a failed prefetch is forgotten so the reader's own request retries it; the page is dropped with its conversation.
- Scroll-up pages grow from 20 items to 100, or 60 on a mobile-width viewport (the shell's `useIsMobileViewport` breakpoint). Only the rows in view mount, so a page costs one request and one prepend whatever its size. On the seeded session a 100-item page is about 62 KB of JSON (60 items: 38 KB; 20 items: 14 KB). The per-gesture chaining budget is kept as 600 items rather than 30 pages, so a folded tool-heavy turn still cannot page the transcript in with the reader's hands off. The reconnect backfill keeps its 20-item page.

```
reader flicks up ──► pane within 2.5 viewports of the top
                       │
                       ├─ prefetchMoreHistory()   (now: page on the wire at once)
                       │
                       └─ pane still for 120 ms ─► loadMoreHistory()
                                                   lands the prefetched page from memory
```

Tried and dropped: a per-bubble-kind virtualizer height estimate (96 px prompt / 400 px reply instead of a flat 280 px). It did not reduce the landing shift on a still pane and is not part of this change.

## Test Plan

Unit (all pass, 880 tests across the four files):

```
cd web && pnpm exec vitest run src/pages/ChatPage.historyLoad.test.tsx src/store/chatStore.test.ts src/hooks/useIsMobileViewport.test.ts src/lib/sessionsApi.test.ts
cd web && pnpm exec tsc -b
```

- `ChatPage.historyLoad.test.tsx`: new "prefetches the page a finger-armed request is waiting to land" (prefetch fires while the touch hold is still waiting, landing follows the settle, the next page is prefetched once one lands inside the threshold) and "prefetches only for a gesture that asked for older history" (no prefetch on load or on the pane's own movement; withdrawn by a wheel-down). The two gesture-budget tests now derive the chained-page count from the 600-item budget and the page size.
- `chatStore.test.ts`: new tests for `prefetchMoreHistory` (one request per cursor, landed from memory by `loadMoreHistory`, failed prefetch retried silently, no prefetch while a page is in flight or after history is exhausted) and "sizes a scroll-up page to the viewport" (`limit=100`, `limit=60` under a mobile-width `matchMedia`). Existing scroll-up tests use the new `SCROLL_UP_HISTORY_PAGE_SIZE`; reconnect tests keep `SESSION_HISTORY_PAGE_SIZE`.
- `sessionsApi.test.ts`: `scrollUpHistoryPageSize` by viewport; `useIsMobileViewport.test.ts`: the new `isMobileViewport()` snapshot.

E2E (passes): the mobile runaway-paging guard, which also covers one-request-on-open and the bounded chain with the larger page:

```
uv run pytest tests/e2e_ui/mobile/test_touch_drag_bounded_history_paging.py --ui-skip-build
```

Manual, as a reader would: open a session with a few hundred items, scroll up with the wheel (desktop) or flick up (phone or a touch-emulating devtools profile). Before: the "Loading earlier messages…" row shows at the top every few screens and the pane waits on it; after: pages land while scrolling, and on a phone the spinner is gone by the time the fling stops. `pre-commit run --from-ref upstream/main --to-ref HEAD` is clean.

### Benchmark

Seeded session of 420 items (60 turns: prompt, reply, two `shell` calls with multi-line output, markdown summary), local server, headless Chromium, driven by the script in the evidence. Desktop: 1280x800, wheel notches of 120 px every 30 ms, 20 ms RTT. Phone: Playwright `iPhone 13`, CDP touch flicks of 400 px every 500 ms, 4x CPU throttle, 100 ms RTT. Each row is the run that reached the first turn; `main` numbers are from the same script on `upstream/main`.

| measure (how) | desktop before | desktop after | phone before | phone after |
| --- | --- | --- | --- | --- |
| history page requests to reach the first turn (fetch wrapper) | 16 | 4 | 16 | 6 |
| time stalled at the top waiting for a page, total / longest (frames with `scrollTop <= 1` ending in a prepend) | 0 / 0 ms | 0 / 0 ms | 2.5 s / 435 ms | 0.48 s / 479 ms |
| long tasks during the scroll, count / total (`PerformanceObserver` longtask) | 0–4 / ≤264 ms | 6 / 346 ms | 53 / 6.0 s | 17 / 2.5 s |
| landing shift on a still pane, largest (paused runs; rows' viewport offset across the prepend frame) | not measurable (wheel smooth-scroll never stills) | same | 137 px (typically 54) | 219 px |
| JSON fetched for the whole history | 191 KB | 189 KB | 191 KB | 189 KB |

The landing shift on a still pane is the transcript's existing prepend hold, unchanged here; it is larger with a larger page and is worth a separate look (see Coverage notes).

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Phone, flicking up through the seeded session (4x CPU, 100 ms RTT): `evidence/before-phone.webm` stops on the loading row at the top for each 20-item page; `evidence/after-phone.webm` keeps moving, six pages in all. Desktop wheel: `evidence/before-desktop.webm` and `evidence/after-desktop.webm`. Still of the phone stopped at the top on `main`: `evidence/before-phone-paused-stall.png`. Captions and the measurement script are in `evidence/README.md`.

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

The prefetch trigger, single flight, failure handling and page-size selection are unit tested; the existing mobile E2E covers the gesture budget with the larger page. Manual verification is the benchmark above, scripted but not a repository test: it measures timing, which the unit layer cannot. Not covered: a real phone over a real network (the phone numbers are an emulated viewport, CPU and RTT in headless Chromium), and the landing shift on a still pane, which this change leaves as it was.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Scrolling up through a long chat fetches older history ahead of the scroll position in larger pages, so pages land while you scroll instead of after you stop, with far fewer loading pauses on phones.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
