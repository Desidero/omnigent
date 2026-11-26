# palette-new-chat-in-project

Needs: none
Covers: 1e5685b24fe0c356

Typing in the ⌘K command palette lists a "New chat in <project>" row for every
project; choosing one opens the new-session composer with that project's
defaults (`/?project=<name>`). Both palettes list the rows: the classic one and
the QuickPick one (`quick_pick_palette`).

- **Turn on:** on by default; the rows appear once you type in ⌘K.
- **Docs:** [Composer](../../feature-map/composer.md) (`palette-new-chat-in-project`).
- **Upstream:** proposed from `feat/palette-new-chat-in-project`,
  [#11394](https://github.com/omnigent-ai/omnigent/pull/11394) (draft, written
  before the QuickPick palette existed); its issue
  [#4409](https://github.com/omnigent-ai/omnigent/issues/4409) was closed by the
  stale bot. Upstream's draft
  [#14806](https://github.com/omnigent-ai/omnigent/pull/14806) (not ours) adds
  "New session in <name>" to QuickPick for the project in view only, as a
  registry command under **Project**. The two do not share code: this series
  lists every project, only while typing, in its own group, and touches none of
  the files that draft adds. If it merges, leave the project in view to its row
  (skip that project here) and take its `newSessionInProjectPath` in place of
  `newChatInProjectPath`.

## Must hold

- With an empty query no project row shows, in either palette, however many projects exist; the sessions-only switcher never lists them.
- A row shows when every typed word is in "New chat in project <name>": `omni`, `new omni` and `project` all reach "New chat in omnigent".
- Choosing a row (Enter or click) closes the palette and opens `/?project=<url-encoded name>`, the composer with that project's defaults. It does not open the project home.
- When only project rows match, the first one is highlighted, so Enter runs it.
- In QuickPick the rows never move above sessions that match the same word, and they are not recorded under Recent.

## Key code

- `web/src/shell/newChatInProject.ts`: `useNewChatInProjectChoices`, `matchNewChatInProject`, `newChatInProjectPath`, `newChatInProjectRowId`
- `web/src/shell/CommandPalette.tsx`: `filteredProjects`, `newChatInProject`
- `web/src/shell/QuickPickCommandPalette.tsx`: `projectChoices`
- `web/src/shell/paletteTarget.ts`: `PaletteTarget`

## Tests

- `web/src/shell/CommandPalette.test.tsx` ("new chat in project"; `CommandPalette.quickPick.test.tsx` runs the same cases against QuickPick)
