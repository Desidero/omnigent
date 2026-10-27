# feat(telemetry): attribute spans to the acting user, runner and host

## Related issue

Closes #10794

## Summary

On a multi-user server that exports traces, every span carried `session.id` but nothing said whose traffic it was or which runner produced it; answering that meant joining `session.id` against the Omnigent database, and spans with no session (host frames, background work) couldn't be attributed at all. The identity was already known: the HTTP middleware binds the authenticated user, session and runner into the debug-logging context on every request, the host hands the owner and runner id to runners as `OMNIGENT_USER_ID` / `OMNIGENT_RUNNER_ID`, and the host daemon knows its own id. This stamps those onto spans the same way `session.id` and `omnigent.skill.active` are stamped today.

- **`enduser.id`** (OTel semconv): the request-scoped user on the server, the process owner on host, runner and harness. Off by default because the id is usually an email; opt in with `OMNIGENT_OTEL_CAPTURE_USER=true`, gated like content capture. The server's root HTTP span starts before auth resolves the user, so the middleware also stamps the current span directly, as the session-id hook does. `enduser.id` rather than `user.id` because it is the stable semconv key for the end user of a request (`user.id` also exists in the same package; happy to switch if maintainers prefer).
- **`omnigent.runner.id`**: the runner bound to the request on the server, falling back to `OMNIGENT_RUNNER_ID` only in runner and harness processes. The fallback policy now lives in one place, `debug_logging.current_runner_id`, which the debug-log sink and the span processor share; `configure_process_logging` records the process kind it already receives, so the processor needs no service-name table. Always on when tracing is on; not personal data.
- **`omnigent.host.id`**: a resource attribute. The host daemon resolves its identity before `telemetry.init("omni-host")` and appends the id to `OTEL_RESOURCE_ATTRIBUTES` via a small `telemetry.set_resource_attribute` helper (also used by the codex launcher for `launch_mode`, replacing its inline copy), so every `Resource.create()` picks it up and the runners and harnesses the host spawns inherit it through the existing `OTEL_*` env allowlist.

Also: `set_session_id` and `set_request_user` share one `_stamp_current_span` helper, the telemetry init log line reports `capture_user`, and `designs/OBSERVABILITY.md` / `docs/databricks.md` document the attributes and the gate.

## Test Plan

- `tests/runtime/test_telemetry.py`: processor tests for `enduser.id` (gate on/off, child spans, no user bound) and `omnigent.runner.id` (bound runner wins; env fallback only when the process source is `runner` or `harness`, parametrized over both); `set_request_user` on a started span; a TestClient + `FastAPIInstrumentor` test asserting the SERVER span and an inner span both carry `enduser.id` with the gate on and nothing with it off, with the middleware registered after instrumentation as the server app factory does; `set_resource_attribute` add/replace; `init("omni-host")` with the host id in `OTEL_RESOURCE_ATTRIBUTES` lands it on the provider resource next to `service.name`; `test_init_reads_capture_flags` covers both flags.
- `tests/server/test_audit_logging_middleware.py`: through the real `create_app` with a header auth provider, the HTTP middleware hands the resolved user (`X-Forwarded-Email`) to `telemetry.set_request_user`.
- `tests/test_debug_logging.py`: `current_runner_id` env fallback only for runner-owned sources, explicit or process-level; `tests/test_process_logging.py`: `configure_process_logging` records the process source.
- Ran: `uv run python -m pytest tests/runtime/test_telemetry.py tests/server/test_audit_logging_middleware.py tests/test_debug_logging.py tests/test_process_logging.py -q` → 403 passed. `tests/inner/test_codex_executor.py tests/harnesses/codex_native/app_server/test_launch_config.py` (codex `launch_mode` resource attribute, now via the shared helper) → pass as part of a 571-passed run. `tests/cli/test_host_daemon_env.py tests/host/test_cli_host.py tests/host/test_daemon_lifecycle.py` → 256 passed. `pre-commit run --files <changed>` clean.
- Not run: a live export to a collector. The host-daemon ordering change (`_serve_host_until_exit`) is not unit-tested; it is three lines of wiring over the tested helper. To check by hand: `OMNIGENT_TELEMETRY_ENABLED=true OMNIGENT_OTEL_CAPTURE_USER=true OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 omnigent host` against a debug collector, send a message from the web UI, and look for `enduser.id`, `omnigent.runner.id` on the server/runner spans and `omnigent.host.id` in the resource of `omni-host`, `omni-runner` and `omni-harness` spans; unset `OMNIGENT_OTEL_CAPTURE_USER` and confirm `enduser.id` disappears while the other two stay.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Evidence is the test set in the Test Plan; no UI change.

## Type of change

- [ ] Bug fix
- [x] Feature
- [ ] UI / frontend change
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

Unit tests exercise the span processors, the helpers and the runner-id policy directly; the TestClient test and the `create_app` middleware test cover the root-span race the issue describes. No test exports real spans; the manual check above is how to see the attributes in a backend.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Exported spans now carry `omnigent.runner.id` and an `omnigent.host.id` resource attribute, plus `enduser.id` when `OMNIGENT_OTEL_CAPTURE_USER=true`, so multi-user traces can be filtered by person, runner and host without a database join.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
