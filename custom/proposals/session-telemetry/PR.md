feat(telemetry): stamp session metadata on harness turn spans

## Related issue

Closes #<issue-session-telemetry, part 2 of 2>

Stacked on #<pr-turn-model-effort> (part 1): its commit is the first on this branch and drops out once it merges; review the two commits after it. Related: #10794 (user and runner attribution) stamps spans the same way but is independent of this PR.

## Summary

ELI5: every span already says *which* session it came from; now it also says what that session is (title, labels, project, agent, branch, workspace, host) and which model and effort the session is running on, so a trace backend can classify conversations without joining the Omnigent database.

- **Session metadata on every span of a turn** (commit 1: `omnigent/runner/session_telemetry.py`, `omnigent/runner/app.py`, `omnigent/runtime/telemetry.py`, `_executor_adapter.py`, `server/schemas.py`). When `OMNIGENT_TELEMETRY_ENABLED` is on, the runner resolves `omnigent.session.title` (only with `OMNIGENT_OTEL_CAPTURE_CONTENT`, titles are often generated from the first message), `omnigent.session.labels.<key>` (internal `omnigent.*` labels skipped), `omnigent.project.id`/`.name` (name cached per project id), `omnigent.agent.name`, `omnigent.git.branch` and, once per session, `omnigent.workspace`, `omnigent.git.remote` (credentials and SSH user stripped with the existing `redact_url`), `omnigent.host.name`. They ride the turn body as `telemetry_attributes`; the adapter binds them with `session_attributes_scope` and a span processor (the mechanism behind `session.id` and `omnigent.skill.active`, generalised to a mapping) stamps them on every span. Server-owned values are re-read each turn so renames, label edits and project moves reach later spans.
- **Bounded and best-effort.** Each server read has a 5 s timeout and the whole resolution shares a 5 s budget (`asyncio.wait_for`); a failure or timeout leaves the turn with the machine-local attributes and one debug log. A turn is never delayed beyond the budget or failed by telemetry.
- **Session model and effort fallback** (commit 2: `session_model`, `omnigent.agent.model`, `omnigent.session.model` + `.source`, `omnigent.session.reasoning_effort`). Read from the same session snapshot, so no extra calls. On the agent span, `gen_ai.request.model` falls back to the configured model and `gen_ai.response.model` is stamped from the session model (`resolved_default`, or the harness's last report as `observed`) until the turn's own observation replaces it.
- Docs: `designs/OBSERVABILITY.md` section 15 lists each session attribute, its source and its gate (labels, project, workspace and remote are exported as ungated metadata, and labels are exported as-is); section 14 gains the session fallback.

No change when telemetry is off. There is no user attribute here; the acting user is `enduser.id` in #10794.

## Test Plan

Unit tests at the lowest layer that owns each piece:

- `tests/runner/test_session_telemetry.py` (new): projection of a session body onto attributes (missing values and internal labels dropped; title needs content capture; local attributes carry no user); git branch and remote against a real temp repo (SSH user and https credentials stripped, detached HEAD, missing folder); server metadata re-read on every call with the project name fetched once and the per-request timeout asserted on the request; a stalled server ends within the budget with the local attributes only; a server failure degrades the same way; `session_model` tells reported from requested and default models.
- `tests/runtime/test_telemetry.py`: `session_attributes_scope` stamps every span inside the scope and nothing outside; binds nothing when telemetry is off or the mapping is empty.
- `tests/runtime/harnesses/test_executor_adapter_skill.py`: the request's attributes land on the agent span and its tool spans and the context var is reset afterwards; the agent-span matrix gains the `default-model-unreported` case (`resolved_default` from the session).
- `tests/runner/test_app_sessions_native_workflow_messages.py`: the runner puts `telemetry_attributes` on the forwarded turn body only with telemetry on.

Ran on this branch (`uv sync --frozen --extra all --group test --group lint`, `OMNIGENT_*` unset):

```
python -m pytest tests/runtime/test_telemetry.py tests/runner/test_session_telemetry.py \
  tests/runtime/harnesses/test_executor_adapter_skill.py tests/inner/test_tracing_genai_semconv.py \
  tests/inner/test_codex_executor.py tests/runner/test_app_sessions_native_workflow_messages.py -q
# 371 passed, 4 skipped, 11 subtests passed
uvx pre-commit run --files <changed files>
# all hooks pass
```

Each commit was also tested on its own: part 1 alone (244 passed, 4 skipped) and commit 1 without the fallback (148 passed across the four files above).

To check by hand: run with `OMNIGENT_TELEMETRY_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at Jaeger (`designs/OBSERVABILITY.md` section 3), start a session with a label and a project, send a turn, rename the session, send another turn. The second turn's spans (agent and tool) carry the new title (with `OMNIGENT_OTEL_CAPTURE_CONTENT=true`) and the label; the agent span shows `gen_ai.response.model` with `omnigent.model.source=observed` once the harness has reported, `resolved_default` before. Stop the server mid-session and send a turn: it still runs, the spans carry only `omnigent.workspace`, `omnigent.git.remote` and `omnigent.host.name`.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Spans from an in-memory exporter for one scripted `ExecutorAdapter` turn (the `test_executor_adapter_skill.py` fixture): one Bash tool call, no model pinned, the harness reporting `claude-opus-4-8-20260915` in usage, session attributes as the runner resolves them with content capture on:

```json
SPAN tool:Bash {
  "gen_ai.operation.name": "execute_tool",
  "gen_ai.tool.name": "Bash",
  "omnigent.agent.model": "claude-opus-4-8",
  "omnigent.agent.name": "coder",
  "omnigent.git.branch": "feat/login-redirect",
  "omnigent.git.remote": "github.com:acme/storefront.git",
  "omnigent.host.name": "dev-box",
  "omnigent.project.id": "proj_8f2a",
  "omnigent.project.name": "Storefront",
  "omnigent.session.labels.priority": "p1",
  "omnigent.session.labels.team": "web",
  "omnigent.session.model": "claude-opus-4-8",
  "omnigent.session.model.source": "resolved_default",
  "omnigent.session.reasoning_effort": "high",
  "omnigent.session.title": "Fix login redirect",
  "omnigent.workspace": "/home/dev/src/storefront",
  "openinference.span.kind": "TOOL",
  "session.id": "64f9f8b060d64cac81118ef3dc1f4471",
  "tool.name": "Bash"
}
SPAN agent:test-agent {
  "gen_ai.agent.name": "test-agent",
  "gen_ai.operation.name": "invoke_agent",
  "gen_ai.request.model": "claude-opus-4-8",
  "gen_ai.response.model": "claude-opus-4-8-20260915",
  "gen_ai.usage.input_tokens": 1523,
  "gen_ai.usage.output_tokens": 847,
  "gen_ai.usage.total_tokens": 2370,
  "llm.model_name": "test-agent",
  "omnigent.agent.model": "claude-opus-4-8",
  "omnigent.agent.name": "coder",
  "omnigent.git.branch": "feat/login-redirect",
  "omnigent.git.remote": "github.com:acme/storefront.git",
  "omnigent.host.name": "dev-box",
  "omnigent.model.source": "observed",
  "omnigent.project.id": "proj_8f2a",
  "omnigent.project.name": "Storefront",
  "omnigent.session.labels.priority": "p1",
  "omnigent.session.labels.team": "web",
  "omnigent.session.model": "claude-opus-4-8",
  "omnigent.session.model.source": "resolved_default",
  "omnigent.session.reasoning_effort": "high",
  "omnigent.session.title": "Fix login redirect",
  "omnigent.workspace": "/home/dev/src/storefront",
  "openinference.span.kind": "AGENT",
  "session.id": "64f9f8b060d64cac81118ef3dc1f4471"
}
```

The same turn with a harness that reports nothing ends with `gen_ai.response.model=claude-opus-4-8` and `omnigent.model.source=resolved_default`.

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
- [ ] Integration tests added / updated
- [ ] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Automated coverage stops at the adapter: the turn-body hand-off is covered by the runner app test and the span processor by `test_telemetry.py`. No E2E was added because no new process or transport boundary is crossed (the attributes ride the existing runner-to-harness turn body).

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Exported spans carry the session's title (with content capture), labels, project, agent, branch, workspace, host, model and reasoning effort

🤖 Generated with [Claude Code](https://claude.com/claude-code)
