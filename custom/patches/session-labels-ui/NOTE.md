# session-labels-ui

Needs: none
Covers: 5215bd827299dae1

View and edit a session's labels in the web UI, delete labels through the API
(a `null` value), and give projects default labels for the sessions created in
them; a `null` label on create leaves that project default off.

- **Turn on:** on by default; the Labels section of the session info popover,
  Project settings → **Default labels**, and the new-session composer's **+**
  menu → Labels.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`labels`) and
  `omnigent/server/API.md` (Create From Existing Agent, Bind Session Runner).
- **Upstream:** proposed from `feat/session-labels-api` and
  `feat/session-labels-ui`.

## Must hold

- `PATCH /v1/sessions/{id}` with a `null` label value deletes that label; the deletes and upserts of one PATCH apply in one store transaction, so a failed upsert leaves the deleted labels in place.
- Reserved and `cost_control.*` keys are rejected for a delete (and for a `null` on create) exactly as for a set; the empty-string clear of `omni_project` and the pin key still works, and `null` clears them too.
- An empty label key or one over 128 characters gets a 400 before any write.
- A session created in a project (imports included) gets the project's `config.labels` under the request's labels, and the request wins; internal, over-length and non-string defaults are skipped. Labels apply only at creation, not when a session moves into a project later.
- A `null` label on create leaves that project default off the new session; with no project or no such default it is ignored.
- The info popover, Project settings and the new-session composer share one label editor: internal labels (`omnigent.*`, `cost_control.*`, `omni_project`) stay hidden, a viewer without edit access gets no controls, and a project default removed in the composer is sent as `null`.

## Key code

- `omnigent/server/routes/_session_create_validation.py`: `project_default_labels`, `create_labels`
- `omnigent/server/routes/sessions/routes_core.py`: `_reject_malformed_label_keys`, `labels_to_delete`
- `omnigent/stores/conversation_store/sqlalchemy_store.py`: `set_labels`, `delete_keys`
- `web/src/components/LabelEditor.tsx`: `LabelEditor`
- `web/src/lib/sessionLabels.ts`: `newSessionLabels`, `projectDefaultLabels`, `isInternalLabelKey`

## Tests

- `tests/server/routes/test_sessions_crud.py::test_patch_session_null_label_deletes_it`
- `tests/server/routes/test_sessions_crud.py::test_patch_session_mixed_label_edit_is_atomic`
- `tests/server/routes/test_session_create_project_consistency.py::test_null_request_label_leaves_project_default_off`
- `web/src/components/AgentInfo.test.tsx`
- `web/src/shell/NewChatDialog.projectCreate.test.tsx`
