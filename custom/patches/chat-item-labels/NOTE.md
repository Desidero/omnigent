# chat-item-labels

Needs: codex-native-mode-instructions, session-labels-ui
Covers: a2e41027d029f67c

Bracketed labels such as `[Q2]` in chat become chips that preview the item
they refer to; `~~[Q2]~~` closes it, and an Open items bar lists what is still
open, puts the items the latest reply mentions first, and lets you dismiss
items. Agents get an instruction to label and close items.

- **Turn on:** on by default; labels render once a transcript uses them.
- **Docs:** [Item labels in chat](../chat-item-labels.md).
- **Upstream:** proposed from `feat/chat-item-citations`; the latest-reply
  emphasis and dismissing items are kept here only.

## Must hold

- A label is one to three capital letters and one to three digits in square brackets. The first message carrying it defines the item; later mentions, in agent or user messages, render as chips whose popover shows the defining block and a Show in conversation link. Labels in code, link text, task-list boxes and numeric footnotes are ignored.
- Labels render only once the transcript uses them (a label recurs in another message, or one message tags several items); a stray `[A4]` stays plain text.
- A struck-through mention (`~~[Q2]~~`) closes the item everywhere; the newest mention decides, so a later plain mention reopens it.
- The Open items bar lists the open labels, puts the items the latest agent reply mentions first (including one that reply just closed, struck through), and hides while the transcript uses no labels.
- A dismissed item leaves the bar's chips and open count and can be restored; dismissals are stored on the session as the `omnigent.items_dismissed` label through `PATCH /v1/sessions/{id}`, a `null` value deleting it when none are left (this is what needs session-labels-ui). An item the agent later closes shows as closed.
- Every agent gets the item-label instruction: SDK harnesses with each turn, native harnesses at launch as part of the stable startup guidance, after the workspace-image guidance. Its example labels match the shape the chat renders. codex-native relies on codex-native-mode-instructions so that guidance does not replace Plan mode's built-in instructions.

## Key code

- `web/src/lib/itemLabels.ts`: `buildItemLabelIndex`, `remarkItemLabels`, `extractItemBlock`, `mentionedInLatestReply`, `DISMISSED_ITEMS_LABEL_KEY`
- `web/src/components/chat/OpenItemsPanel.tsx`: `OpenItemsPanel`, `useDismissedItems`
- `web/src/components/blocks/ChatMarkdown.tsx`: `ItemLabelPopover`, `ItemLabelChip`
- `web/src/components/chat/chatBubbleParts.tsx`: `buildBubbleItemLabelIndex`
- `omnigent/runtime/prompt.py`: `ITEM_LABEL_INSTRUCTION`, `build_native_startup_instructions`

## Tests

- `web/src/lib/itemLabels.test.ts`
- `web/src/components/chat/OpenItemsPanel.test.tsx`
- `web/src/components/blocks/ChatMarkdown.itemLabels.test.tsx`
- `tests/runtime/test_prompt.py::test_native_startup_instructions_keep_only_stable_guidance`
- `tests/runtime/test_prompt.py::test_item_label_examples_match_the_chat_label_shape`
