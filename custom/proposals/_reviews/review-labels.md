# Review: session-labels-ui and gateway-request-tags (standalone on upstream/main 39611f812)

Branches (local only, nothing pushed, `custom`/`main` untouched):

- `feat/session-labels-ui` → `0d20b8a26` in `~/repos/omnigent-wt/feat/session-labels-ui`
- `feat/gateway-request-tags` → `71cbad2bb` in `~/repos/omnigent-wt/feat/gateway-request-tags`

Both worktrees already existed on an older base (8e55c11bd, from a previous
attempt); they were reset to the current `upstream/main` and the series
re-applied from `omnigent-patches/patches/` with `git am -3 -s`.

Verification run on each branch: `uv run --no-sync python -c "import omnigent.server.app"`,
`tsc -b` (session-labels-ui), the tests each patch touches, and
`pre-commit run --files <changed>`; all green (details per series).

---

## session-labels-ui

### Standalone? Yes, with a hand resolution (incidental only)

`git am -3` conflicted in two files, both because the patch was cut from
`custom` where `subscription-accounts` adds a `provider` field next to the
new `labels` field:

- `web/src/lib/projectsApi.ts`: dropped the `provider?: string` member and its
  doc comment; kept `labels?: Record<string, string>`.
- `web/src/shell/ProjectSettingsDialog.tsx`: dropped the `provider` state,
  `setProvider(...)`, the `config.provider` save lines, and the whole
  `<Field label="Account">` block (`accountOptions`, `accountHint`,
  `unlistedProviders` do not exist upstream); kept the `labels` state, the
  dirty/discard warning, the scroll wrapper and the Default labels editor.

No symbol from `subscription-accounts` is used; the `needs:` line in
`patches/series` is apply-order only. The server side applied cleanly.

Result: `tsc -b` clean; vitest 6 files / 819 tests pass; pytest
`test_sessions_crud.py test_sessions_cost_labels.py
test_session_create_project_consistency.py` 85 passed;
`scripts/dump_openapi.py --check` reports `openapi.json` up to date;
pre-commit (ruff, pyrefly, prettier, oxlint, tsc, project lint) passes.

### Verdict

Mergeable in substance, but too big for one PR and carries two things
maintainers will object to. Split it; the server half is an easy accept.

### Must fix

1. **Split into at least two PRs.** (a) Server: `null` deletes a label on
   `PATCH /v1/sessions/{id}` + project `config.labels` defaults at create
   (+ `apply_project_labels`) + `openapi.json`. (b) Web: popover editor,
   project-settings editor, composer "+" > Labels. The 29-file / ~2,100-line
   diff mixes an API change, three UI surfaces and a layout refactor; the
   repo's PR template wants one reviewable change with a demo.
2. **Drop the `ProjectSettingsDialog.tsx` re-indent.** `git diff -w` shows the
   real change is 76+/3-; the other ~400 lines are whitespace from wrapping
   the form in a scroll container. That file also collides with open #5194
   (viewport cap for the same dialog, maintainer-scoped "dialog
   responsiveness" layer in `DialogContent`). Either leave the height cap to
   #5194 and keep the labels editor as a plain `<Field>` sibling, or make the
   cap a one-line className change without restructuring the form.
3. **Commit message hygiene.** Both patch files carry
   `(cherry picked from commit …)` and a duplicated `Signed-off-by`; the
   `custom`-only "Depends on: subscription-accounts" line in `PR.md` is now
   false. Remove before filing.
4. **One Python definition of "internal label".**
   `_session_create_validation.py` adds `_INTERNAL_LABEL_PREFIXES` /
   `project_default_labels`, and the gateway series adds
   `_is_internal_label_key` in `databricks_ai_gateway.py`, plus
   `isInternalLabelKey` in `web/src/lib/sessionLabels.ts`. Upstream has no
   such helper today (grep for `INTERNAL_LABEL` is empty), so whichever PR
   lands first should add one shared predicate (e.g. next to
   `PROJECT_LABEL_KEY` in `omnigent/stores/conversation_store/__init__.py`,
   which is import-light) and the other reuse it. Repo `CLAUDE.md`: reuse
   helpers, no duplication.

### Should fix

- **`apply_project_labels: false` is an awkward API.** The composer sends the
  remaining defaults itself plus a flag that means "don't merge". A reviewer
  will ask why create can't take `labels: {team: null}` (mirroring the new
  PATCH semantics: null = leave this default off) instead of a second field
  on `_SessionCreateRequestBase` and `SessionCreateMetadata`. That would also
  make the client not need to know the merge rule. If the flag stays, say in
  the docstring that it is only meaningful with `project_id`.
