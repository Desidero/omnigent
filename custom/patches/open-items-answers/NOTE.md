# open-items-answers

Needs: open-items-panel, chat-item-comments
Covers: fb9b097f8927305e

When a "Comments on N items" message posts, the browser that sent it
records each stored item's comments as that item's answer, so the item
shows as answered in the Open items panel (and to the agent in
`sys_open_items_list`) and leaves the badge. An expanded item in the panel
also offers Comment.

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

## Key code

- `web/src/lib/openItemAnswers.ts`: `answersInCommentMessage`, `recordItemCommentAnswers`
- `web/src/hooks/useItemCommentMode.ts`: `recordItemCommentAnswers`
- `web/src/components/chat/StoredOpenItemsPanel.tsx`: `requestItemComment`

## Tests

- `web/src/lib/openItemAnswers.test.ts`
- `web/src/hooks/useItemCommentMode.test.tsx`
- `web/src/components/chat/StoredOpenItemsPanel.test.tsx`
