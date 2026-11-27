# open-items-store

Needs: side-schemas, chat-item-labels
Covers: 35e95762cbe69a30

Open items (the questions, risks, findings, follow-ups and pinned links an
agent raises) become records of their session, in the `open_items` side
store, with labels such as `Q7` that the server allocates. Each item is a
thread: the agent creates it with `sys_open_items_raise` (the only way to
create one) and writes it once in chat, where the label only points at it;
the user's comments and the agent's replies (`reply` on
`sys_open_items_update`) and the resolution are stored on it. Agents with the
tools get one instruction for them in place of the text-label one. People
read items through `/v1/sessions/{id}/open-items` and may reply, close,
reopen or retopic. Every write publishes `session.open_items.changed`. The
web does not read the store yet: label chips and the Open items bar still
follow the chat text.

- **Turn on:** on by default; an agent opts out with `tool_groups.open_items: false`.
- **Docs:** [Open items](../open-items.md).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639.

## Must hold

- Labels are unique per session: two raises at once never get the same label, a label is never reused for another item, and a retried raise with the same tool call ID returns the labels its first attempt allocated. A raise that names a label is refused; only an import of chat labels (`open-items-panel`) stores one under its own label.
- The tools only write to their own session: raises and agent updates are accepted only from the session's bound runner (source header and tunnel token), for an agent whose spec keeps the `open_items` group.
- A server or host without the series keeps text labels working: a runner keeps the tools only when the bundle download carries `X-Omnigent-Open-Items: 1`, and without the tools the agent gets the text-only item-label instruction. Nothing is backfilled.
- A link pinned without a title is named by a short form of its URL (host and the start of the path), never the whole URL.
- A reply joins the item's thread once per `ref` (a retried tool call or comment adds nothing) and never closes or reopens the item; the user replying makes an open item answered, the agent replying makes an answered one open. The latest ten replies that fit are kept.
- Agents with the tools get one instruction block in place of the text-label one: every question asked and every risk, finding or follow-up is an item, raised (with a topic) before the reply that has it and never asked as an unlabelled list or question form; each is written once with the returned label; no label the tool did not return is written; comments get `sys_open_items_update` replies, closing only what that settles; items the user closed (`(closed by me)`) stay closed unless asked again; the list beats memory; chat talks about items, not recording them. No struck labels, no chat-only fallback. Agents without the tools keep the text-label instruction.
- The tool descriptions say raising is the only way to create an item and that items and replies show to the user.
- A database that ran the retired chat-notes revision (`open_items0002`) starts: `open_items0003` drops that table, and its downgrade restores it.
- Deleting a session removes its items and counters; forks start with none.
- Reads need read access; people's changes and answers need edit access.
- The open_items tables stay out of the main migration chain, and a build without the series starts against a database that holds them.

## Key code

- `omnigent/stores/open_items_store.py`: `OpenItemsStore`, `record_replies`, `_add_reply`, `delete_open_items_batch`, `OPEN_ITEMS_SIDE_STORE`
- `omnigent/stores/open_items_migrations/open_items0001_create_tables.py`
- `omnigent/stores/open_items_migrations/open_items0003_drop_chat_notes.py`
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
- `tests/runtime/test_prompt.py`
- `tests/stores/test_open_items_store.py::test_replies_build_one_chain_and_never_close_the_item`
- `tests/stores/test_open_items_store.py::test_the_retired_chat_notes_table_is_dropped_and_a_downgrade_restores_it`
