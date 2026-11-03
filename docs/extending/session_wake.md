# Session wake

Server-side automation, such as a goal loop that watches a session's pull
requests, sometimes needs to hand an idle agent a message: "PR #7 failed CI".
The session wake service does that the same way on every harness. It waits
until the session is idle, posts the message as the session owner with a
visible automation label, and never steers it into a turn that is running.

The service is `app.state.session_wake`
(`omnigent.server.session_wake.SessionWakeService`). V1 has no HTTP route:
core modules call it directly, and server-side extension activation will bind
it to an extension's id.

## Requesting a wake

```python
from omnigent.server.session_wake import WakeRequest

outcome = await app.state.session_wake.request(
    WakeRequest(
        session_id=session_id,
        source="ext:acme.goal-loop",  # or "core:<name>"
        on_behalf_of=user_id,  # who turned the automation on
        text="PR #7: the test job failed on the head commit.",
        dedupe_key=digest_of_events,
        evidence_key=digest_of_goal_state,
        max_wakes=10,
        label="Goal loop",
    )
)
```

`request` returns one of:

| Outcome | Meaning |
| --- | --- |
| `queued` | The wake is pending and goes out at the session's next idle moment. It replaced any wake this source had pending for the session. |
| `merged` | With `merge=True`, the text was appended to the pending wake's. |
| `duplicate` | `dedupe_key` equals the last delivered wake's, or the pending one's. Nothing changed. |
| `budget_spent` | This source already delivered `max_wakes` wakes (at most 50) to the session. |
| `not_authorized` | The source is disabled, or `on_behalf_of` lacks EDIT on the session or its account generation is no longer valid. |

`cancel(session_id, source)` drops a pending wake. `status(session_id, source)`
returns whether one is pending, the wakes delivered, the budget, failures in a
row, seconds until the next wake may go out, and why the source was last
stopped. `add_stop_listener(callback)` is called with
`(session_id, source, reason)` when a pending wake is dropped at delivery time:
`not_authorized`, `undeliverable`, `budget_spent` or `session_gone`. A caller
such as a goal loop stops and posts a note then.

`on_behalf_of`'s account generation is taken from the caller's context by
default. Background callers pass the generation they saved when the user
turned the automation on as `generation`.

## When a wake is delivered

- **Only at idle.** An `idle` or `failed` status edge (a
  [core status observer](status_observers.md)) triggers delivery, and a retry
  every 15 seconds covers missed edges and sessions that were already idle. A
  wake is not sent while this server replica sees the session `running`,
  `waiting` or still starting, and only by the replica the session's host is
  connected to.
- **Authorization at every delivery.** Just before sending, the service checks
  again that the source is enabled, that `on_behalf_of` still has EDIT and that
  their account generation is still valid. If not, the wake is dropped and stop
  listeners hear `not_authorized`. A source `ext:<id>` is enabled only when the
  operator enabled extension `<id>` (`create_app(extension_is_enabled=...)`);
  `core:` sources always are.
- **As the session owner.** The message is posted inside the owner's account
  scope through the normal message path, so input policies apply as to a typed
  message. A policy denial counts as a failed delivery.
- **Pacing.** Wakes from one source to one session are at least 2 minutes
  apart. While consecutive wakes carry the same `evidence_key` (the agent took a
  turn and nothing it waits on moved) the gap doubles, up to 30 minutes.
  5 failed deliveries in a row stop the source with `undeliverable`.
- **State is per replica, in memory.** A server restart loses a pending wake
  and the counters; counters of a source with nothing pending are forgotten
  after 6 hours. Keep the automation's own state as the source of truth and
  request again when it reconciles.

## What the agent and the people see

The message text starts with one framework line, for example
`[Automation: Goal loop · on behalf of alice@example.com]`, so the model does
not take it as typed by a person. The stored item is attributed to the session
owner and carries `origin: {kind: "automation", source, on_behalf_of, label}`
(see [the Sessions API](../../omnigent/server/API.md)). The web shows an
**Automation · <label>** chip above the bubble, followed by "on behalf of" the
enabler, and hides the header line the chip replaces.

## Never mid-turn

The server's idle check can be stale: a person can start a turn in a native
terminal, or a queued message can start one, between the check and the
delivery. So the message carries `delivery: "next_turn_only"`, and the decisive
check happens where turns start, in the runner and the harness:

- **SDK harnesses.** The runner runs one turn at a time. A wake that arrives
  mid-turn waits in the runner's queue for the next turn and is never injected
  into the running one.
- **Native harnesses.** A native turn is typed into the agent's own terminal
  or app, and the runner's delivery returns as soon as the input is typed. So
  the runner holds a next-turn-only message while it sees a turn of its own, a
  queued message, a pending approval, the terminal's own `running` or
  `waiting` status, or a keypress in the terminal within the last 5 seconds.
  Messages people send are not held behind it. A waiter checks every second
  and releases the message through the runner's ordered queue, which checks
  again. Stop, interrupt and delete drop held messages.
- **The harness has the last word.** The harness checks once more under its
  own injection lock, just before typing. If it is busy it refuses with
  `next_turn_busy`, and the runner holds the message again instead of failing
  the turn.

| Harness | Final check, under the harness's injection lock | Status |
| --- | --- | --- |
| SDK harnesses | The runner runs one turn at a time; no live injection. | Verified (runner tests, mock-provider e2e) |
| `claude-native` | No pending question, permission prompt or dialog only the terminal shows (MCP approval, settings error, …); Claude's status file is not `busy`/`waiting`; the input box is empty (or shows only Claude's `Try "…"` suggestion). Nothing is typed, and the box is not cleared, until then. | Verified (unit tests; live check pending) |
| `codex-native` | Codex core is asked which turn is active (a `turn/steer` probe that adds no input); the message only ever goes out as `turn/start`, never `turn/steer`. | Verified (unit tests; live check pending) |
| `pi-native` | The resident extension leaves the message in its inbox while Pi's agent loop runs (`agent_start`…`agent_end`), then sends it as a follow-up that starts a turn; it never steers it. | Verified (extension tests; live check pending) |
| Other native harnesses | The runner's hold only, plus a screen that stayed unchanged for 5 seconds, because pane output is their only turn signal. | Unverified |

The automation chip and stored item are the same for every harness. A native
message gets its `origin` when the terminal transcript mirrors it back; a
wake held longer than the pending-input lifetime (10 minutes) arrives without
it, still with its `[Automation: …]` line.
