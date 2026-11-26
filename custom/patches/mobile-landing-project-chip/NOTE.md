# mobile-landing-project-chip

Needs: none
Covers: 3cacaf8c397ab3d9

On phones the new-session landing leads its controls with a chip naming the
project (or "No project"); its menu lists No project and every project with no
search field, and switching keeps the draft.

- **Turn on:** on by default in the mobile layout (phones, and windows narrower than the desktop layout).
- **Docs:** [Composer](../../feature-map/composer.md) (`mobile-project-chip`).
- **Upstream:** proposed from `feat/mobile-landing-project-chip`, [#13487](https://github.com/omnigent-ai/omnigent/pull/13487).

## Must hold

- In the mobile layout the landing's controls under "Start a new session in" start with a chip reading the selected project's name and icon, or "No project".
- The chip's menu lists No project and then every project as radio rows at least 44px tall, with the current one checked and no search field, so opening it never raises the keyboard.
- Picking a project sets `?project=<name>` and keeps every other query parameter; picking No project removes only `project`. Either way the typed draft and attachments stay and the composer takes the new project's defaults.
- The + menu's "Work in a project" behaves as upstream: `?project=` on the landing, the picked project's home on a project home.
- The menu spans a phone's width and is no wider than 28rem on larger windows.
- No chip on desktop (the heading names the project), on Add nested agent, or in a project home's own composer.

## Key code

- `web/src/shell/LandingProjectChip.tsx`: `LandingProjectChip`
- `web/src/shell/NewChatDialog.tsx`: `selectLandingProject`, `projectChip`

## Tests

- `web/src/shell/NewChatLandingScreen.mobileChrome.test.tsx::leads the phone controls and files the visit under a picked project`
- `web/src/shell/NewChatLandingScreen.mobileChrome.test.tsx::names the current project and clears only`
- `web/src/shell/NewChatLandingScreen.mobileChrome.test.tsx::is not rendered on a project home, which already names its project`
