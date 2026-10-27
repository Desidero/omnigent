<!-- Draft PR body for the terminal-touch series; title: feat(web): long-press to select, copy and paste in the terminal on touch devices -->

> Status: the first commit of this series (Termux-style extra-keys row) is a squashed copy of upstream PR #6136, which is still open. Its two iOS fixes (cancel `touchend` on the key row so the soft keyboard stays up; pad the row by the bottom safe area unless the keyboard is docked) will be suggested on #6136 rather than sent here. Drop that commit once #6136 lands. This PR body covers the two new commits, a follow-up to #6136.

## Related issue

Closes #TODO (issue to be opened)
Refs #6136

## Summary

Builds on upstream PR #6136 (extra-keys row); stacked on it and would be rebased once it merges.

On a phone you can now long-press in the terminal to select text, then Copy, Paste or Select screen from a small menu, the way you would in a native terminal app.

The terminal draws to a canvas and xterm only selects with a mouse, so on touch devices there was no way to copy terminal output and no Paste control.

- **Long-press selection.** A still long-press (450 ms) selects the word under the finger through xterm's public `select()` API. On a blank cell it offers Paste only. Continuing the same gesture extends the selection. The `touchend` is cancelled so it never reaches the pane program as a click, and scrolling before the hold time cancels the press.
- **Handles and menu.** Drag handles adjust either end and scroll the scrollback past the edges. A tap, or xterm dropping the selection, dismisses it. The menu offers Copy (through the existing terminal clipboard consent), Paste (through xterm's paste, so bracketed paste applies; hidden on read-only terminals) and Select screen. The iOS long-press callout is disabled on the terminal surface.
- **Native clipboard read on iOS.** In the iOS app, `navigator.clipboard.readText` makes WebKit show its own Paste bubble on every paste. The shell's bridge now exposes `readClipboardText()`, backed by `UIPasteboard`, so the app's Settings › Omnigent › Paste from Other Apps permission applies and "Allow" removes the extra tap. Shells without the method, and the web, keep the `navigator.clipboard` path.

Docs: `feature-map/terminals.md` gains the Extra keys row setting, a `touch-select` entry with a manual check, and the iOS Paste permission.

## Test Plan

```sh
cd web && pnpm exec vitest run src/components/blocks/terminalTouchSelection.test.ts \
  src/components/blocks/TerminalSession.test.ts src/components/blocks/TerminalView.test.tsx
cd web && pnpm exec tsc -b
```

The tests cover word lookup and cell/boundary math, the long-press timing and scroll cancel, extending and dragging handles (including crossing the fixed end), dismissal, copy through clipboard consent, paste through xterm, no Paste on read-only terminals, and paste through the iOS shell's reader when present.

Manual, on a phone or tablet against a throwaway server:

1. Open a session's Terminal view and run `ls -la` or similar.
2. Long-press a word. It is selected with a handle at each end and a menu with Copy, Paste and Select screen. The pane program does not receive a click.
3. Drag a handle up past the top edge. The scrollback scrolls and the selection grows.
4. Tap Copy (accept the clipboard prompt the first time), then paste into another app. The selected text matches.
5. Long-press a blank area and tap Paste. The clipboard text is typed into the terminal as one bracketed paste (for example, multi-line text in a shell does not run line by line).
6. Tap Select screen, then Copy. The whole visible screen is copied.
7. iOS app only: set Settings › Omnigent › Paste from Other Apps to Allow, then Paste. No WebKit Paste bubble appears.

The iOS clipboard part has so far been tested only on a locally built (sideloaded) app.

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

To capture on a clean throwaway server with dummy terminal output:

- [ ] TODO: phone recording of long-press select, dragging a handle into the scrollback, and Copy
- [ ] TODO: phone recording of long-press on a blank cell and Paste of multi-line text
- [ ] TODO: screenshot of the selection menu (Copy / Paste / Select screen) on a read-only terminal (no Paste)
- [ ] TODO: iOS app recording of Paste with "Paste from Other Apps: Allow" (no system Paste bubble)

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

Touch gestures, the system clipboard and the native pasteboard can't be driven in jsdom, so the steps above were checked by hand on an iPhone. The native clipboard read was tested only on a locally built iOS app, not a store build.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Long-press in the terminal on phones and tablets to select text, then copy, paste or select the whole screen
