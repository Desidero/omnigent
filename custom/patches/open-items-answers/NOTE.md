# open-items-answers

Needs: open-items-panel, chat-item-comments
Covers: fa3c9a2b2832f67f

When a "Comments on N items" message posts, the browser that sent it
records each stored item's comments as that item's answer, so the item
shows as answered in the Open items panel (and to the agent in
`sys_open_items_list`) and leaves the badge. An expanded item in the panel
also offers Comment. **Comment and close**, chosen per item in comment mode,
also closes the item, as the user, with the comment as its resolution.

- **Turn on:** on by default with `open-items-panel` and
  `chat-item-comments`, on a server that stores open items.
- **Docs:** [Open items](../open-items.md) (In the web UI: Answers from
  comments), [Item labels in chat](../chat-item-labels.md) (Comment on items).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639, like the store.

## Must hold

- The comment message is sent through the normal send path exactly as before; answers are recorded only after it has posted, by the one page that settles the submission, once.
- A failed or refused answers call never loses or changes the user's message or drafts: the items just stay open, and nothing is shown beyond a console warning.
- On a server that does not advertise `open_items` no answers call is made; labels of letters the store does not use are never sent, and a label the store lacks is skipped by the server.
- Each item's answer is its comments joined (an attachment-only comment names its files), cut to the store's 2,000 characters.
- Comment and close is offered per item (header card, tray toggle, panel row) only on a stored item that is not closed, never on a server without `open_items`; the default is a plain comment, and a close is never read from comment text. The tray and the panel row mark an item that sending closes.
- A closing item's heading ends `(closed by me)`; after the post its answer is recorded and it is closed with `PATCH …/open-items` (`closed_by: user`, the answer as the resolution). A failed close leaves it open with its answer and says so in a toast; the message and drafts are untouched, and an undone send keeps the choice on the drafts.

## Key code

- `web/src/lib/openItemAnswers.ts`: `answersInCommentMessage`, `recordItemCommentAnswers`, `itemCommentHeadingTitle`, `publishStoredOpenItems`, `setItemCommentsClose`
- `web/src/hooks/useItemCommentMode.ts`: `recordItemCommentAnswers`, `toggleItemClose`
- `web/src/components/composer/ItemCommentTray.tsx`: `CloseToggle`, `onClosesChange`
- `web/src/hooks/useStoredOpenItems.ts`: `publishStoredOpenItems`
- `web/src/components/chat/StoredOpenItemsPanel.tsx`: `requestItemComment`, `useItemCommentClosingLabels`

## Tests

- `web/src/lib/openItemAnswers.test.ts`
- `web/src/hooks/useItemCommentMode.test.tsx`
- `web/src/components/composer/ItemCommentTray.test.tsx`
- `web/src/components/chat/StoredOpenItemsPanel.test.tsx`
