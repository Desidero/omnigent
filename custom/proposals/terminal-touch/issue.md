Title: [Feature] Select, copy and paste in the terminal on phones and tablets

### Problem or use case

On a phone or tablet you can't get text out of the terminal or paste text into it. That covers the agent terminal in Terminal view and user shells, in a mobile browser and in the iOS and Android apps.

- **No selection.** xterm draws to a canvas and only selects with a mouse. A long-press on the terminal doesn't select terminal text, and on iOS it may bring up the system callout for the page instead. Copying a path, an error message, a URL the agent printed or a command's output means retyping it.
- **No paste.** The terminal has no Paste control and the iPhone keyboard has no paste key, so there's no obvious way to paste a long token, a multi-line snippet or a command into a TUI (Claude Code, Codex, vim, a shell).

The touch scrolling added in #5853 already makes the scrollback reachable by finger, so you can find the text you want but can't do anything with it. We use the Terminal view on iPhones (iOS app) to drive TUIs, and with the extra-keys row from #6136 in place, copy and paste is the main gap left.

### Proposed solution

Long-press selection with a small action menu, the way native terminal apps on iOS and Android work:

- **Long-press to select.** A still long-press (about 450 ms) selects the word under the finger, using xterm's public `select()` API. Moving the finger before the hold time is up still scrolls as it does now. Dragging after the selection appears, in the same gesture, extends it. The `touchend` is cancelled so the press never reaches the pane program as a click. The system long-press callout is turned off on the terminal surface.
- **Handles.** A drag handle at each end adjusts the range. Dragging past the top or bottom edge scrolls the scrollback, so a selection can cover more than one screen.
- **Menu.** Next to the selection: **Copy** (through the existing terminal clipboard consent prompt), **Paste** (through xterm's `paste()`, so bracketed paste applies and multi-line text arrives as one paste instead of running line by line) and **Select screen** (the whole visible screen). A long-press on a blank cell shows Paste and Select screen only. Read-only terminals don't show Paste.
- **Dismissal.** A tap elsewhere, or xterm clearing the selection, removes the handles and the menu.
- Desktop and mouse input are unchanged; the code only runs for touch events.

This builds on #6136 (the Termux-style extra-keys row) and would be stacked on it: both change the same terminal touch surface, and with the row in place a phone can drive a TUI fully, keys and clipboard. It doesn't depend on the row's code and could also be rebased onto `main` alone.

An optional follow-up for the iOS app: `navigator.clipboard.readText()` in WKWebView shows WebKit's own Paste bubble on every paste. A native clipboard read through the app's bridge would apply the system "Paste from Other Apps" permission instead. This is separate and only affects the iOS shell.

### Alternatives considered

- **tmux copy mode** through the extra-keys row: works for copying inside tmux, but getting text onto the device clipboard still needs OSC 52 and the consent prompt. It is awkward with a soft keyboard and does nothing for paste.
- **A plain "Copy screen" button:** simple, but you can't pick a word or a range, and it doesn't help with paste.
- **An invisible DOM text layer over the canvas** for native selection: it would have to mirror the buffer and track scrolling, resizes and reflow, and it would fight the existing touch-scroll handling. Using xterm's own selection keeps one source of truth.

### Harness

Not applicable

### Platform or device

iOS, Android

### Harness mode

Not applicable

### Expected reach

Some users

### Authentication type

Not authentication-related

### Version

main @ ebd0be9419

---

I have a working implementation on a branch, with unit tests for the word and boundary math, the long-press timing and scroll cancel, the handles, copy through the consent prompt, and paste. I can open it as a PR, but I'm at the project's limit for open PRs right now, so I'll open it when a slot frees up. If a maintainer would like it sooner, I'm happy to swap it in.
