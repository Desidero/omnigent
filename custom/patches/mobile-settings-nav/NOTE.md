# mobile-settings-nav

Needs: none
Covers: 2d328f3e922892f3

Where the Settings menu covers the page (phones, and tablets held upright),
Settings opens as a list of pages on its own: full width, with no page open
behind it, a Back row, a large Settings title, the search field, then sections
as rounded inset groups of 44px rows with a chevron. Like a phone settings
list, no row is highlighted. Choosing a page shows it with the menu closed,
and a Back chevron in the page's header returns to the list. The desktop
layout, and a window wide enough to show the menu beside the page, are
unchanged.

- **Turn on:** on by default on the mobile layout wherever the menu covers the page.
- **Docs:** none (phone Settings navigation; nothing to configure).
- **Upstream:** the list's look is proposed from `feat/mobile-settings-nav`, [#13484](https://github.com/omnigent-ai/omnigent/pull/13484) (draft). Opening on the list instead of General (patch 02) changes upstream's own phone behaviour, which upstream opens on General under the menu; it is not proposed upstream yet.

## Must hold

- Where the menu covers the page (mobile layout under 600px wide, or 600 to 1180px at an aspect taller than 3:4), bare `/settings` (the cog, the Settings command, ⌘K's Search settings, a reload) shows the menu full width on its own: the URL stays `/settings`, no page opens behind it, no row is current, and it has no strip to tap away and no swipe to close.
- That menu shows, top to bottom: a Back row with a left chevron, a level-1 "Settings" title, the Settings search field, and each section as one rounded group of rows separated by hairlines.
- Every phone row is at least 44px tall and ends in a right chevron; no row carries the selected highlight, while on a page the open section's row keeps `aria-current="page"`.
- Upstream's Settings search keeps working on phones: typing replaces the groups with results, the title and Back stay, and clearing the query brings the groups back.
- Choosing a page or a search result shows that page with the menu closed. A page reached any other way (a deep link, a link elsewhere in the app, a reload, or a tablet turned upright while the menu sat beside the page) also opens with the menu closed.
- On such a page the header's Back chevron ("Back to Settings") replaces the menu toggle and returns to the list: back through history when the page was opened from the list, otherwise by replacing the page.
- The list's Back row returns to where the user was before Settings and leaves the drawer open.
- In the desktop layout, and where upstream docks the menu beside the page (a mobile-layout window 600px or wider at a squarish or wider aspect), Settings is upstream's: bare `/settings` opens General beside the menu, a page keeps the menu as the user had it, the header keeps the menu toggle, and the nav has an arrow Back, no title, plain rows, the open section highlighted, no chevrons.

## Key code

- `web/src/shell/settingsNav.tsx`: `SettingsSidebarBody`, `phoneMenu`, `MOBILE_GLASS_SURFACE`, `useBackToSettingsList`
- `web/src/hooks/useAtSettingsRoot.ts`: `useAtSettingsRoot`
- `web/src/App.tsx`: `SettingsIndexRoute`
- `web/src/shell/AppShell.tsx`: `settingsPageBack`, `sideBySideSidebar`
- `web/src/shell/Sidebar.tsx`: `settingsPageList`
- `web/src/shell/ChatHeader.tsx`: `onBackToSettings`

## Tests

- `web/src/shell/settingsNav.test.tsx::renders the menu as titled, grouped disclosure rows`
- `web/src/shell/settingsNav.test.tsx::marks no page current on the bare /settings list`
- `web/src/shell/settingsNav.test.tsx::stays the sidebar nav when the menu docks beside the page`
- `web/src/shell/settingsNav.test.tsx::keeps the title and Back while search results replace the pages`
- `web/src/shell/settingsNav.test.tsx::pops back to the list a page was opened from`
- `web/src/shell/settingsNav.test.tsx::replaces a deep-linked page with the list`
- `web/src/App.test.tsx::keeps bare settings as the page list where the menu covers the page`
- `web/src/App.test.tsx::opens General where the menu docks beside the page`
- `web/src/shell/AppShell.test.tsx::opens a deep-linked page with the menu closed, even from an open drawer`
- `web/src/shell/AppShell.test.tsx::reloads a page with the menu closed and goes Back to the list`
- `web/src/shell/AppShell.test.tsx::closes the menu over a page once turning upright makes it cover the page`
- `web/src/shell/Sidebar.mobileDrawer.test.tsx::shows the bare /settings menu full width with no page behind it to tap back to`
- `web/src/shell/ChatHeader.test.tsx::goes Back to the Settings list instead of opening the menu on a phone Settings page`
