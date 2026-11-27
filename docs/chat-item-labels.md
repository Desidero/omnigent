# Item labels in chat

Long sessions often raise several questions, risks or follow-ups in one reply
and then refer back to them across many short updates. Item labels give each
one a short tag such as `[Q2]`, and the chat turns later mentions of the tag
into a preview of the original item, so you don't have to scroll back or ask
for a recap. There is nothing to turn on.

## How agents label items

Omnigent adds a framework instruction to every agent: tag an item that needs
your decision or attention later once, at its start, with a bracketed label
and a short bold title, then refer to it by the label.

```markdown
[Q2] **Docker socket access?** The build needs the host's Docker socket...
```

The instruction suggests `[Q1]`, `[Q2]` for questions, `[R1]` for risks,
`[F1]` for findings and `[T1]` for follow-up tasks, and asks the agent to close
a settled item by writing its label struck through (`~~[Q2]~~`) in the
sentence that says how it ended.

The same instruction covers pages worth reopening: the agent pins a page it
publishes or keeps coming back to with a link label, `[L1]`, then a short bold
title and the URL. Pinned links show under **Links** (below).

```markdown
[L1] **Release checklist** https://example.com/checklist
```

An agent with the `open_items` tool group gets a different instruction: it
creates each item with its tools, writes it once with the label they return,
and replies to and closes items through them rather than in the text; see
[Open items](open-items.md).

SDK harnesses get the instruction with every turn. Native harnesses take
instructions only at launch, so it joins the stable guidance appended to the
agent's own instructions there: through Claude Code's `--append-system-prompt`
(merged with one you pass yourself, since Claude honours only the last),
Codex's `developer_instructions`, and the startup channel of the other native
harnesses that have one. Where a harness has none, labels still render when
you or the agent write them.

## What the chat shows

- **Labels:** one to three capital letters and one to three digits in square
  brackets, such as `[Q2]` or `[R12]`. Labels in code, task-list boxes
  (`[x]`), numeric footnotes (`[1]`) and link text are ignored.
- **Only once used:** labels render only when the transcript uses them, that
  is, a label recurs in another message or one message tags several items. A
  stray `[A4]` in an unrelated session stays plain text.
- **Chips:** the first message carrying a label defines the item. Later
  mentions, in your messages or the agent's, show as chips. Click one (or
  hover it with a mouse) for a popover with the defining block (its list
  item, heading section, table row or paragraph) and **Show in
  conversation**, which scrolls to it.
- **Closing:** a struck-through mention, `~~[Q2]~~`, closes the item. Its chips
  are struck through everywhere and the popover adds the sentence that closed
  it. The newest mention decides, so a later plain mention reopens it.
- **Open items:** a button in the session header, beside Agent info, carries
  the number of open items as a badge. Click it for a panel (on a phone, tap
  it for a sheet at the bottom of the screen) that lists the open labels as
  chips and every item with its title, closed ones under **Closed (N)**. The
  button appears once the transcript has an item or a link. A transcript shown
  without the session header keeps the list as a bar pinned above the thread.
- **Links:** under the items, the same panel lists the session's links, each
  opening the way a link in chat does. Pinned links come first, in the order
  they were pinned: a link label (`[L1]`, `[L2]`), written by the agent or by
  you, pins the first link in its own block under its bold title, and its chip
  previews that block like any item. Then come the pages the agent's messages
  link to at `https://claude.ai/artifact/…` or `https://claude.ai/code/artifact/…`,
  collected without the agent doing anything: one row per page, newest mention
  first, titled by the newest link text written for it. A link written as a
  bare URL is named from the words around it: a heading or bold title on its
  line (or on the line just above, when the link starts its line), else the
  last few words of the sentence before it; with none of these a page shows
  as a short name such as `Artifact 1f3a9c20` or `example.com/reports`, never
  the whole address. Pages are never fetched for a title. Links inside fenced
  code are skipped. `~~[L1]~~` takes a pinned link off the list, together with
  the collected row for the same page, and a later plain `[L1]` puts it back.
  A link label is not an open item: it is left out of the badge and the items.
- **Loaded history only:** items and links are read from the messages loaded
  in your browser; neither list is stored on the server. In a long session
  whose early history has not been loaded, an item or link mentioned only
  there is missing until you scroll up far enough to load it, and a label
  whose first message is not loaded is described by its earliest loaded
  mention, so a pinned link shows only if that mention carries the link.
  Where the server stores open items, the panel, its badge and the chips take
  stored items from the server instead; see
  [Open items in the web UI](open-items.md#in-the-web-ui).
- **Latest reply:** the Open items list puts the items the agent's newest reply
  mentions first, tinted, and includes an item that reply just closed, struck
  through. Expanded, they sit under **In the latest reply**, ahead of the other
  open items.
- **Dismiss:** each open item in the list has a dismiss button. A dismissed
  item leaves the chips, the open count and the badge; **Show dismissed (N)**
  at the bottom lists it with **Restore**. An item the agent later closes shows
  as closed as usual. Dismissals are stored on the session, as the
  `omnigent.items_dismissed` label, so they follow you to other devices.

## Comment on items

To answer several items at once, comment on each and send the comments
together, like reviewing a document:

1. Click an item's chip (in a message, in the Open items panel, or the label
   in its own defining message) and choose **Comment** in its popover. From
   the Open items panel, this closes the panel.
2. The composer switches to comment mode for that item: a card names it, and
   whatever you had typed is set aside until you save. Attachments, paste,
   @-mentions of files and sessions, and dictation work as usual; a draft keeps
   its tags.
3. Press Enter or the check button to save the comment to **Comment drafts**,
   a tray above the composer. Drafts can be edited or deleted (with Undo), and
   the tray can be collapsed to one line. In comment mode, Enter always saves;
   it never sends.
4. Send as usual: outside comment mode, Enter or the composer's send button
   (which then reads **Send N comments + message**) sends every draft, with
   anything you typed as the General section, as one message. With nothing
   typed it sends just the drafts. The tray's own **Send N comments** button
   does the same, also from comment mode. It queues like any message while the
   agent is busy, and a failed or cancelled send puts the drafts back.

A slash command or skill (including `/btw` and `/side`) or a `!` shell input
always goes on its own and leaves the drafts in the tray. To send only one
part, open the **⋯** menu beside the tray's send button (shown once you have
typed something): **Send comments only** leaves what you typed in the
composer, and **Send message only** sends what you typed and keeps the drafts.
File review comments attached to the composer go in the General section, after
the typed message.

The message is plain markdown that the agent is instructed to answer item by
item:

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

Items follow the order they were defined, comments are numbered only when an
item has several, and attached files are renamed to be unique in the message
(a pasted `image.png` on Q2 becomes `q2-1.png`). Tagged files and sessions are
sent as markers in place, as in any message, and a message that tags a session
ends with the one session tool hint. Chips with unsent drafts show
a dot and chips with sent comments a count; the popover lists each sent
comment with its files and the first sentence about the item in the agent's
next reply. A comment on a closed item leaves it closed.

Sent comments are read back from the transcript, so they show on every device.
Drafts stay in this browser only (attachments included) and survive a reload;
a failed or cancelled send puts them back as drafts. Where the server stores
open items, each comment on a stored item is also recorded in the item's
thread just before the message is sent, so the item shows as answered (see
[Open items in the web UI](open-items.md#in-the-web-ui)). On a stored item
that is not closed, **Comment and close** in the comment's header card (or a
draft's ✓ in the tray) closes the item with the comment as it is sent; its
heading in the message then ends `(closed by me)`.
