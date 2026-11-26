# open-items-links-compact

Needs: chat-item-labels
Covers: 6eca4afecbca8526

The Open items bar of `chat-item-labels` becomes a compact button in the
session header, beside Agent info, with the number of open items as a badge;
it opens a popover on desktop and a sheet on phones. The panel also lists the
session's links: pages the agent's messages link to (first version:
`claude.ai` artifact links), collected without the agent doing anything, and
links pinned with a link label, `[L1] **Title** https://…`. A first version,
meant to be tried and revised.

- **Turn on:** on by default with the series; there is no setting, so leave
  the series out of a build to keep the bar.
- **Docs:** [Item labels in chat](../chat-item-labels.md) (Open items, Links,
  Loaded history only).
- **Upstream:** not proposed yet: there is no upstream issue or pull request,
  and `chat-item-labels`, which it extends, is not upstream either.

## Must hold

- In a session with the header, the open items open from one header button whose badge counts the items that are open: not closed, not dismissed, not a link label. The pinned bar is not shown there. A transcript shown without the session header keeps the bar.
- The panel holds the same tracker as the bar (`OpenItemsPanel` in its `section` layout, not a copy): chips, titles, latest-reply grouping, Closed fold, dismiss and restore, each item's preview. It starts expanded, and "Show in conversation" closes the panel.
- On a phone the panel is a sheet at the bottom of the screen and is not modal, so an item's preview can hand focus to the page behind it (which closes the sheet).
- Links lists pinned links first, in the order pinned, then collected pages, newest mention first, one row per page, titled by the newest link text given. Only agent messages are collected from; fenced code is skipped; each link opens the way a link in chat does.
- Which links are collected is the list `SESSION_LINK_MATCHERS`; adding a kind is adding a matcher.
- A link label is `L` and one to three digits. It is an ordinary item label (same parsing, numbering, chip and preview) that pins the first link in its own block, from the agent or the user, even while the transcript uses no other label. `~~[L1]~~` removes the pin and the collected row for the same page; a later plain `[L1]` restores it.
- Nothing is stored: items and links come from the loaded transcript. What is mentioned only in history not yet loaded is missing until it loads, and a label whose first message is not loaded is described by its earliest loaded mention (the bar's existing limit).
- Every agent gets the pinned-links paragraph as part of the item-label instruction, on the same channels and with the same label shape.
- The series stays clear of the lines `chat-item-comments` changes in the files they share, so the two build together, and the panel calls nothing whose signature that series changes. With both, their glue closes the panel when a comment is started from it.

## Key code

- `web/src/components/chat/SessionItemsButton.tsx`: `SessionItemsButton`
- `web/src/shell/SessionItemsHeaderSlot.tsx`: `SessionItemsHeaderSlot`, `useSessionItemsHeaderHost`
- `web/src/shell/ChatHeader.tsx`: `SessionItemsHeaderSlot`
- `web/src/components/chat/OpenItemsPanel.tsx`: `trackedItems`, `useOpenItemCount`
- `web/src/components/chat/Transcript.tsx`: `TranscriptSessionItems`
- `web/src/lib/sessionLinks.ts`: `collectSessionLinks`, `SESSION_LINK_MATCHERS`, `isLinkItemLabel`, `linksInMarkdown`
- `web/src/lib/itemLabels.ts`: `linesOutsideFences`
- `omnigent/runtime/prompt.py`: `ITEM_LABEL_INSTRUCTION`

## Tests

- `web/src/components/chat/SessionItemsButton.test.tsx`
- `web/src/lib/sessionLinks.test.ts`
- `web/src/shell/ChatHeader.test.tsx`
- `web/src/components/chat/OpenItemsPanel.test.tsx`
- `tests/runtime/test_prompt.py::test_item_label_instruction_shows_how_to_pin_a_link`
- `tests/e2e_ui/chat/test_item_label_chips.py::test_item_label_chip_previews_defining_item`
