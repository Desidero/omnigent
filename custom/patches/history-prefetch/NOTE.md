# history-prefetch

Needs: none
Covers: 997cfb9095ef1016

The next older page of history is fetched as soon as a scroll-up comes near
the top, ahead of the moment it is shown, so paging back through a long
transcript stalls less. One gesture can page in at most 600 items with your
hands off.

- **Turn on:** on by default.
- **Docs:** none (performance).
- **Upstream:** proposed from `fix/history-prefetch` (upstream PR [#13257](https://github.com/omnigent-ai/omnigent/pull/13257)).

## Must hold

- A scroll-up gesture that brings the pane within the load threshold starts fetching the next older page at once, before the loader decides to land it; `loadMoreHistory` then lands that page from memory with no second request.
- One page per cursor is ever fetched: a repeat prefetch for the same cursor, one while a page is loading, or one after history is exhausted does nothing.
- A prefetch shows nothing (no rows, no loading row). A failed one is forgotten silently and the reader's own request fetches the page again; a prefetched page is dropped with its conversation.
- Only a gesture asking for older history prefetches: opening a conversation, the pane moving on its own or a downward gesture never does.
- One gesture chains at most 600 items beyond its first page (six 100-item pages), counted in items so a larger page size does not raise the bound.

## Key code

- `web/src/store/chatStore.ts`: `prefetchMoreHistory`, `prefetchedHistoryPages`, `fetchOlderHistoryPage`, `loadMoreHistory`
- `web/src/components/chat/chatBubbleParts.tsx`: `HistoryAutoLoader`, `prefetchArmedRef`, `SEEK_ITEMS_PER_GESTURE`

## Tests

- `web/src/store/chatStore.test.ts` ("lands a prefetched page from memory and never fetches the same cursor twice", and the two tests after it)
- `web/src/pages/ChatPage.historyLoad.test.tsx` ("prefetches only for a gesture that asked for older history", and the item budget counts)
- `tests/e2e_ui/mobile/test_touch_drag_bounded_history_paging.py::test_one_touch_drag_loads_bounded_history`
