# feat(web): add a project chip to the phone new-session landing

## Related issue

Part of #11083

## Summary

On a phone, the new-session landing no longer says which project you are starting in: the heading always reads "Start a new session in", only the icon above it changes, and the composer placeholder drops the name. Choosing a project is also hidden behind **+ › Work in a project**.

This adds a project chip as the first control under that heading, on phones only. It reads "No project ▾" or the selected project's icon and name, tinted with the brand accent so it reads as the main choice. Tapping it opens a menu with **No project** first, then every project, and a check on the current one. Rows are at least 44px, and there is no search field, so the keyboard stays down.

- Picking a project goes through the same `?project=<name>` switch the + menu already uses (now one shared `selectLandingProject` helper), so the project's defaults prefill the composer as before.
- **No project** removes only `project` from the query string and keeps the other parameters. The landing stays mounted, so the draft text and attachments are kept. The existing reseed effect on a `?project=` change resets the host, workspace and agent to the plain-visit defaults, as it does for the sidebar's **New session** button.
- Picking the project that is already selected no longer pushes a duplicate history entry.
- Desktop is unchanged: it still names the project in the heading and has no chip. **Add nested agent** has no chip either.

The menu is the existing `DropdownMenu` with the mobile glass surface used by other phone menus. The codebase has no bottom-sheet primitive, and `ProjectPicker` has a search field, so I didn't reuse it here. Its `ProjectRowIcon` provides the icons.

This is a smaller step toward #11083: it makes the project choice visible on the phone landing. It doesn't add the prompt on every entry point.

## Test Plan

- `pnpm exec vitest run src/shell/NewChatLandingScreen.mobileChrome.test.tsx` (5 passed). New cases cover the following:
  - The chip is the first phone control and reads "No project".
  - The menu has no text box, lists No project then each project, and every row has the 44px minimum.
  - Picking a project navigates to `/?ref=docs&project=api`.
  - With `?project=web` the chip shows the project's icon and name. No project navigates to `/?ref=docs`. Once that URL is applied to the mounted landing, the chip reads No project, the typed draft is still there, and the message box isn't focused.
  - On desktop the heading names the project and there is no chip.
- `pnpm exec vitest run src/shell/NewChatLandingScreen.onboardingRunner.test.tsx src/shell/NewChatDialog.projectPrefill.test.tsx` (60 passed), and the `project` cases in `src/shell/NewChatDialog.test.tsx` (19 passed).
- `tsc -b` and the pre-commit hooks (prettier, oxlint, type check) pass.

To try it, open the app at phone width with at least one project:
1. Type a draft, then tap **No project** under "Start a new session in".
2. Pick a project. The chip should show its name and the composer should take its defaults, with the draft unchanged.
3. Tap the chip again and pick **No project**. The URL should lose only `project` and the draft should stay.

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
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The prefill after a project switch is the existing `?project=` path, already covered by `NewChatDialog.projectPrefill.test.tsx`. The feature map entry is `feature-map/composer.md` (`mobile-project-chip`).

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

On phones, the new-session screen shows a project chip for choosing which project a session starts in

🤖 Generated with [Claude Code](https://claude.com/claude-code)

