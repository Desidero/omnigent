# Open items

A session's **open items** are the questions, risks, findings and follow-ups its
agent raises for you, and the links it pins, kept as records of the session
rather than only as text in the chat. Each item has a label such as `Q7`, which
Omnigent allocates, so a label is never reused in its session and an item's
state does not depend on how much of the transcript is loaded. It is on by
default; an agent opts out with `tool_groups.open_items: false`.

Agents still write each item once in the chat, as
[item labels](chat-item-labels.md) describe (`[Q7] **Title** detail`, and
`~~[Q7]~~` when it ends), so the chat reads as before and its label chips work
as before. What changes is where the state lives: the agent records items with
its tools, and the store decides whether an item is open.

## What an item holds

| Field | Notes |
| --- | --- |
| `label` | The kind's letter and a number: `Q` question, `R` risk, `F` finding, `T` follow-up, `L` link. Numbers count up per session and kind, 1 to 999. |
| `status` | `open`, `answered` (you replied and the agent has not closed it yet) or `closed`. |
| `title`, `detail` | A few words (at most 160 characters), then the full item (at most 6,000). |
| `topic` | Optional short slug naming the piece of work, such as `cache-rollout`, so items of one coordinator session group. |
| `links` | Up to 8 http(s) links supporting the item. A link item (`L`) is a pinned URL; pinning one URL twice returns the same item, and one pinned without a title is named by a short form of its URL (`example.com/reports/…`). |
| `raised_by` | The sub-agent an item speaks for, when the agent raising it relays it. |
| `resolution`, `closed_by` | How a closed item ended, and whether the agent or a person closed it. |
| `answers` | Your latest five replies. |

A session holds at most 500 items. Items are deleted with their session. A fork
or a side chat starts with none, and session export and import leave them out;
the forked transcript's labels still render as chat labels.

## Agent tools

The `open_items` tool group gives every agent three tools, which reach only the
calling session's items:

