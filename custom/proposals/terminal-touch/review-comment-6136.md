<!-- posted 2026-10-23: https://github.com/omnigent-ai/omnigent/pull/6136#discussion_r4363312757; addressed in d2c80fe (2026-10-27) -->
We have been running this PR on iPhones (iOS app) for a few weeks now, and it is a big improvement for driving TUIs from a phone. Two iOS-specific issues came up that we have been carrying as a local fix; both still apply to the current head (92f437a).

- **Every tap on the row dismisses the soft keyboard on iOS.** `pointerdown` is prevented, but WebKit still moves focus to the tapped button on the synthetic click that follows `touchend`, so xterm's textarea blurs and the keyboard closes after each key. Cancelling `touchend` on the toolbar keeps focus on the terminal (`web/src/components/blocks/TerminalExtraKeys.tsx`, line 204):

  ```suggestion
        onContextMenu={(e) => e.preventDefault()}
        // iOS moves focus on the tap's synthetic click even after pointerdown is
        // prevented; cancelling touchend keeps xterm's textarea and the keyboard.
        onTouchEnd={(e) => e.preventDefault()}
  ```

- **The bottom keys sit under the home indicator in the iOS terminal view.** The `.main-terminal-view` rule in `index.css` zeroes the safe-area padding on the assumption that a native bottom bar spacer reserves it, but on `main` the terminal view no longer reserves anything at the bottom, so PgUp/PgDn and the arrows end up under the rounded corners. What we found works is to drop the inset only while the keyboard is docked (it covers the home indicator then), using the existing `useIOSNativeKeyboardInset` hook:

  ```diff
  --- a/web/src/components/blocks/TerminalExtraKeys.tsx
  +++ b/web/src/components/blocks/TerminalExtraKeys.tsx
  @@ import { cn } from "@/lib/utils";
  +import { useIOSNativeKeyboardInset } from "@/hooks/useIOSNativeKeyboardInset";
  @@   const transformRef = useRef<ExtraKeysInputTransform | null>(null);
  +  const keyboardOpen = useIOSNativeKeyboardInset() > 0;
  @@       data-testid="terminal-extra-keys"
  +      data-keyboard-open={keyboardOpen || undefined}
  --- a/web/src/index.css
  +++ b/web/src/index.css
  -/* The mobile drawer and the iOS terminal-first surface already reserve the
  -   bottom inset (drawer padding / native bar spacer); don't add it twice. */
  +/* The mobile drawer already reserves the bottom inset, and a docked iOS
  +   keyboard covers the home indicator; don't add the inset in either case. */
   :is([data-ios-native], [data-android-native]) .mobile-panel-drawer .terminal-extra-keys,
  -[data-ios-native] .main-terminal-view .terminal-extra-keys {
  +[data-ios-native] .terminal-extra-keys[data-keyboard-open] {
     padding-bottom: 0.25rem;
   }
  ```

We also have two small unit tests for these (touchend returns `false` and sends once; `data-keyboard-open` follows the mocked inset) in `TerminalExtraKeys.test.tsx`. Happy to open them as a follow-up PR on top of this one if you would rather keep this PR as is.

---

Addressed: btli folded both fixes into the PR on 2026-10-27 (head `d2c80fe`, "fix(web): keep the iOS keyboard and home-indicator inset with extra keys", with us as co-author), including both unit tests. Our patch 1 now matches that head (see `../_reviews/review-6136-terminal-extra-keys.md`), so it can be dropped as-is when #6136 merges; no follow-up patch or PR is needed for the iOS fixes.
