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

## HTTP API

| Route (under `/v1`) | Caller | Purpose |
| --- | --- | --- |
| `GET /sessions/{id}/open-items` | read access | One page in label order, with counts by status and kind over all items and the topics in use. Filters: `status` (repeatable; `all` for every status), `kind` (repeatable), `topic`, `raised_by`, `has_links`, `q` (text search), `limit` (1 to 200), `after` (a label). |
| `POST /sessions/{id}/open-items` | the session's runner | Raise items for an agent with the `open_items` group. |
| `PATCH /sessions/{id}/open-items` | the session's runner, or a person with edit access | Close, reopen, retitle, retopic or relink items. |
| `POST /sessions/{id}/open-items/answers` | edit access | Record replies; an open item becomes answered. |

Each write publishes `session.open_items.changed` on the session's stream with
the labels written and the open count. `GET /v1/info` reports `open_items: true`
when the server stores them. The request and response shapes are in
[`omnigent/server/API.md`](../omnigent/server/API.md#open-items).

## Compatibility

Nothing is backfilled: items a session labelled in chat before stay chat
labels until an agent adopts them with `label`. A server or host without this
feature keeps working with text labels, and the web chips read the chat text
as before. The items live in their own tables, apart from the main migration
chain (see [side stores](extending/side_schemas.md)): a build without the
feature starts against a database that holds them and leaves them alone.
Search runs over the session's items in the server, not in SQL, because a
deployment may encrypt their content.
