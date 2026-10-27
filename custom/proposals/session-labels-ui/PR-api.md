<!-- Title: feat(server): delete session labels with null and default labels per project -->
<!-- Branch: feat/session-labels-api (one commit on upstream/main) -->
## Related issue

Closes #<to be filed> (drafted in `issue-session-labels.md`)

Partially addresses #8689: the `UpdateSessionRequest.labels` docstring and the regenerated `openapi.json` now say that a labels PATCH merges, that unmentioned keys stay, and that `null` deletes a key.

## Summary

A session's labels (`team: ml`) are the one place to put your own metadata on a session, but a label could not be removed again, and a project could not give its sessions a starting set.

- `PATCH /v1/sessions/{id}` deletes a label whose value is `null`. Reserved and `cost_control.*` keys are rejected for a delete exactly as for a set; the empty-string clear for `omni_project` and the caller's pin key is unchanged, and both take `null` too. An empty or over-width key (the column is 128 characters) is a 400 instead of a database error on PostgreSQL.
- Creating a session in a project merges the project's `config.labels` under the request's labels (the request wins), next to the `agent_id`, `workspace` and `git` defaults the resolver already applies, so API, automation and import creates get them too. Internal, over-length and non-string entries in the config are skipped (the config is opaque client JSON and stays unvalidated on write; the `ProjectObject.config` docstring says so). A `null` request value leaves that default off the new session, mirroring the PATCH delete; a `null` for any other key is ignored and a reserved key is rejected either way. Defaults apply at creation only; moving a session into a project later adds none.
- `is_internal_label_key` in `omnigent.stores.conversation_store` is now the one definition of Omnigent-owned label keys (`omni_project`, `omnigent.*`, `cost_control.*`), for the server and for clients to mirror.
- `omnigent/server/API.md` documents deleting a label with `null` and a project's default labels on create.

Follow-up for the Python client (#8689, #10418): `SessionsNamespace.set_labels` is typed `dict[str, str]` and its docstring describes the old empty-string behaviour; it can be widened to `dict[str, str | None]` (or gain `delete_label`) once this lands. I can send that PR.

A web UI for labels (info popover editor, project "Default labels", composer "+" > Labels) is stacked on this branch as a separate PR.

## Test Plan

Tests added or changed:

- `tests/server/routes/test_sessions_crud.py`: `null` deletes a label while the rest of the PATCH upserts; `null` for a reserved key is rejected and the stored value survives; `omni_project` and the pin clear with `""` or `null`; empty and 129-character keys are a 400 before any write.
- `tests/server/routes/test_sessions_cost_labels.py`: an editor cannot delete `cost_control.plan`; ordinary set and delete in one PATCH still work.
- `tests/server/routes/test_session_create_project_consistency.py`: project defaults fill in under the request's labels (request wins, malformed and internal entries skipped); `null` leaves a default off, with and without a project; `null` for a reserved key on create is a 400; malformed `config.labels` shapes are ignored; the multipart (bundle) and import paths get the defaults.
- `tests/stores/test_conversation_labels.py`: `is_internal_label_key`.

```sh
uv run pytest tests/server/routes/test_sessions_crud.py tests/server/routes/test_sessions_cost_labels.py \
  tests/server/routes/test_session_create_project_consistency.py tests/stores/test_conversation_labels.py
uv run python scripts/dump_openapi.py --check
```

116 passed; `openapi.json` is up to date; `pre-commit run --files <changed>` passes.

Manual:

1. `curl -X PATCH $SERVER/v1/sessions/<id> -H 'Content-Type: application/json' -d '{"labels": {"team": "ml"}}'`, then `-d '{"labels": {"team": null}}'`: the response and `GET /v1/sessions/<id>` no longer list `team`.
2. `-d '{"labels": {"omnigent.archived_at": null}}'` is a 400 and the label is unchanged.
3. `PATCH /v1/projects/<id>` with `{"config": {"labels": {"cost_center": "research"}}}`, then `POST /v1/sessions` with `{"project_id": "<id>", ...}`: the new session has `cost_center: research`; with `"labels": {"cost_center": null}` it has not.
4. Move an existing session into the project (`PATCH` with `project_id`): it gains no labels.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

The route tests above exercise each new behaviour through the HTTP API; the curl steps in Test Plan reproduce them by hand.

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

Route tests run the JSON, multipart and import create paths and the PATCH path against the in-memory store; no browser or E2E layer is involved in this change.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Delete a session label by setting it to `null` in `PATCH /v1/sessions/{id}`, and give a project default labels (`config.labels`) that its new sessions receive

🤖 Generated with [Claude Code](https://claude.com/claude-code)
