# [Bug] codex-native: a web `!command` is sent to the model as a prompt instead of running as a shell command

### Description

In a codex-native session, typing `!ls -la` (or any `!command`) in the web composer does not run the command. The runner forwards the text to Codex as an ordinary user message (`turn/start` / `turn/steer`), so the model gets a prompt that reads `!ls -la` and answers it in prose, often by running `ls -la` itself through its own tool call. Claude-native sessions run the same input as a shell command and mirror it as `terminal_command` input/output items, so the queued web bubble settles.

Cause: `omnigent/inner/codex_native_executor.py` only knows two delivery methods, `turn/start` and `turn/steer`. It never calls the app-server's `thread/shellCommand` RPC, and `omnigent/harnesses/codex_native/forwarder.py` treats Codex's `commandExecution` items with `source: "userShell"` like model tool calls, so there is no `terminal_command` mirror to settle the pending web input. `git grep shellCommand upstream/main -- omnigent/harnesses/codex_native omnigent/inner` is empty.

Proposed fix: route a lone `!command` web input to `thread/shellCommand` on the session's thread (inside any active turn), and have the forwarder mirror `userShell` items as `terminal_command` input (at `item/started`) and output (at `item/completed`), unwrapping Codex's `<shell> -lc '<command>'` wrapper so the mirror matches the typed command. Text that merely starts with `!` but is not a lone command (for example `!important: keep going`) still goes to the model. Patch ready on `fix/codex-native-shell-input`.

Prior art checked: #9218 (stop flagging shell-mode web messages as undelivered) is about the server's pending-input accounting for shell-mode messages, not about Codex running them; #10856 (deliver code-block runs to the agent's next turn) is about the code-block Run feature, not composer `!` input. No open issue or PR routes `!command` to `thread/shellCommand`.

### Steps to reproduce

1. Start a codex-native session from the web UI (real `codex` and `tmux` on the host), open the terminal view until it shows connected, then switch to the chat view.
2. Send `!echo hello-from-shell` from the composer.
3. Watch the Codex pane and the chat.

Expected: `echo hello-from-shell` runs in Codex's shell (as it does when typed with `!` in the Codex TUI), the chat shows the `!echo hello-from-shell` user bubble followed by a terminal command item with its output, and no model turn runs.

Actual: a model turn starts; the assistant replies to the text `!echo hello-from-shell` (or runs it through a tool call). `GET /v1/sessions/{id}/items` holds no `terminal_command` item for it. The web bubble stays pending until the next model message settles it.

Automated: `tests/e2e_ui/messages/test_native_codex_shell_input.py::test_web_shell_input_runs_in_codex_shell_not_as_prompt` fails on `main` (no `terminal_command` input is mirrored and the mock model's fallback reply appears a second time) and passes with the fix.

### Version

main @ 39611f812

### Harness

Codex

### Harness mode

Native

### Platform or device

Linux

### Observed impact

Some users or sessions

### Authentication type

Not authentication-related
