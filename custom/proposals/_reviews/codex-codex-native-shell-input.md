# Codex review: codex-native-shell-input

Reviewed 2026-10-23 after rebasing onto `upstream/main` = 3f2ccf56e. Same fallback command as in `codex-claude-native-teammates.md` (stdin diff, no commands); model gpt-6.1-sol (OpenAI Codex v0.159.2).

## Raw review

```
codex
I’ll review only the supplied diff and guidance, focusing on concrete bugs and coverage gaps. I won’t run commands.
codex
I would request changes for two correctness issues. This review uses only the supplied material; I did not run commands or tests.

To verify, submit a slow shell command followed immediately by a normal message, then check that both execute once and in order. Also submit `!printf '<%s>\n' foo\ ` with a literal space after the final backslash; the output should preserve that space as `<foo >`.

Findings:

- **P1 — `omnigent/inner/codex_native_executor.py:458` — Shell delivery leaves an idle bridge looking idle.** `_run_codex_shell_command` returns after the empty RPC acknowledgement without recording or waiting for the shell’s turn. The injection lock can then be released before the forwarder processes `turn/started`. A following message reads `active_turn_id=None` and attempts `turn/start` while the shell turn is already running. This reintroduces the read-decide-RPC race that the executor’s serialization comment explicitly guards against, risking rejection or incorrect routing of the following input. Coordinate shell acceptance with bridge turn state before releasing serialization, and cover a delayed `turn/started` followed by another injection.

- **P2 — `omnigent/inner/codex_native_executor.py:1151` — Trimming changes valid shell commands.** Both `text.strip()` and `text[1:].strip()` remove command characters that can be significant to the shell. For example, a trailing escaped space in `!printf '<%s>\n' foo\ ` is removed, changing the argument passed to `printf`. Preserve the command body after identifying the `!` prefix; use a separate whitespace check to reject empty commands. Add coverage for trailing escaped whitespace and multiline input.
```

## Disposition

- P1 (shell ack leaves an idle bridge looking idle; a follow-up message could `turn/start` while the shell turn runs): **fixed**. When `active_turn_id` was `None`, `_run_codex_shell_command` now holds the injection lock until the forwarder records the shell's `turn/started` in bridge state (`_wait_for_shell_turn`, 50 ms polls, 2 s bound; a command that finishes before its turn is observed just runs the bound out). Tests: `test_shell_input_waits_for_the_forwarder_to_record_its_turn` (a message enqueued right after the shell command steers `turn_shell`), `test_shell_input_wait_for_its_turn_is_bounded`; `test_shell_input_runs_through_thread_shell_command` now has the fake record the turn the way the forwarder does. When a turn was already active the shell runs inside it and nothing changes.
- P2 (`strip()` removes shell-significant trailing characters such as an escaped space): **fixed**. Only the whitespace around the `!` prefix and trailing newlines are dropped; `test_shell_command_keeps_its_body` covers an escaped trailing space, a heredoc body and padding. The server's pending-input match collapses whitespace on both sides, so the mirror still settles the web bubble.
