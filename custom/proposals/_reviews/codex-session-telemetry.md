# Codex review: session-telemetry (`feat/turn-model-effort` and `feat/session-telemetry`)

Command: `codex exec --sandbox read-only -` with the prompt, CLAUDE.md and the branch diff pasted on stdin
(`codex review --base` rejects a custom prompt, and the bubblewrap sandbox cannot run shell commands in this
environment). Model: gpt-6.1-sol (codex-cli 0.159.2). Two runs: `feat/turn-model-effort` (one commit) and
`feat/session-telemetry` (asked to focus on its two commits; the whole-branch diff and the two-commit diff were both pasted).

## Disposition: feat/turn-model-effort

1. "Observed replaces requested" untested with conflicting values — **fixed**: new matrix case
   `observed-replaces-requested` in `tests/runtime/harnesses/test_executor_adapter_skill.py` (override
   `openai/gpt-5.4-mini` + effort `High`, turn completes with usage model `gpt-5.5-2026-09` and effort `medium`;
   request attributes keep the requested values, the effective ones become the observed values with `source=observed`).
   The existing `requested` case already covers an explicit request with no observation.
2. Codex `_default_effort` after a model switch — **not a bug**: the cache is upstream code, reset on every
   `thread/start` and resolved against `_thread_model`; a model change on the SDK path starts a new thread.

## Disposition: feat/session-telemetry (commits 2 and 3)

1. `session_model` returns `None` with no `llm_model` but a configured model — **fixed** (commit 3): the configured
   model is now the last rung (`resolved_default`), with the `configured-only` case in `tests/runner/test_session_telemetry.py`.
2. No session-effort fallback on the agent span — **not a bug**: the runner already forwards the session's remembered
   effort (`_session_reasoning_effort`) as the turn's `reasoning.effort`, so it is the agent span's requested effort
   whenever the harness accepts it; stamping it when the harness rejected the level would be wrong.
