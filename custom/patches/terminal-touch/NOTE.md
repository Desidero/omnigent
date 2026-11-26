# terminal-touch

Needs: none
Covers: 5d8f561610acca50

The terminal on phones and tablets: an extra-keys row under it sends the keys
a soft keyboard lacks (Esc, Tab, Shift+Tab, arrows, Home/End, PgUp/PgDn, and
sticky Ctrl, Alt and Shift), and a long-press selects terminal text, with a
menu to Copy, Paste and Select screen. In the iOS app, Paste reads the
clipboard natively, so the app's paste permission applies instead of a prompt
on every paste. Upstream's one-finger swipe scrolling works as before.

- **Turn on:** on by default on touch devices. Settings → Appearance → Touch &
  mobile → **Extra keys row** chooses Auto (touch devices), Always or Never;
  the long-press has no setting. Native paste needs an iOS app built with the
  series.
- **Docs:** [Terminals](../../feature-map/terminals.md) (`touch-keys`,
  `touch-select`, and the iOS Paste gotcha).
- **Upstream:** the extra-keys row is carried from
  [#6136](https://github.com/omnigent-ai/omnigent/pull/6136) (not ours, open),
  squashed from its head `2a68aafb59`; the second patch is what that head
  lacks to pass main's web tests. The long-press and native paste are not
  proposed upstream yet (an issue and a pull request are drafted, not
  filed).

## Must hold

- The row shows under a terminal the user can type into when the setting is Always, or Auto on a coarse pointer or in the iOS or Android app, at any width; never on a read-only attach, and it is not rendered at all otherwise.
- A row key goes out as one frame with the bytes a hardware key would send: a lone `ESC`, `CSI Z` for Shift+Tab, arrows and Home/End following application cursor mode. A tapped modifier applies to the next row key or typed character and then releases; a held one stays until tapped; a locked one survives a reconnect.
- Tapping a plain row key never moves focus, so it neither raises nor dismisses the soft keyboard.
- The Extra keys row setting has a Settings search entry; no control of it is exempted in the unowned-controls baseline.
- A still long-press (450 ms) selects the word under the finger, or offers Paste alone on a blank cell; a finger that moves before then scrolls as upstream's touch scrolling does. The press never reaches the program as a click.
- Copy goes through the terminal clipboard consent; Paste goes through xterm's paste, so bracketed paste applies, and is not offered on a read-only terminal.
- In an iOS app that has `readClipboardText`, Paste uses it; every other shell and browser uses `navigator.clipboard`.

## Key code

- `web/src/components/blocks/TerminalExtraKeys.tsx`: `TerminalExtraKeys`, `ExtraKeysTarget`
- `web/src/components/blocks/terminalExtraKeysModel.ts`: `encodeExtraKey`, `encodeModifiedInput`, `reduceModifiers`
- `web/src/hooks/useTerminalExtraKeysVisibility.ts`: `useTerminalExtraKeysVisibility`
- `web/src/pages/settings/search/catalog/appearance.ts`: `TERMINAL_EXTRA_KEYS_ENTRY`
- `web/src/components/blocks/terminalTouchSelection.ts`: `TerminalTouchSelection`, `wordRangeAt`, `TOUCH_SELECT_LONG_PRESS_MS`
- `web/src/components/blocks/TerminalSession.ts`: `sendInput`, `setInputTransform`, `touchSelection`, `paste`
- `web/src/components/blocks/TerminalView.tsx`: `pasteFromClipboard`, `copyTouchSelection`, `showExtraKeys`
- `web/src/lib/nativeBridge.ts`: `canReadNativeClipboard`, `readNativeClipboardText`
- `web/ios/Omnigent/OmnigentWebView.swift`: `readClipboardText` (not compiled by the web checks)

## Tests

- `web/src/components/blocks/TerminalExtraKeys.test.tsx`
- `web/src/components/blocks/terminalExtraKeysModel.test.ts`
- `web/src/hooks/useTerminalExtraKeysVisibility.test.ts`
- `web/src/components/blocks/terminalTouchSelection.test.ts::does nothing before the hold time, or once the finger starts scrolling`
- `web/src/components/blocks/TerminalSession.test.ts::selects a word on long-press without scrolling or sending a tap to the program`
- `web/src/components/blocks/TerminalView.test.tsx` ("extra-keys row", "touch selection menu", including "pastes through the iOS shell's clipboard reader when it has one")
- `web/src/pages/settings/search/settingsPageAudit.test.tsx::finds an owner for every control it renders, and shows every row and part somewhere`
- `tests/e2e_ui/terminal/test_extra_keys.py` (browser test from the carried pull request; not run locally)
