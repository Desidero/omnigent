<!-- Draft PR body for the run-suggested-commands series; title: feat(web): Run button for agent-suggested shell commands -->
## Related issue

Closes #TODO (issue to be opened)

## Summary

When an agent asks you to run a command ("please run `! gcloud auth login`"), the chat now shows a Run button next to it. One tap confirms the exact commands and sends each one to the session's shell, as if you had typed `!command` yourself.

Today you have to copy each command and paste it into the composer with a `!` prefix, one at a time, which is slow on desktop and awkward on a phone.

- **Where Run appears.** On agent prose only (never user text or a reply that is still streaming): fenced code blocks whose lines start with `!`, shell-language blocks (`bash`, `sh`, `shell`, `zsh`, `console`, `shell-session`), and inline `` `! cmd` `` spans. In a block with `!` lines, those lines are the commands and the rest is commentary; a shell block yields one command per line, keeping only `$ `-prompted lines when it looks like a transcript. Backslash continuations are joined. Heredocs, `!!`, and blocks with more than 10 commands get no Run button, because splitting them would change what runs.
- **Confirm, then queue.** Run opens a dialog listing the exact `!commands` in order. Confirming queues each as its own `!command` input through the normal message queue, so commands never merge into one turn and each runs on its own idle edge.
- **Harness support.** The button shows only for harnesses whose composer treats `!command` as a shell input: claude-native (unchanged, it already has a shell mode) and codex-native. For codex-native, a lone `!command` input is now sent to the app-server `thread/shellCommand` RPC instead of `turn/start`/`turn/steer` (also when typed by hand, also mid-turn), and the forwarder mirrors Codex's `userShell` `commandExecution` items as `terminal_command` input/output items, which settles the queued bubble. `!!text` and `!` inputs with attachments still go to the model as prompts.

This change is carried in the patch series on Desidero/omnigent's `patches` branch until it lands upstream.

Docs: new `docs/run-suggested-commands.md` (where Run appears, what it does, and how to turn it off per session or by default) and a `run-suggested-commands` entry in `feature-map/native-harnesses.md` naming the two journeys.

## Test Plan

Tests added or changed:

- `web/src/lib/runnableCommands.test.ts`: command extraction (`!` lines, shell blocks, prompts, continuations, heredocs, the 10-command cap, inline spans, harness gate).
- `web/src/components/chat/RunCommandsProvider.test.tsx`: confirm runs commands in order, cancel runs nothing, Run hidden when the text does not opt in or the harness has no shell input.
- `tests/harnesses/codex_native/test_codex_native.py`: unwrapping Codex's `<shell> -lc '<cmd>'`, mirroring user shell commands live and on resume backfill.
- `tests/inner/test_codex_native_executor.py`: a `!command` goes through `thread/shellCommand`; `!!text`, `!` and `say !hi` stay prompts.
- `tests/e2e_ui/messages/test_native_claude_shell_input.py::test_run_button_queues_each_suggested_command` and the new `tests/e2e_ui/messages/test_native_codex_shell_input.py` (both `nightly`; need `claude`/`codex` on PATH).

```sh
cd web && pnpm exec vitest run src/lib/runnableCommands.test.ts src/components/chat/RunCommandsProvider.test.tsx
cd web && pnpm exec tsc -b
uv run pytest tests/harnesses/codex_native/test_codex_native.py tests/inner/test_codex_native_executor.py
uv run pytest -m nightly tests/e2e_ui/messages/test_native_claude_shell_input.py tests/e2e_ui/messages/test_native_codex_shell_input.py
```

Manual:

1. Start a claude-native session and ask: "Reply with a code block containing `!echo one` and `!echo two` on separate lines, then an inline `` `! date` ``."
2. Hover the code block: a Run button sits next to Copy. Click it; the dialog reads "Run 2 commands?" and lists `!echo one`, `!echo two`. Confirm: two shell bubbles run in order and their output appears in the transcript.
3. Click the Run icon after the inline `! date` span; confirm; it runs.
4. Click Run and then Cancel: nothing is queued.
5. Repeat steps 1-2 in a codex-native session, including once while the agent is mid-turn. The commands run in Codex's shell (visible in the TUI) and appear as terminal command items in the web chat; none is sent to the model as a prompt.
6. Ask for a ```` ```bash ```` block with a heredoc, and a block with 11 commands: neither shows Run.
7. In an SDK-harness session, Run never appears.

## Demo

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: recording of clicking Run on a two-command block in a claude-native session, the confirm dialog, and both commands running (throwaway server, dummy session)
- [ ] TODO: screenshot of the Run icon on an inline `! cmd` span
- [ ] TODO: recording of the same flow in a codex-native session, showing terminal command items in the web chat
- [ ] TODO: mobile-width screenshot of the confirm dialog

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
- [x] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Extraction rules and the confirm dialog are covered by Vitest; the codex-native shell routing and mirroring by unit tests at the executor and forwarder layers. The two browser journeys are marked `nightly` because they launch the real Claude and Codex CLIs against the mock LLM.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Shell commands an agent suggests in chat get a Run button that confirms and runs them as `!command` shell inputs in claude-native and codex-native sessions
