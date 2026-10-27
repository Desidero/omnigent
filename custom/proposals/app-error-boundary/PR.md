# fix(web): show the error instead of a blank page when rendering crashes

## Related issue

Closes #

<!-- No upstream issue yet. -->

## Summary

When anything in the web UI throws while rendering, the whole window goes blank and nothing is logged on the server. Reloading recovers it, but the error is lost. This change shows the error with a Reload button instead.

- `ChunkLoadErrorBoundary` is the app's only root boundary. It rethrows everything except failed chunk loads, so any other render error unmounts the React tree. Earlier fixes put local boundaries around individual crash sites (#5406 mermaid, #5742 Codex inline images, #7995 and #9263 PDF viewer). Crash sites that haven't been found yet still blank the app.
- `AppErrorBoundary` wraps `ChunkLoadErrorBoundary` in `App`. Chunk-load errors keep their automatic reload. Any other error, including thrown non-`Error` values, shows the message, the JS stack, the React component stack and the path (no query string or hash), with **Reload** and **Copy details** buttons, and is still logged with `console.error`.
- No reset on navigation: the sidebar is part of the crashed tree, so Reload is the only way out.

## Test Plan

- `web/src/components/AppErrorBoundary.test.tsx` (under StrictMode): a thrown `Error` shows the message, the component stack and the path. Copy details passes them to `copyText`, Reload calls `location.reload`, and a failed clipboard write leaves the fallback in place. Thrown `null`, a string and a prototype-less object each still render the fallback; the `null` and prototype-less cases failed against the first version of the boundary.
- `web/src/App.test.tsx`: extended the chunk-recovery scenario. An ordinary render error at `/tasks` and `/mount/tasks` shows the generic fallback without reloading. Both cases fail if the wrapper is removed from `App`.
- Manual: forced a `TypeError` in a routed page under `vite` dev and confirmed the fallback rendered in place of a blank window.
- `vitest run src/components/AppErrorBoundary.test.tsx src/App.test.tsx` (23 passed), `tsc -b`, oxlint, prettier and pre-commit pass.
- Pre-existing and unrelated: `ChunkLoadErrorBoundary.test.tsx > offers manual recovery when storage cannot guard an automatic reload` fails without this change too.

## Demo

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

<!-- TODO: screenshot of the fallback from a throwaway server. -->

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
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Manual check: a forced render error in a dev build showed the fallback with the stack instead of a blank window.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

A rendering error now shows the error and a Reload button instead of a blank window.
