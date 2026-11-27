# app-error-boundary

Needs: none
Covers: a2ef1cd5b7ba0403

Upstream's render error fallback ("Unable to display …" with Try again) also
shows the error, the component stack and the path, with Copy details and
Reload.

- **Turn on:** on by default; shown only when rendering crashes.
- **Docs:** none (error screen).
- **Upstream:** drafted, not on a contribution branch yet.

## Must hold

- When rendering crashes inside a `RenderErrorBoundary` that has no `fallback` of its own, the screen keeps upstream's "Unable to display ..." line and Try again, and adds the error (its stack, or name and message), the component stack and `Path: <pathname>` in a scrollable, selectable block.
- Copy details copies that same text, and Reload does a full page reload.
- A boundary given its own `fallback` still renders only that, and chunk-load errors still pass to upstream's chunk boundary.
- An error value that cannot be turned into a string shows as "Unknown error"; the fallback itself must not throw.

## Key code

- `web/src/components/RenderErrorBoundary.tsx`: `RenderErrorBoundary`, `describeError`, `componentStack`

## Tests

- `web/src/components/RenderErrorBoundary.test.tsx`
