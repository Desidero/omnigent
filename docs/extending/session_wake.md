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

`label` (at most 64 characters) and `on_behalf_of` (at most 256) appear in the
one-line header, so `request` raises `ValueError` if either holds `]`, a newline
or another control character. `evidence_key` has no default: without one, wakes
are simply at least 2 minutes apart (see Pacing).

`cancel(session_id, source)` drops a pending wake. `status(session_id, source)`
returns whether one is pending or in flight, the wakes delivered, the budget,
failures in a row, seconds until the next wake may go out, and why the source
was last stopped. `add_stop_listener(callback)` is called with
`(session_id, source, reason)` when a source's wake is dropped or a person
stops the turn its delivered wake started. The same stop can be reported more
than once (a second Stop of that turn, for example), so make the callback
idempotent:

| Reason | When | What a caller such as a goal loop does |
| --- | --- | --- |
| `stopped_by_user` | A person stopped or interrupted the session while this source's wake was pending or in flight, or while the session was in a turn whose input was this source's delivered wake (see Stop wins below). | Pause; don't request again until something new happens. |
| `stopped_by_agent` | An orchestrating agent stopped or interrupted it (`sys_cancel_task`) while this source's wake was pending or in flight. | Pause, as above. |
| `not_authorized` | Checked at delivery (see below). | Stop and post a note. |
| `undeliverable` | 5 failed deliveries in a row. | Stop and post a note. |
| `budget_spent` | `max_wakes` reached. | Stop. |
| `session_gone` | The session was deleted, archived or closed. | Stop. |

`on_behalf_of`'s account generation is taken from the caller's context by
default. Background callers pass the generation they saved when the user
turned the automation on as `generation`.

## When a wake is delivered

- **Only at idle.** An `idle` or `failed` status edge that ends a turn (a
  [core status observer](status_observers.md)) triggers delivery, and a retry
  every 15 seconds covers missed edges and sessions that were already idle. The
  `idle` a Stop, an archive or an orphaned turn's settlement publishes doesn't
  count. A wake is not sent while this server replica sees the session
  `running`, `waiting` or still starting, never to an archived or closed session
  (that stops the source with `session_gone`), and only by the replica the
  session's host is connected to.
- **Stop wins.** A Stop or interrupt from the web or the API drops every
  source's pending and in-flight wake for the session, and stop listeners hear
  `stopped_by_user` (or `stopped_by_agent` when an orchestrating agent sent
  it). A person's Stop can also stop the source of a wake already delivered,
  with `stopped_by_user`, when all of these hold at that moment: the server
  sees the session `running` or `waiting`; no other message is on its way to
  the runner (a person's message still queued or being dispatched came after
  the wake); no wake is being posted or in flight (that wake would be the
  newest input, so no earlier one is looked for); and the session's latest
  turn-starting input is that wake. The latest turn-starting input is the
  newest stored user message, hidden ones included, or slash command, looked
  for past the turn's output up to 5,000 stored items back: a Stop of a turn
  longer than that doesn't stop the wake's source (the server logs a warning).
  A hidden message stored in the wake's own turn (context delivered with it)
  doesn't count; one from a later turn (a timer or notification) does, as does
  a person's `/skill` or message. A Stop of an idle session, and an agent's
  interrupt, stop no delivered wake's source. The runner drops the wakes it
  holds or has queued behind a turn on every harness, and Pi's extension drops
  the ones waiting in its inbox. If the Stop arrives while a wake is being
  posted, the service asks the runner to drop that one queued wake as soon as
  the post returns, and a post that fails after a Stop doesn't bring the wake
  back. A wake the runner already started (or an SDK message already
  persisted) can't be taken back, and a client that loaded the session during
  that post may show the taken-back wake as a queued bubble until it reloads.
  A Stop typed in the native terminal itself (Escape, ctrl+c) isn't seen by
  the server, so it does not drop pending wakes.
  A delivered wake stays in the transcript and counts toward `max_wakes`
  whether or not its turn was stopped. What the Stop leaves behind depends on
  the harness (see the table below): on `claude-native`, Claude Code puts a
  stopped prompt it never answered back into its input box, as it does for a
  person's message stopped early. A wake's text shows there as
  `[Pasted text #N …]`; it holds later wakes until someone clears the box, and
  pressing Enter sends it again. Omnigent leaves that draft alone, because it
  can't tell it apart from one a person typed.
