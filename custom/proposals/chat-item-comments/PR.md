<!-- Draft PR body for the chat-item-comments series; title: feat(web): comment on labelled items and submit the comments together -->
## Related issue

Closes #TODO (issue to be opened)

## Summary

Depends on: chat-item-labels (stacked; would be rebased or split for upstream).

When an agent raises several labelled items ([Q2], [R1], ...), you can now comment on each one, like reviewing a document, and send all the comments as one message that keeps every answer attached to its item.

Answering several items in one long hand-typed reply loses the structure: the agent has to work out which paragraph answers which item, and nothing ties the answer back to the item afterwards.

- **Comment mode.** Clicking a chip (in a message, in the Open items panel, or the label in its own defining message, which is now clickable) opens the item popover, which gains a Comment button. Comment switches the real composer into comment mode for that item: a header card names it, and any text already typed is set aside until the comment is saved, so attachments, paste, @-mentions and dictation work as usual.
- **Drafts tray.** Enter or the check button saves the comment to a tray above the composer, styled like the queued-messages strip. It can be minimized to one line, and drafts can be edited or deleted (with undo). Chips show an amber dot for unsent drafts and a count for sent comments.
- **Submit together.** "Submit comments (N)" sends every draft as one plain-markdown user message through the normal send path, so it queues like any message while the agent is busy (the queue row reads "3 comments on Q2 R1"). Text typed in the composer goes along as a General section:

  ```markdown
  Comments on 2 items:

  #### [Q2] <item title>

  **1.** <comment>

  **2.** <comment>

  Attachments: q2-1.png

  #### [R1] <item title>

  <comment>

  #### General

  <typed message>
  ```

  Sections follow the order the items were defined; comments are numbered only when an item has several; headings inside a comment are demoted to bold. Attachments are real file blocks, renamed to be unique within the message (a pasted `image.png` on Q2 becomes `q2-1.png`) and listed by name, since native harnesses drop file blocks on the transcript round trip.
- **Threading without new storage.** The label index parses the sections back out of user messages, and the popover lists each comment with its files and the first sentence about the item in the next agent message, on any device and after reload. A comment heading counts as a mention but leaves an item open or closed; a plain mention still reopens it.
- **Drafts are local.** Drafts live in this browser: localStorage keyed by session, synced between tabs with the `storage` event, with attachment bytes in IndexedDB. Submitted drafts stay marked as sent until the message posts; cancelling or editing the queued message, a failed send, or closing the page while it waited in the in-memory queue restores them as drafts.
- **Agent instruction.** The item-label instruction in `omnigent/runtime/prompt.py` gains the reply rule: answer each commented item by its label, and a comment on a closed item does not reopen it. If maintainers prefer, this PR can be split into a renderer-only change plus a separate instruction change.

No server, protocol or schema change beyond the instruction text.

Docs: `docs/chat-item-labels.md` gains a "Comment on items" section with the steps, the message format and where drafts are kept.

## Test Plan

Tests added or changed:

- `web/src/lib/itemComments.test.ts`, `web/src/lib/itemCommentDrafts.test.ts`, `web/src/lib/itemCommentFiles.test.ts`, `web/src/lib/itemLabels.test.ts`: message format, parsing comments back out of user messages, draft storage and restore, attachment renaming, mention/close semantics.
- `web/src/hooks/useItemCommentMode.test.tsx`, `web/src/components/composer/ItemCommentTray.test.tsx`: comment mode, tray editing, delete with undo, minimize, submit.
- `web/src/components/blocks/ChatMarkdown.itemLabels.test.tsx`, `web/src/pages/ChatPage.composer.test.tsx`, `web/src/pages/QueuedMessagesStrip.test.tsx`: chip popover Comment button, defining-label click, queued-row text, restore on cancel.
- `tests/e2e_ui/chat/test_item_label_chips.py::test_item_comments_submit_together_and_thread_in_popover`: browser journey from comment to submit to threaded popover.

```sh
cd web && pnpm exec vitest run src/lib/itemComments.test.ts src/lib/itemCommentDrafts.test.ts \
  src/lib/itemCommentFiles.test.ts src/lib/itemLabels.test.ts src/hooks/useItemCommentMode.test.tsx \
  src/components/composer/ItemCommentTray.test.tsx src/components/blocks/ChatMarkdown.itemLabels.test.tsx \
  src/pages/ChatPage.composer.test.tsx src/pages/QueuedMessagesStrip.test.tsx
cd web && pnpm exec tsc -b
uv run pytest tests/e2e_ui/chat/test_item_label_chips.py
```

Manual:

1. Ask an agent for a reply that raises at least two labelled items, e.g. "List three open questions labelled [Q1]..[Q3]."
2. Click the [Q2] chip, then Comment. Type a comment and paste an image; press Enter. The draft appears in the tray and the chip shows an amber dot.
3. Add a second comment on Q2 and one on Q1. Type a general note in the composer. Reload the page: the drafts and the image are still there. Open a second tab of the same session: the drafts appear there too.
4. Edit one draft and delete another, then undo the delete.
5. Click "Submit comments (N)". The sent message uses the format above, with the image renamed (`q2-1.png`). The chips now show a count.
6. While the agent replies, its answers start with the item labels. Click the [Q2] chip: the popover lists both comments, the attachment, and the first sentence of the agent's answer.
7. Submit comments while the agent is busy: the queued row reads "N comments on ...". Cancel it from the queue: the drafts return to the tray.

## Demo

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: recording of commenting on two items, editing a draft in the tray, and submitting (throwaway server, dummy conversation)
- [ ] TODO: screenshot of the sent message as rendered in the transcript
- [ ] TODO: screenshot of a chip popover listing comments with an attachment and the agent's first-sentence reply
- [ ] TODO: screenshot of the queued-message row reading "N comments on ..." and of the minimized tray
- [ ] TODO: mobile-width screenshot of comment mode and the tray

## Type of change

- [ ] Bug fix
- [x] Feature
- [x] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [x] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Unit and component tests cover formatting, parsing, draft persistence and restore paths; one browser test covers the end-to-end comment, submit and popover threading journey. Cross-tab sync and IndexedDB persistence across reloads are covered at the unit level with stubs.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Comment on labelled chat items such as [Q2] and send all the comments together as one structured message, with each comment shown under its item
