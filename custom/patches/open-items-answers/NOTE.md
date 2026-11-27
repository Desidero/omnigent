# open-items-answers

Needs: open-items-panel, chat-item-comments
Covers: 1a66ecb89ec0b8cf

Comments on stored open items join each item's thread: just before a
"Comments on N items" message is sent, the browser that sends it records each
stored item's comments as the user's replies, so the item shows as answered
in the Open items panel and to the agent in `sys_open_items_list` when its
turn starts. A stored item's chip previews its thread from the store, each
reply once, instead of sentences found in the chat; a chip of a label written
only in the chat offers **Record**. An expanded item in the panel also offers
Comment. **Comment and close**, chosen per item in comment mode, also closes
the item, as the user, with the comment as its resolution.

- **Turn on:** on by default with `open-items-panel` and
  `chat-item-comments`, on a server that stores open items.
- **Docs:** [Open items](../open-items.md) (In the web UI: Comments join
  the thread, The item card, Record, Comment and close), [Item labels in chat](../chat-item-labels.md) (Comment on items).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639, like the store.

## Must hold

- The comment message stays one message and one turn, sent through the normal send path; its replies are recorded just before it is sent, by the page that sends it, named after the message (a hash of its text), so sending the same message again records nothing new.
- The send waits at most three seconds for the record; a failed, refused or slow call never loses, holds back or changes the user's message or drafts, and shows nothing beyond a console warning.
- On a server that does not advertise `open_items` no replies call is made; labels of letters the store does not use are never sent, and a label the store lacks is skipped by the server.
- Each item's reply is its comments joined (an attachment-only comment names its files), cut to the store's 2,000 characters.
- A stored item's chip preview shows the store's replies and resolution, each once (no resolution that repeats the last reply), and none of the comments, "Agent replied" sentences or closing sentences the chat text gives.
- A chip of a chat-only label of a letter the store uses offers **Record** only where the server stores open items and the session's composer takes comments; it imports that one label under its own label. Nothing is recorded without that click.
- Comment and close is offered per item (header card, tray toggle, panel row) only on a stored item that is not closed, never on a server without `open_items`; the default is a plain comment, and a close is never read from comment text. The tray and the panel row mark an item that sending closes.
- A closing item's heading ends `(closed by me)`; before the message goes its reply is recorded and it is closed with `PATCH …/open-items` (`closed_by: user`, the comment as the resolution). A failed close leaves it open with its reply and says so in a toast; the message and drafts are untouched, and an undone send keeps the choice on the drafts.

## Key code

- `web/src/lib/openItemAnswers.ts`: `answersInCommentMessage`, `recordItemCommentAnswers`, `recordItemCommentsBeforeSend`, `commentMessageRef`, `itemCommentHeadingTitle`, `publishStoredOpenItems`, `setItemCommentsClose`
- `web/src/hooks/useItemCommentMode.ts`: `recordItemCommentsBeforeSend`, `toggleItemClose`
- `web/src/components/blocks/ChatMarkdown.tsx`: `ItemLabelPreview`, `RecordChatItem`, `StoredItemThread`
- `web/src/components/composer/ItemCommentTray.tsx`: `CloseToggle`, `onClosesChange`
- `web/src/hooks/useStoredOpenItems.ts`: `publishStoredOpenItems`
- `web/src/components/chat/StoredOpenItemsPanel.tsx`: `requestItemComment`, `useItemCommentClosingLabels`

## Tests

- `web/src/lib/openItemAnswers.test.ts`
- `web/src/components/blocks/ChatMarkdown.storedItems.test.tsx`
- `web/src/hooks/useItemCommentMode.test.tsx`
- `web/src/components/composer/ItemCommentTray.test.tsx`
- `web/src/components/chat/StoredOpenItemsPanel.test.tsx`
