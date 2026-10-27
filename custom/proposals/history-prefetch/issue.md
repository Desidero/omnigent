# [Bug] Scrolling up through a long transcript stutters, worst on a phone: a 20-item page is fetched only once the pane is still, then prepended with a hitch

### Description

Scrolling back through the history of a long session is choppy. On a desktop with a wheel it reads as a stutter every screen or two; on a phone it is the main way to re-read an agent's earlier work, and every flick that reaches the top of what is loaded stops dead on "Loading earlier messages…" for a beat before the next slice appears, with a visible shift when it lands.

Cause, from `web/src/components/chat/chatBubbleParts.tsx` (`HistoryAutoLoader`) and `web/src/store/chatStore.ts` (`loadMoreHistory`):

- Older history is paged in 20 items at a time (`SESSION_HISTORY_PAGE_SIZE` in `web/src/lib/sessionsApi.ts`), while the open loads 100 (`INITIAL_WINDOW_ITEMS`). A turn with a prompt, a reply and a couple of tool calls is 5–7 items, so a page is three or four turns, roughly one phone screen. Paging a few hundred items back takes about one round trip plus one prepend per screen read.
- The fetch is armed by a gesture and fires when the pane is within 2.5 viewports of the top, which is fine on a desktop. On touch, the request is deliberately held until the pane has been still for 120 ms (so a page landing mid-fling does not kill the momentum), and only then does it go to the network. The round trip therefore starts after the reader has stopped, so the reader waits for the whole fetch plus the prepend render every time.
- Each prepend is a store update plus a transcript re-render, which on a phone-class CPU is a 100–400 ms main-thread task. With 20-item pages that hitch repeats sixteen times over a 420-item session.

The transcript's own prepend hold (`web/src/components/chat/Transcript.tsx`) keeps the read position well across a landing; the problem is how often and how late pages land, not where.

Proposed fix (patch ready on `fix/history-prefetch`):

1. Fetch the next older page as soon as a seeking gesture brings the pane within the load threshold, before the landing decision, and have `loadMoreHistory` land it from memory. One page per cursor is in flight at a time; a failed prefetch is forgotten and the reader's own request retries it. The touch settle hold still governs the landing, so a fling is not interrupted.
2. Raise the scroll-up page to 100 items, 60 on a mobile-width viewport (the shell's existing `useIsMobileViewport` breakpoint). Only the rows in view mount, so a page costs one request and one prepend whatever its size; a 100-item page of mixed prompts, replies and tool output is about 60 KB of JSON on the seeded session below.

Prior art checked: the per-gesture page budget and touch settle hold in `HistoryAutoLoader` (and `tests/e2e_ui/mobile/test_touch_drag_bounded_history_paging.py`) address runaway paging on folded tool-heavy turns, not the latency or granularity of ordinary paging. No open issue or PR prefetches history pages or sizes them to the viewport.

### Steps to reproduce

1. Seed a session with a few hundred mixed items (the script under `bench/` in the PR evidence creates 60 turns of prompt, reply, two `shell` calls with multi-line output and a markdown summary: 420 items) and open it at `/c/<session_id>`.
2. Desktop (1280x800): hover the transcript and wheel up steadily in 120 px notches every 30 ms until the first turn is at the top.
3. Phone (Playwright `iPhone 13` descriptor, CDP touch flicks of 400 px every 500 ms, 4x CPU throttling, 100 ms added RTT): flick up until the first turn is at the top.
4. Count `/v1/sessions/<id>/items` requests, time spent with `scrollTop <= 1` while a page is pending, and `longtask` entries during the scroll.

Expected: pages arrive before the reader reaches the top; a few requests cover the whole history; no stop at the top.

Actual on `main` (median of two runs, measured by the script in the PR evidence):

| | desktop | phone |
| --- | --- | --- |
| history page requests to reach the first turn | 16 | 16 |
| time stalled at the top waiting for a page (total / longest) | 0 / 0 ms | 2.5 s / 435 ms |
| long tasks during the scroll (count / total) | 0–4 / up to 264 ms | 53 / 6.0 s |

The phone recording in the PR evidence shows the spinner row at the top with the pane stopped, repeated for each page.

### Version

main @ 65be0f2468

### OS

Ubuntu 24.04 (server and headless Chromium)

### Harness

Not applicable

### Harness mode

Not applicable

### Platform or device

Linux, iOS, Android

### Observed impact

Most users or sessions

### Authentication type

Not authentication-related
