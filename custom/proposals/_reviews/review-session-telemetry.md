# Review: feat/session-telemetry (session metadata + model/effort on spans)

Branch: `feat/session-telemetry` in `~/repos/omnigent-wt/feat/session-telemetry`
= `upstream/main` (01787ce0a) + 9a7e75680 (attribution, temporary base) + the two commits.

## Verdict

Sound design, well tested, ready to propose after the Must-fix items. The two
commits reuse the existing span-processor mechanism (`make_span_attribute_processor`
generalised to a mapping) and keep every lookup best-effort, so a failure never
touches a turn. Recommend splitting commit 2 (below) and rebasing the branch
straight onto `upstream/main` so it does not wait on #10794.

## Must fix

1. **`omnigent.git.remote` can leak credentials.** `git remote get-url origin`
   returns the URL verbatim, and `https://user:ghp_xxx@github.com/acme/app.git`
   style remotes are common on CI boxes and in sandboxes. Strip the userinfo
   (`urllib.parse.urlsplit` → rebuild without `username`/`password`; leave
   `git@host:path` SSH forms alone) in `git_remote_url` and add a test case to
   `test_git_lookups_read_the_repo_and_tolerate_failures`.
2. **Unbounded wait before the turn is forwarded.** `_get_json` uses the runner's
   `server_client`, whose timeout is `httpx.Timeout(5.0, read=None)`
   (`omnigent/runner/app.py` ~L7905): a stalled server read blocks
   `_session_span_attributes`, and with it the harness POST, indefinitely. The
   other per-turn session reads pass `timeout=10.0` (app.py ~L3768). Pass an
   explicit timeout (2-5 s is plenty for metadata) and consider wrapping the
   whole resolution in `asyncio.wait_for` so telemetry can never add more than a
   few seconds to turn start.
3. **Commit messages reference private patches.** Commit 1 ends with
   "Not upstream yet: needs the telemetry-attribution patch..." plus a
   "(cherry picked from ...)" line; commit 2 ends with "Not upstream yet: the
   session fallback needs the session-telemetry patch...". Reword for the PR:
   drop both trailers and the cherry-pick line; say "`enduser.id` (#10794)"
   where commit 1 talks about the user attribute. Authorship stays as is.
4. **Lint under upstream's ruff config** (found by `pre-commit`): two unused
   `# noqa: BLE001` in `session_telemetry.py` (commit 1) and `str | None | object`
   → `str | object | None` in `tracing.py` (commit 2). Folded into the owning
   commits on the branch with autosquash fixups (authors unchanged).

## Should fix

- **Per-turn cost is unbounded by caching.** Each turn does, sequentially and
  before the harness sees the message: `GET /v1/sessions/{id}` +
  `GET /v1/projects/{id}` (when filed in a project) + `git rev-parse` in a
  thread (when the session records no `git_branch`). The runner's existing
  `_session_snapshot` is cached per session, so the new session GET is purely
  additional. Cheap options: cache the project name per `project_id` (projects
  rarely rename; drop on session cleanup like `_session_telemetry_local_attributes`),
  or have `SessionResponse` carry `project_name` so the second call goes away.
  Re-reading the session itself each turn is justified (renames, label edits,
  `/model`), and the message says so; say it in the `resolve_session_attributes`
  docstring too.
- **Docs are missing for commit 1.** It adds no documentation (the stat in the
  hand-off was wrong: `designs/OBSERVABILITY.md` is only touched by commit 2).
  Section 14 of OBSERVABILITY.md then refers to "the other session attributes"
  that are documented nowhere. Add a table of the session attributes with
  source and gate to OBSERVABILITY.md (section 8's config table at ~L297 for the
  `OMNIGENT_OTEL_CAPTURE_CONTENT` title gate; section 13 lists
  `session.id` / `omnigent.skill.active` as the ambient-attribute examples and
  should name `session_attributes_scope`). The issue draft's table can be
  pasted in.
- **PII posture, documented rather than gated.** The title gate is right
  (titles are generated from the first message). Labels, project name,
  workspace path (can embed a username: `/home/alice/...`) and git remote are
  metadata, and labels are the classification keys the feature exists for, so
  gating them behind `OMNIGENT_OTEL_CAPTURE_CONTENT` would defeat it. Do say in
  the docs that labels are exported as-is (keys become attribute names, values
  free text) so operators know. An allowlist (`OMNIGENT_OTEL_SESSION_LABELS=team,priority`)
  is a reasonable follow-up if maintainers ask; not needed for v1. Note the
  gate is evaluated in the runner process (`session_metadata_attributes`), not
  in the span processor: the harness stamps whatever the runner sent.
