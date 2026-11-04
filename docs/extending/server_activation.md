# Extension server activation (experimental)

> Experimental and fork-only: the API below may change or be replaced by an
> upstream design.

An extension can run Python code in the server process: an
`async def activate(ctx)` that the server calls once at startup. Use it for
automation that reacts to sessions, such as a loop that watches a session's pull
requests and wakes the agent when CI fails.

## Declare and enable it

Name the function in the manifest as `package.module:function`. It must be in
the extension's own package, the one that holds its manifest entry point, and
its module must be a file the installed distribution recorded. Editable
installs record none, so they are never activated: install a wheel.

```python
ExtensionManifest(
    id="acme.goal-loop",
    ...,
    entrypoints=ExtensionEntrypoints(server="acme_goal_loop.server:activate"),
)
```

The server activates the extension only when the operator enabled it in the
server config, the same switch that turns on its UI slots and state:

```yaml
extensions:
  acme.goal-loop:
    enabled: true
```

`omni extensions doctor acme.goal-loop` imports the entrypoint without running
it and reports what activation would do.

`ctx` is a convenience, not a sandbox. Server code runs in the server process
with its full privileges and can reach every workspace; only operators should
install and enable it.

## Lifecycle

- **Startup.** After the server's services start, the entrypoints of the
  enabled extensions are imported, one after another, and then activated
  concurrently; each `activate` has 10 seconds. It may return `None`, or an
  `async def` with no arguments that the server calls at shutdown.
- **Time limits bound waiting, not code.** Each `activate`, deactivate function
  and command callback runs as its own task. When its time is up the server
  cancels it and stops waiting; code that ignores the cancellation keeps
  running unattended. An import, and code that blocks without awaiting, can't
  be bounded in-process: they stall the whole server.
- **Quarantine.** If activation fails (the import fails or exits, the
  entrypoint is outside the extension's package or distribution or isn't an
  `async def`, `activate` raises, cancels itself, raises `SystemExit` or times
  out), the error is logged and the extension is *quarantined*: its server
  code doesn't run until the next start. Anything it set up during `activate`
  is undone (callbacks, tasks and the wakes it requested). The server keeps
  serving. Quarantine never changes what the operator enabled: the extension's
  pages, slot items, state, commands and published fields keep working, the same
  on every replica.
- **No health checks.** Nothing quarantines or disables an extension after it
  activated. A callback or task that fails is logged (status callbacks are
  also counted); one that raises `SystemExit` fails like any other error.
- **Shutdown.** Extensions deactivate concurrently, before the server's
  services stop. The deactivate function has 5 seconds; then the extension's
  remaining tasks are cancelled, and the server waits up to 5 more seconds for
  them, so extensions hold shutdown for at most 10 seconds. A failing
  extension never stops the rest of the server's cleanup.

`GET /v1/extensions/diagnostics` (administrators) lists each activation:
`active`, `quarantined` with its error, or `stopped`.

## What `ctx` gives the extension

`ctx` is an `omnigent.server.extension_activation.ExtensionContext`, bound to
the extension's id. Calls that take a session act in the current workspace
(see `ctx.workspace`).

| Member | What it does |
| --- | --- |
| `extension_id`, `version`, `logger` | The extension's id, its manifest version, and a logger named `omnigent.extensions.<id>`. |
| `subscribe_status(callback)` | `async callback(observation)` for every [session status observation](status_observers.md). Best-effort: also reconcile on a timer. Once per extension. |
| `state.read / entries / write / clear` | The extension's own [session state](extension_state.md), as its server code: `service` keys included, published keys mirrored as labels, compare-and-set with `expected_version`. Clients watching the session list get a changed published key on the stream's next rescan (`WS /v1/sessions/updates`, every 4 seconds). |
| `state.sessions(key_prefix=None)` | An async iterator over every session, in every workspace, where the extension holds state (holding a key with that prefix), as `SessionRef(workspace_id, session_id)`, read 100 at a time. A `key_prefix` filters rows rather than narrowing the index range, so a rare prefix reads more; prefer listing without one. |
| `on_command(callback)` | `async callback(event)` after one of the extension's declared commands runs, before the command's HTTP response. All of the extension's callbacks run concurrently and together have 5 seconds. `event` is a `CommandEvent` with the session, command, key, caller and the caller's account generation. |
| `pull_requests(session_id)` | The session's linked pull requests as stored (URL, repository, number, title, state, draft), read-only, or `None`. |
| `pull_request_info(session_id, pr_url)` | One linked PR as the Pull Requests panel reads it (the `session.github.info` payload: head commit, checks, reviews, comments, mergeability), through the session's runner or host. `None` unless the session's host is connected to this replica. Raises `TimeoutError` after 30 seconds. Like the panel, the read refreshes the stored PR list. |
| `wake.request(session_id, text, *, on_behalf_of, generation, ...)` | A [session wake](session_wake.md) with `source="ext:<id>"`. Also `wake.cancel`, `wake.status`. |
| `wake.on_stop(callback)` | `async callback(session_id, reason)` when one of the extension's pending wakes is dropped (`not_authorized`, `undeliverable`, `budget_spent`, `session_gone`, `stopped_by_user`, `stopped_by_agent`). |
| `serves_session(session_id, require_host=False)` | Whether this replica owns the session (see below). With `require_host=True`, a session without a host is not served. |
| `workspace(workspace_id)` | A context manager to act in a session's workspace, e.g. for a `SessionRef`. |
| `create_task(coroutine)` | Background work, cancelled at deactivation; a failure is logged. |

Callbacks must be `async def`. Status observations and command events run in
the session's workspace already.

## Identity: on whose behalf wakes go out

The extension acts for the user who turned the automation on (the *enabler*),
never for itself:

- A user turns the automation on through one of the extension's declared
  commands. `on_command` hears it with `event.user_id` and
  `event.generation` (their account generation, `None` without account
  authentication). Record both in the extension's state before returning.
- The command has already committed, so it answers success even if the
  callback fails or runs out of time (the server logs an error). Treat a goal
  with no recorded enabler as stopped, and say so in the extension's UI.
- Background code has no request context, so `ctx.wake.request` takes
  `on_behalf_of` and `generation` explicitly: pass the recorded enabler.
- The wake service checks at every delivery that the enabler still has EDIT on
  the session, that their generation is still valid and that the extension is
  still enabled, and posts the message as the session owner with the enabler
  shown in its attribution. A failed check drops the wake and `on_stop` hears
  `not_authorized`; stop the automation then.

## Several replicas

Every replica activates every enabled extension. Each one hears only the status
edges it publishes and the commands it serves, and its wake service delivers
only to sessions whose host is connected to it. So act on a session only from
the replica that owns it: check `await ctx.serves_session(session_id)` before
polling or waking, as the session wake service does. A session with no host
counts as served on every replica, so single-owner work (a goal loop) should
check `await ctx.serves_session(session_id, require_host=True)`. Keep what must survive a restart or a
move to another replica in session state, not in memory.

A typical loop: on activation, `create_task` a reconciling poll that walks
`state.sessions()`, skips sessions without a host or that this replica doesn't
serve, and checks each
goal; use `subscribe_status` only as a hint to check one session sooner.
