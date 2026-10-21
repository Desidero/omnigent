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

SDK harnesses get the instruction with every turn. claude-native and
codex-native take instructions only at launch, so it is appended to the
agent's own instructions there: through Claude Code's `--append-system-prompt`
(merged with one you pass yourself, since Claude honours only the last) and
Codex's `developer_instructions`. Other native harnesses have no instruction
channel; labels still render when you or the agent write them.

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
- **Open items:** a bar above the thread lists the open labels as chips.
  Expand it for every item with its title, closed ones under **Closed (N)**.

## Comment on items

To answer several items at once, comment on each and send the comments
together, like reviewing a document:

1. Click an item's chip (in a message, in the Open items bar, or the label in
   its own defining message) and choose **Comment** in its popover.
2. The composer switches to comment mode for that item: a card names it, and
   whatever you had typed is set aside until you save. Attachments, paste,
   @-mentions and dictation work as usual.
3. Press Enter or the check button to save the comment to **Comment drafts**,
   a tray above the composer. Drafts can be edited or deleted (with Undo), and
   the tray can be collapsed to one line.
4. Choose **Send N comments** (or **Send N comments + message** when you have
   also typed a message) to send every draft as one message. It queues like any
   message while the agent is busy.

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
(a pasted `image.png` on Q2 becomes `q2-1.png`). Chips with unsent drafts show
a dot and chips with sent comments a count; the popover lists each sent
comment with its files and the first sentence about the item in the agent's
next reply. A comment on a closed item leaves it closed.

Sent comments are read back from the transcript, so they show on every device.
Drafts stay in this browser only (attachments included) and survive a reload;
a failed or cancelled send puts them back as drafts.
