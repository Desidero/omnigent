# Security review: upstream PR #6136 (btli), extra-keys row, head d2c80fe

Third-party code we carry as `terminal-touch` patch 1. Read before running
anything from it, as the house rule asks for any outside PR. Diff:
`git diff $(git merge-base d2c80fe upstream/main) d2c80fe` (merge base
869f320366, 15 commits, 24 files, +2492/-25), which matches `gh pr diff 6136`
line for line. Line numbers below are at d2c80fe. Report only; nothing in the
PR was modified.

## Verdict

**No security concerns. Safe to keep carrying and running.** The change is
confined to the web terminal UI, a Settings card and its tests. It sends
nothing anywhere new, renders no HTML from data, adds no dependency and
touches no script, CI or workflow file.

## What was checked

- **Data leaving the browser:** no `fetch`, `XMLHttpRequest`, `WebSocket`,
  `sendBeacon`, `postMessage`, `window.open` or URL in any source file. Key
  bytes go out only through the terminal's existing WebSocket, via
  `TerminalSession.sendInput` (`web/src/components/blocks/TerminalSession.ts:999`),
  which is the same send code the `onData` handler used before, moved into a
  method.
- **Analytics:** the new Select passes `componentId="settings.appearance.terminal_extra_keys"`
  and `valueHasNoPii` (`web/src/pages/SettingsPage.tsx:596-597`), so the chosen
  mode (`auto` / `on` / `off`) goes through upstream's existing UI analytics
  (`web/src/components/ui/select.tsx:18`). Three fixed values, no PII; same
  pattern as the other Settings selects.
- **Code execution / HTML injection:** no `eval`, `new Function`, `innerHTML`,
  `dangerouslySetInnerHTML`, `insertAdjacentHTML` or `document.write`. Key
  labels are static strings from `EXTRA_KEY_ROWS`
  (`web/src/components/blocks/terminalExtraKeysModel.ts:25`) rendered as React
  text.
- **Clipboard:** no clipboard read or write. The one clipboard-adjacent effect:
  `sendInput` stamps `lastUserInputAt` (`TerminalSession.ts:1003`), the
  "recent local input" signal that gates OSC 52 clipboard writes
  (`TerminalSession.ts:1057`). Row taps and wheel reports stamp it. Both are
  real user gestures, and wheel reports already stamped it before the PR (they
  went through `term.input` and `onData`). No path lets pane output or a remote
  peer stamp it, so the consent gate is not weakened.
- **Input rewriting:** `setInputTransform` (`TerminalSession.ts:991`) rewrites
  single-character `onData` chunks while a sticky modifier is armed or locked.
  Longer chunks (paste, IME commits) pass through unchanged
  (`terminalExtraKeysModel.ts:152`). Row keys and wheel reports skip the
  transform. The transform is cleared when the row unmounts
  (`web/src/components/blocks/TerminalExtraKeys.tsx:108-113`), so a stuck
  modifier cannot outlive the row.
- **Storage:** one `localStorage` key, `omnigent:terminal-extra-keys`
  (`web/src/lib/terminalExtraKeysPreferences.ts:7`). It holds only the
  enumerated mode, is normalized on read (an unknown value falls back to
  `auto`), and every access is in `try`/`catch`. Settings' reset clears it
  (`SettingsPage.tsx:1085`).
- **Dependencies, lockfiles, scripts, CI:** none. No change to
  `package.json`, `pnpm-lock.yaml`, `pyproject.toml`, `uv.lock`, `.github/`,
  `scripts/` or any build config.
- **Outside the terminal UI:** the Settings page (a "Touch & mobile" group
  and its card), `web/src/components/theme/AppearancePreviews.tsx` (a
  static thumbnail; the existing clip-path became a shared constant),
  `web/src/index.css` (styles for `.terminal-extra-keys` only), unit tests,
  Storybook stories and five PNG snapshot baselines (8 to 13 KB each, the
  same files as our patch). No server, runner, native iOS/Android or Python
  application code.
- **Tests:** the E2E file `tests/e2e_ui/terminal/test_extra_keys.py` imports
  only `os`, `re`, `time`, `pathlib` and Playwright. It types
  `stty raw -echo; cat > '<tmp_path>/keys.txt'` into the test's own throwaway
  shell (line 196) to record the bytes, reads `OMNIGENT_E2E_RECORD_DIR` for
  optional video (line 39), and may force `pointer: coarse` through CDP
  (line 54). Everything is test-local. The vitest files mock only in-repo
  modules (`@/hooks/useIOSNativeKeyboardInset`, `./TerminalSession`,
  `next-themes`, `@/lib/embedded`, `@/lib/CapabilitiesContext`).

## Non-security notes (functional, minor)

- `encodeModifiedInput` passes multi-character chunks through unchanged, but
  the transform still consumes an armed modifier on any `onData` chunk
  (`TerminalExtraKeys.tsx:88-97`). `onData` also carries xterm's own replies
  (cursor-position reports, focus in/out reports when a program enables them),
  so a program query that lands between tapping Ctrl and typing the letter can
  disarm Ctrl. This is Termux's documented semantics for typed input. A reply
  arriving in that window is rare. Not worth raising unless it shows up in use.

## Relation to our copy

Patch 1 at `custom/BASE` (65be0f2468) is the PR's change plus our
`touch-keys` entry in `feature-map/terminals.md`, which the series docs rule
needs. Since `series/terminal-touch-6136-head` the web code is byte-identical
to d2c80fe for every file the PR adds, and its hunks in the files that
already existed (`TerminalSession.ts`, `TerminalView.tsx`, `index.css`,
`SettingsPage.tsx` and their tests) match the PR's hunks line for line.
