<!-- Draft PR body for the sidebar-attention-filter series; title: feat(web): filter the sidebar to sessions that need you or changed recently -->

## Related issue

Closes #TODO (issue to be opened)

## Summary

Two new options in the sidebar's filter menu: show only sessions waiting on you, and show only sessions updated in the last day, 3 days, week or month. Each active filter also shows as a removable chip beside the filter button.

The sidebar lists every session and every project folder, so the few sessions waiting on you get lost. The status grouping can surface them, but it sits behind a release flag and drops the project folders.

This PR adds two device-local filters to the sessions filter menu, next to the My / Shared / All / Archived scope and independent of the grouping flag:

- **Needs me**: sessions with a pending approval or unread agent output, using the same read state as the unread dot. A failure you have already seen doesn't count.
- **Updated**: Any time / Last 24 hours / Last 3 days / Last 7 days / Last 30 days. These are rolling windows rather than calendar days, so the shortest one doesn't empty out just after midnight. The choices come from one ordered table, so adding another window is a one-line change.

While either filter is on:

- project folders with nothing matching are hidden (except the one the composer targets);
- the filter icon is highlighted and empty states say "No matching sessions" / "No matching projects";
- a chip per active filter sits beside the filter button: the window in short form (`24h`, `3d`, `7d`, `30d`) and `Needs me`. Each chip is a button (for example "Clear Updated filter: last 3 days") that clears only its own filter; activated from the keyboard, it returns focus to the filter button;
- the open session stays listed, so reading it doesn't remove it from the list;
- project reordering and infinite scroll inside folders pause, since they work on the full lists.

Pins are unaffected, as with the scope filter. The choice is stored per device in `web/src/lib/sidebarFocusPreferences.ts`, and the matching rule lives in `matchesSidebarFocus` in `sidebarNav.ts`.

Docs: `feature-map/sessions.md` gains an `attention-filters` entry: what each filter matches, how to reach it, a manual check, and the gotcha that older pages stop loading while a filter is on.

## Test Plan

```sh
cd web && pnpm exec vitest run src/lib/sidebarFocusPreferences.test.ts \
  src/shell/sidebarNav.test.ts src/shell/Sidebar.test.tsx
cd web && pnpm exec tsc -b
```

The tests cover the stored preference (defaults, round trip, previously stored ids, corrupt values, the window table and its short labels), the matching rule (pending approvals and unseen output count, seen failures don't, each window's rolling boundary including 3 days, the window just after midnight, both filters together), a sidebar render where Needs me keeps approval and unread sessions and hides folders with neither, and the chips (shown only while a filter is on, one per filter, clearing only their own filter and persisting it, reachable with Shift+Tab and activated with Enter).

Manual, on a throwaway server with dummy sessions:

1. Create a few sessions, some in projects. Leave one with a pending approval and one with an unread reply, and read the rest.
2. Open the sidebar's filter menu and tick **Needs me**. Only the approval and unread sessions remain, folders with neither disappear, and the filter icon is highlighted. Pinned sessions stay.
3. Open one of the remaining sessions. It stays in the list after being read. Switch to another session; the read one drops out.
4. Untick Needs me and set **Updated › Last 3 days**. Only sessions active in the last 72 hours are listed, and a `3d` chip appears beside the filter button.
5. Tick **Needs me** again. A second `Needs me` chip appears. Click the `3d` chip: the window resets to Any time and only the Needs me chip remains. Tab to the Needs me chip and press Enter: it clears and focus lands on the filter button.
6. Set a filter and reload the page. The filter and its chip are still there. Clear it and every session and project folder returns.
7. Repeat steps 4 and 5 in dark mode and at phone width.

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

To capture on a clean throwaway server with dummy sessions and projects:

- [ ] TODO: screenshot of the filter menu showing Needs me and the Updated submenu
- [ ] TODO: screenshots of the `3d` and `Needs me` chips beside the filter button, light and dark, desktop and phone width
- [ ] TODO: before/after screenshots of the sidebar with Needs me on (folders without matches hidden, filter icon highlighted)
- [ ] TODO: short recording of opening a matching session, reading it, and moving on so it drops out of the filtered list

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
- [ ] Integration tests added / updated
- [ ] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The filter logic and the sidebar render are covered by component tests. The manual steps check the live read-state updates, which the tests stub.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Filter the sidebar to sessions that need you, or to sessions updated in the last 24 hours, 3 days, 7 days or 30 days, with a chip that shows and clears each active filter
