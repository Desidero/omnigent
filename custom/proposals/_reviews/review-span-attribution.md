# Review: `feat/span-attribution` (9a7e75680) vs issue #10794

Worktree reviewed: the `feat/span-attribution` checkout. Line numbers below are from that checkout.

## Verdict

**Ready after fixes.** No correctness bugs found; the context-var plumbing, PII gate and empty-value handling all check out, and the root-HTTP-span stamping works on the real middleware order (verified empirically, see "Tests run"). What blocks a clean PR is scope: the commit silently drops one of the three attributes the issue promises (`omnigent.host.id`) and silently adds a knob the issue never proposed (`OMNIGENT_OTEL_LOCAL_USER`). Fix the scope mismatch either way, dedupe the runner-fallback policy, add the missing server-layer test, and finish the docs.

## Must fix

1. **`omnigent.host.id` is not implemented** — nothing in the diff touches `omnigent/host/connect.py`, resource creation, or `_entry.py`; the commit message and OBSERVABILITY row don't mention it either.
   - Why: the issue (your own) lists it as the third deliverable ("as a resource attribute on the host daemon and the processes it spawns"). A maintainer reading the PR against the issue will ask where it is.
   - Suggested change, either:
     - **Implement** (small): the host knows its id after `load_or_create_host_identity` (`omnigent/host/connect.py:5284`), which currently runs *after* `telemetry.init("omni-host")` (`:5278`). Resolve identity first (or read `OMNIGENT_HOST_ID` when set) and append `omnigent.host.id=<id>` to `OTEL_RESOURCE_ATTRIBUTES` before `init` — `Resource.create()` in `_init_otel_traces` (`telemetry.py:1155`), metrics (`:1211`) and logs (`:1301`) all merge that env var, so no new code path is needed in telemetry.py. Runners already receive the host id as `OMNIGENT_RUNNER_SLICE_KEY` (`connect.py:949`), and `OTEL_*` rides the runner allowlist (`:749`), so appending to `OTEL_RESOURCE_ATTRIBUTES` in the host env before spawn covers runner + harness too.
     - **Or descope explicitly**: say in the PR Summary and in a comment on #10794 that host.id is deferred and why, so the PR doesn't claim to close the issue.

2. **`OMNIGENT_OTEL_LOCAL_USER` is scope creep not covered by the issue** (`telemetry.py:60-61, 126-140, 1367`; `OBSERVABILITY.md:298`; commit message bullet 3).
   - Why: the issue says "I'm happy to change the attribute names or the gate if maintainers prefer" and the repo asks for an issue before larger changes. A second env var, a new `"local"`-rewriting rule, and a new `omnigent.runtime -> omnigent.server.auth` import (`telemetry.py:136`) are exactly the things that get a PR bounced to "please discuss first". The issue itself also says `OTEL_RESOURCE_ATTRIBUTES` already solves single-user installs, which undercuts the justification.
   - Suggested change: drop it from this PR (it is self-contained: the global, `_attributed_user`, the env read, the doc row, and the `local.*` test cases), and if you still want it, propose it on the issue or as a follow-up. If you keep it, add a sentence to the issue first and hoist the `RESERVED_USER_LOCAL` import out of the per-span hot path (`_attributed_user` runs a function-level import on every span start while the gate is on).

## Should fix

3. **Runner-id fallback policy is now defined twice** — `telemetry.py:63-64, 421-431, 1372` (`_RUNNER_SERVICE_NAMES` / `_runner_process`, keyed on the `service_name` string) vs `debug_logging.py:579-580` (`source in {"runner", "harness"}`, keyed on the sink source).
   - Why: repo CLAUDE.md says to reuse helpers and not duplicate policy; the two gates can drift (e.g. a new process kind). The literal strings `"omni-runner"` / `"omni-harness"` are also copied from the callers (`runner/_entry.py:1761`, `runtime/harnesses/_runner.py:453`) with no shared constant, and no test exercises the `"omni-harness"` branch.
   - Suggested change: make `debug_logging.current_runner_id()` the single owner of the fallback (it already owns `_runner_id_var` and `RUNNER_ID_ENV_VAR`), e.g. `current_runner_id(*, process_env_fallback: bool)` or a module-level "this process owns its runner id" flag set once by the runner/harness entry points, and have both the log sink and the span processor call it. At minimum, export the service-name constants and reference them from the callers.

