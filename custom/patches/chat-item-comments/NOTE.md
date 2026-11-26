# chat-item-comments

Needs: chat-item-labels
Covers: d4c2312045f8a611

Comment on labelled items and send the comments together as one structured
message the agent answers item by item. The composer's ordinary send takes the
unsent drafts along with the typed message; commands and `!` shell inputs go
alone, and the tray's menu sends only the comments or only the message.

- **Turn on:** on by default; choose **Comment** in an item's popover.
- **Docs:** [Item labels in chat](../chat-item-labels.md) (Comment on items).
- **Upstream:** not proposed yet: there is no upstream issue or pull request.
  It is prepared on `feat/chat-item-comments`, to go up together with the
  labelled-items renderer of `chat-item-labels`.

## Must hold

- Comment in an item's popover puts the composer in comment mode for that item: what was typed is set aside, and Enter saves the comment as a draft in the tray and never sends.
- Outside comment mode the composer's ordinary send, and the tray's send button, send every draft and the typed message (as a `#### General` section) as one user message through the normal send path, so it queues like any message. Sections follow the order the items were defined, and comments are numbered only when an item has several.
- A slash command, skill or `!` shell input goes alone and leaves the drafts in the tray; the tray's menu sends only the comments or only the message.
- Sent comments are stored nowhere new: the label index parses them back out of user messages, so `parseItemCommentMessage` must read what `buildItemCommentMessage` writes. A comment heading counts as a mention but leaves the item open or closed as it was.
- Drafts stay in the browser (localStorage per session, synced between tabs, attachment bytes in IndexedDB). Submitted drafts are kept until the message posts; a cancelled, edited, failed or orphaned send puts them back as drafts.
- Web only, with no server, protocol or schema change, apart from the reply rule added to the item-label instruction: answer each commented item by its label, and a comment on a closed item does not reopen it.

## Key code

- `web/src/lib/itemComments.ts`: `buildItemCommentMessage`, `parseItemCommentMessage`, `scanItemLabelSource`
- `web/src/hooks/useItemCommentMode.ts`: `useItemCommentMode`, `itemCommentSubmissionFate`
- `web/src/lib/itemCommentDrafts.ts`: `markItemCommentsSubmitted`, `completeItemCommentSubmission`, `restoreItemCommentSubmission`
- `web/src/pages/ChatPage.tsx`: `sendsWithoutCommentDrafts`
- `web/src/components/composer/ItemCommentTray.tsx`: `ItemCommentTray`, `ItemCommentModeHeader`

## Tests

- `web/src/lib/itemComments.test.ts`
- `web/src/hooks/useItemCommentMode.test.tsx`
- `web/src/pages/ChatPage.composer.test.tsx`
- `web/src/lib/itemCommentDrafts.test.ts`
- `tests/e2e_ui/chat/test_item_label_chips.py::test_item_comments_submit_together_and_thread_in_popover`
