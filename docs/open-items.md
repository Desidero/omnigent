# Open items

A session's **open items** are the questions, risks, findings and follow-ups its
agent raises for you, and the links it pins, kept as records of the session
rather than only as text in the chat. Each item has a label such as `Q7`, which
Omnigent allocates, so a label is never reused in its session and an item's
state does not depend on how much of the transcript is loaded. It is on by
default; an agent opts out with `tool_groups.open_items: false`.

An item works like a comment thread on a document. The agent creates it with
its tool, which is the only way an item is made, and then writes it once in the
chat as `[Q7] **Title** detail`. That label in the chat is an anchor: it points
at the stored item and never changes it. Replies (your comments and the
agent's answers) and the resolution live on the item, and the store alone
decides whether an item is open. Agents without the tools keep writing
[item labels](chat-item-labels.md) as text.

## What an item holds

| Field | Notes |
| --- | --- |
| `label` | The kind's letter and a number: `Q` question, `R` risk, `F` finding, `T` follow-up, `L` link. Numbers count up per session and kind, 1 to 999. |
| `status` | `open`, `answered` (you replied and the agent has not replied or closed it yet) or `closed`. A reply never closes an item. |
| `title`, `detail` | A few words (at most 160 characters), then the full item (at most 6,000). |
| `topic` | Optional short slug naming the piece of work, such as `cache-rollout`, so items of one coordinator session group. |
| `links` | Up to 8 http(s) links supporting the item. A link item (`L`) is a pinned URL; pinning one URL twice returns the same item, and one pinned without a title is named by a short form of its URL (`example.com/reports/…`). |
| `raised_by` | The sub-agent an item speaks for, when the agent raising it relays it. |
| `resolution`, `closed_by` | How a closed item ended, and whether the agent or a person closed it. |
| `replies` | The item's thread, oldest first: each with `author` (`user` or `agent`), `text` (at most 2,000 characters), `at`, and `by` for a person. The latest ten are kept, fewer if they would not fit the item's stored size. |

A session holds at most 500 items. Items are deleted with their session. A fork
or a side chat starts with none, and session export and import leave them out;
the forked transcript's labels still render as chat labels.

## Agent tools

The `open_items` tool group gives every agent three tools, which reach only the
calling session's items:

| Tool | Arguments | Result |
| --- | --- | --- |
| `sys_open_items_raise` | `items` (1 to 10): `kind` (`question`, `risk`, `finding`, `follow_up`, `link`), `title`, `detail`, and optionally `topic`, `links`, `url` (a link item's URL), `raised_by` | Per item its `label`, `status` and `title`, `duplicate: true` for a link already pinned, or an `error`; then `open_count` and the `topics` in use. |
| `sys_open_items_update` | `updates` (1 to 20): `label` and any of `reply` (the agent's reply on the item's thread), `status` (`open` or `closed`), `resolution` (required to close), `title`, `detail`, `topic` (empty clears it), `add_links`, `remove_links` | Per label its new state, or its own error. |
| `sys_open_items_list` | Optionally `status` (`open`, `answered`, `closed` or `all`; default open and answered), `kind`, `topic`, `query`, `limit` (1 to 100, default 50), `after` (a label) | Compact rows in label order: a 300-character detail preview, the latest three replies, how closed items ended; `truncated` and `next_after` when more remain, counts by status and the topics. |

Errors start with a code: `invalid_input`, `too_large`, `session_full`,
`label_taken`, `not_found`, or `unavailable` when the server does not store open
items. The agent cannot pick a label: a raise that names one is refused.

A raise retried by the harness with the same tool call ID returns the labels
its first attempt allocated, and a retried update adds its reply once. Two
raises at once in one session never get the same label.

Agents with the tools get one framework instruction for them in place of the
text-label one: every question the agent asks and every risk, finding or
follow-up is an item (not an unlabelled list or a question form); raise them
before writing the reply (several per call, each with a topic), write each
item once in chat as `[Q7] **Title** detail` with the returned label, refer to
it by label afterwards and never write a label the tool did not return; answer
comments on items with `sys_open_items_update` replies, closing with a one-line
resolution only what that settles; leave items the user closed (a comment
heading ending `(closed by me)`) closed unless the user asks again; list
instead of relying on memory; and talk about the items in chat, not about
recording them. The tool descriptions say that items and replies
show to the user. Nothing in the chat text creates, closes or reopens an
item.

### Which sessions get the tools

- **SDK harnesses** get them with the turn's tools; **claude-native**,
  **codex-native**, **pi-native**, **antigravity-native** and **hermes** get
  them through the Omnigent tool relay, like the Inbox tools. Native harnesses
  without the relay never see them and keep the text-label instruction.
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
- **Chips:** a stored item's label in the chat is its anchor: its chips
  follow the stored status (struck once the item is closed, whatever the chat
  wrote), and a plain or struck mention never changes the item.
- **Groups:** items the latest reply mentions come first, then the open ones,
  then **Answered** (you replied and the agent has not replied yet), with
  **Closed (N)** folded at the end. The badge counts open items: answered and
  closed ones, chat-only items you dismissed and pinned links are left out.
- **Details:** select an item to expand it: its detail, links, its thread
  (your comments and the agent's replies, each once, in order), how it was
  closed (left out when the resolution only repeats the last reply), and
  **Show in conversation** when a loaded message has it. Its chip previews it
  where the chat raised it.
- **Changes (edit access):** the ✕ on an open stored item closes it, recorded
  as closed by a person with the resolution "Closed from the Open items panel";
  expanded, you can write the resolution yourself, **Reopen** a closed item, or
  **Set topic**. The agent sees every change in `sys_open_items_list`.
- **Comments join the thread:** with [comments on items](chat-item-labels.md#comment-on-items),
  an expanded item also offers **Comment**. When you send a "Comments on N
  items" message, the browser first records each stored item's comments in
  its thread (`POST …/open-items/replies`, named after the message so sending
  it again records nothing new), then sends the message as one turn: an open
  item becomes **Answered**, and the agent finds the comments in
  `sys_open_items_list`. The send waits at most a few seconds for that record,
  and a failed record never holds or changes the message. Labels the server
  does not hold are skipped.
- **The item card:** a stored item's chip previews where it was raised, then
  its thread from the store (your comments and the agent's replies, each once)
  and how it was closed, the resolution left out when it only repeats the last
  reply. Replies and closing sentences in the chat text are not read for it.
- **Record:** a chip of a label written only in the chat (one the server does
  not hold, of a letter it uses) says so and offers **Record** to a person who
  can comment, which stores it under its own label as **Import** does. Nothing
  is recorded from the chat unless someone asks.
- **Comment and close:** on a stored item that is not closed, the comment's
  header card offers **Comment and close** (on a phone, **Close**), the
  tray's ✓ switches it per item, and an expanded panel row offers it next to
  **Comment**. The item is marked **closes when sent** in the panel and
  **closes** in the tray until the message goes. The message tells the agent
  with a heading ending `(closed by me)`; just before it goes, the comment is
  recorded and the item is closed by you (`PATCH …/open-items`, `closed_by`
  `user`) with the comment as its resolution, cut to 2,000 characters. If the
  close fails, the item stays open with the comment and a toast says so. A
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
| `PATCH /sessions/{id}/open-items` | the session's runner, or a person with edit access | Reply to, close, reopen, retitle, retopic or relink items. |
| `POST /sessions/{id}/open-items/replies` | edit access | Record a person's replies (a `ref` makes a retry add nothing); an open item becomes answered. |
| `POST /sessions/{id}/open-items/import` | edit access | Store items written in the chat under their own labels, closed if the chat closed them. |

Each write publishes `session.open_items.changed` on the session's stream with
the labels written and the open count. `GET /v1/info` reports `open_items: true`
when the server stores them. The request and response shapes are in
[`omnigent/server/API.md`](../omnigent/server/API.md#open-items).

## Compatibility

Nothing is backfilled: items a session labelled in chat before stay chat
labels until you import them from the panel. A server or host without this
feature keeps working with text labels, and the web reads the chat text as
before. The items live in their own tables, apart from the main migration
chain (see [side stores](extending/side_schemas.md)): a build without the
feature starts against a database that holds them and leaves them alone.
Search runs over the session's items in the server, not in SQL, because a
deployment may encrypt their content.
