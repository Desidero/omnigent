# Evidence: lean history items

All captures: Chromium 1280x900 via Playwright, local server with the built
SPA, seeded session from `../bench/seed_session.py` (330 items, 150 tool
outputs averaging 4.5 KB). `before-*` is `main @ 65be0f2468`; `after-*` is the
branch. Captured with `../bench/capture_ui.py` and `../bench/capture_loading.py`.

- `before-collapsed.png` — the newest turn's tool run unfolded, rows collapsed;
  the initial 100-item window behind it cost 225,616 bytes (see
  `before-requests.json`, 459 ms on localhost).
- `before-expanded.png` — a `Read` row expanded: output was already in the page.
- `before-requests.json` — the single history request on open, bytes and ms.
- `after-collapsed.png` — the same view on the branch; nothing visible changes
  while the initial window costs 7,211 bytes on the wire (`after-requests.json`).
- `after-loading.png` — a `Read` row expanded with the per-item fetch held open
  for 4 s by a Playwright route: the 400-character preview is shown with the
  "Showing the first 400 of 4,320 characters; loading the full output…" note.
- `after-expanded.png` — the same row after the fetch (26 ms, 1,390 bytes):
  the full output replaced the preview.
- `after-requests.json` — the history request (`tool_output=preview`, gzip) and
  the per-item request made on expand.

Benchmark tables: `../bench/before.md` and `../bench/after.md`, produced by
`../bench/bench_items.py --session <id> --label before|after` (median of 15
localhost requests per row; `wire bytes` is what crossed the socket).
