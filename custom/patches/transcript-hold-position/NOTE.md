# transcript-hold-position

Needs: none
Covers: 3c358f524b126134

Scrolled up in a transcript, you keep your place while rows above you change
height: a reply still streaming, a tool group settling, an image loading,
rows measured as you scroll back. The transcript holds the row you are
reading itself instead of leaving it to the virtual list's own correction,
which skips rows crossing the top of the view, skips upward scrolls and, on
an iPhone, waits until the touch has ended.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/transcript-hold-position`.

## Must hold

- A reader scrolled up keeps the row they are reading at the same place in the view while rows above it grow or shrink (a reply streaming, a tool group settling, an image loading, rows re-measured on the way up), also during an upward scroll and while a touch is down.
- The held row is the first row fully inside the viewport, else the topmost row crossing it (one row taller than the view); when no row from the previous hold intersects the viewport, nothing moves.
- The hold is the only in-list correction: react-virtual's own per-row scroll adjustment stays off for the whole life of the list, so no height change is counted twice, and content above the list is compensated separately from list-relative offsets.
- A row that a history page renamed is held by its bottom edge for that page only; a row re-keyed with the same content moves nothing.
- Unchanged from upstream: follow-tail at the bottom, the lock release and synchronous row measurement when a history page is prepended, the mount-time restore (no hold while it is pinning) and native-find mode.

## Key code

- `web/src/components/chat/Transcript.tsx`: `holdAnchorRow`, `holdScrollDelta`, `HeldRow` (which row is held and by how much)
- `web/src/components/chat/Transcript.tsx`: `VirtualBubbleList`, `holdReaderPosition`, `rowSnapshotRef`, `shouldAdjustScrollPositionOnItemSizeChange` (where the hold runs)

## Tests

- `web/src/components/chat/Transcript.virtualList.test.tsx` ("holds the row under the reader while rows above it change height")
- `web/src/components/chat/Transcript.scrollRestore.test.ts` ("transcript read-position hold")
