# telemetry-attribution

Needs: none
Covers: a0d74241563131ff

Exported spans carry the runner (`omnigent.runner.id`), the host
(`omnigent.host.id`, a resource attribute) and, when you opt in, the acting
user (`enduser.id`).

- **Turn on:** with telemetry on (`OMNIGENT_TELEMETRY_ENABLED`), runner and
  host need nothing more; set `OMNIGENT_OTEL_CAPTURE_USER=true` for the user.
- **Docs:** `designs/OBSERVABILITY.md` (Configuration: the variable table and
  actor attribution) and [Databricks](../databricks.md) (Reference: env var
  summary).
- **Upstream:** proposed from `feat/span-attribution`.

## Must hold

- With telemetry on, spans carry `omnigent.runner.id`: the runner bound to the request, falling back to the process's own `OMNIGENT_RUNNER_ID` only in runner and harness processes, so server and host spans name a runner only when one is bound.
- `enduser.id` is stamped only when `OMNIGENT_OTEL_CAPTURE_USER` is truthy: the authenticated request user on the server, the process owner on host, runner and harness.
- On the server, the root HTTP span (which starts before auth resolves the user) also gets `enduser.id` when opted in.
- The host daemon adds `omnigent.host.id` to `OTEL_RESOURCE_ATTRIBUTES` before telemetry starts, so its own spans and those of the runners and harnesses it spawns carry it as a resource attribute, with no opt-in.
- Setting one resource attribute replaces that key and keeps the others; Codex's `launch_mode=omni` attribute is set the same way.

## Key code

- `omnigent/runtime/telemetry.py`: `should_capture_user`, `set_request_user`, `set_resource_attribute`, `_make_runner_id_processor`, `_make_user_id_processor`
- `omnigent/debug_logging.py`: `current_runner_id`, `set_process_source`, `_RUNNER_OWNED_SOURCES`
- `omnigent/host/connect.py`: `_serve_host_until_exit`, `set_resource_attribute`
- `omnigent/server/app.py`: `set_request_user`

## Tests

- `tests/runtime/test_telemetry.py::test_runner_id_processor_uses_bound_runner_then_own_process_env`
- `tests/runtime/test_telemetry.py::test_user_id_processor_stamps_enduser_only_when_opted_in`
- `tests/runtime/test_telemetry.py::test_fastapi_server_span_carries_enduser_id_when_opted_in`
- `tests/runtime/test_telemetry.py::test_init_resource_carries_host_id_from_env`
- `tests/test_debug_logging.py::test_current_runner_id_env_fallback_only_for_runner_owned_sources`
