# mobile-sidebar-nav-strip

Needs: none
Covers: f61607e26b2e68d8

On phones the drawer's New session, Automations, Workflows and Inbox rows fold
into one strip of icon-over-label cells, which leaves more room for the session
list. The strip doesn't scroll; Canvas, Usage and extension pages stay rows
below it. The desktop layout, and a window that shows the sidebar beside the
chat, keep the rows.

- **Turn on:** on by default in the phone drawer.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`mobile-primary-nav-strip`).
- **Upstream:** proposed from `feat/mobile-sidebar-nav-strip`, [#13488](https://github.com/omnigent-ai/omnigent/pull/13488) (draft); issue [#13482](https://github.com/omnigent-ai/omnigent/issues/13482).

## Must hold

- In the overlay drawer (mobile layout, sidebar over the chat) the primary nav starts with one strip holding, in this order, New session (shown as "New"), Automations, Workflows and Inbox as equal-width cells at least 44px tall. Automations and Workflows appear only when upstream would show their rows.
- Every destination upstream shows in the primary nav stays one tap away: the ones not in the strip (Canvas, Usage, extension pages) are full-width rows directly below it.
- Each cell keeps its row's link, test id, active highlight with `aria-current`, and closes the drawer on a plain tap but not on a modifier click. New keeps the accessible name "New session"; the Inbox count sits on its cell's corner with the same label as the row's badge.
- The desktop layout and the side-by-side layout (sidebar docked beside the chat) render upstream's stacked rows, including New session's shortcut hint.
- TODO(owner): four cells still read well at 320px wide (labels truncate rather than wrap).

## Key code

- `web/src/shell/PrimaryNavLink.tsx`: `PrimaryNavLink`, `PrimaryNavStrip`, `PrimaryNavLayout`
- `web/src/shell/Sidebar.tsx`: `navLayout`, `PrimaryNavStrip`

## Tests

- `web/src/shell/Sidebar.mobileDrawer.test.tsx::puts the core destinations in one strip of equal-width cells at least 44px tall`
- `web/src/shell/Sidebar.mobileDrawer.test.tsx::adds Workflows as a cell between Automations and Inbox when its page is on`
- `web/src/shell/Sidebar.mobileDrawer.test.tsx::keeps two cells when automations are off for the caller`
- `web/src/shell/Sidebar.mobileDrawer.test.tsx::renders Canvas and Usage as full-width rows below the strip`
- `web/src/shell/Sidebar.test.tsx::renders an extension page as a row below the phone drawer's strip`