4. **No test at the server layer for the one thing the issue is about** (the root HTTP span race). `tests/runtime/test_telemetry.py:991-1017` tests `set_request_user` against a hand-started span; nothing asserts that `_record_server_metrics` (`server/app.py:2157`) calls it with the resolved user, or that under `FastAPIInstrumentor` the SERVER span and its children both carry `enduser.id`.
   - Why: tests/README.md asks for the nearest scenario at the lowest reliable layer; the nearest ones are `tests/server/test_audit_logging_middleware.py` (middleware) and `test_httpx_to_fastapi_propagates_trace_across_http_hop` (`test_telemetry.py:1430`, TestClient + instrumentor). The middleware ordering (`instrument_fastapi_app` is called before `@app.middleware("http")` is registered, `server/app.py:1871` vs `:2117`) only works because the instrumentor overrides `build_middleware_stack`; a test pins that.
   - Suggested change: (a) in `test_audit_logging_middleware.py`, monkeypatch `telemetry.set_request_user` with a spy and assert it is called with the auth-provider user; (b) add one TestClient test modelled on `:1430` that installs `_make_user_id_processor`, sets the user in an `@app.middleware("http")` added after instrumentation, and asserts `enduser.id` on both the SERVER span and an inner span. I ran exactly this ad hoc and it passes, so it is cheap to add.

5. **OBSERVABILITY.md is now internally inconsistent.** The env-var row at `:297` is accurate, but the doc still enumerates the ambient attributes as only `session.id` and `omnigent.skill.active` at `:473` (table row "Cross-cutting attribute on every span"), `:483-484`, and `:506`.
   - Suggested change: add `enduser.id` (gated) and `omnigent.runner.id` to those three places; one sentence on the runner/harness env fallback next to the `session.id` cross-trace paragraph (`:305-315`) would also explain why host frames get a runner id only when bound.

6. **`docs/databricks.md:612-614`** is the user-facing OTEL env table (lists `OMNIGENT_OTEL_CAPTURE_CONTENT` under "Apps env"). Add a `OMNIGENT_OTEL_CAPTURE_USER` row there; it is the only user-facing doc that lists these vars.

7. **`set_request_user` duplicates `set_session_id`'s body** (`telemetry.py:296-303` vs `:318-327`: get current span, check `is_recording`, `set_attribute`, swallow). Factor a `_stamp_current_span(key, value)` helper used by both (and arguably by `_fastapi_session_id_hook:500`).

8. **Init log line not updated** (`telemetry.py:1394-1398` logs `capture_content=` only). Add `capture_user=`; operators will otherwise have no way to confirm the PII gate state from logs.

## Nits

9. `tests/runtime/test_telemetry.py:724` — `test_init_respects_capture_content_flag` now asserts capture-user, local-user and `_runner_process` too; rename (e.g. `test_init_reads_capture_flags_and_process_kind`) or split so a failure names the right flag.
10. `telemetry.py:63-64` comment is fine; the `_runner_process` name is a little opaque (`_runner_id_from_own_env` or similar reads better, and goes away if item 3 is done).
11. `debug_logging.py:312-314` — `current_runner_id()` is a fine addition; consider giving it the same docstring shape as `current_user_id()` (what it does *not* include: the env fallback), since that asymmetry is the whole point of item 3.
12. `enduser.id` is correct and still current in the installed semconv (0.65b0 only deprecates `enduser.role`/`enduser.scope`); `user.id` also exists in the same package. Worth one line in the PR saying why `enduser.id` was picked, in case a maintainer prefers `user.id`.
13. Attribute names follow the repo's `omnigent.*` convention (`omnigent.skill.active`, `omnigent.message.payload`). Comments are short, scenario-based, no PR numbers. Commit is signed off.
14. Behavioural note, not a bug: on the server, `current_user_id()` falls back to `OMNIGENT_USER_ID` from the process env (`debug_logging.py:304`). A server started from inside a runner (as this session is) would attribute every unauthenticated span to that inherited user. Same as debug logs today, so consistent; mention it in the docstring of `_make_user_id_processor` or leave it.

