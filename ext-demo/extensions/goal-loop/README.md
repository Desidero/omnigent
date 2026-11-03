# Goal loop extension

`desidero.goal-loop` keeps a session working on a goal until the goal is met,
the same way on every harness. It has one goal type, **`pr-green`**: keep the
session's pull requests green. When a check fails on a PR's head commit, a
repository owner, member or collaborator comments or reviews, or the PR stops
merging cleanly, the loop wakes the agent at its next idle moment with what
changed. When CI passes, the PR merges cleanly and no trusted reviewer is
asking for changes, the goal is met and the session's badge turns green.

It is built only from extension APIs: server activation
([`server_activation.md`](../../../docs/extending/server_activation.md)),
session state, published fields and commands
([`extension_state.md`](../../../docs/extending/extension_state.md)), the session
wake service ([`session_wake.md`](../../../docs/extending/session_wake.md)),
status observers and the UI slots.

## Use it

| Where | What |
| --- | --- |
| Composer action **Goals** | Opens the Goals page. While goals run its label is the published `summary`, e.g. "Watching 2 PRs". |
| Goals page | **All PRs in this session** (every PR the session links now and later), one box per linked PR, each PR's goal state and wakes used, and **Stop all goals**. |
| Session row badge | The published `goal`: Watching (`eye`), Needs work (`octagon-alert`), Met (`circle-check`), Stopped (`square-parking`). |
| Session row tooltip | The `summary`. |
| Session row menu | **Stop all goals** (asks first). |

Turning a goal on, off or stopping all needs edit access to the session; anyone
who can read it sees the badge, the summary and the page (read-only).

Wake messages arrive as **Automation · Goal loop**, on behalf of the person who
turned that goal on, and only when the session is idle. A message lists only the
PRs with something new (at most 15 events per PR, about 8,000 characters in
all), for example:

```text
[Automation: Goal loop · on behalf of alice@example.com]
Goal: PR green — #7 needs attention

Pull request: https://github.com/org/repo/pull/7 (head 1a2b3c4)

What changed:
- Check failed: lint — https://github.com/org/repo/actions/runs/…

You are watching this pull request until it is green. …
```

## Install and enable

Server code runs only from an installed wheel, and only when the operator
enables the extension:

```bash
cd ext-demo/extensions/goal-loop
uv build --wheel
uv pip install dist/desidero_goal_loop-0.1.0-py3-none-any.whl   # into the server's environment
```

```yaml
# ~/.omnigent/config.yaml
extensions:
  desidero.goal-loop:
    enabled: true
```

`DESIDERO_GOAL_LOOP_INTERVAL_S` (default 90, at least 5) sets how often the
loop re-checks every session with goals; an idle edge also checks a session
about 5 seconds later.

## How it works

- **Goal types.** `goals.py` declares the interface: `targets` (what "All"
  enrols), `baseline`, `check` (new events, red or not, met or stopped),
  `wake_text`, `stop_text`. `pr_green.py` implements it; the docstring of
  `goals.py` sketches what a second type would look like.
- **The loop** (`loop.py`) re-checks on a timer, plus soon after a session's
  turn ends (a status observation is only a hint). It checks and writes goals
  only on the replica the session's host is connected to
  (`ctx.serves_session(sid, require_host=True)`), and writes them with
  compare-and-set, so a concurrent change wins and the next check re-reads.
  It reads each PR with `ctx.pull_request_info(session_id, pr_url)`, the Pull
  Requests panel's payload; a PR that can't be read (host offline, a timeout)
  is skipped for that check only.
- **Wakes** go through `ctx.wake.request` on behalf of the person who set the
  goal's toggle (their user and account generation, recorded from the
  command), with a `dedupe_key` digested from the reported events and an
  `evidence_key` digested from each PR's head, checks, mergeability and reviews
  (the wake service backs off while it doesn't change). There is one wake at a
  time per session, so goals turned on by different people take turns. Events
  count as reported only once the wake service has delivered the wake; a
  dropped wake is asked for again at the next check.
- **Stops.** A goal ends when it is met (`green`, or `merged`), when its PR is
  closed or its checks are unreadable, when it is turned off or "Stop all"
  runs, when its 10 wakes are spent, or when the wake service drops the wake as
  `undeliverable` or `session_gone`; `not_authorized` ends only the goals of
  the person who lost access. A person (or an orchestrating agent) stopping the
  session, or the wake service's own per-session budget, only **pauses**: the
  same events are not sent again, new ones are, and one person's paused
  goals don't hold back anyone else's. Turning a goal on again,
  including after "Stop all", restarts it. "Stop all" on a session whose host
  is connected to another replica clears the toggles at once and leaves the
  goals to that replica's next check, which also drops toggles set in the
  same second as the stop.
- **State** (extension session state, so it survives restarts and moves):

  | Key | Visibility | Holds |
  | --- | --- | --- |
  | `all`, `pr:<owner>/<repo>/<n>` | editors | `on`/`off` toggles, written by commands |
  | `stop`, `refresh` | editors | control keys the commands write; `stop` is cleared once applied, `refresh` is answered (a fresh view and a check) and left set |
  | `enablers` | service | who last set each toggle, and their account generation |
  | `g:<digest of the PR URL>` | service | one envelope per goal: status, reason, enabler, reported-event state, wakes |
  | `loop` | service | the requested wake's dedupe key, delivery mark and enabler, a paused key, and a "Stop all" count |
  | `goals` | readers | the page's view |
  | `goal`, `count`, `summary` | published | the badge, the active goal count and the label |

  A session keeps at most 25 goals; the oldest ended ones make room for new PRs.

## Known gaps

- **No notes in the transcript.** The session wake service has no path for a
  note that starts no turn (the `pr-watch` series posted one), so neither a met
  goal nor a stop (budget spent, undeliverable, not authorized, turned off) is
  written to the transcript. They show only as the published `goal` badge and
  summary and as each PR's note on the Goals page. Adding a no-turn note is a
  core change.
- **Older GitHub readers.** Trusted-author filtering uses `author_association`
  on comments and reviewers, repeat reviews use each reviewer's `submitted_at`,
  and conflicts use `mergeable`. From a reader without them, no comment or
  review text reaches the agent (a requested change still keeps the goal
  unmet), a second review in the same state is missed, and conflicts fall back
  to `merge_state_status == "DIRTY"`.

## Develop

```bash
# Page bundle (committed under src/desidero_goal_loop/dist)
cd ext-demo/extensions/goal-loop/web
../../../../web/node_modules/.bin/vite build && node scripts/ensure-newline.mjs
../../../../web/node_modules/.bin/vitest run --root .
../../../../web/node_modules/.bin/tsc -p tsconfig.json

# Server code
uv run pytest tests/extensions/goal_loop tests/server/test_goal_loop_extension.py
```

## Credits

- The detection, dedupe and stop rules, their instructions to the agent and
  their tests are ported from Desidero's `pr-watch` series ("watch a session's
  pull requests until they're green"), which ran as a core patch with its own
  poll loop, label storage and delivery.
- Analytic Endeavors' pull-request receipts, a parallel idea; no code is taken
  from them.
