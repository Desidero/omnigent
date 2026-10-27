# Pre-PR review: `fix/toast-safe-area` (f2e1daaf5)

Diff: 3 added lines in `web/src/shell/AppShell.tsx` (branch lines 2813, 2815, 2820;
the same `<Toaster>` block sits at upstream/main `AppShell.tsx:2823-2834`).
Report only; nothing was modified.

## Verdict

**Ship it after amending the commit message** (one factual error, see Must fix).
The code is correct, minimal, uses the repo's own safe-area variable, formats
clean (prettier --check passes), compiles and runs (the identical `custom`
copy is already deployed), and rebases onto
upstream/main with no conflicts. A tiny unit test is cheap and worth adding
(see Tests) but not blocking.

Correctness notes behind the verdict:

- Library: sonner 2.0.8 (`web/package.json:100`) through the wrapper
  `web/src/components/ui/sonner.tsx`; the app has exactly one mount,
  `AppShell.tsx:2823` (upstream numbering). Test files mount their own
  `<Toaster>` and are unaffected.
- Layer: right one. sonner's `offset`/`mobileOffset` go through `assignOffset`
  (`web/node_modules/sonner/dist/index.mjs:898`), which writes
  `--offset-top` / `--mobile-offset-top` as inline custom properties on the
  toaster container `<ol data-sonner-toaster>`; CSS then does
  `[data-y-position=top] { top: var(--offset-top) }` (`dist/styles.css:73`,
  mobile variant `:457`). Individual toasts are `position:absolute; top:0`
  inside that container, so moving the container moves the stack. The patch
  touches the container, not per-toast styles. Per-key: `assignOffset` only
  overrides the keys given, so `left` keeps sonner's 24px/16px defaults.
- Top vs bottom: position is `top-center`, so only `top` matters today; the
  bottom edge was already inset-aware via `updateOverlayToastOffset`
  (`web/src/lib/updateOverlayInset.ts:4`, `1rem + var(--omnigent-inset-bottom)`),
  and the patch mirrors that shape. Both offsets are now safe-area aware if
  the position ever changes.
- Landscape / left-right insets: not needed. sonner's mobile rules apply only
  below 600 CSS px (`styles.css:430`); every iPhone in landscape is >= 667px
  wide, so the desktop rules apply: the container is centered
  (`left:50%; translateX(-50%)`, `styles.css:68-70`) at a fixed 356px width,
  which never reaches the notch/Dynamic Island on the short edge, and iOS
  reports `safe-area-inset-top` = 0 in landscape, so the toast sits at
  sonner's normal 24px. Portrait (< 600px) uses full width minus the 16px /
  1rem side offsets; portrait has no left/right insets.
- `--omnigent-inset-top` is the repo's established helper
  (`web/src/index.css:221`, = `--omnigent-safe-top` =
  `max(env(safe-area-inset-top), var(--omnigent-android-safe-area-top))`,
  `index.css:197-200`). It deliberately excludes the iOS floating
  server-switcher pill footprint (`--omnigent-native-top-bar`), so a toast can
  overlap that 36px pill (`web/ios/Omnigent/WebShellView.swift:485-487`) when
  the pill is shown; that is the same relationship a toast has with the web
  chat header on every platform, and per
  `tests/e2e_ui/mobile/test_ios_server_selector_placement.py` the pill is no
  longer requested over the chat surface. Not a problem.
- Electron / plain browsers: nothing injects `viewport-fit=cover`
  (`web/index.html:19` has none; the iOS and Android shells inject it
  themselves at `web/ios/Omnigent/OmnigentWebView.swift:151` and
  `web/android/.../NativeBridgeScript.kt:43`), so `env()` is 0, the Android
  var is unset, and `calc(24px + 0px)` is the pre-patch value. No regression.
  Do not add `viewport-fit=cover` to `index.html` in this PR.
- Android shell: **does** get a top inset (see Must fix), which is the desired
  behavior (edge-to-edge draws behind the status bar).
- `max()` vs `calc()`: additive `calc()` is correct. `max(24px, 59px)` would
  butt the toast against the Dynamic Island with zero gap; `calc` keeps the
  24px/16px breathing room, and matches the bottom helper.
- Custom-property inheritance: sonner renders inline in the React tree (no
  portal), and the var is defined on `:root`, so it resolves inside the `<ol>`.

## Must fix

