# Open items

A session's agent records the questions, risks, findings and follow-ups it raises, and the links it pins, as stored open items with labels the server allocates (`Q7`), and still writes each one once in the chat. Agents close, reopen and list items through their tools; people read them over the API and may close, reopen, retopic or answer them. There is no panel for them yet: the chat's label chips and Open items bar still read the chat text.

## Sub-features

- `items-raise`: `sys_open_items_raise` allocates labels per session and kind; a retried call gets the same labels; a pinned URL pinned again returns the same item; `label` adopts a chat label if it is free.
- `items-update`: `sys_open_items_update` closes with a resolution, reopens, and edits title, detail, topic and links, each label with its own result.
- `items-list`: `sys_open_items_list` and `GET /v1/sessions/{id}/open-items` list in label order with status, kind, topic and text filters, counts and topics.
- `items-from-chat`: after a turn, labels the agent wrote only in chat are recorded (`raised_by: auto`) and struck ones closed (`closed_by: auto`); its next message carries one `[Open items]` framework note, at most three per session.
- `items-answers`: a person's replies, recorded with `POST …/open-items/answers`, mark an open item answered.
- `items-event`: every write publishes `session.open_items.changed` on the session's stream.
- `items-unavailable`: on a server or host without open items, or an agent with `tool_groups.open_items: false`, there are no tools and the agent labels items in chat only.
- `items-delete`: deleting a session deletes its items; a fork starts with none.

## How to get to it (user POV)

- Chat: ask an agent with the default tool groups something that leaves it open questions; it calls `sys_open_items_raise`, which shows as a tool row, and writes the items with the returned labels.
- Chat: answer or settle an item; the agent closes it with `sys_open_items_update` and strikes its label.
- API: `GET /v1/sessions/{id}/open-items` with read access; `PATCH` and `POST …/answers` with edit access.
- Agent spec: `tool_groups.open_items: false` turns the tools off for that agent.

## Driving it with the repro environment

Preconditions: a local server and runner from this checkout; any harness.

- Store (labels under concurrency, retries, adoption, caps, close and reopen, answers, list filters, session delete): `tests/stores/test_open_items_store.py`. Set `OMNIGENT_TEST_DB_URI` to run it on PostgreSQL or CockroachDB.
- Chat-only labels and the note: `tests/server/test_open_items_auto.py` (recording, idempotency, caps, takeover, strikes, the note's text and limit, a session without the group); delivery per harness: `tests/inner/test_framework_text_notices.py`, `tests/inner/test_sdk_resize_notices.py`, `omnigent/resources/pi_native/omnigent_pi_native_extension.test.js`; the label rules shared with the web: `tests/entities/test_item_labels.py` and `web/src/lib/itemLabelCases.test.ts`.
- Routes, permissions, the live event, `/v1/info` and the bundle header, and the runner's tool handlers through the real routes: `tests/server/routes/test_open_items_routes.py::test_the_agents_tools_raise_update_and_list_through_the_runner`.
- Registration, the native relay and an older server: `tests/runner/test_open_items_tool_dispatch.py`, `tests/runner/test_tool_groups_surface.py`, `tests/runner/test_runner_entry.py::test_runner_keeps_open_items_tools_only_when_the_server_stores_them`.
- Instruction text: `tests/runtime/test_prompt.py::test_stored_items_guidance_follows_the_open_items_tool_group`.
- Human check: in a new session, ask the agent to review a small change and list its open questions. Expect one `sys_open_items_raise` tool row and the items written as `[Q1] **Title** detail`. Then `curl -H 'X-Forwarded-Email: <you>' <server>/v1/sessions/<id>/open-items` lists them as `open`. Answer one in chat and ask the agent to close it: expect a `sys_open_items_update` row, a struck `~~[Q1]~~`, and the item `closed` with `closed_by: agent` in the API.

## Gotchas

- The web UI does not read the store yet: chips and the Open items bar still follow the chat text, so an item closed only through the API still shows open in the bar.
- Hosts without the series do not know the `open_items` key in `tool_groups:`, and an agent spec naming it fails to load there.
- A CLI-launched claude-native or codex-native session composes its startup instruction from the local wrapper spec, so it mentions the tools even when the server lacks them; the instruction's last sentence covers that.
- Labels are unique per session, not across a session tree: a child session counts from Q1.
