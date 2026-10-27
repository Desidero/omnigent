# feat(web): start a new chat in a project from the command palette

## Related issue

Closes #4409

## Summary

The command palette's **New chat** always opened a plain composer. Starting a session with a project's stored defaults (host, workspace, agent, model, worktree) meant leaving the keyboard for the sidebar's per-project pencil, or the composer's unsearchable **+ › Work in a project** menu.

- While the palette query is non-empty, it now also lists **New chat in \<project\>** rows, one per project, matched when every typed word appears in the label or its group heading (so `new omni`, `omni` and `project` all find "New chat in Omnigent").
- A row opens the composer at `/?project=<name>`, the same route the per-project pencil already uses, so the project's defaults prefill exactly as they do today (`NewChatDialog` resolves name → id → config).
- The rows stay hidden while the query is empty so a long project list doesn't push **Actions** out of view, and the sessions-only switcher leaves them out.
- Legacy label-only projects (no project id) open a plain composer filed under the label, matching the pencil.

This is the small PR the author of #6627 suggested when closing that draft ("what remains of #4409 would be a much smaller PR against the current code"). A follow-up, stacked on this one, adds a project prompt on every new-session entry point (#11083); that one waits for agreement on the default.

## Test Plan

- `web/src/shell/CommandPalette.test.tsx`: new cases assert that project rows appear only with a non-empty query, that every typed word must match, that typing `project` alone lists every project, that the sessions-only switcher omits them, and that choosing a row by click or by Enter on the highlighted row navigates to `/?project=<name>` and closes the palette.
- `feature-map/composer.md` gains a `palette-new-chat-in-project` entry with the manual check.
- `npx vitest run src/shell/CommandPalette.test.tsx src/shell/AppShell.test.tsx` (225 tests) and `node_modules/.bin/tsc -b` pass; pre-commit (prettier, oxlint, custom lint) clean.
- Manual, in a dev build with three projects: ⌘K, type part of a project name, Enter on the row, confirm the composer shows that project's host, workspace and agent.

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Desktop. Typing `new` lists every project under the New chat action; a longer query filters:

![Command palette listing "New chat in" rows for every project](img/palette-project-rows.png)

![Command palette filtered to one project](img/palette-project-rows-filtered.png)

After choosing a row, the composer opens bound to that project (the capture environment has no hosts, so the host and workspace chips stay empty here; against a real host they prefill as the per-project pencil does):

![Composer prefilled from the chosen project](img/composer-prefilled.png)

Phone width (390×844). The palette is a full-screen sheet; the same rows appear:

![Mobile palette filtered to one project](img/mobile-palette-project-rows-filtered.png)

![Mobile composer bound to the chosen project](img/mobile-composer-prefilled.png)

One pre-existing quirk, unchanged by this PR: when the palette is opened from the mobile drawer's search button, choosing any row (a session today, a project row here) navigates but leaves the drawer open over the new page, because the palette's handlers only close the palette. The drawer's own links close it. Worth a separate small fix; noted here so it isn't mistaken for a regression.

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

The component tests cover row visibility, matching and navigation. The `/?project=` prefill is existing behaviour exercised by the pencil's tests, so it was checked by hand rather than re-tested here.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Start a new chat in a project from the command palette: type part of the project's name and pick "New chat in …".

🤖 Generated with [Claude Code](https://claude.com/claude-code)
