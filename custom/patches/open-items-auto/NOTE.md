# open-items-auto

Needs: open-items-store, open-items-links-compact
Covers: d852f672b8f30df4

Items an agent with the open items tools writes only in chat are not lost:
after each turn the server reads the agent's new messages with the chat's
own label rules, records each label the store lacks (`raised_by: auto`) and
closes each item struck through (`closed_by: auto`). When that changed
something, the agent's next message carries one `[Open items]` note, as
model context and never inside the user's message, saying what was added
and asking it to use `sys_open_items_raise` next time; the transcript shows
the note as its own collapsed system row. The instruction says nothing about
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
- The note reaches the model as context, never as the user's text, on every path a message takes to the harness (first turn, cold resume, later turns, steering): Claude SDK and claude-native (`UserPromptSubmit` hook context), codex-native (its `UserPromptSubmit` hook), OpenAI Agents (a system message) and pi-native (a hidden message at agent start). The runner's executor adapter hands notice blocks only to executors that read them and never joins them into the user's text. Other harnesses record but get no note, and their note is not taken.
- The user's message holds only what they typed, stored and rendered. The note is its own transcript row: an info-level `error` item with code `framework_note`, persisted and published when the note is taken, rendered as a collapsed `System:` row that expands to the note, after a reload too. An `error` item is display-only (`NON_CONTENT_ITEM_TYPES`, never replayed to the agent) and upstream already uses its info level for notices; a new item type would need a new code in the item-type codec, which a refresh could collide with.
- No agent instruction mentions automatic recording.

## Key code

- `omnigent/entities/item_labels.py`: `item_labels_in`, `struck_item_labels_in`, `extract_item_block`, `item_label_title_parts`, `defines_label`, `links_in_markdown`
- `omnigent/server/open_items_auto.py`: `ChatItemRecorder`, `show_note`, `chat_changes`, `chat_note_text`, `with_pending_note`, `NOTE_LIMIT`, `NOTE_HARNESSES`, `NOTE_ROW_CODE`
- `omnigent/stores/open_items_store.py`: `record_from_chat`, `take_chat_note`, `SqlOpenItemChatNote`
- `omnigent/stores/open_items_migrations/open_items0002_chat_notes.py`
- `omnigent/server/routes/_sessions/orchestration.py`: `with_pending_note`
- `omnigent/server/routes/_sessions/helpers.py`: `open_items_auto`
- `omnigent/inner/native_attachments.py`: `framework_text_notice_block`, `framework_text_notices`, `is_framework_text_notice`
- `omnigent/runtime/harnesses/_executor_adapter.py`: `_normalize_message_content`, `_extract_injection_content`, `_join_text_blocks`, `_reads_framework_notices`
- `omnigent/inner/executor.py`: `reads_framework_notices`
- `web/src/lib/systemMessage.ts`: `frameworkNoteMessage`, `FRAMEWORK_NOTE_CODE`
- `web/src/components/blocks/BlockRenderer.tsx`: `BlockRenderer`
- `omnigent/harnesses/codex_native/hook.py`: `_main_framework_context`
- `omnigent/harnesses/codex_native/app_server.py`: `_codex_framework_context_hook`
- `omnigent/resources/pi_native/omnigent_pi_native_extension.js`: `before_agent_start`

## Tests

- `tests/server/test_open_items_auto.py`
- `tests/entities/test_item_labels.py`
- `web/src/lib/itemLabelCases.test.ts`
- `tests/inner/test_framework_text_notices.py`
- `web/src/components/blocks/FrameworkNoteRow.test.tsx`
- `tests/inner/test_sdk_resize_notices.py`
- `tests/harnesses/codex_native/app_server/test_policy_hooks.py::test_user_prompt_submit_carries_the_route_turn_hook`
- `omnigent/resources/pi_native/omnigent_pi_native_extension.test.js`
