<!-- Draft PR body for the session-history-paging series; title: feat(sessions): let agents page session history and find recent sessions -->

## Related issue

Closes #TODO (feature request to be opened)

## Summary

Agents that review past sessions, such as a scheduled retro, can now find what changed since their last run and read a long session from start to end, page by page.

Before this, `sys_session_list` returned sessions in creation order with no timestamps, and `sys_session_get_history` could only return the last 50 items. A long transcript couldn't be walked, and "sessions active since yesterday" couldn't be found.

- **`sys_session_list`** (global `sessions` view) gains optional `updated_after` (ISO-8601; no offset means UTC), `order_by` (`created` | `updated`) and `ownership` (`any` | `mine` | `shared`). Each row now reports `created_at`, `updated_at` (ISO-8601 UTC) and `owner`. Continuation cursors are bound to the filters, so a cursor can't be replayed under different ones. Backed by a new `updated_after` query param on `GET /v1/sessions` (strictly later than the given epoch seconds), implemented in the conversation store.
- **`sys_session_get_history`** gains `order='asc'` and an `after` item cursor, so an agent reads forward from the start or resumes from a saved position, using the existing `GET /v1/sessions/{id}/items` paging. Results carry `next_cursor` and `has_more`, plus `has_older` on a most-recent read. An unknown cursor returns `invalid_cursor`, distinct from `session_not_found`. Pending elicitations are appended only on the page that reaches the newest item.
- Defaults, the `tail_items` cap and the character budget are unchanged, so existing calls behave as before. The history path imports the database layer only when a read needs it, so host startup stays free of it.

Docs: `docs/AGENT_YAML_SPEC.md` describes the new `sys_session_list` and `sys_session_get_history` arguments, and `omnigent/server/API.md` the `updated_after` filter on `GET /v1/sessions`.

## Test Plan

```sh
uv run pytest tests/runner/test_runner_dispatch.py tests/tools/builtins/test_sys_session.py \
  tests/stores/test_conversation_store.py tests/server/integration/test_sessions_endpoints.py
```

New tests cover forward paging through a whole session, resuming from a tail-read cursor after new items arrive, telling a bad cursor from a missing session, pending elicitations deferred to the last forward page, filter validation, the legacy query staying unchanged without filters, and the exclusive `updated_after` bound in the store and on the endpoint.

Manual, on a throwaway server with a few sessions:

1. `curl -s "$SERVER/v1/sessions?updated_after=$(date -d '1 hour ago' +%s)"` returns only sessions with activity in the last hour.
2. In a session whose agent has the session tools, ask it to call `sys_session_list` with `updated_after` set to an hour ago and `order_by: "updated"`. Rows come back most recently active first, each with `created_at`, `updated_at` and `owner`.
3. Ask it to read a session with more than 50 items using `sys_session_get_history` with `order: "asc"`, then follow `next_cursor` as `after` until `has_more` is false. The pages cover every item once, oldest first.
4. Ask it to call `sys_session_get_history` with `after: "not-an-item"`. It gets `invalid_cursor`, not `session_not_found`.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: attach the tool results from manual steps 2 to 4 (a filtered `sys_session_list`, two consecutive forward pages showing `next_cursor` / `has_more`, and the `invalid_cursor` error) from a throwaway server with dummy sessions

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

Paging and filters are tested at the tool-dispatch and store layers, and `updated_after` through the HTTP endpoint in `tests/server/integration/test_sessions_endpoints.py`.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.