1. **Commit message body is wrong about Android.**
   `git log -1 --format=%B fix/toast-safe-area`, last sentence: "Desktop and
   Android without a top inset keep sonner's default gaps."
   Why: the Android shell injects the status-bar height into
   `--omnigent-android-safe-area-top` *and* `--omnigent-safe-top`
   (`web/android/app/src/main/java/ai/omnigent/android/MainActivity.kt:1630-1632`,
   from `bars.top` at `:943`/`:969`), which `index.css:197-200` folds into
   `--omnigent-inset-top`. So Android-shell toasts move down by the status-bar
   height too (good, and should be stated, not denied; a reviewer who knows
   the Android shell will flag it). Suggested wording:
   "The Android shell feeds its status-bar inset through the same variable, so
   it gets the same treatment; browsers and the Electron shell, where the
   inset is 0px, keep sonner's default gaps." Consider the title
   `fix(web): keep top toasts below the native status bar / Dynamic Island`.
   Amend with `git commit --amend -s` (keep the sign-off) and force-push the
   contribution branch; also fix the `custom` copy (Nit 4).

## Should fix

1. **Add a unit test (2-3 lines) by extracting the offsets next to the
   existing helper.** `AppShell.tsx:2814-2823` now duplicates
   `right: "1rem"` / `bottom: updateOverlayToastOffset(...)` across `offset`
   and `mobileOffset`, and the new `top` strings are untested string
   arithmetic. Suggested: in `web/src/lib/updateOverlayInset.ts` add
   `toasterOffsets(updateOverlayHeight)` returning `{ offset, mobileOffset }`
   (top `calc(24px + var(--omnigent-inset-top))` / `calc(16px + ...)`), use it
   as `{...toasterOffsets(updateOverlayHeight)}` in AppShell, and add one `it`
   to `web/src/lib/updateOverlayInset.test.ts` asserting both `top` strings.
   This is the repo's "lowest reliable layer" and reuses the helper that
   already owns the bottom expression. Alternative (no refactor): a render
   assertion in `web/src/shell/AppShell.test.tsx` (it does not mock sonner;
   `:299` imports the real `toast`):
   `expect(document.querySelector("[data-sonner-toaster]")?.style.getPropertyValue("--offset-top")).toBe("calc(24px + var(--omnigent-inset-top))")`
   and the `--mobile-offset-top` twin; jsdom reads inline custom properties
   (same pattern as `web/src/lib/customTheme.test.ts:283`).

## Nits

1. `AppShell.tsx:2813` comment `// Top toasts start below the iOS status bar / Dynamic Island.`
   says iOS only; it applies to the Android shell too. Suggest
   `// Keep top toasts below the native status bar / Dynamic Island.` or drop
   it (the `calc` is self-describing). Short, no issue numbers: fine per
   repo CLAUDE.md.
2. `24px` / `16px` are hand-copied from sonner's unexported
   `VIEWPORT_OFFSET` / `MOBILE_VIEWPORT_OFFSET` (`dist/index.mjs:466,468`).
   Acceptable (they are sonner's documented defaults and this is the only way
   to keep them), but the bottom offset uses `1rem`; mixing px and rem is
   cosmetic. No change required.
3. `var(--omnigent-inset-top)` without a `, 0px` fallback matches
   `chatBubbleParts.tsx:2056`, `CanvasPage.tsx:582` and index.css, while
   `StreamBudgetBanner.tsx:18` / `TerminalClipboardPrompt.tsx:110` use a
   fallback. Both styles exist; the var is always defined on `:root`. Fine.
4. (Local, not the PR) The `custom` copy 87063d904 says "Carried on custom
   until our upstream PR for this lands (not opened yet)." `~/repos/CLAUDE.md`
   asks for `Not upstream yet: proposed from fix/toast-safe-area; drop this
   copy once it merges.` Reword at the next `custom` rebase.

## Tests

- In the commit: none. Existing related coverage: `updateOverlayInset.test.ts`
  (bottom expression only), `components/ui/toast.test.tsx`,
  `archiveUndoToast.test.tsx` (render real `<Toaster>`), none asserts top
  offset.
- Recommended: the helper + unit test above (Should fix 1). A full e2e is
  possible but disproportionate: the repo already emulates a notch in
  Chromium via CDP `Emulation.setSafeAreaInsetsOverride`
  (`tests/e2e_ui/mobile/test_native_shell_plan_header_overlap.py:182-183`,
  47px top), so a mobile e2e could fire a toast and assert
  `bounding_box().y >= 47 + 16`; mention it only if a maintainer asks.
- Suggested PR template answers: Test coverage = "Unit tests added" (if the
  helper test lands) + "Manual verification completed". Coverage notes:
  "The offset strings are unit-tested; the safe-area value itself comes from
  `env(safe-area-inset-top)` which jsdom cannot resolve, so placement was
  verified on an iPhone (iOS app, Dynamic Island) and emulated in Chromium
  with CDP `Emulation.setSafeAreaInsetsOverride` (the mechanism the mobile
  e2e suite uses); desktop/Electron unchanged (inset 0px)."
- Release notes: small user-facing fix; "No" is defensible per the repo rule
  for small fixes. If "Yes": "iOS/Android apps: notification toasts no longer
  hide under the status bar or Dynamic Island."

## Upstream drift

