# claude-native-teammates

Needs: none
Covers: f594c36bd8cafcc8

Claude Code agent-team teammates show up as child sessions titled
"<name>: <description>", and their deliveries no longer appear as raw
`<teammate-message>` bubbles in the lead's chat.

- **Turn on:** on by default.
- **Docs:** none (fixes).
- **Upstream:** proposed from `fix/claude-native-teammate-children` and
  `fix/claude-native-teammate-delivery`.

## Must hold

- An agent-team teammate (a sub-agent meta with `taskKind: "in_process_teammate"` and no `toolUseId`) is registered as a child session of the lead without waiting for spawn correlation; a meta that lacks `toolUseId` for any other reason stays unregistered.
- The teammate's child session is labelled `<name>: <description>` (whichever part exists when the other is empty) and is registered with the stable tool-use id `teammate:<agent id>`, which a server without this series accepts.
- A Task sub-agent that a teammate spawns is registered under the teammate's child session.
- A user record or queued prompt with no `origin` key whose text is nothing but Claude's framed teammate delivery is stored as hidden (`is_meta`) context, so the lead's chat shows no raw `<teammate-message>` bubble.
- The same text stays a visible user message when the record has `origin: {"kind": "human"}` or an explicit null `origin`, when the envelope lacks Claude's delivery prefix, or when any text follows the framing.

## Key code

- `omnigent/harnesses/claude_native/forwarder.py`: `_is_in_process_teammate`, `_IN_PROCESS_TEAMMATE_TASK_KIND`, `_read_subagent_meta`, `_forward_available_subagents`
- `omnigent/harnesses/claude_native/bridge.py`: `_is_internal_agent_text`, `_is_unattributed_teammate_delivery`, `_teammate_envelope_shape`

## Tests

- `tests/harnesses/claude_native/forwarder/test_subagent_discovery.py::test_subagent_watcher_registers_an_in_process_teammate_under_the_lead`
- `tests/harnesses/claude_native/forwarder/test_subagent_discovery.py::test_subagent_watcher_registers_a_teammate_spawned_subagent_under_the_teammate`
- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_claude_framed_delivery_without_origin_is_internal`
- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_real_claude_2_1_304_teammate_delivery_is_internal`
- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_queued_framed_delivery_from_a_human_stays_visible`
