# open-items-panel

Needs: open-items-store, open-items-links-compact
Covers: 48334cdffbf0670d

The Open items panel behind the session header's button, its badge and the
chat's label chips read the session's stored open items, kept live by
`session.open_items.changed`, instead of only the loaded chat text. A stored
item's label in the chat is only its anchor: the store alone decides its
state, and an expanded row shows its stored thread. A label the chat has but
the store does not is listed as "chat only". People with edit access close
(one tap, or with a resolution), reopen and retopic stored items from the
panel, and import the chat's own labels into the store.

- **Turn on:** on by default on a server with `open-items-store`
  (`/v1/info` `open_items`); without it the panel reads the chat as before.
- **Docs:** [Open items](../open-items.md) (In the web UI, HTTP API),
  [Item labels in chat](../chat-item-labels.md) (Loaded history only).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639, like the store.

## Must hold

- Without the server capability, or while the stored list cannot be read, the panel, badge and chips render from the chat exactly as `open-items-links-compact` does, and nothing is fetched.
- A stored label takes its state from the store everywhere (panel, badge, chips, popovers), whatever the chat wrote: struck in chat but open in the store shows open, with nothing offered from the chat's sentence; closed only in the store shows struck.
- An expanded stored row shows the item's replies in stored order, each once, then how it was closed; a resolution that only repeats the last reply is left out.
- The badge counts open items only: stored items with status open plus open, undismissed chat-only labels; answered, closed and link items are left out. Stored items show even when none of their messages are loaded.
- Closing a stored item from the panel is a `PATCH` recorded as closed by a person; the `omnigent.items_dismissed` label is never written for a stored item and is still read for chat-only ones.
- Close, reopen, topic and import appear only with edit access; a refused write leaves the list as stored and says why in a toast.
- Links pins every open stored link first, under its stored title (a short form of the URL when that is empty or the URL itself), whether or not a loaded message pins it; a closed stored link takes its pin and its page off the list.
- Import stores only labels the user asks for, under their own labels (the store's letters, links with a URL), closed if the chat closed or the user dismissed them; a label already stored is left alone, and counting moves past imported labels.
- The panel calls nothing whose signature `chat-item-comments` changes, and stays off the lines that series and its glue with `open-items-links-compact` change.

## Key code

- `web/src/lib/openItems.ts`: `mergeStoredOpenItems`, `openItemRows`, `withStoredLinks`, `chatItemImport`, `chatItemsToImport`, `fetchStoredOpenItems`, `importChatItems`
- `web/src/components/chat/StoredItemThread.tsx`: `StoredItemThread`
- `web/src/hooks/useStoredOpenItems.ts`: `useStoredOpenItems`, `useSessionOpenItemCount`, `useSessionItemsIndex`
- `web/src/components/chat/StoredOpenItemsPanel.tsx`: `StoredOpenItemsPanel`, `SessionOpenItemsSection`
- `web/src/components/chat/SessionItemsButton.tsx`: `SessionOpenItemsSection`
- `web/src/components/chat/Transcript.tsx`: `mergeStoredOpenItems`, `withStoredLinks`
- `web/src/lib/sse.ts`: `session.open_items.changed`
- `web/src/store/chatStore.ts`: `session_open_items_changed`
- `omnigent/server/open_items.py`: `import_open_items`, `OpenItemsImportRequest`

## Tests

- `web/src/lib/openItems.test.ts`
- `web/src/components/chat/StoredOpenItemsPanel.test.tsx`
- `web/src/store/chatStore.openItems.test.ts`
- `web/src/lib/sessionEvents.test.ts`
- `tests/server/routes/test_open_items_routes.py::test_editors_import_chat_labels_and_counting_moves_past_them`
