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
