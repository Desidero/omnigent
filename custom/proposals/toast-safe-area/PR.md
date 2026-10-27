# fix(web): keep top toasts below the native status bar / Dynamic Island

## Related issue

Closes #

<!-- No upstream issue exists for this; it is a 3-line bug fix. If a maintainer wants one, I will file it. -->

## Summary

In the iOS app, toasts render top-center with sonner's fixed 16px (phone) / 24px (desktop) top gap, so they sat under the status bar and Dynamic Island and could not be read. The toaster already lifts its bottom edge above the home indicator with `--omnigent-inset-bottom`; this gives the top edge the matching `--omnigent-inset-top`, the same safe-area helper the lightbox close button uses (7ea138029).

- `offset.top` and `mobileOffset.top` on the `Toaster` become `calc(<sonner default> + var(--omnigent-inset-top))`; the other sides are unchanged. The offsets live in a small `toasterOffsets()` helper next to the existing bottom-offset helper so the strings are unit-tested and `AppShell` no longer repeats them.
- Where the inset is 0 (desktop browsers, Electron) nothing moves. The Android shell injects its status-bar height into the same variable, so Android toasts clear the status bar too.
- `calc()` rather than `max()` on purpose: `max()` would butt the toast against the Dynamic Island with no gap.

## Test Plan

- Before/after captured in Chromium with the same CDP safe-area override the mobile e2e suite uses (`Emulation.setSafeAreaInsetsOverride`, top 59px for an iPhone 14 Pro), which drives the real `env()` path: see Demo.
- Measured in that emulation: before, toaster `--mobile-offset-top: 16px`; after, `calc(16px + max(59px, 0px))`, toaster top 75px. Identical in light and dark.
- Checked on an iPhone in the iOS shell (production runs this fix): unpin a session from the header menu, the toast sits fully below the Dynamic Island with a 16px gap, centered; rotated to landscape, unchanged (sonner's desktop rules apply above 600px and iOS reports no top inset there).
- `web/src/lib/updateOverlayInset.test.ts`: new case asserts the desktop (`24px`) and mobile (`16px`) top offsets include `var(--omnigent-inset-top)` and that both bottom offsets still come from `updateOverlayToastOffset`.
- `npx vitest run src/shell/AppShell.test.tsx src/lib/updateOverlayInset.test.ts` (193 tests) and `node_modules/.bin/tsc -b` pass; pre-commit (prettier, oxlint, custom lint) clean.

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Before and after at an iPhone 14 Pro viewport (390×844 @2x) with a 59px top inset applied through Chromium's `Emulation.setSafeAreaInsetsOverride`, so `env(safe-area-inset-top)` really resolves to 59px (a probe element measured it). The red band and pill mark the inset region; they are drawn on afterwards for clarity. Toast trigger: pin then unpin the session from the header menu.

Before: the toaster's top is 16px, so the toast (y 16–74) sits under the status bar and Dynamic Island.

![Before: toast overlaps the top inset band](img/toast-before-portrait.png)

After: the toaster's top is `calc(16px + 59px)`, so the toast (y 75–133) starts 16px below the band.

![After: toast sits below the inset band](img/toast-after-portrait.png)

Dark theme, after:

![After, dark theme](img/toast-after-dark.png)

Desktop (1280×800, no inset): unchanged, the toast keeps sonner's 24px default gap:

![Desktop toast placement, unchanged](img/toast-desktop-after.png)

## Type of change

- [x] Bug fix
- [ ] Feature
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

The offset strings are unit-tested; the safe-area value itself comes from `env(safe-area-inset-top)`, which jsdom cannot resolve, so placement was verified on a phone and with Chromium's safe-area emulation (the mechanism the mobile e2e suite uses). The existing `AppShell` tests cover that the toaster still mounts.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
