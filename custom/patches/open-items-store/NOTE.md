# open-items-store

Needs: side-schemas, chat-item-labels
Covers: eac050d9e70d0988

Open items (the questions, risks, findings, follow-ups and pinned links an
agent raises) become records of their session, in the `open_items` side
store, with labels such as `Q7` that the server allocates. Agents raise, close
and list them with three `sys_open_items_*` tools and still write each item
once in chat; people read them through `/v1/sessions/{id}/open-items` and may
close, reopen, retopic or answer them. Every write publishes
`session.open_items.changed`. The web does not read the store yet: label chips
and the Open items bar still follow the chat text.

- **Turn on:** on by default; an agent opts out with `tool_groups.open_items: false`.
- **Docs:** [Open items](../open-items.md).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639.

## Must hold

- Labels are unique per session: two raises at once never get the same label, a label is never reused for another item, and a retried raise with the same tool call ID returns the labels its first attempt allocated.
- The tools only write to their own session: raises and agent updates are accepted only from the session's bound runner (source header and tunnel token), for an agent whose spec keeps the `open_items` group.
- A server or host without the series keeps text labels working: a runner keeps the tools only when the bundle download carries `X-Omnigent-Open-Items: 1`, and without the tools the agent gets the text-only item-label instruction. Nothing is backfilled.
- A link pinned without a title is named by a short form of its URL (host and the start of the path), never the whole URL.
- Agents with the tools are told to record every item, pinned links included, with `sys_open_items_raise` before writing it, with a topic.
- Agents with the tools are told that items the user closed (a comment heading ending `(closed by me)` included) stay closed unless the user asks again.
- Deleting a session removes its items and counters; forks start with none.
- Reads need read access; people's changes and answers need edit access.
- The open_items tables stay out of the main migration chain, and a build without the series starts against a database that holds them.

## Key code

- `omnigent/stores/open_items_store.py`: `OpenItemsStore`, `delete_open_items_batch`, `OPEN_ITEMS_SIDE_STORE`
- `omnigent/stores/open_items_migrations/open_items0001_create_tables.py`
- `omnigent/entities/open_items.py`: `normalize_new_item`, `normalize_change`, `page_items`
- `omnigent/server/open_items.py`: `create_open_items_router`, `open_store`
- `omnigent/runner/open_items_tools.py`: `execute_open_items_tool`
- `omnigent/tools/builtins/open_items.py`: `SysOpenItemsRaiseTool`, `SysOpenItemsUpdateTool`, `SysOpenItemsListTool`
- `omnigent/open_items_availability.py`: `OPEN_ITEMS_HEADER`, `without_open_items_tools`
- `omnigent/runtime/prompt.py`: `OPEN_ITEMS_INSTRUCTION`
- `omnigent/runner/tool_dispatch.py`: `_OPEN_ITEMS_TOOLS`

## Tests

- `tests/stores/test_open_items_store.py`
- `tests/server/routes/test_open_items_routes.py`
- `tests/runner/test_open_items_tool_dispatch.py`
- `tests/runner/test_tool_groups_surface.py`
- `tests/runner/test_runner_entry.py::test_runner_keeps_open_items_tools_only_when_the_server_stores_them`
- `tests/runtime/test_prompt.py::test_stored_items_guidance_follows_the_open_items_tool_group`
