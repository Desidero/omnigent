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

The second is the [session wake](session_wake.md) service: an `idle` or
`failed` edge prompts it to deliver the session's pending wakes. It also
retries on a timer, so a missed edge only delays a wake.

## Extension observers

Extensions receive the same observations, best-effort, through
`omnigent.server.extension_status_observers.ExtensionStatusObservers`. The
server builds one at startup (`app.state.extension_status_observers`) under the
same operator enablement as extension state. An activated extension subscribes
with `ctx.subscribe_status(callback)` (see
[Extension server activation](server_activation.md)), which calls
`subscribe(extension_id, callback)` on its behalf, on the server's event loop.

- **Who receives them.** Only extensions that are installed and enabled by the
  operator, as the server's `is_enabled` check reports. It runs inline on every
  status edge for every subscriber, so it must be a constant-time, in-memory
  lookup. It is checked when an extension subscribes and again before each
  observation is queued, so a disabled extension stops receiving them.
- **Async only.** A callback must be an `async def`; `subscribe` rejects any
  other callable with a `TypeError`. Callbacks run on the server's event loop,
  one at a time per extension.
- **Context.** Each callback runs in a copy of the publisher's context, so
  `current_workspace_id()` is the session's workspace.
- **Timeout.** A callback is cancelled after 10 seconds by default. One that
  ignores the cancellation keeps its place until it returns, so the extension's
  later observations wait behind it (and are dropped once the backlog is
  full); it never runs alongside another of the same extension's callbacks.
- **Bounded backlog.** Each extension may have at most 256 observations queued
  or running. Beyond that, new observations are dropped.
- **Counted, not quarantined.** Deliveries, failures, timeouts and drops are
  counted per extension (`stats()`), and the first of each kind is logged as a
  warning. None of them disables the extension.

Because observations can be dropped, an extension that acts on them must also
reconcile on its own schedule; treat an observation as a hint to check sooner.

### Shutdown

At shutdown, `aclose()` stops new deliveries and waits at most a bounded time
(2 seconds by default) for queued observations. Whatever is still queued or
running then is cancelled, abandoned and counted. This bounds how long the
application waits, not how long a callback runs: one that ignores cancellation
can keep running until the event loop closes.
