# feat(web): ask for a project when starting a new session

> **Held.** #11083 says "open once there's agreement on the default". The review's three must-fixes (stale load-error row gated out of the project step, Enter-on-first-row tests, Settings switch tests) have landed on the branch; it opens only after a maintainer reacts to the issue.

## Related issue

Closes #11083

## Summary

A project stores the settings a new session needs, but every "new session" entry point opened a plain composer with no project, so sessions started in the wrong place and landed unfiled unless you remembered the per-project pencil. When at least one project exists, the new-session hotkey, the sidebar's **New session** and Sessions **+**, and the palette's **New chat** now first open a "Start a new session in…" picker:

- **No project** is the first row, so Enter straight away still gives a plain composer; projects follow, filtered by name as you type.
- Picking a project opens `/?project=<name>`, the route the pencil already uses, so its defaults prefill exactly as today.
- Middle-click and ⌘/Ctrl-click on the sidebar links still open a plain composer in a new tab. `/`, `/new`, the logo, the post-archive redirect and the extension `openNewSession` API never prompt.
- **Settings › General › Sessions › Ask for a project when starting a session** turns it off. On by default, but a no-op until you have a project.

One shared `handleNewSession` in `AppShell` drives all entry points; the picker reuses the command palette dialog (already a full-screen sheet on mobile) and `useProjects`. The preference is a per-browser setting stored like the other General toggles. Stacked on the #4409 palette PR.

## Test Plan

- `CommandPalette.test.tsx`: project step renders No project first, filters by name, Enter with an empty query opens the plain composer (`/`), typing `lab` then Enter navigates to `/?project=home%20lab`, and a stale session-load error from the previous ⌘K fetch is not shown on the project step.
- `useNewSessionHotkey.test.tsx`, `Sidebar.test.tsx`, `AppShell.test.tsx`: each entry point routes through the prompt when projects exist and straight to the composer when the switch is off or no projects exist; modified clicks bypass it.
- `newChatProjectPromptPreferences.test.ts`: default on, persisted off.
- `SettingsPage.test.tsx`: the **Ask for a project when starting a session** switch renders on by default and turning it off persists `"off"`, mirroring the neighbouring session-titles switch tests.
- `npx vitest run` on the changed files (517 tests across 6 files), `tsc -b`, pre-commit (prettier, oxlint, custom lint) clean.
- Manual on desktop and at phone width: see Demo.

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Hotkey with projects present:

![Picker: No project first, then projects](img/prompt-picker.png)

Typing filters the list:

![Picker filtered to one project](img/prompt-picker-filtered.png)

Phone width (390×844): the drawer's New session, the full-screen picker, and the picker filtered:

![Mobile drawer with New session](img/mobile-drawer-new-session.png)

![Mobile full-screen picker](img/mobile-picker.png)

![Mobile picker filtered to one project](img/mobile-prompt-picker-filtered.png)

The switch, desktop and phone:

![Settings › General › Sessions switch](img/settings-switch.png)

![Settings switch at phone width](img/mobile-settings-switch.png)

Dark theme:

![Picker in dark theme](img/dark-prompt-picker.png)

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
- [x] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The component tests cover each entry point and the switch; the mobile drawer-to-sheet handoff was checked by hand in an iPhone-sized viewport (screenshots above).

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

When you have projects, starting a new session first asks which project it belongs to (or none); turn it off in Settings › General › Sessions.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
