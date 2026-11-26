# lean-history-items

Needs: history-prefetch
Covers: e5a39e068e20b3c9

History pages carry only the head of long tool outputs, and expanding a tool
row fetches the full result. Needs `history-prefetch`.

- **Turn on:** on by default in the web app; API clients opt in with
  `tool_output=preview` on `GET /v1/sessions/{id}/items`.
- **Docs:** `omnigent/server/API.md` (List Session Items, Get Session Item).
- **Upstream:** proposed from `feat/lean-history-items` (upstream PR [#13259](https://github.com/omnigent-ai/omnigent/pull/13259)).

## Must hold

- `GET /v1/sessions/{id}/items?tool_output=preview` returns each `function_call_output` longer than 400 characters as its first 400 characters plus `output_length` and `output_truncated: true`; shorter outputs and every other item are unchanged, so an item without `output_truncated` is complete.
- The default stays `tool_output=full`: a caller that does not send the parameter (the export, the inbox readers, other API clients) gets full items as before.
- `GET /v1/sessions/{id}/items/{item_id}` returns one committed item in full, in the list's flat shape, and 404 for an unknown session, an unknown item, an item of another session or a queued input.
- Both reads are gzipped for clients that send `Accept-Encoding: gzip`.
- The web app loads history (the first window, scroll-up pages including the prefetched one, reconnect backfill) with previews; expanding a tool row whose output is a preview fetches the full item once and swaps it in, with a loading note meanwhile and a retry on failure.
- Results that render as cards from their text (AskUserQuestion, ExitPlanMode, `sys_advise_models`) are fetched in full with the page; a card is never built from a cut-off result, and if that fetch fails the plain tool row shows instead.

## Key code

- `omnigent/server/routes/sessions/routes_items.py`: `project_tool_output_preview`, `TOOL_OUTPUT_PREVIEW_CHARS`, `get_session_item`, `GZipFileContentRoute`
- `web/src/lib/sessionsApi.ts`: `fetchSessionItem`, `inflateOutputsRenderedAsCards`, `TOOLS_RENDERED_FROM_OUTPUT`
- `web/src/store/conversationSnapshot.ts`: `fetchHistoryPage` (every history read that asks for previews goes through it)
- `web/src/store/chatStore.ts`: `loadToolOutput`, `toolOutputLoads`
- `web/src/components/blocks/ToolCard.tsx`: `OutputPreviewNotice`, `truncatedOutputLength`

## Tests

- `tests/server/integration/test_sessions_endpoints.py::test_list_session_items_preview_stubs_long_tool_output`
- `tests/server/integration/test_sessions_endpoints.py::test_get_session_item_returns_full_item`
- `tests/server/integration/test_sessions_endpoints.py::test_session_item_reads_are_gzipped`
- `web/src/lib/sessionsApi.test.ts` ("fetchSessionItemsPage with lean tool output")
- `web/src/components/blocks/ToolCard.test.ts` ("fetches the full output once when a lean-page preview row is expanded")
