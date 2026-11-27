# open-items-filters

Needs: open-items-panel
Covers: 1c041fa9ba35a1a0

The Open items panel gets a search box and one row of chips (Open,
Answered and Closed with counts, the kinds present, the topics in use) once
it holds five items or more, and groups items by status, topic or kind. The
grouping is remembered per browser; the search, chips and folds survive
closing the panel. On a phone the search stays first in the sheet and the
chips scroll sideways in one row.

- **Turn on:** on by default with `open-items-panel`, on a server that stores
  open items; the chat-only panel is unchanged.
- **Docs:** [Open items](../open-items.md) (In the web UI: Groups, Search and
  filters).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639, like the store.

## Must hold

- Filtering runs in the browser over the loaded list: no request is made for a search, a chip or a grouping.
- The search matches every typed word, case-insensitively, in an item's label, title, detail or topic; a chip keeps one status, kind or topic, and selecting it again clears it; each chip's count is what selecting it would list.
- Status grouping lists the latest reply's items, then Open, Answered and Closed (folded unless a search or chip is active); topic grouping puts items without a topic last; kind grouping follows label order with other letters last.
- The grouping is stored per browser (`omnigent:open-items-grouping`); the search, chips and folds are kept per session until the page reloads, so the phone sheet reopens as it was left.
- Without the server capability the panel is the chat's tracker, exactly as before; there are no Settings controls.

## Key code

- `web/src/lib/openItemFilters.ts`: `filterOpenItemRows`, `openItemFacetCounts`, `groupOpenItemRows`, `useOpenItemGrouping`, `useOpenItemsView`
- `web/src/components/chat/OpenItemsFilterBar.tsx`: `OpenItemsFilterBar`
- `web/src/components/chat/StoredOpenItemsPanel.tsx`: `StoredOpenItemsPanel`, `GroupHeading`

## Tests

- `web/src/lib/openItemFilters.test.ts`
- `web/src/components/chat/StoredOpenItemsPanel.test.tsx`