- **Project `config.labels` is never validated on write.** Only read-side
  filtering (`project_default_labels`). Fine because the config is opaque
  JSON, but a maintainer may want the project PATCH to reject bad shapes
  rather than silently drop them at create. At minimum say so in
  `docs/` for the project config.
- `LABEL_KEY_MAX_LEN = 128` is introduced in `db_models.py` and used for
  validation; the server's PATCH path still does not enforce key length (the
  DB raises `DataError` on Postgres). Validate in `UpdateSessionRequest`
  (`Field(max_length=…)` on keys is not possible; a validator) so the UI
  limits are not the only guard.
- Import path: `imports.py` now spreads `resolved_create.body.labels` under
  the native agent's presentation labels. Verify `ImportSessionRequest` has
  `labels` in `model_fields` (otherwise the `"labels" in
  body.__class__.model_fields` guard means imports silently get none; the
  test `test_import_with_project_defaults_workspace_and_files_session`
  passes, so it does today — keep that test).
- `useNewSessionLabels` drops removed-default edits when `projectName`
  changes but keeps added labels; document that in the hook (a user who
  switches project keeps `ticket: 42`, loses the removal of `team`).
- `AgentInfo.tsx`: `isEditorLevel(permissionLevel)` gates the controls, but
  the PATCH will be rejected server-side for viewers anyway; good. The section
  is hidden for read-only viewers with zero labels — fine, but say so in
  `feature-map/sessions.md` (it says "a view-only collaborator sees the
  labels without controls").

### Tests

Right layers: route tests for delete/reserved/project-merge (including
multipart and import), component tests for the three editors, pure
unit tests for `sessionLabels.ts` and the cache overlay. No E2E, which is
acceptable; the manual steps in `PR.md` are concrete. Minor: the
`test_patch_rejects_deleting_server_reserved_label` parametrisation covers
`omnigent.*` keys; add one `omni_project` / pinned case for the
empty-string-vs-null symmetry (there is one for `omni_project` in
`test_patch_session_empty_project_removes_label`, none for the pin).

### Drift between proposals and patch

- `issue.md` describes three things (popover, API delete, project defaults).
  The patch also adds the composer "+" > Labels editor, `apply_project_labels`,
  the dialog viewport cap and the unsaved-changes warning; `PR.md` has them
  but the issue should too, or the PR should drop them.
- `PR.md` "Depends on: subscription-accounts (stacked…)" is wrong after this
  resolution.
- `PR.md` Demo section is all TODO; a UI PR without media will be bounced.
- `PR.md` says "Upstream PR #5194 targets the same problem; whichever lands
  first, the other can drop its copy" — #5194 is a large maintainer-side
  branch (90+ files) that moves the fix into `DialogContent`; our copy will
  not "drop", it will conflict. See Must fix 2.

### Overlap with #8689 and its PRs #8719 / #10418

Both PRs are from `app/omni-resolve-agent` (bot), both open, #10418
"Supersedes #8719". They touch only `sdks/python-client/**` and
`tests/frontends/sdk/**`: a typed `Session` with cost/lineage fields,
`SessionsNamespace.set_labels(session_id, labels: dict[str, str])`,
`delete(session_id, delete_branch=False)`, `info()`, `usage()`,
`list_hosts()`, and a URL-segment confinement helper. Neither adds label
deletion on the server; `set_labels` documents the current server behaviour
verbatim: "PATCH upserts, so labels merge, unmentioned keys stay, and an
empty string is stored rather than removing the key". So our server half
does not duplicate them; it changes the semantics they document. Two
consequences:

- When our `null`-deletes PR lands, #10418's `set_labels` type
  (`dict[str, str]`) and docstring become stale; mention #8689/#10418 in
  the PR so the client can be widened to `dict[str, str | None]` (or gain
  `delete_label`). That is the natural hook for the "I can send a PR"
  sentence in `issue.md`.
- #8689's ask "document whether a labels patch merges or replaces" is
  answered by our `UpdateSessionRequest` docstring change and the
  regenerated `openapi.json`; cite it as partially addressed, not closed.

### Fit

Labels already exist in the data model, are seeded from agent YAML, read by
policies and cost telemetry, and are the only user metadata on a session.
Exposing them in the UI and fixing the "cannot delete a label" API gap is a
real hole (#8689 independently asks for client label updates and merge
semantics documentation). #2117 (btli, closed July) scoped multi-valued
`conversation_tags` as an internal design and was closed in five minutes;
nothing in it conflicts with editing single-valued labels, but a maintainer
may still ask "is this the tags feature?" — the issue text pre-empts that
correctly. Project default labels are a natural pairing with the project
defaults that already exist (`agent_id`, `workspace`, `git`).

Expect push-back on: PR size, the dialog refactor vs #5194, the extra create
flag, and (mildly) adding a fourth place where the composer collects state.
Churn is moderate: `routes_core.py`, `NewChatDialog.tsx` and
`ProjectSettingsDialog.tsx` all moved several times since mid-September
(`ac1a7a95f`, `3021efcbe`, `87475559d`), so land the server half quickly and
rebase the web half.

### Route

- Server half: file the feature issue (trimmed to the three items) and open
  the PR now; cite #8689. Small, tested, `openapi.json` regenerated.
- Web half: PR after the server half merges, without the re-indent, with
  recordings. Keep the composer "+" > Labels in it only if the issue mentions
  it; otherwise a third PR.
- Nothing here needs the blocked `subscription-accounts` series.

---

## gateway-request-tags

### Standalone? Yes, with a one-hunk test resolution (incidental only)

The only conflict was in
`tests/runner/test_app_sessions_native_terminals_runtime.py`: the patch's
context asserted `developer_instructions` ends with `ITEM_LABEL_INSTRUCTION`
(from `chat-item-labels`). Resolved by keeping upstream's assertion and adding
only the new `build_calls[0]["session_labels"]["team"] == "ml"` line. No
`chat-item-labels` symbol is used anywhere in the code; `needs:
chat-item-labels` is apply-order only.

Result: import ok; pytest on the ten touched files/selections: 517 + 86 + 43
passed, 1 skipped; pre-commit passes.

### Does it build on #10410, not beside it?

Yes. Same module (`omnigent/databricks_ai_gateway.py`), same
`is_databricks_ai_gateway_url` gate, and the header is added in the same
spots #10410 stamps attribution: `with_gateway_attribution_lines` →
`with_gateway_request_tags_line` on the `ANTHROPIC_CUSTOM_HEADERS` block
(claude-sdk `_resolve_gateway_env`, claude-native launch), the provider
`http_headers` block in `materialize_codex_provider_config` (codex, via
`env_http_headers`), and `_build_models_json` (pi). claude-native applies it
as a launch-time wrapper (`claude_config_with_gateway_request_tags`) over the
config #10410 built, which is unavoidable because the session is unknown
when the provider config is built.

Two gaps relative to #10410's coverage:

- **pi-native and opencode-native** are stamped by #10410
  (`pi_native/credentials.py`, `opencode_native/provider.py`) but get no tags
  here. The issue text says "later"; a maintainer will ask why, since
  `with_gateway_attribution` is the shared funnel for both.
- **#11118 (open, yaoharry)** rewrites `with_gateway_attribution_lines` to
  merge/dedupe headers case-insensitively and makes repeated passes
  idempotent. `with_gateway_request_tags_line` just appends, and
  `claude_config_with_gateway_request_tags` falls back to
  `os.environ[ANTHROPIC_CUSTOM_HEADERS]`, so an `omnigent claude` started
  inside a tagged process can end up with two `Request-Tags` lines. Build on
  #11118's merge helper once it lands (it also touches the signer and shim).

### Overlap with yaoharry's open PRs #11118 / #11099 and merged #11226

Read via `gh pr view` / `gh pr diff` (no search).

**(1) Conflict or duplication?** No duplication: neither PR sends a
per-request/per-session tag; both only carry the two static
`Databricks-Custom-*` attribution headers. Textual conflicts, yes, in three
places, all adjacent-hunk:

- `omnigent/databricks_ai_gateway.py`: #11118 rewrites
  `gateway_attribution_headers` / `with_gateway_attribution` /
  `with_gateway_attribution_lines` (case-insensitive merge, dedupe, replace
  stale fields, idempotent on repeated passes). Our new functions are appended
  after them, so `git am -3` will cope, but our
  `with_gateway_request_tags_line` is a plain append and should be rewritten
  on top of #11118's merge logic so a second pass does not add a second
  `Request-Tags` line.
- `omnigent/inner/claude_sdk_executor.py::_resolve_gateway_env`: #11118
  restructures the function (generic-provider branch, folds
  `os.environ[ANTHROPIC_CUSTOM_HEADERS]` into the attribution call); our
  tags block sits immediately after that call. Will conflict; trivial to
  re-place.
- `omnigent/inner/codex_executor.py::materialize_codex_provider_config`:
  #11118 adds managed-config providers (`/etc/codex/managed_config.toml`) and
  `include_managed_config`, and rewrites the `http_headers` line where our
  `env_http_headers` block sits. Will conflict; trivial to re-place. Note that
  #11118 deliberately adds a *partial* table for managed providers ("Codex
  still owns routing and auth"); adding `env_http_headers` to those tables
  is fine (metadata only), but say so.
- #11118 also adds attribution inside `claude_gateway_shim.py` (the SDK
  proxy) using `with_gateway_attribution(dict(headers), …)`; the shim
  forwards all non-hop-by-hop request headers, so the tags header Claude
  Code sends passes through untouched. No change needed, but a shim test
  asserting that would close the question.
