# subagent-only-routing

Needs: none
Covers: 031720589fcb2f62

A Claude Code or Codex session keeps the model you picked and lets Smart
Routing choose the model of each sub-agent it starts. Before, the CLI's own
sub-agents (Claude Code's `Agent`/`Task`, Codex's `spawn_agent`) were routed
only on a session launched on Smart Routing, which also routes the session's
own model.

- **Turn on:** needs Smart Routing on the server. In the new-session composer,
  pick a Claude Code or Codex model and check **Route sub-agents** in the model
  menu, or create the session with `subagent_routing_override: "on"`. The same
  row in the session's model menu turns it off and on. The gate is installed
  by the host when the session launches, so hosts need this build; a session
  created without the option routes child sessions only if its switch is
  turned on later. Refused on a session with a bound inference profile.
- **Docs:** [Composer](../../feature-map/composer.md) (`route-sub-agents`) and
  `subagent_routing_override` in the [API reference](../../omnigent/server/API.md).
- **Upstream:** not upstream yet; tracked by issue [#14897](https://github.com/omnigent-ai/omnigent/issues/14897).

## Must hold

- Creating a native Claude Code or Codex session with `subagent_routing_override: "on"` stamps the label `omnigent.routing.subagent_routing: "1"`; it needs no `cost_control_mode_override`, and the session keeps the model it was created with.
- Every launch of a session with that label installs the spawn-routing endpoint and hook (on Codex also the routed-spawn tool approvals and the extended model catalog) and nothing that routes the session's own model: no first-message hook, no alias or launch-model pins.
- Launches read the label, not the switch; the switch is read per spawn, so turning it off and on applies to the next sub-agent, and a native session created without the option that is switched on later routes its Omnigent child sessions only.
- Spawns stay in the session's model family, and `sys_agent_list` offers such a session only agents of that family.
- Turning the switch on, at create or by `PATCH`, fails with 400 `invalid_input` on a session with a bound inference profile.
- The new-session composer offers **Route sub-agents** only on a server with Smart Routing and beside a Claude Code or Codex model the user picked; the session's model menu has the same row, which says **Child sessions only** when the launch installed no gate.

## Key code

- `omnigent/runner/subagent_routing.py`: `SUBAGENT_ROUTING_LABEL_KEY`, `SUBAGENT_ONLY_HOOK_HARNESSES`, `SessionRoutingClass`, `routes_spawns`, `routing_class_from_snapshot`
- `omnigent/runner/native/orchestration.py`: `_start_subagent_router_for_native_session`, `subagent_routing`
- `omnigent/server/routes/_sessions/orchestration.py`: `_create_session_from_existing_agent`, `SUBAGENT_ROUTING_LABEL_KEY`
- `omnigent/runner/tool_dispatch.py`: `_spawn_family`
- `web/src/components/CostRoutingControl.tsx`: `subagentRoutingReach`, `SUBAGENT_ROUTING_LABEL_KEY`

## Tests

- `tests/runner/test_app_sessions_native_terminals_autocreate.py::test_a_subagent_only_claude_native_launch_gates_spawns_and_keeps_its_model`
- `tests/server/routes/test_native_smart_routing_create.py::test_create_marks_a_native_session_that_asks_for_subagent_routing`
- `tests/runner/test_agent_list_spawn_family.py::test_subagent_only_session_sees_only_its_own_family`
- `tests/server/test_sandbox_inference_routes.py::test_routing_switches_are_refused_on_a_bound_profile`
- `web/src/components/composer/SubagentRoutingItem.test.tsx`
