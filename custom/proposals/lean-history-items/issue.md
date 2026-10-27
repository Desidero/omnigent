<!-- Title: [Feature] Lean session history pages: tool output on demand -->

### Problem or use case

A session's `GET /v1/sessions/{id}/items` page returns every tool result in
full. The web chat renders tool rows collapsed and only shows a result when the
reader expands it, so almost all of those bytes are never displayed. On a
transcript with realistic tool output (file reads, test runs, searches of a few
KB each) a 20-item page is ~40 KB and a 200-item page ~500 KB, uncompressed.
That cost is why the chat holds a narrow window of the session: a 20-item
history page and a 100-item initial window that weighs 225 KB on open.

Measured on `main @ 65be0f2468` with a seeded 330-item session (150 tool
outputs averaging 4.5 KB): opening the session moved 225,616 bytes for the
initial window in 459 ms on localhost; a 200-item page was 495,940 bytes.

### Proposed solution

- An opt-in projection on the list route, `tool_output=preview`, that returns
  each long `function_call_output` as its first 400 characters plus
  `output_length` and `output_truncated: true`. Short outputs and all other
  items are unchanged; the default stays `full`.
- `GET /v1/sessions/{id}/items/{item_id}` to read one item in full.
- Gzip on both reads, as the workspace-file reads already do.
- The web requests previews for history and fetches a result in full the
  first time its row is expanded, caching it in the store. Results that are
  rendered as cards from their text (AskUserQuestion, ExitPlanMode,
  sys_advise_models) are fetched in full with the page.

With that, 200 preview items gzipped (~14 KB) cost a third of today's 20 full
items, and the 100-item initial window moves ~7 KB instead of 225 KB, which
lets the history page size grow by about 5x at today's wire cost.

### Alternatives considered

- Gzip alone: a 200-item full page still moves ~100 KB and the browser still
  parses 500 KB of JSON it does not render.
- Dropping output entirely from history pages: the common short results (edit
  acknowledgements, small command output) would then need a fetch each, and
  the expanded card would be blank while loading; a short preview covers both.
- Shrinking the page size further: trades bytes for more round trips and a
  smaller window of the session.

### Harness

Not applicable

### Platform or device

Not platform-specific

### Harness mode

Not applicable

### Expected reach

Most users

### Authentication type

Not authentication-related

Version: main @ 65be0f2468
