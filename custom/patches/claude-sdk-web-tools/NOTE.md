# claude-sdk-web-tools

Needs: none
Covers: afc8cfea9604c457

claude-sdk agents can use Claude Code's own WebSearch and WebFetch.

- **Turn on:** `native_tools: [WebSearch, WebFetch]` under the agent's
  `executor` (`executor.config.native_tools` in a directory bundle).
- **Docs:** [Agent YAML spec](../AGENT_YAML_SPEC.md) (Claude SDK built-in web
  tools).
- **Upstream:** not proposed yet: there is no upstream issue or pull request.
  It is prepared on `feat/claude-sdk-native-tools`.

## Must hold

- A `claude-sdk` agent with `native_tools: [WebSearch, WebFetch]` (`executor.config.native_tools` in a directory bundle) gets those Claude Code built-in tools; without the setting only `Skill` and `ToolSearch` are enabled, as upstream.
- Only `WebSearch` and `WebFetch` are accepted: another name, a value that is not a list of names, or `native_tools` on a harness other than `claude-sdk` fails spec validation.
- Every call to an opted-in tool still reaches the `TOOL_CALL` policy gate (the tools stay off `allowed_tools`); in `auto` permission mode it is then approved without a prompt, and in other modes it still prompts.
- `WebSearch` is withheld when `ANTHROPIC_BASE_URL` points at a non-Anthropic host, unless a Bedrock, Vertex or Foundry flag is set (those gate it themselves); `WebFetch` stays available.
- The setting survives bundle transport and reaches the harness process as `HARNESS_CLAUDE_SDK_NATIVE_TOOLS` (a JSON list); unsupported names found there are dropped with a warning.

## Key code

- `omnigent/inner/datamodel.py`: `CLAUDE_SDK_NATIVE_TOOLS`, `claude_sdk_native_tools_error`
- `omnigent/inner/claude_sdk_executor.py`: `_native_tools_for_endpoint`, `_CLAUDE_CLOUD_PROVIDER_FLAG_ENVS`
- `omnigent/inner/claude_sdk_harness.py`: `_resolve_native_tools`, `_ENV_NATIVE_TOOLS`
- `omnigent/runtime/workflow.py`: `_build_claude_sdk_spawn_env`
- `omnigent/spec/_omnigent_compat.py`: `validate_omnigent_executor`

## Tests

- `tests/spec/test_claude_sdk_native_tools.py::test_native_tools_rejects_invalid_values`
- `tests/spec/test_claude_sdk_native_tools.py::test_native_tools_survives_bundle_transport`
- `tests/inner/test_claude_sdk_executor.py::test_native_tool_skips_prompt_in_auto_mode_but_not_policy`
- `tests/inner/test_claude_sdk_executor.py::test_native_tools_for_endpoint_withholds_websearch_on_gateways`
- `tests/runtime/test_claude_sdk_spawn_env.py::test_native_tools_threads_to_env`
