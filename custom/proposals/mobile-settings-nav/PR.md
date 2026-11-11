# feat(web): make the phone Settings menu read as a list of pages

## Related issue

Part of #12036 (44pt rows on touch devices), for the Settings menu only; it does not close the issue.

## Summary

On phones, the sidebar gear opens Settings in a full-screen drawer, and tapping a row closes it onto that page. The drawer looked exactly like the sidebar, so it wasn't obvious that rows open pages:

- At bare `/settings`, **General** was highlighted although no page was open.
- Rows had no disclosure cue.
- Rows were about 33px tall, below the 44px `mobile-touch-target` floor the primary nav already uses.

At phone widths (`useIsMobileViewport`), `SettingsSidebarBody` now renders:

- a large **Settings** title under the Back row, which gets a `‹` chevron and the touch-target floor. The label and target stay the same.
- each section as a rounded inset group (`MOBILE_GLASS_SURFACE`) with hairline separators.
- rows with `mobile-touch-target`, a trailing `ChevronRightIcon` and an inset focus ring, since the rounded group clips an outer one.
- no current row at bare `/settings`. Once a page is open, its row is still marked when the drawer is reopened.

Desktop and tablet widths render exactly as before.

## Test Plan

- `settingsNav.test.tsx`: a new phone block (matchMedia stubbed below `md`) checks the title, Back chevron and touch target, the grouped container, the row chevron/touch-target/inset-focus classes, no `aria-current` at bare `/settings`, and that `/settings/appearance` keeps Appearance current. The desktop geometry test now also asserts no touch-target class, no chevron and no title.
- `cd web && pnpm exec vitest run src/shell/settingsNav.test.tsx src/shell/Sidebar.mobileDrawer.test.tsx src/shell/Sidebar.test.tsx`: 311 passed.
- pre-commit (prettier, oxlint, type check, custom lint) on the changed files: passed.

Manual check on a phone (or a touch device emulator below 768px): open the sidebar, tap the gear, and confirm that nothing is highlighted, rows are 44px with chevrons inside rounded groups, and Back returns where you came from. Tap Appearance, reopen the menu from the page header, and confirm Appearance is highlighted. At desktop width, Settings should look unchanged.

## Demo

Screenshots to follow from a phone build.

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

## Type of change

- [ ] Bug fix
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
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Component tests cover the phone/desktop class and selection branches. Rendered row height and focus visibility still need the phone screenshots above.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

