# gateway-request-tags

Needs: none
Covers: 93d893c76cd23900

Requests to a Databricks Unity Gateway carry the session id and the session's
labels in the `Databricks-Ai-Gateway-Request-Tags` header, next to upstream's
CI tags and within its 4 KiB budget.

- **Turn on:** on by default for gateway providers;
  `OMNIGENT_GATEWAY_REQUEST_TAGS=0` in the host's (or CLI's) environment turns
  it off.
- **Docs:** [Databricks](../databricks.md) (Session request tags).
- **Upstream:** proposed from `feat/gateway-request-tags`.

## Must hold

- Requests that claude-native, claude-sdk, codex, codex-native and pi send to a Databricks Unity Gateway URL carry `Databricks-Ai-Gateway-Request-Tags`: a compact ASCII JSON object with `omnigent_session_id` and the session's user labels. Other gateways and providers never get the header.
- Omnigent-owned labels (`omnigent.*`, `cost_control.*`, `omni_project`) are not sent.
- Upstream's CI tags go in the same object and win over a label of the same name; past the 4 KiB budget labels are dropped in key order while the session id and the CI tags are kept.
- `OMNIGENT_GATEWAY_REQUEST_TAGS=0` in the environment of the host daemon or the CLI turns the header off; the host forwards the variable to its runners.
- Tags are read when the harness process or native CLI starts, so a label edit reaches the header after the next launch or respawn.
- A codex-native app-server carries only its own session's tags, never tags inherited from the environment that launched it.

## Key code

- `omnigent/databricks_ai_gateway.py`: `gateway_request_tags`, `gateway_request_tags_value`, `gateway_request_tags_headers`, `with_gateway_request_tags_line`, `REQUEST_TAGS_SWITCH_ENV`
- `omnigent/runner/app.py`: `_with_gateway_request_tags`, `_spawn_env_may_reach_unity_gateway`
- `omnigent/harnesses/claude_native/main.py`: `claude_config_with_gateway_request_tags`
- `omnigent/inner/codex_executor.py`: `materialize_codex_provider_config`, `REQUEST_TAGS_VALUE_ENV`
- `omnigent/harnesses/codex_native/app_server.py`: `build_codex_native_server`, `gateway_request_tags_env`

## Tests

- `tests/test_databricks_ai_gateway.py::test_gateway_request_tags_send_the_session_id_and_user_labels_only`
- `tests/test_databricks_ai_gateway.py::test_gateway_request_tags_drop_labels_past_the_cap_but_keep_the_session_id`
- `tests/test_databricks_ai_gateway.py::test_gateway_request_tags_switch`
- `tests/runner/test_app_claude_native_launch_args.py::test_auto_create_claude_terminal_tags_unity_gateway_requests_with_session_labels`
- `tests/runner/test_runner_dispatch.py::test_sdk_spawn_env_carries_the_session_request_tags`
