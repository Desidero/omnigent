# session-telemetry

Needs: telemetry-attribution
Covers: fe055cdf07631ff3

Every span of a turn carries session metadata (title, labels, project, agent,
git branch and remote, workspace, host name), and the agent span records the
model and reasoning effort the turn asked for and ran with, falling back to
the session's and the agent's configured model when the harness reports none.

- **Turn on:** with telemetry on (`OMNIGENT_TELEMETRY_ENABLED`); the session
  title also needs `OMNIGENT_OTEL_CAPTURE_CONTENT`.
- **Docs:** `designs/OBSERVABILITY.md` (Model and effort attributes, Session
  attributes) and [Databricks](../databricks.md) (Which model and effort a
  turn ran with).
- **Upstream:** proposed from `feat/turn-model-effort` and, stacked on it,
  `feat/session-telemetry`.

## Must hold

- With telemetry on, the runner resolves session attributes for each turn and sends them on the turn body as `telemetry_attributes`; every span the harness emits for that turn carries them. With telemetry off nothing is resolved or sent.
- Title, labels (`omnigent.session.labels.<key>`, internal `omnigent.*` labels skipped), project, agent and git branch are re-read each turn; workspace, git remote (credentials stripped) and host name are resolved once per session. The title is sent only when `OMNIGENT_OTEL_CAPTURE_CONTENT` is on, and no user attribute is stamped here.
- A server read that fails or does not finish within a few seconds leaves the turn with the machine-local attributes only; telemetry never fails a turn.
- On the agent span, `gen_ai.request.model` is the turn's model override, else the agent's configured model, and never the agent name; `gen_ai.agent.name`, `llm.model_name` and `gen_ai.provider.name` keep their upstream values.
- The agent span carries `gen_ai.response.model` with `omnigent.model.source` (`observed`, `requested` or `resolved_default`), stamped from the session model at turn start and replaced by what the harness reports at turn end; every span of the turn also carries `omnigent.agent.model`, `omnigent.session.model`, `omnigent.session.model.source` and `omnigent.session.reasoning_effort`.
- `omnigent.reasoning_effort.requested` records the effort a turn asked for; `omnigent.reasoning_effort` and its `.source` are set only when the level is known (requested, or reported by the harness, as Codex does for its thread default) and are never guessed.

## Key code

- `omnigent/runner/session_telemetry.py`: `resolve_session_attributes`, `session_metadata_attributes`, `local_session_attributes`, `session_model`
- `omnigent/inner/tracing.py`: `set_requested_turn_settings`, `set_observed_turn_settings`, `TURN_MODEL_SOURCE`, `SESSION_MODEL`
- `omnigent/runtime/telemetry.py`: `session_attributes_scope`, `make_span_attributes_processor`
- `omnigent/runner/app.py`: `_session_span_attributes`
- `omnigent/server/schemas.py`: `telemetry_attributes`

## Tests

- `tests/runner/test_session_telemetry.py::test_resolve_session_attributes_reads_server_metadata_each_call`
- `tests/runner/test_session_telemetry.py::test_session_model_tells_reports_from_requests_and_defaults`
- `tests/runtime/harnesses/test_executor_adapter_skill.py::test_agent_span_records_the_model_and_effort_the_turn_ran_with`
- `tests/runtime/harnesses/test_executor_adapter_skill.py::test_session_attributes_stamp_every_turn_span`
- `tests/runner/test_app_sessions_native_workflow_messages.py::test_session_span_attributes_reach_the_harness_only_with_telemetry`
