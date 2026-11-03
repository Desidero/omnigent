# Session status observers

Server code can react to session status edges without polling. Every edge that
`_publish_status` takes, changing a session's cached status (`idle`,
`running`, `waiting`, `failed`), becomes one `session.status` observation,
which the server hands to its observers.

Two writers change the cached status without `_publish_status`, so their edges
are not observed: a runner reconnect that clears a disconnect-caused `failed`
back to `idle`, and the runner status probe that refreshes the cache from the
runner's answer. Anything that must act on idle sessions reconciles to cover
them.

## What an observation is

An observation is a display-state edge as one server replica published it,
with `schema_version` 1:

| Field | Meaning |
| --- | --- |
| `session_id` | The session. Ids are unique only within a workspace. |
| `workspace_id` | The publisher's workspace. |
| `previous_status` | The status this replica cached before the edge, or `null` after a restart. |
| `status` | The new status. |
| `persist_requested` | Whether the publisher asked to mirror the status onto the session row. Stops, archives and orphan settlement publish `idle` without it. The write is best-effort, so this does not mean it committed. |
| `response_id` | The response the edge names, when it names one. |
| `blocked_on` | What a `waiting` edge waits for, when known. |
| `observed_at` | When the edge was published (Unix seconds). |

It is not a lifecycle event:

- An `idle` edge does not prove the model finished its turn. For several native
  harnesses it means the terminal went quiet.
- A `waiting` edge is not a durable, answerable decision.
- A `failed` session stays `failed` against a trailing `idle`, so that `idle`
  is not observed. The next `running` edge, or an `idle` that the harness
  confirms as a finished turn, is.
- Repeating the current status is not an edge.
- Each replica observes only the edges it publishes: mostly those of the
  sessions whose runner it serves, but a stop, an archive or the settling of an
  orphaned turn publishes `idle` on whichever replica handles that request.
- Observations are not stored or replayed. Anything that must not miss an edge
  reconciles on its own schedule.

## Core observers

Core server modules register an observer with
`omnigent.server.session_status_observers.register_core_observer`. Core
observers run inline, after the edge is published (status cache, queued row write
and live stream), in registration order, with the publisher's context (so
`current_workspace_id()` is the session's workspace). A status that fails
validation is never observed. An observer that raises is logged; the others
and the publisher continue.

A core observer must return quickly and never block. One that needs I/O, or
wants to start a turn, schedules that work on the event loop rather than doing
it inline.

The first core observer is the pull request refresher. On an `idle` edge that
follows `running` or `waiting` and has `persist_requested`, it refreshes the
session's stored pull requests once (see
[Pull request providers](../git-pull-requests.md)). Stops, archives and
failures don't refresh. Listed sessions are still refreshed when stale, so a
missed edge only delays a refresh.
