# sidebar-sticky-toolbar

Needs: none
Covers: 74476b90eeffbbc5

The sidebar's filter, Select sessions and bulk-action bar sit in a toolbar row
above the session list, so they stay in view however far the list scrolls.

- **Turn on:** on by default.
- **Docs:** [Sessions](../../feature-map/sessions.md) (Sidebar filter menu).
- **Upstream:** not proposed yet; no pull request or pushed branch.

## Must hold

- The filter (funnel) and Select sessions are in a row between the primary nav and the scrolling session list, outside the scroll container, labelled with the current Display choice (My sessions, All sessions, ...). Scrolling the list never moves them.
- While selecting, the bulk-action bar sits in the same toolbar under that row, Select hides and the filter stays; there is exactly one bulk bar whichever scope started the selection (the toolbar's Select, or the Projects menu's Select sessions).
- It is the same in every layout: `sidebar_grouping_ui` on or off, any grouping, and Display → Shared with me. No section header shows the filter or Select; the Sessions (or first group's, or Shared with me) header keeps New session.
- An empty list still shows the toolbar, so a filter that hides everything can be changed.
- The section headers' `persistentHeaderAction` and `afterHeader` slots stay in the code unused; nothing may start passing the filter or bulk bar to them again.

## Key code

- `web/src/shell/Sidebar.tsx`: `listToolbarSlot`, `toolbarSlot`, `listToolbar`, `bulkBar`, `sidebar-list-toolbar`

## Tests

- `web/src/shell/Sidebar.test.tsx::keeps the filter and Select in the list toolbar above the scrolling list`
- `web/src/shell/Sidebar.test.tsx::puts the filter and Select in the list toolbar, leaving New session on Sessions`
- `web/src/shell/Sidebar.test.tsx::selects project, Shared and Sessions rows together from the list toolbar`
- `web/src/shell/Sidebar.bulkActionLayout.test.tsx`