| Tool | Arguments | Result |
| --- | --- | --- |
| `sys_open_items_raise` | `items` (1 to 10): `kind` (`question`, `risk`, `finding`, `follow_up`, `link`), `title`, `detail`, and optionally `topic`, `links`, `url` (a link item's URL), `raised_by`, `label` (a label already written in chat, to adopt it) | Per item its `label`, `status` and `title`, `duplicate: true` for a link already pinned, or an `error`; then `open_count` and the `topics` in use. |
| `sys_open_items_update` | `updates` (1 to 20): `label` and any of `status` (`open` or `closed`), `resolution` (required to close), `title`, `detail`, `topic` (empty clears it), `add_links`, `remove_links` | Per label its new state, or its own error. |
| `sys_open_items_list` | Optionally `status` (`open`, `answered`, `closed` or `all`; default open and answered), `kind`, `topic`, `query`, `limit` (1 to 100, default 50), `after` (a label) | Compact rows in label order: a 300-character detail preview, the latest answer, how closed items ended; `truncated` and `next_after` when more remain, counts by status and the topics. |

Errors start with a code: `invalid_input`, `too_large`, `session_full`,
`label_taken`, `not_found`, or `unavailable` when the server does not store open
items (the agent then labels items in chat only).

A raise retried by the harness with the same tool call ID returns the labels
its first attempt allocated. Two raises at once in one session never get the
same label. Adopting a label from chat takes it only if no item has it, and
moves counting past it.

The framework instruction for item labels gains a part for these tools: record
every item, pinned links included, with `sys_open_items_raise` before presenting
it, with a topic, and write it with the returned label, never pick a number or
write a new label without recording it, close with `sys_open_items_update` and a one-line resolution and then
strike the label in chat, list instead of relying on memory, leave an item the
user closed closed (one whose comment heading ends `(closed by me)` included)
unless the user asks again, and label in chat only if the tools are missing.

### Items labelled only in chat

Agents with the tools are asked to record every item with
`sys_open_items_raise`, and that instruction does not mention what follows. When
an agent writes an item in chat anyway, as `[Q3] **Title** detail`, the server
records it so that it is not lost:

- **When:** after each turn ends, off the turn's path, the server reads the
  agent messages written since it last looked (the first time, only the latest
  turn: older history is not backfilled), with the same label rules as the
  chat (labels in code, link text and passing mentions are skipped; a label
  counts where it starts its line or list item).
- **Recorded:** a label the session's store does not have is stored under that
  label, with its title, its block as the detail and the links in it, and
  `raised_by: "auto"`; a link label stores its first link. A label the store
  already has, from a tool or an earlier read, is left alone, so a repeated
  read, a retry or an edited message adds nothing. Raising that label with the
  tool later takes the item over (its title, detail, topic and links), keeping
  the number. The session's cap of 500 items applies, and a read records or
  closes at most 20 labels.
- **Closed:** a struck label (`~~[Q3]~~`) closes its item if it is still open,
  with the sentence that struck it as the resolution and `closed_by: "auto"`.
  Nothing is reopened from chat.
- **The note:** when a read changed something, the agent's next message
  carries one framework note, given to the model as context for that turn and
  never shown as your text:

  ```text
  [Open items] Q3 "Region?" and R1 "No snapshot" were labelled in chat without being recorded, so they were added for you. Next time record items with sys_open_items_raise; set a topic or close them with sys_open_items_update if needed. Closed from chat: Q1. Open now: 4.
  ```

  A read that changes nothing leaves no note. A session's agent gets at most
  three notes; after that, recording goes on without them.
- **Harnesses:** SDK harnesses get the note as context through the same
  framework-notice channel as upload notices (Claude SDK as prompt-hook context,
  the others as a system message), claude-native and codex-native through
  their `UserPromptSubmit` hook, and pi-native as a hidden message when the
  agent starts. Other native harnesses get the items recorded but no note.
- **Turn off:** with the tools, `tool_groups.open_items: false`; nothing is
  read for an agent without them.

### Which sessions get the tools

- **SDK harnesses** get them with the turn's tools; **claude-native**,
  **codex-native**, **pi-native**, **antigravity-native** and **hermes** get
  them through the Omnigent tool relay, like the Inbox tools. Native harnesses
  without the relay never see them and keep text labels, as the instruction's
  last sentence tells them.
- The runner keeps the group only when the server says, on the agent bundle
  download, that it stores open items (`X-Omnigent-Open-Items: 1`). A server
  without this feature sends no such header, so its sessions keep the
  text-only instruction and no tools.
- An agent spec turns the group off with:

  ```yaml
  tool_groups:
    open_items: false
  ```

  A host whose Omnigent predates the group rejects an agent spec that names
  it, so set the key only once every host has it.

## In the web UI

Where the server stores open items (`GET /v1/info` reports `open_items: true`),
the **Open items** section of the session header's panel (see
[item labels](chat-item-labels.md#what-the-chat-shows)) lists the session's
stored items, whether or not their messages are loaded in your browser, and
stays current as the agent raises and closes them.

- **One list:** each stored item shows its stored status. A label written in
  the chat that the server does not hold is listed too, marked **chat only**,
  with its state read from the chat as before. Pinned links stay under
  **Links**, which lists every open stored link first, under the title the
  agent gave it (a short form of its URL when it gave none), whether or not a
  loaded message pins it; a closed stored link leaves the list with its page.
- **Chips:** a label's chips in the chat follow the stored status: a stored
  item is closed exactly when the server says so, whatever the chat wrote, and
  its popover shows the stored resolution when the chat never struck it.
- **Groups:** by default, items the latest reply mentions come first, then
  **Open**, **Answered** (you replied and the agent has not closed it yet) and
  **Closed**, folded. **By topic** groups items under their topic (items
  without one under **No topic**, last) and **By kind** under Questions,
  Risks, Findings, Follow-ups and Other, open items first in each group. Each
  group's heading folds it. The grouping is remembered in this browser. The
  badge counts open items: answered and closed ones, chat-only items you
  dismissed and pinned links are left out.
- **Search and filters:** once the list holds five items or more, a search box
  and one row of chips sit above it: **Open**, **Answered** and **Closed** with
  their counts, the kinds present, and the topics in use (`#cache-rollout`).
  The search matches every word you type in an item's label, title, detail or
  topic; a chip keeps only its status, kind or topic, and selecting it again
  clears it. Each count is what selecting that chip would list. Filtering runs
  in the browser over the loaded list. A search shows every match, folded
  groups included. On a phone the search stays at the top of the sheet and
  the chips scroll sideways in one row. The search, chips and folds stay as
  you left them when the panel closes, until the page reloads.
- **Details:** select an item to expand it: its detail, links, your latest
  answers, how it was closed, and **Show in conversation** when a loaded
  message has it. An item the server recorded from a label written only in
  chat says **recorded from chat**, and one it closed from a struck label says
  **Closed in chat**. Its chip previews it where the chat raised it.
- **Changes (edit access):** the ✕ on an open stored item closes it, recorded
  as closed by a person with the resolution "Closed from the Open items panel";
  expanded, you can write the resolution yourself, **Reopen** a closed item, or
  **Set topic**. When the chat struck a label that is still open in the store,
  the item is marked **closed in chat** and its details offer **Close** with
  the chat's sentence as the resolution. The agent sees every change in
  `sys_open_items_list`.
- **Answers from comments:** with [comments on items](chat-item-labels.md#comment-on-items),
  an expanded item also offers **Comment**. When a "Comments on N items"
  message posts, the browser that sent it records each item's comments as
  that item's answer (`POST …/open-items/answers`): an open stored item
  becomes **Answered** and lists the answer, and the agent sees it in
  `sys_open_items_list`. The message itself goes through the normal send path
  first, so if recording fails the item just stays open. Labels the server
  does not hold are skipped.
- **Comment and close:** on a stored item that is not closed, the comment's
  header card offers **Comment and close** (on a phone, **Close**), the
  tray's ✓ switches it per item, and an expanded panel row offers it next to
  **Comment**. The item is marked **closes when sent** in the panel and
  **closes** in the tray until the message posts. The message tells the agent
  with a heading ending `(closed by me)`; after it posts, the item's answer is
  recorded and the item is closed by you (`PATCH …/open-items`, `closed_by`
  `user`) with the comment as its resolution, cut to 2,000 characters. If the
  close fails, the item stays open with its answer and a toast says so. A
  close is never read from what a comment says.
- **Chat-only items** keep their dismiss button; dismissals are still stored
  as the `omnigent.items_dismissed` session label, which is read for chat-only
  items and never written for stored ones.
- **Import from chat (edit access):** when the chat has labels the server
  does not hold, such as a session's items from before the store, the panel
  offers **Import N from chat**. It stores each under its own label, with the
  title and block the chat gives it, closed (by you) if the chat closed or you
  dismissed it, so counting moves past them and an agent never reuses one.
  Pinned links (`[L1]`) are imported with their URL, and labels of other
  letters (such as `[A4]`) stay chat only.

On a server without open items the panel reads the chat alone, exactly as
[item labels](chat-item-labels.md) describe.

## HTTP API

| Route (under `/v1`) | Caller | Purpose |
| --- | --- | --- |
| `GET /sessions/{id}/open-items` | read access | One page in label order, with counts by status and kind over all items and the topics in use. Filters: `status` (repeatable; `all` for every status), `kind` (repeatable), `topic`, `raised_by`, `has_links`, `q` (text search), `limit` (1 to 200), `after` (a label). |
| `POST /sessions/{id}/open-items` | the session's runner | Raise items for an agent with the `open_items` group. |
| `PATCH /sessions/{id}/open-items` | the session's runner, or a person with edit access | Close, reopen, retitle, retopic or relink items. |
| `POST /sessions/{id}/open-items/answers` | edit access | Record replies; an open item becomes answered. |
| `POST /sessions/{id}/open-items/import` | edit access | Store items written in the chat under their own labels, closed if the chat closed them. |

Each write publishes `session.open_items.changed` on the session's stream with
the labels written and the open count. `GET /v1/info` reports `open_items: true`
when the server stores them. The request and response shapes are in
[`omnigent/server/API.md`](../omnigent/server/API.md#open-items).

## Compatibility

Nothing is backfilled: items a session labelled in chat before stay chat
labels until an agent adopts them with `label` or you import them from the
panel. A server or host without this
feature keeps working with text labels, and the web reads the chat text as
before. The items live in their own tables, apart from the main migration
chain (see [side stores](extending/side_schemas.md)): a build without the
feature starts against a database that holds them and leaves them alone.
Search runs over the session's items in the server, not in SQL, because a
deployment may encrypt their content.
