# feat(web): fold the phone drawer's primary nav into one strip

## Related issue

Closes #13482

## Summary

On a phone, the sidebar drawer's primary nav (New session, Automations, Inbox, Canvas) is four stacked 44pt rows, about 179pt above the session list. This folds them into one strip under the header, which gives the session list about 39% more height (roughly four more rows) while every target stays at least 44pt.

- **Phone drawer only:** equal-width cells, each an icon over a short label (New, Automations, Inbox, Canvas), about 58pt tall, in a rounded glass container (the existing mobile glass surface). The active cell keeps the existing active highlight; the Inbox count sits on the cell's corner with an unchanged `aria-label`.
- **Extra destinations:** Usage and extension pages add cells; the cells keep a 72px minimum width, so past four the strip scrolls sideways (the drawer's swipe-to-close already leaves horizontal scrollers alone). An active cell beyond either edge is scrolled into view. I chose this over a "More" cell because it needs no menu and keeps every destination one tap away.
- **Unchanged:** desktop, tablet, and the side-by-side layout on wide phones keep the stacked rows with identical classes. Links, `onNavClick` drawer closing (plain taps close, modifier-clicks don't), `componentId`s, test ids, active-route detection, and `aria-keyshortcuts` are kept. New keeps the accessible name "New session"; the hover-only shortcut hint is not rendered in the strip.
- **Shape of the change:** every primary nav item now renders through `PrimaryNavLink`, which takes a `row` or `cell` layout, so both layouts share one definition per destination. As a side effect, New session, Automations, Inbox and Usage now set `aria-current="page"` when active, like Canvas and extension pages already did.

## Test Plan

- `pnpm exec vitest run src/shell/Sidebar.mobileDrawer.test.tsx src/shell/Sidebar.test.tsx src/extensions` and the other `src/shell/Sidebar*.test.tsx` files: all pass.
- New in `Sidebar.mobileDrawer.test.tsx`: strip cells on a phone (order, 44px minimum, equal width, scrolling strip), New's accessible name and missing hint, active highlight with `aria-current`, the Inbox badge on the corner, drawer closing on plain taps but not modifier clicks, scrolling the active cell into view from either side (mocked layout), and stacked rows on desktop and side-by-side layouts. `Sidebar.test.tsx` adds an extension page rendered as a cell.
- Existing desktop row assertions (classes, badge treatment, shortcut hint) pass unchanged.
- `tsc -b` and the pre-commit hooks pass.
- E2E UI tests that use these test ids at phone width (Canvas, Automations) still find and click the same elements; they were read, not rerun.

## Demo

Screenshots to follow from a phone build.

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

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
- [x] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Component tests cover the layout switch, accessibility names, active state, badge and drawer closing. Visual proportions on a real phone come with the screenshots.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

On phones, the sidebar's New session, Automations, Inbox and Canvas links share one compact strip, leaving more room for sessions

🤖 Generated with [Claude Code](https://claude.com/claude-code)

