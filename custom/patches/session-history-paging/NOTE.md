# session-history-paging

Needs: none
Covers: 242785f4a50c6bc1

Agents can list sessions by recent activity, and page through a session's
whole history, forward from the start or from a saved cursor.

- **Turn on:** on by default; new optional arguments on `sys_session_list`
  (`updated_after`, `order_by`) and `sys_session_get_history`, and
  `updated_after` on `GET /v1/sessions`. The older `ownership` argument is an
  alias of upstream's `visibility` until 0.24.0.
- **Docs:** [Agent YAML spec](../AGENT_YAML_SPEC.md) (session read tools) and
  `omnigent/server/API.md` (List Sessions).
- **Upstream:** not proposed yet: the feature request is not opened and there
  is no pull request. It is prepared on `feat/session-history-paging`.

## Must hold

- `sys_session_list` accepts `updated_after` (ISO-8601; no offset means UTC) and `order_by` (`created`, the default, or `updated`) for its `sessions` list, and each row reports `created_at` and `updated_at`; an invalid value is rejected before any server request.
- `GET /v1/sessions` accepts `updated_after` (Unix epoch seconds) and returns only sessions whose `updated_at` is strictly later, on every read of a page it re-reads wider past hidden side chats.
- The older `ownership` argument (`any`, `mine`, `shared`) stays an alias of `visibility` (`any` is `all`) until 0.24.0; an `ownership` that disagrees with an explicit `visibility` is an error.
- `sys_session_get_history` with `order: "asc"` reads forward from the first item, and `after` (a `next_cursor` from an earlier read) resumes just after that item; `after` alone implies `asc`, and `after` with `order: "desc"` is an error.
- History results carry `next_cursor` and `has_more`, plus `has_older` on a most-recent read; a cursor that no longer resolves returns `invalid_cursor`, distinct from `session_not_found`.
- With none of the new arguments both tools behave as before: the same list query, a most-recent history read, and the `tail_items` cap and character budget unchanged.

## Key code

- `omnigent/runner/tool_dispatch.py`: `_parse_session_list_recency`, `_SESSION_LIST_OWNERSHIP_VISIBILITY`, `_session_get_history_via_rest`, `_session_exists`
- `omnigent/tools/builtins/spawn.py`: `_parse_history_window`, `_history_page_fields`, `SysSessionGetHistoryTool`, `SysSessionListTool`
- `omnigent/stores/conversation_store/sqlalchemy_store.py`: `updated_after`
- `omnigent/server/routes/sessions/routes_core.py`: `updated_after`

## Tests

- `tests/runner/test_runner_dispatch.py::test_session_history_forward_page_uses_items_cursor`
- `tests/runner/test_runner_dispatch.py::test_session_history_distinguishes_bad_cursor_from_missing_session`
- `tests/runner/test_runner_dispatch.py::test_session_list_forwards_activity_filters_and_reports_timestamps`
- `tests/tools/builtins/test_sys_session.py::test_peek_forward_paging_walks_whole_session`
- `tests/stores/test_conversation_store.py::test_list_conversations_updated_after_is_exclusive`
- `tests/server/routes/test_sessions_crud.py::test_list_sessions_side_chat_reread_keeps_updated_after`