- #11099 (signer `extra_headers`, ucode binding only) and the signer part of
  #11118 append fixed headers from the signer config and drop client copies
  of *those* names only. `_validate_headers` rejects a fixed denylist, so a
  client-sent `Databricks-Ai-Gateway-Request-Tags` is forwarded. The tags
  therefore survive signer-backed Codex; but #11099 sets
  `include_managed_config=self._signer is None`, so for signer workers only
  the generated provider is materialised. Our `env_http_headers` is added to
  every gateway provider, including the generated one, so signer-backed Codex
  still sends tags. One signer test would prove it.
- #11226 (merged 2026-10-21, "Route native Codex's Databricks gateway and
  auth through ucode state") touched `codex_native/app_server.py`; the
  patch applied cleanly on top of it and the launch-config tests pass, so no
  residual conflict.

**(2) Rebase on #11118 once it merges?** Yes. It is a maintainer PR
explicitly framed as the follow-up to #10410 and it owns the three helpers
we extend; landing before it would force yaoharry to rebase around our
append-only helper and then we would have to redo it anyway. Also adopt its
merge/dedupe style for the tags line (idempotent, case-insensitive name
match). Independent of #11099 (signer only).

**(3) Does on-by-default label sending survive their direction?** The
session id does; the labels need an opt-in or a namespace. Evidence from
their PRs: every value they send is fixed and process-owned ("The values are
fixed in the signer, not taken from the client, so a sandboxed worker can't
spoof them" — #11099; #11118 strips client-sent copies of the attribution
headers before re-stamping). Their stated goal is that the gateway can trust
what Omnigent claims about itself. Free-text labels written by any session
editor, sent under raw keys that gateway policies can match
(`event:context.request_tags`), cut against that: a collaborator can make
another user's requests carry `team=finance`. So: keep
`omnigent_session_id` default-on (it is as trustworthy as the attribution
headers: runner-owned, read from the init envelope), and either prefix labels
(`omnigent_label_*`) or gate them behind an explicit switch
(`OMNIGENT_GATEWAY_REQUEST_TAGS=labels`). Ask in the issue which they
prefer; I would propose the prefix with default-on since it removes the
policy collision without losing the join.

