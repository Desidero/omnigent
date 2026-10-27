# Codex review: toast-safe-area

Command: `codex exec -C <worktree> --sandbox read-only -` with the maintainer-review prompt, the repo's CLAUDE.md and `git diff -U40 <base>...HEAD` piped on stdin (`codex review --base` rejects a custom prompt, and the bundled bubblewrap sandbox cannot run commands in this environment, so the diff was supplied inline). Model: gpt-6.1-sol (codex-cli 0.159.2). Reviewed at the rebase onto upstream/main 3f2ccf56e.

## Disposition

No findings. Codex noted the unit test cannot prove `--omnigent-inset-top` resolves in a browser; that is already covered by the Chromium safe-area emulation captures and the on-device check in the PR's Test Plan and Demo.

## Raw output

```
I’m GPT-6, running as Codex.

No confirmed change-request findings in the supplied diff. The helper preserves the existing bottom and right offsets, adds the top inset to both desktop and mobile configurations, and is wired into `AppShell`. The new exported helper has unit coverage, consistent with `CLAUDE.md`.

The remaining gap is browser verification: `web/src/lib/updateOverlayInset.test.ts:23` checks the generated strings, but cannot establish that `--omnigent-inset-top` resolves correctly or that the rendered toast clears the native status bar. That is a validation limitation, not a demonstrated bug.

Before merging, verify on an iPhone with a notch or Dynamic Island:

- Trigger a top toast in portrait and landscape; confirm it clears the status bar.
- Show the update overlay and trigger a bottom toast; confirm the existing clearance remains.
- Check desktop rendering for excessive top spacing.

Include screenshots or video in the PR’s Demo section as required by `CLAUDE.md`. I reviewed only the supplied diff and instructions; I did not run tests or inspect surrounding code.
```
