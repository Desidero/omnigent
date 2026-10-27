# Codex review: new-chat-project-prompt

Command: `codex exec -C <worktree> --sandbox read-only -` with the maintainer-review prompt, the repo's CLAUDE.md and `git diff -U40 <base>...HEAD` piped on stdin (`codex review --base` rejects a custom prompt, and the bundled bubblewrap sandbox cannot run commands in this environment, so the diff was supplied inline). Model: gpt-6.1-sol (codex-cli 0.159.2). Reviewed at the rebase onto upstream/main 3f2ccf56e.

## Disposition

1. [P2] An unresolved project list was treated as "no projects", so a new session started before the list loaded skipped the prompt — **fixed**: `useShouldPromptForProject` now prompts while the list is unresolved; `CommandPalette`'s project step steps aside to the plain composer (`onOpenChange(false)` + `navigate("/")`) when the list resolves empty or fails, so users without projects never keep a dialog they would not otherwise see. Two `AppShell.test.tsx` cases drive the hotkey with the list unresolved, then resolve it empty (composer opens) or with a project (picker lists it). Amended into the commit; 522 tests pass, `tsc -b` clean.

## Raw output

```
I’m Codex, based on GPT-6. I reviewed only the supplied top-commit diff against the supplied CLAUDE.md. I would request one change:

- **[P2] Project loading silently bypasses the enabled prompt** — `web/src/hooks/useNewChatProjectPrompt.ts:12–14`. Defaulting unresolved query data to `[]` treats “projects haven’t loaded” as “no projects exist.” On a fresh load or server switch, invoking New session before the projects request completes immediately navigates to `/`, even for users with projects and the setting enabled. `handleNewSession` never revisits that decision when the request finishes. Distinguish loading from a confirmed empty result and preserve the requested action until project availability is known.

  Add coverage for invoking New session while projects are unresolved, then resolving with a project versus an empty list. The new AppShell tests supply already-loaded projects, so they cannot catch this case.

To verify manually, throttle the network, reload an existing session with projects present, and invoke New session before the projects response completes. With the setting enabled, it should still offer project selection.

Tests were not run; this review is limited to the supplied diff and context.
```