### Verdict

Technically sound and well-tested; the header path is right. The open
question is policy, not code: labels are free text written by any editor of
the session, and the gateway treats tags as policy inputs. Needs a
maintainer decision on default-on before it is worth polishing.

### Must fix

1. **Decide and document who controls the tag namespace.** Databricks' docs
   (fetched: `/aws/en/ai-gateway/request-tagging`) say service policies can
   evaluate `event:context.request_tags`, e.g. "require tag X to allow". With
   this patch any session editor (not just the owner) can set `team=…` and
   have it reach a gateway policy running under the launching user's token.
   Options a maintainer will accept: prefix user labels
   (`omnigent_label_<key>` or `omnigent.label.<key>`), or send only
   `omnigent_session_id` by default and make labels opt-in
   (`OMNIGENT_GATEWAY_REQUEST_TAGS=labels`). The issue already offers
   opt-in; pick the prefix instead, it keeps joins trivial and removes the
   collision with org-defined tags like `project`/`team`.
2. **Reuse one internal-label predicate** (see session-labels-ui Must fix 4).
   `_is_internal_label_key` here and `_INTERNAL_LABEL_PREFIXES` there are the
   same rule in two modules; the gateway one lazily imports
   `omnigent.stores.conversation_store` and `omnigent.util.cost_plan` into the
   runner/harness process just to read two constants.