- Branch is 389 commits behind upstream/main (not ~358).
- Dry-run merge: the invocation in the task errors out (`git merge-tree
  --write-tree` takes `--merge-base`, exit 129). Correct form:
  `git merge-tree --write-tree --merge-base $(git merge-base upstream/main fix/toast-safe-area) upstream/main fix/toast-safe-area`
  -> tree `54ac9e9352377e29c810af023d82c3ff4a624efd`, exit 0, **no conflicts**.
  `git diff fix/toast-safe-area upstream/main -- web/src/shell/AppShell.tsx`
  shows no change to the Toaster block since the branch base.
- Upstream does not handle this yet. `git grep -n safe-area-inset
  upstream/main -- web/src` hits only `index.css` and the composer
  `pb-[max(20px,env(safe-area-inset-bottom))]` classes; nothing on toasts.
  `git log upstream/main -- web/src/components/ui/sonner.tsx web/index.html
  web/src/lib/updateOverlayInset.ts`: latest are 74f94c3d5 (desktop onboarding
  progress), d3a946286 (archive toast restyle), b83d7546f (toast bottom
  offset for the update overlay) -- none touch the top offset.
- Related upstream commits since Sept (keyword search): 7ea138029 "Fix
  lightbox close button hidden behind status bar on mobile" uses the same
  `calc(50px + var(--omnigent-inset-top))` pattern (`chatBubbleParts.tsx:2056`)
  -- cite it in the PR as precedent; f16f422ea (Plan tracker below native
  header); d87b48d8b (iPad support: viewport > 600px so the desktop `offset`
  path covers it, iPad top inset 24px). No duplicate fix.
- sonner is still 2.0.8 on upstream/main, so the offset API is unchanged.
- `custom` copy: 87063d904 is code-identical (`git range-diff
  87063d904^..87063d904 f2e1daaf5^..f2e1daaf5` differs only by the "Carried on
  custom" line in the message). The requested `git diff 87063d904
  fix/toast-safe-area --stat` is noise (997 files: other custom patches plus
  upstream drift) and not a useful comparison. The copy is
  already deployed, so **every running instance carries the fix**; there is
  no deployed "before" to photograph (see below).

## Demo capture steps

Real-device "after" (recommended; the PR template wants an image for UI
changes):

1. On the iPhone open the Omnigent app on an instance that carries the fix,
   portrait, light or dark theme, any session list visible.
2. Trigger a toast with Undo (these are the easiest reliable ones):
   - Archive a throwaway session: open it, header kebab (three dots) ->
     Archive. Toast "Archived 1 session" with Undo, lasts 3 s
     (`archiveUndoToast.tsx:13`). Tap Undo afterwards.
   - Or unpin a pinned session from the sidebar row -> "Unpinned session" toast
     with Undo.
   Hold the screenshot gesture (side button + volume up) ready; it is instant.
   If 3 s is tight, take a screen recording and grab a frame.
3. What to look for: the toast's top edge is clearly below the Dynamic Island /
   status-bar text (16px gap under the 59px inset on 14 Pro-class phones; ~47px
   on notch phones), fully readable, horizontally centered with 16px side
   margins, and the Undo button tappable. Also rotate to landscape once: toast
   centered, 24px from the top, nothing under the island.
4. Optional "before" on the same phone without a redeploy: if the app's
   WKWebView is inspectable from the Mac (Safari > Develop > iPhone > Omnigent),
   select `ol[data-sonner-toaster]` in Elements while a toast is showing and
   set `--mobile-offset-top: 16px` inline; that is exactly sonner's pre-patch
   value. Screenshot the phone. Skip if the build is not inspectable.

Emulated "before/after" in Chromium (acceptable as a clearly labelled stand-in,
and the better option for the "before" since nothing deployed has it):

- Prefer the repo's own mechanism over a CSS override: Playwright + CDP
  `Emulation.setSafeAreaInsetsOverride` with
  `{"top": 59, "left": 0, "bottom": 34, "right": 0}` at a 393x659 (iPhone 15
  Pro) viewport drives the real `env(safe-area-inset-top)` path, the same way
  `tests/e2e_ui/mobile/test_native_shell_plan_header_overlap.py:182-183` does
  (with the `_IOS_SHELL_INIT_SCRIPT` stub so `data-ios-native` is set). Run
  the web app from `upstream/main` for "before" and from the branch for
  "after", fire the archive toast, screenshot both. Label them "emulated
  insets" in the Demo section.
- A plain devtools CSS override (`:root { --omnigent-inset-top: 59px }` or
  `--omnigent-android-safe-area-top: 59px`) also reproduces the geometry and is
  fine for an illustrative before/after, but it bypasses `env()`; if used, say
  so in the PR. Do not present either emulation as a device capture.
- Keep captures outside the tracked tree and attach them to the PR as GitHub
  uploads (repo CLAUDE.md: no committed demo media).