- **One at a time.** On a native session a wake stays *in flight* from the
  moment the runner takes it until the terminal records it in the transcript.
  Meanwhile new requests only replace or merge the pending text on the server;
  nothing more is sent. A wake counts toward `max_wakes` and pacing only once
  its message is persisted (at once on SDK sessions): when the transcript
  mirror settles the wake's queued input, by its text or in order, even if that
  happens before the post returns. An in-order settlement takes a wake's queued
  input only for text that starts with the `[Automation:` header; for other
  text it passes over queued wakes, so a person's message behind one still
  settles and the wake stays queued for its own mirror. If it is dropped before that (a
  Stop, or the runner's 10-minute hold limit), it counts as a failed delivery.
- **Authorization at every delivery.** Just before sending, the service checks
  again that the source is enabled, that `on_behalf_of` still has EDIT and that
  their account generation is still valid. If not, the wake is dropped and stop
  listeners hear `not_authorized`. A source `ext:<id>` is enabled only when the
  operator enabled extension `<id>` (`extensions.<id>.enabled: true` in the
  server config, or `create_app(extension_is_enabled=...)`); `core:` sources
  always are. Once a wake has reached the runner it is not
  checked again: one the runner is still holding goes out when the session is
  idle unless someone stops or interrupts the session first.
- **As the session owner.** The message is posted inside the owner's account
  scope through the normal message path, so input policies apply as to a typed
  message, with the owner as `event.context.actor`. The automation is in
  `event.context.origin` (`kind`, `source`, `on_behalf_of`, `label`), so an
  operator can write policies for automation and its enabler (see
  [Policies](../POLICIES.md)). A policy denial counts as a failed delivery.
- **Pacing.** Wakes from one source to one session are at least 2 minutes
  apart. While consecutive wakes carry the same `evidence_key` (the agent took a
  turn and nothing it waits on moved) the gap doubles, up to 30 minutes.
  `merge=True` appends only to text not yet sent; a request that arrives while
  a wake is being posted starts a new pending wake.
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
  After it types a message (not a bare slash command such as `/model` or
  `/cost`, which may start no turn) into a claude, codex or pi terminal, it
  treats the turn as running until that terminal reports `idle` or `failed`,
  because the terminal's own status can lag the prompt it just took. If no
  `running` edge from the terminal itself (not the runner's own publish)
  followed within 20 seconds, the delivery counts as settled
  (the command started no turn, or an edge was lost); the harness's own check
  below still decides. Messages people send
  are not held behind it. A waiter checks every second and releases the
  message through the runner's ordered queue, which checks again. Stop,
  interrupt and delete drop held messages, and so does a hold older than
  10 minutes (the server's record of the queued input expires with it).
- **The harness has the last word.** The harness checks once more under its
  own injection lock, just before typing. If it is busy it refuses with
  `next_turn_busy`, and the runner holds the message again (retrying after
  5 seconds) instead of failing the turn. The runner publishes no `running`
  edge for a native wake, so a refusal changes no status; the terminal reports
  its own turn's edges once it starts one.

| Harness | Final check, just before the turn starts | After a Stop of an unanswered wake turn | Status |
| --- | --- | --- | --- |
| SDK harnesses | The runner runs one turn at a time; no live injection. | The turn ends; nothing is left to send. | Verified (runner tests, server and runner integration test, live check on claude-sdk) |
| `claude-native` | No pending question, permission prompt or dialog only the terminal shows (MCP approval, settings error, …); Claude's status file (found by the session's live processes and the pane's pid) is not `busy`/`waiting`; and the input box is read whole and empty, or shows only Claude's `Try "…"` suggestion. A draft, shell mode, the ctrl+r history search, an overlay, a draft taller than the terminal or a box that can't be read all keep it waiting; a box hidden by output another process printed over it is repainted once (as for a person's message) and read again. A routed `/model` switch is typed only into that empty box. Where a person's message waits inside the executor (for a question, a dialog or an input box that won't read clear), a wake is refused back to the runner's hold instead. A wake never dismisses a surface or clears a draft; it checks the box again just before pasting and refuses if anything appeared. Known limits: a real draft that starts with `Try "` reads as Claude's suggestion, and vim mode's NORMAL state is untested. | Claude Code puts the wake's text back in its input box as `[Pasted text #N …]`, which holds later wakes until it is cleared (Enter sends it again). | Verified (unit tests and a live check) |
| `codex-native` | The runner reads the Codex terminal's composer just before it hands the wake to the harness: only a composer showing nothing or Codex's own dimmed placeholder (e.g. `Ask Codex to do anything`) is free; a draft, shell mode, a disabled composer or an unreadable pane keeps the wake held. (Codex takes the turn over its app-server, which a draft doesn't block, and the harness has no access to the pane, so this read happens in the runner; nothing is ever typed into or cleared from the composer.) Then Codex core is asked which turn is active (a `turn/steer` probe that adds no input); the message only ever goes out as `turn/start`, never `turn/steer`. If the probe gets no answer, the bridge's record decides and a warning is logged. | The wake went to Codex over its app-server, not through the composer, so the composer keeps only what a person typed there (not live-checked). | Verified (unit tests; live check of turn rules; draft hold pending a live check) |
| `pi-native` | The resident extension leaves the message in its inbox while Pi's agent loop runs (`agent_start`…`agent_end`), then sends it as a follow-up that starts a turn; it never steers it. An interrupt drops the wakes waiting there. | The wake was sent by the extension, not typed into Pi's editor (not live-checked). | Verified (extension tests; live check pending) |
| Other native harnesses | The runner's hold only, plus a screen that stayed unchanged for 5 seconds, because pane output is their only turn signal. | Depends on the terminal; the runner typed the wake like a person's message. | Unverified |

The automation chip and stored item are the same for every harness. A native
message gets its `origin` when the terminal transcript mirrors it back; a
wake is never held longer than that record lives (10 minutes). A native wake
the mirror settles only in order (its mirrored text didn't match), or records
after its queued input was dropped or expired, is stored without `origin`:
it shows no chip, and a Stop of its turn stops no source.
