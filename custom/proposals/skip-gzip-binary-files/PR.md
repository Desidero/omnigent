<!-- Draft PR body for the skip-gzip-binary-files series; title: fix(server): handle streamed downloads with gzip middleware -->
> Status: carried copy of upstream PR #10585; no new PR needed. Drop this series once #10585 merges.

## Related issue

Refs #10481 (closed by upstream PR #10585)

## Summary

Image previews and file downloads failed with "Error loading file: 500" when the server ran Starlette 1.8.0. This series is a squashed copy of upstream PR #10585, which fixes that.

- **Cause.** Starlette 1.8.0 checks the gzip responder's exclusion flag on `http.response.start`, but the `skip_gzip` opt-out only set it on the first body message. Binary file reads (images, PDFs, as base64 JSON) and downloads then never sent their start message through `BaseHTTPMiddleware`, and the server answered 500.
- **Fix.** `_StateAwareGZipResponder` reads the opt-out on `http.response.start` and passes the start and every body message through unchanged.
- **Download proxy hardening (also from #10585).** No runner, or a send-time connection failure, now returns a typed 503 `runner_unavailable` instead of 502; the first chunk is prefetched before headers are committed; the runner stream is closed with cancellation-shielded cleanup; error-body read failures return 502 `runner download failed`.

## Test Plan

Tests added: `tests/server/routes/test_session_resources.py` (responder start ordering, binary read and download through an HTTP middleware layer, typed 503s, prefetch and cancellation cleanup, error-body read failures).

```sh
uv run pytest tests/server/routes/test_session_resources.py
```

Manual: on a server with Starlette 1.8.0 installed, open an image or PDF in the session file viewer and download a file from it. Both load instead of showing "Error loading file: 500". Stop the host and retry a download: the response is a 503 `runner_unavailable`.

See #10585 for the full test plan, including runs against Starlette 1.8.0.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

N/A for this carried copy; evidence lives on #10585.

## Type of change

- [x] Bug fix
- [ ] Feature
- [ ] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [ ] Unit tests added / updated
- [x] Integration tests added / updated
- [ ] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Regression tests exercise the real gzip route and runner download route through an HTTP middleware layer, as described on #10585.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

File previews and downloads work with gzip enabled, and downloads return a typed error when the runner is unavailable