3. Model-source inference by string comparison — **dismissed as a documented heuristic**: the snapshot carries no
   provenance; a report equal to the configured model is exported with the right value and the conservative source
   `resolved_default`. OBSERVABILITY.md §14 says the source is inferred ("a snapshot `llm_model` that differs from the
   configured model counts as a harness report"), so operators know the rule.
4. Local lookups outside the timeout boundary — **dismissed**: `local_session_attributes` never raises
   (`_run` returns `(None, "", "")` on spawn error or timeout and the git call has the runner's git timeout), it runs
   once per session, and `_session_runtime_cwd` is the same cached helper the turn path already awaits.
5. Malformed-skill privacy assertions moved into the session-attributes test — **fixed** (commit 2): the
   `"private task details"` and `_active_skill_var` assertions are back in
   `test_malformed_skill_call_exports_no_argument_content`; the new test keeps only its own assertions.

## Raw output: feat/turn-model-effort

codex
I’ll review the pasted diff for correctness, test gaps, and convention violations, and mark anything that depends on unseen code as unverified.
codex
I would request additional regression coverage before merging. I found no confirmed correctness bug in the supplied diff.

1. **[P2] The central “observed replaces requested” behavior is untested.**  
   **File:** `tests/runtime/harnesses/test_executor_adapter_skill.py:309`  
   The new matrix tests requested values and observed values separately, but never supplies conflicting requested and observed values. Consequently, it would still pass if completion stopped replacing the requested model or effort—the central promise of this change.

   Add a case requesting model A / effort `high`, then completing with usage model B / effort `medium`. Assert:
   
   - Request attributes retain A and `high`.
   - Effective attributes become B and `medium`.
   - Both source attributes become `observed`.

   Also cover an explicit request followed by completion without observations, confirming the requested fallback survives. This is changed behavior requiring coverage under `CLAUDE.md`.

2. **[P2, unverified] Codex’s cached default must belong to the current turn’s model.**  
   **File:** `omnigent/inner/codex_executor.py:3760`  
   `turn_effort = effort or self._default_effort` now publishes the cached default as an **observed applied effort**. That is correct only if `_default_effort` remains authoritative after model changes and thread settings updates. The pasted context does not establish that invariant, and the extended test exercises effort changes without visibly exercising model changes.

   If a reused session can switch models while retaining the previous model’s default, telemetry will report the wrong effort as observed. Verify the existing refresh logic; add a model-switch regression if that path is supported. This is a risk to investigate, not a demonstrated bug.

Verification: run the three changed test modules. For a manual check, send one turn with explicit model/effort and another using defaults; inspect their exported agent spans for preserved request attributes, observed completion values where available, and absent effort when unknown.

I could not verify test execution, pre-commit results, PR-template compliance, or the test-guide/helper-reuse requirements from the pasted material.

## Raw output: feat/session-telemetry

codex
I’ll focus on the last two commits and review only the pasted material. I’ll distinguish issues visible in the diff from concerns that depend on code not included here.
codex
I would request changes. These findings concern only the last two commits; line numbers refer to the final files in the pasted diff. No commands or tests were run.

1. **[P2] The configured model is not actually used as the final fallback.**  
   `omnigent/runner/session_telemetry.py:57–63`, `session_model()`

   With `session={}` and `configured_model="gpt-5.5"`, this returns `None`. The configured model is used only for comparison, despite the documented fallback being report → override → configured model. Consequently, the runner can send `omnigent.agent.model` while omitting `omnigent.session.model`, and an unreported turn still gets no `gen_ai.response.model`.

   Return the configured model with `resolved_default` when neither snapshot field supplies a model. Add a unit case with a known configured model and absent/null `llm_model`.

2. **[P2] The turn never falls back to the session’s reasoning effort.**  
   `omnigent/inner/tracing.py:417–420`, `set_requested_turn_settings()`

   The runner exports `SESSION_REASONING_EFFORT`, but this method reads only the session model. For a session carrying effort `high`, a request without an explicit effort and a harness completion without an effort report leaves `omnigent.reasoning_effort` unset.

   This misses the effort half of the stated change. Use the session effort when the turn supplies no effort, while preserving explicit default/reset semantics. Extend the adapter matrix with session effort present, no turn effort, and no observed effort.

3. **[P2] Comparing model strings cannot reliably identify an observed model.**  
   `omnigent/runner/session_telemetry.py:55–62`, `session_model()`

   Consider a configured model `gpt-5.5`, a harness report of that same model, and a session override `gpt-5.4-mini`. The function returns the override as `requested`, discarding the actual report because it equals the configured model. Without an override, that same real report is incorrectly classified as `resolved_default`.

   The snapshot described here conflates configured and reported values; equality cannot recover their provenance. Carry an explicit reported-model/source field, or avoid claiming that this heuristic reliably distinguishes observations. Add coverage for a report equal to the configured model.

   **Unverified:** whether the conflicting report/override state occurs in normal operation depends on server update behavior not included in the paste. The function’s inability to distinguish equal configured and observed values is visible directly.

4. **[P2] Machine-local telemetry work sits outside the failure and timeout boundary.**  
   `omnigent/runner/app.py:2110–2115` and `:5144`

   The forwarding path awaits `_session_runtime_cwd()` and `local_session_attributes()` before entering `resolve_session_attributes()`’s guarded five-second budget. An exception here escapes the telemetry fallback, and a stalled local lookup prevents the harness from receiving the turn. Moving work to a thread does not bound the await.

   Wrap the complete enrichment operation in the best-effort boundary, including workspace and local resolution. Add forwarding tests that inject a local lookup exception and a stalled local lookup, asserting that the harness still receives the turn.

   **Unverified:** the actual timeout and exception guarantees of `_git` and `_session_runtime_cwd` are not supplied. The missing outer boundary is visible in the diff.

5. **[P2] Existing privacy assertions were accidentally moved into an unrelated test.**  
   `tests/runtime/harnesses/test_executor_adapter_skill.py:309–334`

   The new test definition splits `test_malformed_skill_call_exports_no_argument_content()` before its existing span-content and active-skill cleanup assertions. Those assertions now run after an ordinary `Bash` call with `{"command": "ls"}`. Checking that those spans lack `"private task details"` no longer exercises the malformed skill arguments, so the privacy regression check has become ineffective.

   Restore those assertions to the malformed-skill test. Keep session-attribute assertions in the new test. This is a concrete loss of existing coverage under CLAUDE.md’s requirement to retain sufficient coverage.

To verify the fixes, extend the existing unit and adapter scenarios above, then run:

```bash
pytest tests/runner/test_session_telemetry.py \
  tests/runner/test_app_sessions_native_workflow_messages.py \
  tests/runtime/harnesses/test_executor_adapter_skill.py \
  tests/runtime/test_telemetry.py
```

For a manual check, use a session with a configured model and effort, send a turn without overrides, and inspect its agent span. Then make metadata resolution fail and confirm another turn still reaches the harness.
