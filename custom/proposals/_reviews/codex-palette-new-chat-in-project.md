# Codex review: palette-new-chat-in-project

Command: `codex exec -C <worktree> --sandbox read-only -` with the maintainer-review prompt, the repo's CLAUDE.md and `git diff -U40 <base>...HEAD` piped on stdin (`codex review --base` rejects a custom prompt, and the bundled bubblewrap sandbox cannot run commands in this environment, so the diff was supplied inline). Model: gpt-6.1-sol (codex-cli 0.159.2). Reviewed at the rebase onto upstream/main 3f2ccf56e.

## Disposition

1. [P2] "Project defaults are claimed but never tested" — **dismissed**: the row only navigates to `/?project=<name>`, the route the per-project pencil already uses; the name → id → stored host/workspace/agent prefill is existing behaviour covered by `web/src/shell/NewChatDialog.projectPrefill.test.tsx`. The PR's Coverage notes now name that file instead of re-testing the handoff.

## Raw output

```
I’ll review the supplied diff against the repository guidance, separating confirmed problems from behavior that needs coverage. I won’t run shell commands.
Model: GPT-6.

- **[P2] Project defaults are claimed but never tested.** [CommandPalette.test.tsx:394](web/src/shell/CommandPalette.test.tsx:394) — “opens the composer with the project's defaults” only checks a mocked navigation call. Neither project fixture contains defaults, and the composer never renders. This test would pass if the destination ignored `project` entirely. The feature map nevertheless claims host, workspace, and agent are prefilled. Add or identify existing coverage that exercises the real query-parameter handoff and asserts those selections, reusing an existing composer scenario as CLAUDE.md requires.

I found no confirmed correctness bugs in the supplied implementation. URL encoding, hiding rows for empty input, and excluding them from the sessions-only switcher are handled and tested. The supplied context does not establish whether the destination already has sufficient defaults coverage; if it does, reference that coverage instead of adding redundant tests.

To verify manually: configure distinct host, workspace, and agent defaults for two projects. From an existing session, open ⌘/Ctrl+K, search each project, and select its row using both Enter and a click. Confirm the composer shows the selected project's defaults. Repeat while already on the new-session page, including with an existing draft.

Review was limited to the supplied diff and CLAUDE.md; tests were not run.
```
