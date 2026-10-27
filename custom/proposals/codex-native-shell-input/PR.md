# fix(codex-native): run web !command inputs as shell commands

## Related issue

Closes #<to be filed>

## Summary

ELI5: typing `!ls` in the web chat of a Codex session asked the model about `!ls` instead of running `ls`. Now the command runs in Codex's shell, like it does in the Codex TUI and in Claude-native sessions.

- **Cause.** The codex-native executor only delivered web input with `turn/start` and `turn/steer`, so a `!command` reached Codex as a prompt. The forwarder also treated Codex's `userShell` `commandExecution` items like model tool calls, so nothing mirrored the command as `terminal_command` items and the queued web bubble never settled.
- **Fix.** A lone `!command` is sent to the app-server's `thread/shellCommand` RPC on the session thread (its ack carries no turn id; the turn arrives via `turn/started`). The forwarder mirrors `userShell` items as `terminal_command` input at `item/started` and output at `item/completed` (input posted at completion only when start was missed, e.g. resume backfill), unwrapping the `<shell> -lc '<command>'` wrapper so the mirror matches the typed command. Text that only starts with `!` but is not a lone command is still sent to the model.

## Test Plan

- New unit tests: `tests/harnesses/codex_native/test_codex_native.py::test_user_shell_command_recovers_the_typed_command`, `::test_forwarder_mirrors_user_shell_command_as_terminal_command`; `tests/inner/test_codex_native_executor.py::test_shell_input_runs_through_thread_shell_command`, `::test_non_shell_bang_text_is_sent_as_a_prompt`.
- New nightly e2e: `tests/e2e_ui/messages/test_native_codex_shell_input.py::test_web_shell_input_runs_in_codex_shell_not_as_prompt` (real `codex` + `tmux`, mock LLM): sends `!echo <marker>` from the composer, waits for the `terminal_command` input mirror, asserts `pending_inputs` is empty and that the model's fallback reply did not appear a second time (the command never reached it as a prompt). Fails on `main`, passes here (1 passed in 30 s).
- `uv run --no-sync python -m pytest tests/harnesses/codex_native tests/inner/test_codex_native_executor.py -q`: 1869 passed.
- `pre-commit run --files <changed files>`: all hooks pass.

```sh
uv run pytest tests/harnesses/codex_native tests/inner/test_codex_native_executor.py -q
uv run pytest tests/e2e_ui/messages/test_native_codex_shell_input.py -q
```

Manual: open a codex-native session in the web UI, switch to the chat view, send `!echo hi`. The command runs in the Codex pane, the chat shows the `!echo hi` bubble settled with a terminal command item carrying `hi`, and no model turn runs.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Backend change; the e2e test above is the evidence (fails on `main`, passes here).

## Type of change

- [x] Bug fix
- [ ] Feature
- [ ] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [x] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The unit tests cover the delivery routing and the forwarder mirror; the e2e test covers the real Codex app-server round trip.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

`!command` inputs sent from the web chat of a Codex session now run as shell commands instead of being sent to the model as a prompt.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
