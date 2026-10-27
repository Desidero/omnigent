feat(telemetry): record the model and effort a turn ran with

## Related issue

Closes #<issue-session-telemetry, part 1 of 2>

Standalone: applies to `main` on its own. The session-metadata PR (part 2) stacks on it.

## Summary

ELI5: the agent span said only what a turn *asked for*. A turn left on the defaults asked for nothing, so `gen_ai.request.model` fell back to the agent name and no effort was recorded. Now the span also says what the turn *ran with*, whenever the harness reports it, and never guesses.

- `gen_ai.request.model` is set only when the turn requested a model (`omnigent/inner/tracing.py`, `start_agent_span(request_model=...)`). The agent name stays in `gen_ai.agent.name`; `llm.model_name` and `gen_ai.provider.name` are unchanged for MLflow and OpenInference views.
- The agent span gains `gen_ai.response.model` + `omnigent.model.source` (`observed` from the turn's usage model, `requested` when only the override is known) and `omnigent.reasoning_effort.requested` / `omnigent.reasoning_effort` + `.source` (only when the level is on the shared effort ladder). A value observed at turn end replaces the one stamped at turn start (`set_requested_turn_settings` / `set_observed_turn_settings`, called from `_executor_adapter.py`).
- `TurnComplete.reasoning_effort` lets a harness report the effort it applied; Codex reports its thread default. Harnesses that report nothing (Claude Code, Claude Agent SDK, pi, OpenAI Agents) leave a default effort unset.
- Docs: `designs/OBSERVABILITY.md` section 14 (attribute table and which harness reports what), pointer from `docs/databricks.md`.

No change when telemetry is off.

## Test Plan

- `tests/inner/test_tracing_genai_semconv.py`: no `gen_ai.request.model` when none was requested; `llm.model_name` keeps the agent name.
- `tests/inner/test_codex_executor.py`: each Codex turn's `TurnComplete` reports the effort it ran at (configured default, then the applied efforts).
- `tests/runtime/harnesses/test_executor_adapter_skill.py`: a parametrised agent-span matrix with the in-memory exporter: default model observed from usage / unknowable, explicit override + effort (`requested`), default effort observed / unreported.

Ran on this branch (`uv sync --frozen --extra all --group test --group lint`, `OMNIGENT_*` unset):

```
python -m pytest tests/inner/test_tracing_genai_semconv.py tests/inner/test_codex_executor.py \
  tests/runtime/harnesses/test_executor_adapter_skill.py -q
# 244 passed, 4 skipped, 11 subtests passed
uvx pre-commit run --files <changed files>
# all hooks pass
```

To check by hand: run with `OMNIGENT_TELEMETRY_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at Jaeger (`designs/OBSERVABILITY.md` section 3), send a turn to a codex agent with `/effort high`, then one without. The first agent span shows `omnigent.reasoning_effort=high` with `.source=requested`; the second shows the thread default with `.source=observed`; both show `gen_ai.response.model` with `omnigent.model.source=observed` and no `gen_ai.request.model` unless a model was pinned.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Agent span from an in-memory exporter for one scripted `ExecutorAdapter` turn (the `test_executor_adapter_skill.py` fixture): override `anthropic/claude-opus-4-8`, effort `high`, the harness reporting `claude-opus-4-8-20260915` in usage and effort `high` on `TurnComplete`:

```json
SPAN agent:test-agent {
  "gen_ai.agent.name": "test-agent",
  "gen_ai.operation.name": "invoke_agent",
  "gen_ai.provider.name": "anthropic",
  "gen_ai.request.model": "claude-opus-4-8",
  "gen_ai.response.model": "claude-opus-4-8-20260915",
  "gen_ai.usage.input_tokens": 1523,
  "gen_ai.usage.output_tokens": 847,
  "gen_ai.usage.total_tokens": 2370,
  "llm.model_name": "anthropic/claude-opus-4-8",
  "omnigent.model.source": "observed",
  "omnigent.reasoning_effort": "high",
  "omnigent.reasoning_effort.requested": "high",
  "omnigent.reasoning_effort.source": "observed",
  "openinference.span.kind": "AGENT",
  "session.id": "da82f2d17f924efc9ade284f4f6c1e53"
}
```

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

The adapter matrix runs the real `ExecutorAdapter` against a mock executor with an in-memory exporter, so it covers the span attributes end to end within the harness process. No new process or transport boundary is crossed, so no E2E was added.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