3. **Commit message hygiene** as above (`cherry picked from`, duplicate
   `Signed-off-by`, stale "Depends on: chat-item-labels" in `PR.md`).

### Should fix

- **Cover pi-native and opencode-native** or state in the PR why they are
  out (they write provider files per host, not per session; the env-var
  hand-off used for pi/codex does not reach them). Without that the matrix
  in `docs/databricks.md` is inconsistent with #10410's.
- **Idempotent append**: replace an existing `Databricks-Ai-Gateway-Request-Tags`
  line rather than appending (`with_gateway_request_tags_line`), matching
  #11118's direction.
- **Size cap rationale.** Databricks publishes no limit; 8 KiB is a guess
  ("well under common proxy header-size limits"). Node's default
  `--max-http-header-size` is 16 KiB for the whole header block and Claude
  Code also carries `anthropic-beta` and auth headers, so 8 KiB is on the
  high side. 2–4 KiB with the same drop-in-key-order rule is safer; say which
  limit the number is derived from.
- `gateway_request_tags` drops a label that would overflow but continues
  scanning later (shorter) keys, so the dropped set is not a prefix of the
  sorted keys. Deterministic, but "dropped in key order" in the docs reads as
  a prefix cut. Either stop at the first overflow or document the behaviour.
- The signer path (`model_signing.py`) only rejects a fixed set of headers, so
  the tags header passes through for signer-backed Codex; worth one test
  since #11099 adds signer-side attribution and a reviewer will ask.
- `claude_config_with_gateway_request_tags` only looks at
  `claude_config.env[ANTHROPIC_BASE_URL]`; a user whose own environment
  points `ANTHROPIC_BASE_URL` at a gateway with `claude_config=None` gets no
  tags. Acceptable (matches #10410's "known limitation 1"), but list it.
- `docs/databricks.md` "Covered harnesses" line should name the uncovered
  ones explicitly.

### Tests

Lowest layer throughout: builder/cap/switch in
`tests/test_databricks_ai_gateway.py`; per-harness wiring in the executor
tests with the env stubbed; runner hand-off in `test_runner_dispatch.py` with
`httpx.MockTransport` (fetch only when labels are not in the envelope and the
harness can reach a gateway). Good. Missing: a test that a non-ASCII or
`$`-containing label survives the pi `$$` escape end to end (the pi test
asserts the escaped string only), and the idempotency case above.

### Drift between proposals and patch

- `issue.md` says Codex takes labels "the way #11000 turns a session label
  into a per-launch header"; #11000 (dbczumar) is still open, so cite it as
  the pattern, not as landed.
- `PR.md` "Depends on: chat-item-labels" is wrong after this resolution.
- `PR.md` claims `omnigent host enable` keeps the switch in the service
  definition; the patch only adds the name to `_RUNNER_ENV_ALLOWLIST` and the
  parametrised `test_release_controls_reach_daemon_and_runner` case. That
  test does cover the daemon/runner path; confirm it also covers the systemd
  unit before keeping the sentence.
- Demo section is TODO and requires a real gateway; the manual steps are
  fine, but say in Coverage notes that the usage-table row was not observed
  if that stays true.

### Fit

This is squarely "good for Databricks": #10410 and #11118/#11099 were
written at the Unity Gateway team's request to attribute Omnigent traffic,
and per-session tags are the next question that team gets ("which session
cost what"). The join key (`omnigent_session_id`) alone would likely be
accepted quickly. The label pass-through is the contentious part: it turns
user-editable session metadata into gateway policy input and ships with no
namespace, default-on. Expect a maintainer to ask for the prefix or for
labels to be opt-in, and to ask why pi-native/opencode are excluded.

Churn is high in `claude_native/main.py`, `codex_native/app_server.py`,
`runner/app.py` and `runner/native/orchestration.py` (dozens of commits since
mid-September, including #11226 "Route native Codex's Databricks gateway and
auth through ucode state" and #11321 last week). `databricks_ai_gateway.py`
itself has only #8812 and #10410, but #11118 is open against it. File the
issue now, rebase the PR after #11118 merges.

### Route

- File the feature issue now (it is the right venue to settle default-on vs
  prefix vs opt-in, and to ask whether pi-native/opencode must be in scope).
- Open the PR after #11118 lands, split as: (1) `omnigent_session_id` only,
  all harnesses #10410 covers; (2) labels pass-through with the chosen
  namespace rule. (1) is low-risk and likely to be merged fast.
- Independent of `chat-item-labels` and of `session-labels-ui` at the code
  level; the UI series only makes labels easier to set.
