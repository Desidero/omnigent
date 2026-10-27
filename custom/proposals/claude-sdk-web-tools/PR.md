<!-- Draft PR body for the claude-sdk-web-tools series; title: feat(claude-sdk): opt into Claude Code's WebSearch and WebFetch -->

## Related issue

Closes #TODO (issue to be opened)

## Summary

A `claude-sdk` agent can now turn on Claude Code's own web search and web fetch tools with one line of agent YAML.

The claude-sdk harness pins Claude Code's built-in tools to `Skill` and `ToolSearch`, so a claude-sdk agent can't use Claude's own web search, even on a first-party subscription. Omnigent's `web_search` builtin needs a separate search backend and key, and it is a different tool.

```yaml
executor:
  harness: claude-sdk
  native_tools: [WebSearch, WebFetch]
```

- New `executor.native_tools` (or `executor.config.native_tools` in a directory bundle). Only `WebSearch` and `WebFetch` are accepted. Other names, non-list values and non-claude-sdk harnesses fail spec validation.
- The named tools join the CLI's base tool set. They stay off `allowed_tools`, so every call still passes the `TOOL_CALL` policy gate. In `auto` permission mode the gate then approves them without a prompt, as it does for Omnigent's own tools.
- `WebSearch` is withheld when `ANTHROPIC_BASE_URL` points at a non-Anthropic gateway, because Claude Code runs it as a nested `web_search` request the gateway can't serve. Bedrock, Vertex and Foundry modes gate it themselves. `WebFetch` stays available.
- The value travels through YAML loading, bundle transport and the `AgentDef` round trip, and reaches the harness as `HARNESS_CLAUDE_SDK_NATIVE_TOOLS`.
- Documented in `docs/AGENT_YAML_SPEC.md`.

## Test Plan

```sh
uv run pytest tests/spec/test_claude_sdk_native_tools.py tests/inner/test_claude_sdk_executor.py \
  tests/inner/test_claude_sdk_harness.py tests/runtime/test_claude_sdk_spawn_env.py
```

The tests cover the value surviving YAML and bundle loading, rejection of invalid values and other harnesses, the spawn env, the harness decoding the env var (dropping unsupported names), the base tool set and auto-mode approval, and `WebSearch` being withheld on non-Anthropic gateways while cloud-provider modes keep it.

Manual, on a throwaway server with a Claude subscription or Anthropic API key:

1. Create a claude-sdk agent with `native_tools: [WebSearch, WebFetch]` and start a chat with it.
2. Ask "What is the latest release of Python? Search the web." The chat shows a `WebSearch` tool call with results, without an approval prompt in auto mode.
3. Ask it to fetch `https://example.com` and summarize it. A `WebFetch` call runs.
4. Add a `TOOL_CALL` policy that denies `WebSearch` and repeat step 2. The call is blocked by the policy.
5. Start the same agent with `ANTHROPIC_BASE_URL` set to a non-Anthropic gateway. `WebSearch` is no longer offered and `WebFetch` still works.
6. Set `native_tools: [Bash]` and load the agent. It fails validation with "unsupported tool(s) Bash; supported: WebFetch, WebSearch".

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: attach the chat transcript (or screenshot) of steps 2 and 3 showing the `WebSearch` and `WebFetch` tool calls, and the validation error from step 6

## Type of change

- [ ] Bug fix
- [x] Feature
- [ ] UI / frontend change
- [ ] Refactor / chore
- [x] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [ ] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Real web search needs a live Anthropic endpoint, so the tests check the tool set and permission decisions passed to the SDK. The manual steps cover the live calls.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

claude-sdk agents can turn on Claude Code's built-in WebSearch and WebFetch with `executor.native_tools`
