# mcp-registry-tool-patterns

Needs: none
Covers: 3186018fbd03e596

An entry in an MCP registry service's `tools` allowlist can be a pattern in
which `*` stands for any run of characters (`search_*`, `*_read`,
`get_*_by_id`), or `"*"` alone for every tool, so the registry file no longer
has to be regenerated each time a service adds a tool. The match is literal,
case-sensitive and anchored; exact names work as before. A pattern is checked
on every listing and call, not expanded once, so a tool the service adds later
is callable as soon as its name matches.

- **Turn on:** write a pattern in `tools` in the `OMNIGENT_MCP_REGISTRY` file
  and restart the server. Replace patterns with names before rolling back: a
  build without this series reads a pattern as an exact name that matches
  nothing, without an error.
- **Docs:** "Tool allowlist patterns" in the
  [registry README](../../examples/mcp-registry/README.md#tool-allowlist-patterns);
  one line in the [gateway design](../../designs/MCP_REGISTRY_GATEWAY.md).
- **Upstream:** not proposed, no contribution branch. No open upstream issue or
  pull request asks for patterns (searched 2026-11-26); upstream's design
  treats the exact allowlist as the administrator's review step. Neighbours on
  the same model: [#13295](https://github.com/omnigent-ai/omnigent/pull/13295)
  (icons, draft) and [#14064](https://github.com/omnigent-ai/omnigent/issues/14064)
  (Basic auth).

## Must hold

- The allowlist is enforced on the server for every call: a tool no entry admits is refused before the credential is resolved or the upstream is contacted, on the gateway route and the session route, whether or not it was ever listed.
- Listings (connection test, gateway `tools/list`, session tool discovery) hold only tools an entry admits.
- An entry without `*` admits exactly that name, as before the series.
- A pattern is compared as literal text against the whole name; regular-expression syntax in an entry has no meaning and nothing from the file is compiled.
- `"*"` allows every tool only when it is the sole entry, and the server logs a warning naming the service at startup; `tools` stays required and nonempty.
- `**`, or `?`, `[`, `]` in an entry with `*`, and `"*"` beside other entries fail registry validation at load.
- Nothing that narrows access is loosened: `allowed_users`, an agent's own exact `tools` list and tool-call policies still apply, and a policy deny wins over a pattern.

## Key code

- `omnigent/server/mcp_registry.py`: `_tool_pattern_matches`, `allows_tool`, `allows_every_tool`, `validate_service`
- `omnigent/server/registry_gateway.py`: `registry_tools`, `execute_registry_tool`
- `omnigent/server/mcp_policy_adapter.py`: `list_tools`
- `web/src/components/McpRegistry.tsx`: `ServiceConnection`

## Tests

- `tests/server/test_mcp_registry.py::test_allowlist_patterns_are_literal_and_anchored`
- `tests/server/test_mcp_registry.py::test_any_allowlist_entry_may_admit_a_tool`
- `tests/server/test_mcp_registry.py::test_ambiguous_allowlist_patterns_fail_validation`
- `tests/server/test_mcp_registry.py::test_patterns_are_checked_on_every_call_and_filter_discovery`
- `tests/server/test_mcp_registry.py::test_a_registry_file_with_patterns_loads_and_allowing_everything_is_logged`
- `tests/server/integration/test_mcp_registry.py::test_allowlist_patterns_filter_discovery_and_gate_each_call`
- `web/src/components/McpRegistry.test.tsx`