- **Reuse.** `_git_output` duplicates `omnigent/runner/github_resource._git`
  (`_run` with a configurable timeout). Either import it or move the two-line
  helper somewhere shared. `_SESSION_METADATA_PARAMS` is imported from the
  private `omnigent.runner.native.orchestration`; `omnigent.runner.native`
  re-exports it (app.py does the private import too, so minor).
  `socket.gethostname()` is acceptable for the runner (it has no view of the
  host's configured identity name from `omnigent/host/identity.py`); say so in
  the docstring.
- **`session_model()` infers "observed" from `llm_model != configured_model`.**
  Matches the server's normal order (`routes/_sessions/orchestration.py`
  ~L13432-13466: spec model, replaced by `reported_model`), but in the
  sandbox-inference branch an unreported session returns
  `model_override or catalog default_model`, which the runner then labels
  `observed`. Either accept and document that `omnigent.session.model.source`
  is inferred, or have the server expose `reported_model` on the response so
  the runner reads the fact instead of inferring it.
- **`_SAME_AS_MODEL` sentinel in `start_agent_span`.** The adapter is the only
  production caller; making `request_model` an explicit keyword (no sentinel,
  `str | None`) and updating the semconv tests is simpler than the
  `str | object | None` typing. Minor.
- **Naming** follows the existing `omnigent.<area>.<leaf>` convention
  (`omnigent.runner.id`, `omnigent.skill.active`); `gen_ai.request.model` /
  `gen_ai.response.model` are real semconv keys used per spec. The one overlap:
  `omnigent.agent.model` (every span) and `gen_ai.request.model` (agent span)
  carry the same value on default-model turns; fine, but document that
  `omnigent.agent.model` is the configured default and `gen_ai.request.model`
  is what this turn asked for. Also `omnigent.reasoning_effort` (turn) vs
  `omnigent.session.reasoning_effort` (session) is clear once documented.

## Split?

Yes. Commit 2 is two changes with different dependencies:

- **(a) "record the model and effort a turn actually ran with"**, standalone:
  `inner/tracing.py` (`set_turn_model`, `set_turn_reasoning_effort`,
  `set_requested_turn_settings` without the session branch,
  `set_observed_turn_settings`, `request_model` on `start_agent_span`),
  `inner/executor.py` (`TurnComplete.reasoning_effort`), `inner/codex_executor.py`,
  the adapter minus the `session_attributes` lines, OBSERVABILITY §14 minus the
  session paragraph, `docs/databricks.md`; tests: `test_tracing_genai_semconv.py`,
  `test_codex_executor.py`, adapter cases `default-model-observed`,
  `model-unknowable`, `requested`, `default-effort-observed`, `default-effort-unreported`.
  This applies to `upstream/main` on its own and could be its own PR.
- **(b) "fall back to the session's model and effort"**, needs commit 1:
  `session_telemetry.session_model` + the four `AGENT_MODEL` / `SESSION_*`
  attributes, `app.py` `configured_model` plumbing, the adapter's
  `session_attributes.get(AGENT_MODEL)` fallback and session branch of
  `set_requested_turn_settings`, the session paragraph in §14; tests:
  `test_session_model_tells_reports_from_requests_and_defaults`, the
  `resolve_session_attributes` additions, adapter case `default-model-unreported`.

Either ship (a) as a separate small PR first (it changes `gen_ai.request.model`
behaviour for default-model turns, worth its own review) and keep commit 1 +
(b) here, or keep one PR with three commits in the order 1, (a), (b).
`feat/span-resolved-model` (6957ccd7d) already exists but sits on the whole
`custom` stack, so it is not a clean cut of (a).

## Tests

Run in the worktree (`uv sync --frozen --extra all --group test --group lint`),
`OMNIGENT_*`/`RUNNER_SERVER_URL` unset:

- `tests/runtime/test_telemetry.py tests/runner/test_session_telemetry.py
  tests/runtime/harnesses/test_executor_adapter_skill.py
  tests/inner/test_tracing_genai_semconv.py tests/inner/test_codex_executor.py`:
  339 passed, 4 skipped, 11 subtests passed (71 s).
- `tests/runner/test_app_sessions_native_workflow_messages.py`: 32 passed.
- `uvx pre-commit run --files <16 changed files>`: all hooks pass after the two
  ruff auto-fixes (see Must fix 4); pyrefly passes.

Coverage is at the right layers (projection and git helpers as pure unit tests,
span processor in `test_telemetry.py`, adapter matrix with the in-memory
exporter, one runner-app test for the hand-off). Gaps to add with the fixes:
credential stripping in `git_remote_url`, the lookup timeout, and a
`session_attributes_scope` test for an empty mapping. The git test spawns real
`git` (skipped when absent) which is acceptable.

## Standalone?

Yes. Cherry-picking 0b76c20be straight onto `upstream/main` conflicts only in
`omnigent/runtime/telemetry.py` and `tests/runtime/test_telemetry.py`, and both
are adjacency: the hunks sit next to the attribution patch's
`_make_user_id_processor` / `_make_runner_id_processor` and their tests. Keeping
only the session-attributes processor and test resolves it; 66e01188a then
applies clean. The probe (a throwaway detached worktree, since removed; head 9dfbf5f3d) carried
zero attribution code (`git diff upstream/main | grep -c enduser` = 0). The
only real tie to #10794 is the sentence in commit 1's message about
`enduser.id`, so the series can be proposed without waiting on the attribution
PR; reference #10794 as related instead of stacking.
