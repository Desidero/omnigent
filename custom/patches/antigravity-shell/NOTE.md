# antigravity-shell

Needs: none
Covers: 7276d47365a490c2

The Gemini (`harness: antigravity`) agent can run shell commands. The SDK's
default policy denied its `run_command` tool outright and the harness turned
that into a failed turn. Now each shell call passes Omnigent's own gate: the
agent's `tool_call` policies first (DENY refuses, ASK asks), then
`executor.config.permission_mode` (`auto`, the default, and
`bypassPermissions` run it; any other value, e.g. `default`, asks on an
approval card). A refused call fails as a tool call with its reason and the
model carries on; rejecting the card ends the turn, as on the other SDK
harnesses. Approval cards say "Antigravity wants to use run_command".

- **Turn on:** on by default; set `executor.config.permission_mode: default`
  to be asked before every command.
- **Docs:** [Agent YAML](../AGENT_YAML_SPEC.md) (Antigravity (Gemini)).
- **Upstream:** not proposed yet. Bug report
  [#8484](https://github.com/omnigent-ai/omnigent/issues/8484); the open
  [#8497](https://github.com/omnigent-ai/omnigent/pull/8497) routes the SDK's
  ask-user handler to the card instead and does not apply Omnigent policies.

## Must hold

- A Gemini shell call follows the session's permission mode and Omnigent policies: under `auto` or `bypassPermissions` it runs unless a policy objects; under any other mode it runs only after the user approves the card.
- An Omnigent `tool_call` policy that denies `run_command` refuses the call in every mode, without asking, and the model sees the policy's reason.
- A policy ASK asks the user even under `bypassPermissions`.
- A refused shell call (policy, user, or no way to decide) fails that tool call only: the SDK's report of the refusal is neither assistant text nor a turn error.
- When the gate cannot decide (evaluator error, unknown verdict, approval needed with no approval bridge) the command does not run.
- Other SDK tools are not gated by this series.
- Works with SDK 0.1.2 (the refusal closes the already-streamed call once) and 0.1.23.

## Key code

- `omnigent/inner/antigravity_executor.py`: `_build_shell_gate_hook`, `_shell_command_denial`, `_ask_to_run_shell_command`, `_is_shell_denial_report`, `_open_agent`
- `omnigent/inner/antigravity_harness.py`: `_ENV_PERMISSION_MODE`, `create_app`
- `omnigent/runtime/workflow.py`: `_build_antigravity_spawn_env`

## Tests

- `tests/inner/test_antigravity_executor.py::test_shell_command_runs_without_asking_when_policy_allows`
- `tests/inner/test_antigravity_executor.py::test_shell_command_asks_and_runs_when_approved`
- `tests/inner/test_antigravity_executor.py::test_refused_shell_command_fails_the_call_and_the_turn_continues`
- `tests/inner/test_antigravity_executor.py::test_shell_command_denied_by_omnigent_policy`
- `tests/inner/test_antigravity_executor.py::test_policy_ask_prompts_even_in_a_mode_that_does_not_ask`
- `tests/inner/test_antigravity_executor.py::test_shell_gate_fails_closed`
- `tests/inner/test_antigravity_executor.py::test_refusal_on_an_sdk_that_streams_the_call_first`
- `tests/inner/test_antigravity_harness.py::test_approval_cards_name_antigravity`
- `tests/runtime/test_antigravity_spawn_env.py::test_permission_mode_threads_into_env_var`
