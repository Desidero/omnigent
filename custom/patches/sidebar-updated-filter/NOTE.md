# sidebar-updated-filter

Needs: none
Covers: 971071ed29c41990

A sidebar filter for sessions updated recently (**Updated**: 24 hours, 3, 7
or 30 days), with a chip beside the filter button while it is on.

- **Turn on:** on by default; choose a window under **Updated** in the
  sidebar's filter menu. Saved per device.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`updated-filter`).
- **Upstream:** not proposed yet; no pull request or pushed branch. Upstream's
  filters behind `sidebar_saved_views` are not wired into the sidebar yet and
  have no update-time field.

## Must hold

- The filter menu offers Updated with Any time, Last 24 hours, Last 3 days, Last 7 days and Last 30 days, as rolling windows from now. With `sidebar_grouping_ui` on it is a submenu directly under Display that shows the current window and, on phones, opens in place under a Back row; with the flag off it follows the Display list.
- With a window chosen, the session lists and project folders show only sessions updated inside it. Pinned sessions and the open session always stay listed.
- A project folder with no match is hidden, except the folder the new-session composer targets and the folder of an open project home.
- While the filter is on, the filter button is highlighted and a chip (24h, 3d, 7d, 30d) sits beside it; activating the chip clears the filter, and from the keyboard focus lands on the filter button.
- The choice survives a reload (local storage key `omnigent:sidebar-focus`), and an unknown stored value reads as Any time.
- Changing the filter leaves selection mode; with it on, projects cannot be reordered.
- TODO(owner): the main list and paginated folders keep offering older pages while the filter is on, as the earlier version of this series did; only a folder that lists every loaded session stops paging.

## Key code

- `web/src/lib/sidebarFocusPreferences.ts`: `SIDEBAR_RECENCY_OPTIONS`, `readSidebarFocus`, `writeSidebarFocus`
- `web/src/shell/sidebarNav.ts`: `matchesSidebarFocus`
- `web/src/shell/Sidebar.tsx`: `focusMatches`, `visibleProjectGroups`, `SessionUpdatedFilterSub`, `SessionUpdatedFilterChip`

## Tests

- `web/src/lib/sidebarFocusPreferences.test.ts`
- `web/src/shell/sidebarNav.test.ts::matchesSidebarFocus`
- `web/src/shell/Sidebar.test.tsx::Updated keeps recent sessions and hides folders with none`
- `web/src/shell/Sidebar.test.tsx::shows a removable chip for the Updated filter beside the filter button`
- `web/src/shell/Sidebar.test.tsx::lists Updated under Display in the filter menu, with its current window`
- `web/src/shell/Sidebar.test.tsx::opens the Updated submenu in place on a mobile viewport`
