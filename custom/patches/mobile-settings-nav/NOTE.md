# mobile-settings-nav

Needs: none
Covers: b9ee2585417e7a32

On phones the Settings menu reads as a list of pages: a Back row, a large
Settings title, the search field, then sections as rounded inset groups of
44px rows with a chevron. Like a phone settings list, no row is highlighted.
The desktop layout, and a window wide enough to show the menu beside the page,
are unchanged.

- **Turn on:** on by default in the phone drawer.
- **Docs:** none (layout polish of the phone Settings menu).
- **Upstream:** proposed from `feat/mobile-settings-nav`, [#13484](https://github.com/omnigent-ai/omnigent/pull/13484) (draft).

## Must hold

- In the overlay drawer (mobile layout, menu over the page) the menu shows, top to bottom: a Back row with a left chevron, a level-1 "Settings" title, the Settings search field, and each section as one rounded group of rows separated by hairlines.
- Every phone row is at least 44px tall and ends in a right chevron; no row carries the selected highlight, while the open section's row keeps `aria-current="page"`.
- Upstream's Settings search keeps working on phones: typing replaces the groups with results, the title and Back stay, and clearing the query brings the groups back.
- Back returns to where the user was before Settings and leaves the drawer open; tapping a page closes the drawer onto that page.
- In the desktop layout, and where upstream docks the menu beside the page (a mobile-layout window 600px or wider at a squarish or wider aspect), the nav is upstream's: arrow Back, no title, plain rows, the open section highlighted, no chevrons.

## Key code

- `web/src/shell/settingsNav.tsx`: `SettingsSidebarBody`, `phoneMenu`, `MOBILE_GLASS_SURFACE`

## Tests

- `web/src/shell/settingsNav.test.tsx::renders the menu as titled, grouped disclosure rows`
- `web/src/shell/settingsNav.test.tsx::stays the sidebar nav when the menu docks beside the page`
- `web/src/shell/settingsNav.test.tsx::puts the search field between the title and the pages`
- `web/src/shell/settingsNav.test.tsx::keeps the title and Back while search results replace the pages`
