# new-chat-project-prompt

Needs: none
Covers: 7a17463180a36684

Starting a new session asks which project it belongs to: the new-session hotkey,
the sidebar's New session links and ⌘K's New chat (either palette) open a
"Start a new session in…" picker with No project first, then every project.
Picking one opens the composer with that project's defaults. On a project's
home page they don't ask: the session starts in that project. Below the `md`
breakpoint the prompt is a bottom sheet without a search field.

- **Turn on:** on by default once you have a project; turn it off with
  Settings → General → Sessions → **Ask for a project when starting a session**
  (kept per device).
- **Docs:** [Composer](../../feature-map/composer.md) (`new-session-project-prompt`).
- **Upstream:** proposed from `feat/new-chat-project-prompt`,
  [#11397](https://github.com/omnigent-ai/omnigent/pull/11397) (draft, written
  when the prompt was a step of the one command palette); issue
  [#11083](https://github.com/omnigent-ai/omnigent/issues/11083). It no longer
  builds on `palette-new-chat-in-project`: the prompt is its own picker, so the
  two only meet in the feature map and the palette's test file.

## Must hold

- With the prompt on and at least one project, away from a project's home page, a plain click on either sidebar New session link, the new-session shortcut, and New chat in either palette open the prompt instead of the composer, leaving the current page as it is until a choice is made. Escape or a click outside changes nothing.
- No project opens `/`; a project opens `/?project=<url-encoded name>`.
- On a project's home page, with the prompt on, all three entry points start the session in that project without showing the prompt: on desktop the home's composer opens over the board, as the home's New session button does; on phones `/?project=<name>` opens. This holds even before the project list has loaded. The prompt is only for places with no project home in view.
- On the composer filed under a project (`/?project=<name>`) the prompt still asks, with that project highlighted on desktop so Enter starts the session there; the sheet marks it Current.
- With the prompt off, with no project, or when the project list fails to load, the same entry points open the plain composer. A prompt opened before the list loaded lists projects as they arrive and steps aside if none do.
- Modified and middle clicks on the links still open the composer in a new tab.
- The prompt and the command palette never stack: whichever opens last replaces the other.

## Key code

- `web/src/store/newSessionProjectPrompt.ts`: `startNewSession`, `askForProjectOnNewSessionClick`, `useNewSessionProjectPromptStore`
- `web/src/shell/NewSessionProjectPrompt.tsx`: `NewSessionProjectPrompt`, `projectInView`, `newSessionPath`
- `web/src/shell/NewSessionProjectSheet.tsx`: `NewSessionProjectSheet`
- `web/src/components/ui/bottom-sheet.tsx`: `BottomSheet`, `BottomSheetContent`
- `web/src/lib/newChatProjectPromptPreferences.ts`: `readNewChatProjectPromptEnabled`
- `web/src/pages/settings/search/catalog/general.ts`: `NEW_CHAT_PROJECT_PROMPT_ENTRY`
- `web/src/shell/AppShellOverlays.tsx`: `NewSessionProjectPrompt`
- `web/src/shell/Sidebar.tsx`: `askForProjectOnNewSessionClick`
- `web/src/hooks/useNewSessionHotkey.ts`: `startNewSession`
- `web/src/shell/appCommands.ts`: `startNewSession`

## Tests

- `web/src/shell/NewSessionProjectPrompt.test.tsx`
- `web/src/store/newSessionProjectPrompt.test.ts`
- `web/src/shell/Sidebar.newSessionPrompt.test.tsx`
- `web/src/components/ui/bottom-sheet.test.tsx`
- `web/src/pages/SettingsPage.test.tsx::asks for a project on new sessions by default and persists turning it off`
- `web/src/pages/settings/search/settingsSearchSource.test.ts`