## Promised but missing

- `omnigent.host.id` resource attribute on the host daemon and spawned runner/harness processes (see item 1). Everything else in the issue is present: `enduser.id` via processor + middleware stamp, opt-in gate off by default, `omnigent.runner.id` with request binding first and runner/harness env fallback.
- Not promised but added: `OMNIGENT_OTEL_LOCAL_USER` (item 2).

Verified against the issue's correctness list:
- Context-var propagation: `on_start` reads the vars at span start. asyncio tasks spawned inside a request copy the context, so background work kicked off by a request inherits the user/runner; long-lived loops created at startup carry none (attribute omitted). `asyncio.to_thread` copies context; raw `loop.run_in_executor` does not, which already affects `session.id` the same way. Host daemon: `OMNIGENT_USER_ID` is set into the host's own env after the first tunnel upgrade (`connect.py:4593`) and injected into runners (`:1978`); runner sets `OMNIGENT_RUNNER_ID` into its env (`_entry.py:1435`) and the harness inherits. `OMNIGENT_OTEL_*` reaches runners via the prefix allowlist (`connect.py:749`).
- Root HTTP span race: works. The instrumentor's `build_middleware_stack` override keeps `OpenTelemetryMiddleware` outermost even though `_record_server_metrics` is registered later, so the SERVER span is current and recording when `set_request_user` runs; children get it from the processor via the context var set in the same middleware.
- PII gate defaults off: module default `False`, only read inside `init()` after the master opt-in; both the processor and `set_request_user` re-check at call time; the off case is tested.
- No None/empty attributes: `make_span_attribute_processor` skips falsy values; `set_request_user` returns early on falsy input; `_local_user` is stripped and `or None`'d.

## Upstream drift

- Base `ba5d16c79`, 158 commits behind `upstream/main` (not 127).
- No commits on `upstream/main` since the base touch `omnigent/runtime/telemetry.py`, `omnigent/debug_logging.py`, `designs/OBSERVABILITY.md` or `tests/runtime/test_telemetry.py`. `omnigent/server/app.py` has four unrelated commits (#10826, #11040, #10999, #9814).
- #10725 (telemetry E2E host identity) and #10713 (deps) are already ancestors of the base; neither overlaps.
- `git merge-tree --write-tree upstream/main feat/span-attribution` exits 0 (tree `ee6202bae`), i.e. the rebase is conflict-free. Rebase onto `upstream/main` before opening the PR anyway so CI runs on current main.

## Tests run

- Env: unset all `OMNIGENT_*` / `RUNNER_SERVER_URL`; the `feat/span-attribution` worktree (existing `.venv`, OTel SDK + FastAPI instrumentation present, semconv 0.65b0, sdk 1.44.0).
- `timeout 230 uv run --no-sync python -m pytest tests/runtime/test_telemetry.py -q` → **81 passed, 1 warning in 0.61s**.
- Ad hoc middleware-order check (`<scratch>/mw_order.py`): FastAPI app, `FastAPIInstrumentor.instrument_app` first, then an `@app.middleware("http")` that calls `set_current_user_id` + `telemetry.set_request_user(current_user_id())`, user processor installed. Result: SERVER span and all child spans (`inner`, `http send`) carry `enduser.id='alice@example.com'`; the middleware observed a recording span named `GET /v1/sessions/conv_123/x`. This is the test the PR should include (item 4).
- Not run: `tests/server/test_audit_logging_middleware.py` (no change there yet) or `pre-commit`; run `pre-commit run --all-files` after the fixes.
