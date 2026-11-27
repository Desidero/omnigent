# open-items-auto

Needs: open-items-store, open-items-links-compact
Covers: b2e52ff246afab65

Items an agent with the open items tools writes only in chat are not lost:
after each turn the server reads the agent's new messages with the chat's
own label rules, records each label the store lacks (`raised_by: auto`) and
closes each item struck through (`closed_by: auto`). When that changed
something, the agent's next message carries one `[Open items]` note, as
context it never sees as user text, saying what was added and asking it to
use `sys_open_items_raise` next time. The instruction says nothing about
this, so agents keep using the tool.

- **Turn on:** on by default for agents with the `open_items` tool group;
  `tool_groups.open_items: false` turns it off with the tools.
- **Docs:** [Open items](../open-items.md) (Items labelled only in chat).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639, like the store.

## Must hold

- Reading happens after the turn's idle edge, off the turn's path; a turn is never held for it. The first read of a session covers only its latest turn, so older history is not backfilled.
- A label the store already has is never changed by a read: retries, repeated reads and edited messages add nothing, and a label a tool raised keeps its content. A later tool raise of a recorded label takes the item over and keeps the number; counting moves past recorded labels.
- Labels in fenced or inline code, link text, task boxes and footnotes are ignored, and a label counts as an item only where it starts its line or list item, as the web reads it (both parsers pass the same cases file).
- A struck label closes its item only while it is open; nothing is reopened from chat. The session cap holds, and one read changes at most 20 labels.
- The note has the stable shape `[Open items] <labels with titles> was/were labelled in chat without being recorded, so it was/they were added for you. Next time record items with sys_open_items_raise; set a topic or close them with sys_open_items_update if needed. Closed from chat: <labels>. Open now: <n>.`; there is none when a read changed nothing, and at most three per session.
- The note reaches the model, never the transcript, on SDK harnesses (Claude SDK prompt-hook context, others as a system message), claude-native and codex-native (`UserPromptSubmit` hook context) and pi-native (a hidden message at agent start). Other native harnesses record but get no note.
- No agent instruction mentions automatic recording.

## Key code

- `omnigent/entities/item_labels.py`: `item_labels_in`, `struck_item_labels_in`, `extract_item_block`, `item_label_title_parts`, `defines_label`, `links_in_markdown`
- `omnigent/server/open_items_auto.py`: `ChatItemRecorder`, `chat_changes`, `chat_note_text`, `with_pending_note`, `NOTE_LIMIT`
- `omnigent/stores/open_items_store.py`: `record_from_chat`, `take_chat_note`, `SqlOpenItemChatNote`
- `omnigent/stores/open_items_migrations/open_items0002_chat_notes.py`
- `omnigent/server/routes/_sessions/orchestration.py`: `with_pending_note`
- `omnigent/server/routes/_sessions/helpers.py`: `open_items_auto`
- `omnigent/inner/native_attachments.py`: `framework_text_notice_block`, `framework_text_notices`
- `omnigent/harnesses/codex_native/hook.py`: `_main_framework_context`
- `omnigent/harnesses/codex_native/app_server.py`: `_codex_framework_context_hook`
- `omnigent/resources/pi_native/omnigent_pi_native_extension.js`: `before_agent_start`

## Tests

- `tests/server/test_open_items_auto.py`
- `tests/entities/test_item_labels.py`
- `web/src/lib/itemLabelCases.test.ts`
- `tests/inner/test_framework_text_notices.py`
- `tests/inner/test_sdk_resize_notices.py`
- `tests/harnesses/codex_native/app_server/test_policy_hooks.py::test_user_prompt_submit_carries_the_route_turn_hook`
- `omnigent/resources/pi_native/omnigent_pi_native_extension.test.js`
