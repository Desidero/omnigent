# feat(routing): route only the sub-agents of a native session

Draft. Not proposed yet: no contribution branch exists, and the demo and a live
routed spawn are still to do.

## Related issue

Closes #14897

## Summary

ELI5: you pick the coordinator's model yourself, and Smart Routing picks a model for each sub-agent it starts.

- **Before.** The gate that routes a native CLI's own sub-agents (Claude Code's `Agent`/`Task`, Codex's `spawn_agent`) is installed when the terminal launches, and only for a session launched on Smart Routing, which also routes the session's own model. `subagent_routing_override` on a plain native session therefore routed Omnigent child sessions only, and since the harness selectors were unified the web UI has no control for the switch at all (`setSubagentRouting` has no caller).
- **Launch.** A create that sends `subagent_routing_override: "on"` on a native Claude Code or Codex session stamps the label `omnigent.routing.subagent_routing`. `routing_class_from_snapshot` turns it into `SessionRoutingClass.subagent_routing`, and every launch of such a session starts the spawn-routing endpoint and registers the spawn hook. On Codex the advertisement also turns on the routed-spawn tool approvals, and the launch asks for the extended model catalog a routed spawn may need. Nothing that concerns the session's own model is added: no first-message hook, no alias pins, no launch-model pin.
- **Why a label.** The gate cannot be added after launch, while the switch can change at any time. Reading the switch at launch would make "has the gate" depend on when the terminal last restarted; the label is fixed at create, like the auto-harness label, and travels in the init snapshot's labels, so the envelope does not change.
- **Web.** The new-session composer shows **Route sub-agents** under Smart Routing when a Claude Code or Codex model is picked. The session's model menu has the same row, on every session `isSubagentRoutingSession` already describes. A native session without the gate whose switch was turned on through the API shows the row as **Child sessions only**.
- **Unchanged.** The switch is read per spawn. Spawns stay in the session's model family (`_reject_out_of_family_child`), and `sys_agent_list` is confined for these sessions too. A session whose switch is turned on after a plain create keeps today's behaviour.
- **Bound inference profiles.** A create with a bound profile now refuses the switch, as `PATCH` already did. See the last section.

Limits worth knowing:

- Claude Code's `Agent` tool takes a family alias, not a model id. A routed pick is applied when the session has an alias for exactly that model; otherwise the spawn keeps the model it asked for. A Smart Routing session re-pins its aliases to the router's arms for this; a session whose model the user picked does not, because that would also move the model its own alias resolves to.
- The gate is installed by the host. A host on an older build ignores the label and routes child sessions only.
- The option is not kept in the new-session draft: leaving the composer and coming back clears the checkbox.

## Test Plan

- `tests/runner/test_subagent_router_launch.py`: the label gives `subagent_routing` and no `turn_routing`; a sub-agent-only launch on `claude-native` and `codex-native` starts the endpoint; `claude-sdk`, `codex` and `pi-native` do not.
- `tests/runner/test_app_sessions_native_terminals_autocreate.py`: a sub-agent-only Claude Code launch has the spawn hook, no `route-turn` hook, and the same `--model` and `ANTHROPIC_*` environment as a plain launch. The existing plain-launch test is unchanged.
- `tests/runner/test_codex_native_launch_config.py`: the launch config reads the label, on the envelope and the legacy path, and a switch turned on later without it stays plain. `tests/harnesses/codex_native/app_server/test_session_profiles.py` (plain Codex home) passes unchanged.
- `tests/runner/test_agent_list_spawn_family.py`: the listing is confined to the session's family.
- `tests/server/routes/test_native_smart_routing_create.py`: which creates get the label.
- `tests/server/test_sandbox_inference_routes.py`: both routing switches are refused on a bound profile, at create and on `PATCH`.
- Web: `SubagentRoutingItem.test.tsx`, `CostRoutingControl.test.tsx`, `NewChatDialog.test.tsx` (the create body), `chatStore.test.ts` (the switch on a given session).

Not done: a routed spawn against a live router, on either CLI.

## Demo

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

To do: the new-session row, the in-session row, and a routed spawn's chip.

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
- [x] Integration tests added / updated
- [ ] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The Codex launch site (the endpoint's environment and the catalog flag reaching the app-server) is covered through its inputs, the launch config and the endpoint start, and by the existing per-class Codex home tests; there is no new end-to-end launch test.

## Release notes

- [x] Yes
- [ ] No

## Changelog

Claude Code and Codex sessions can keep the model you pick and let Smart Routing choose models for their sub-agents only ("Route sub-agents" in the model menu).

## Bound inference profiles: not relaxed here

A session whose harness has an `inference:` binding refuses both routing switches ("Automatic provider routing is unavailable for a bound inference profile"). The rule came with per-harness providers and curated model selection (https://github.com/omnigent-ai/omnigent/pull/7783); its design doc says an explicit binding is authoritative and that Smart Routing cannot replace the bound provider (`designs/MANAGED_SANDBOX_MODEL_SELECTION.md`). What it protects:

1. Inference for the session goes to the bound provider, with the credential saved for the session's owner.
2. The models the session may use are the binding's saved list (`model_allowlist`, or its intersection with discovery), which is checked whenever a model is selected.

For the CLI's own sub-agents, point 1 holds by construction: they run inside the session's harness process, which only talks to the bound provider. Point 2 does not hold today, and one more thing the rule covers implicitly does not either:

- Candidates for a routed spawn come from the runner's live catalog, or the static table when the host reads as gateway-backed (it always does for a sandbox, where no host has reported), plus the unadvertised Codex arms. None of these consult the saved list, so a routed pick can be a model the binding excludes. Codex takes the id as is.
- The routing call sends the spawn's prompt to the router. That is the workspace router when it answers and the built-in judge, on the server's own `llm:` provider, when it does not (`route_with_fallback`). Either way the call runs under the server's credential, not the session owner's.
- Omnigent child sessions follow the same switch through a different path (`route_session_harness`), which can also re-decide the child's harness, while a child inherits its parent's saved profile for one harness.

Allowing sub-agent routing when the bound provider is the workspace gateway the external router serves would therefore need all of: candidates limited to the saved catalog on every path (no static table, no unadvertised arms); the external router only, with no fallback to the judge, and only when its host is the binding's own workspace; a decision on whose credential the routing call uses; and the child-session path either excluded or made to honour the profile. None of that can be checked without a deployment that binds a profile, so it is left out.

Options:

- **Keep the rule** (this PR). Deployments that bind a profile have no routing in those sessions.
- **Relax for the CLI's own sub-agents only**, with the conditions above, and keep refusing child-session routing for bound parents. This is the smallest sound change, and wants its own issue and a maintainer's view on the credential question.
- **Do not bind where routing is wanted.** A sandbox target without an `inference:` binding is not subject to the rule.
