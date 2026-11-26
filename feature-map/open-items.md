# Open items

A session's agent creates the questions, risks, findings and follow-ups it raises, and the links it pins, as stored open items with labels the server allocates (`Q7`), and writes each one once in the chat, where the label only points at it. Each item keeps a reply thread: people's comments and the agent's replies. Agents reply to, close, reopen and list items through their tools; people read them over the API and in the Open items panel of the session header, where they may close, reopen and retopic them.

## Sub-features

- `items-raise`: `sys_open_items_raise` allocates labels per session and kind; a retried call gets the same labels; a pinned URL pinned again returns the same item; the agent cannot choose a label.
- `items-update`: `sys_open_items_update` replies on the item's thread, closes with a resolution, reopens, and edits title, detail, topic and links, each label with its own result; a reply alone never closes an item.
- `items-list`: `sys_open_items_list` and `GET /v1/sessions/{id}/open-items` list in label order with status, kind, topic and text filters, counts and topics.
- `items-replies`: a person's replies, recorded with `POST …/open-items/replies` (once per `ref`), mark an open item answered; the agent's reply hands it back as open.
- `items-event`: every write publishes `session.open_items.changed` on the session's stream.
- `items-unavailable`: on a server or host without open items, or an agent with `tool_groups.open_items: false`, there are no tools and the agent gets the text-label instruction.
- `items-delete`: deleting a session deletes its items; a fork starts with none.
- `items-panel`: on a server reporting `open_items`, the header panel, its badge and the chat's chips read the stored list (kept live by the event), with chat-only labels marked as such; without it, they read the chat alone.
- `items-user-change`: a person with edit access closes (one tap, or with a resolution), reopens and retopics stored items from the panel; a stored item struck only in the chat is offered for closing.

## How to get to it (user POV)

- Chat: ask an agent with the default tool groups something that leaves it open questions; it calls `sys_open_items_raise`, which shows as a tool row, and writes the items with the returned labels.
- Chat: answer or settle an item; the agent replies and closes it with `sys_open_items_update`.
- API: `GET /v1/sessions/{id}/open-items` with read access; `PATCH` and `POST …/replies` with edit access.
- Web: the bookmark button in the session header (badge = open items) opens the panel; select a row to expand it; ✕ closes a stored item.
- Agent spec: `tool_groups.open_items: false` turns the tools off for that agent.

## Driving it with the repro environment

Preconditions: a local server and runner from this checkout; any harness.

- Store (labels under concurrency, retries, imported labels, caps, close and reopen, reply threads, list filters, session delete, the migration that drops the retired chat notes table): `tests/stores/test_open_items_store.py`. Set `OMNIGENT_TEST_DB_URI` to run it on PostgreSQL or CockroachDB.
- Routes, permissions, the live event, `/v1/info` and the bundle header, and the runner's tool handlers through the real routes: `tests/server/routes/test_open_items_routes.py::test_the_agents_tools_raise_update_and_list_through_the_runner`.
- Registration, the native relay and an older server: `tests/runner/test_open_items_tool_dispatch.py`, `tests/runner/test_tool_groups_surface.py`, `tests/runner/test_runner_entry.py::test_runner_keeps_open_items_tools_only_when_the_server_stores_them`.
- Codex approval: `tests/harnesses/codex_native/app_server/test_session_profiles.py::test_the_open_items_tools_run_without_a_prompt_and_no_other_tool_is_added`.
- Instruction text: `tests/runtime/test_prompt.py::test_stored_items_guidance_follows_the_open_items_tool_group`, `::test_stored_items_guidance_names_the_tools_and_never_strikes_labels`.
- Web merge and rows: `web/src/lib/openItems.test.ts`; panel, badge and user changes: `web/src/components/chat/StoredOpenItemsPanel.test.tsx`; the live event: `web/src/store/chatStore.openItems.test.ts`.
- Human check (panel): with items raised as above, open the header's bookmark button. Expect the badge to count the open items, each row its stored title, and an answered or closed one under its group. Tap ✕ on one: it moves to **Closed (N)**, the badge drops, its chips in the chat strike through, and `sys_open_items_list` shows it `closed_by: user`. On a server without the store the panel looks as before.
- Human check: in a new session, ask the agent to review a small change and list its open questions. Expect one `sys_open_items_raise` tool row and the items written as `[Q1] **Title** detail`. Then `curl -H 'X-Forwarded-Email: <you>' <server>/v1/sessions/<id>/open-items` lists them as `open`. Answer one in chat and ask the agent to close it: expect a `sys_open_items_update` row with a `reply`, and the item `closed` with `closed_by: agent` and the reply in its `replies` in the API. The agent does not strike labels.

## Gotchas

- A stored item closed only through the API shows struck chips; their popover's "Show" goes to the label's latest loaded mention, since no message closed it.
- The pinned Open items bar (a transcript without the session header) reads the merged chip state but keeps its old layout and lists only labels in loaded messages.
- Hosts without the series do not know the `open_items` key in `tool_groups:`, and an agent spec naming it fails to load there.
- A CLI-launched claude-native or codex-native session composes its startup instruction from the local wrapper spec, so it mentions the tools even when the server lacks them; the tools then answer `unavailable`.
- Labels are unique per session, not across a session tree: a child session counts from Q1.
