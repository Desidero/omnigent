# claude-native-delegate-idle

Needs: none
Covers: 1aa49b5907039389

A Claude lead session stops showing Working, and takes follow-ups without
Steer, once its turn ends while agent-team teammates keep running. Upstream's
background-agent hold ([#12561](https://github.com/omnigent-ai/omnigent/pull/12561)) does this for sub-agents; this series counts
teammates as background agents too.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed as an extension of upstream's [#12561](https://github.com/omnigent-ai/omnigent/pull/12561).

## Must hold

- A Stop hook background task of type `teammate` counts as a background agent: a lead whose teammates are still running gets upstream's background-agent hold instead of staying Working after its turn.
- A running teammate stays out of the background-shell tally (`background_task_count` is 0), so the shell indicator does not over-count.

## Key code

- `omnigent/harnesses/claude_native/bridge.py`: `_BACKGROUND_AGENT_TASK_TYPES`

## Tests

- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_hook_record_stop_keeps_running_teammates_out_of_the_shell_tally`
