<!-- Title: feat: lean session history pages with on-demand tool output -->

## Related issue

Closes #<lean-history-items issue>

## Summary

ELI5: a session's history page used to carry every tool result in full even
though the chat shows them collapsed, so a page of 20 items weighed 40 KB and
the web could only afford a small window of the transcript. The server can now
send each long tool output as a 400-character preview with its length, and the
web fetches a result in full only when the reader expands its row.

- Server: `GET /v1/sessions/{id}/items?tool_output=preview` returns each
  `function_call_output` longer than 400 characters as its head plus
  `output_length` and `output_truncated: true`; shorter outputs and every other
  item are byte-for-byte the full item, and the default `full` is unchanged.
  New `GET /v1/sessions/{id}/items/{item_id}` returns one committed item in
  full (queued inputs stay hidden, as in the list). Both reads are on a
  `GZipFileContentRoute` router like the workspace-file reads. `API.md` and
  `openapi.json` updated.
- Web: transcript hydration (initial window, scroll-up pages, reconnect
  backfill) requests previews. A tool row whose output is a preview shows the
  head with a "loading the full output" note when expanded, asks the store for
  the item (`loadToolOutput`, one request per item shared across cards), and
  swaps the full result into the block; a failure offers Retry. Results that
  are rendered as cards from their text (AskUserQuestion, ExitPlanMode,
  sys_advise_models) are inflated when the page is fetched, so those cards
  never see a cut-off result. Live-streamed output in the current turn is
  unchanged, as are the export and inbox readers, which still request `full`.
- History page size constants are not changed here. With previews, 200 items
  gzipped (14 KB) cost a third of today's 20 full items (40 KB raw); the
  100-item initial window moves 7 KB on the wire instead of 225 KB.

Benchmark (seeded session: 330 items, 150 tool outputs averaging 4.5 KB;
localhost, median of 15; `bench/bench_items.py`):

| Request | Before (wire bytes / ms) | After (wire bytes / ms) |
| --- | --- | --- |
| 20 items, full, no gzip | 40,489 / 5.9 | 40,489 / 5.5 |
| 20 items, full, gzip | 40,489 / 7.9 (not compressed) | 8,874 / 6.3 |
| 20 items, preview, gzip | n/a (flag ignored) | 1,880 / 6.1 (7 stubs) |
| 200 items, full, no gzip | 495,940 / 18.6 | 495,940 / 18.1 |
| 200 items, full, gzip | 495,940 / 18.0 (not compressed) | 103,984 / 24.4 |
| 200 items, preview, no gzip | n/a | 86,325 / 14.8 (75 stubs) |
| 200 items, preview, gzip | n/a | 13,655 / 17.1 |
| one item in full (largest, 11.7 KB) | 404 | 3,278 / 4.8 (gzip) |
| web open: initial 100-item window (Playwright) | 225,616 / 459 | 7,211 / 229, expand fetch 1,390 / 26 |

## Test Plan

- `uv run pytest tests/server/routes/test_session_items_preview.py tests/server/integration/test_sessions_endpoints.py -k "preview or session_item or list_session_items"`
  (projection unit test; preview page vs full page; per-item read incl. 404 for
  unknown, cross-session and queued ids; gzip on both reads)
- `cd web && pnpm exec vitest run src/lib/sessionsApi.test.ts src/lib/itemsToBlocks.test.ts src/lib/renderItems.test.ts src/store/chatStore.test.ts src/components/blocks/ToolCard.test.ts`
  (preview flag and card-result inflation; truncation markers through blocks
  and render items; store loads a result once and swaps it in; the card fetches
  on expand, shows the loading note, retries on failure)
- `cd web && pnpm exec tsc -b`; `pre-commit run` on the change set.
- Manual: seed a session with `bench/seed_session.py` against a local server,
  open it, expand a `Read` row; capture with `bench/capture_ui.py` and
  `bench/capture_loading.py` (holds the per-item fetch to show the note).

## Demo

- [x] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Before: `evidence/before-collapsed.png` (tool rows, 225 KB initial window),
`evidence/before-expanded.png`. After: `evidence/after-collapsed.png` (same
rows, 7 KB on the wire), `evidence/after-loading.png` (preview head with the
loading note while the full item is fetched), `evidence/after-expanded.png`
(full output after the fetch). Request logs: `evidence/*-requests.json`.

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
- [x] Integration tests added / updated
- [ ] E2E tests added / updated
- [x] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Manual verification covered the built SPA against a local server: opening a
seeded 330-item session, expanding a long `Read` result (full output arrives
and replaces the preview), and the loading note with the per-item fetch held
open. The byte and timing numbers come from `bench/bench_items.py` and
`bench/capture_ui.py`, both included.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Session history loads with tool-output previews and fetches a result in full when you expand it, so long transcripts open many times lighter

🤖 Generated with [Claude Code](https://claude.com/claude-code)
