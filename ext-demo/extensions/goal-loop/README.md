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
| Goals page | **All PRs in this session** (every PR the session links now and later), one box per linked PR, each PR's goal state and wakes used, **Resume** on a paused goal, and **Stop all goals**. |
| Session row badge | The published `goal`: Watching (`eye`), Needs work (`octagon-alert`), Met (`circle-check`), Stopped (`square-parking`), Paused (`circle-ellipsis`). |
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
  runs, when its 10 wakes are spent, or when the wake service drops the wake
  as `undeliverable` or `session_gone`; `not_authorized` ends only the goals
  of the person who lost access. Turning a goal on again, including after
  "Stop all", restarts it. "Stop all" on a session whose host is connected to
  another replica clears the toggles at once and leaves the goals to that
  replica's next check, which also drops toggles set in the same second as the
  stop.
- **Pauses.** A person stopping the session (the web's Stop, or an interrupt
  through the API) while the loop's wake is waiting, or stopping the turn that
  wake started, **pauses** every active goal in the session, whoever turned it
  on. A paused goal shows on the page as, for example, "Paused by Stop · 1/10
  wakes · Resume to continue" (people who can only read the session are told
  someone who can edit it can resume it), the badge and summary say paused,
  and it is not read or woken for, even when its PR changes. **Resume** on the
  Goals page carries it on where it stopped: the wakes it used still count
  toward its budget, and its wakes now go out on behalf of the person who
  resumed it. Events reported by earlier wakes stay reported. When the Stop
  ended the turn of a delivered wake, that wake's events are owed: after
  Resume the next check reads the PR as usual, and if that doesn't end the
  goal (met, merged, closed), reads it again against what was reported before
  that wake; events found that way are reported again, as a new wake with its
  own dedupe key, after the usual gap between wakes. If that read fails, the
  goal asks for no wake (not even for new events) until a later check reads
  it, so nothing owed is left out; they are owed again if the new wake is
  stopped or dropped in turn. A Stop that only dropped a waiting wake owes
  nothing: that wake's events were never reported, so they come back by
  themselves. So the next check may wake the agent for a PR that is still red.
  Turning a toggle on again (clear and tick a box, or **All PRs** off and on)
  restarts the goals that toggle asks for from scratch, with a fresh budget,
  as for an ended goal: **All PRs** restarts the paused goals of PRs without
  their own box setting. A toggle set before the Stop doesn't undo it. A
  paused goal whose PR is merged is met ("merged"), and one whose PR is closed
  ends ("closed"), without being read. Resume on a goal that isn't paused
  (met, stopped, or ended by its budget) changes nothing. An orchestrating
  agent stopping the session, or the wake service's own per-session budget,
  only holds back the same events; new ones are sent. A Stop typed in the
  agent's own terminal isn't seen by the server, so it pauses nothing.
- **State** (extension session state, so it survives restarts and moves):

  | Key | Visibility | Holds |
  | --- | --- | --- |
  | `all`, `pr:<owner>/<repo>/<n>` | editors | `on`/`off` toggles, written by commands |
  | `stop`, `resume`, `refresh` | editors | control keys the commands write; `stop` and `resume` (the paused goal's PR) are cleared once applied, `refresh` is answered (a fresh view and a check) and left set |
  | `enablers` | service | who last set each toggle or resumed a goal, and their account generation |
  | `g:<digest of the PR URL>` | service | one envelope per goal: status (including `paused`), reason, enabler, reported-event state, wakes, the reported state from before its last wake (`before_wake`, for a Stop of that wake's turn), whether that wake's events are owed (`unhandled`, then `reoffer` once resumed) and how often they were offered again (`reoffers`) |
  | `loop` | service | the requested wake's dedupe key, delivery mark and enabler, the last enabler woken, the events held back per enabler, and a "Stop all" count |
  | `goals` | readers | the page's view |
  | `goal`, `count`, `summary` | published | the badge, the active goal count and the label |

  A session keeps at most 25 goals; the oldest ended ones make room for new PRs.
  Paused goals are kept, so a session full of them enrols no new PR until one
  is resumed, turned off or ends.

## Known gaps

- **No notes in the transcript.** The session wake service has no path for a
  note that starts no turn (the `pr-watch` series posted one), so neither a met
  goal nor a stop (budget spent, undeliverable, not authorized, turned off) is
  written to the transcript. They show only as the published `goal` badge and
  summary and as each PR's note on the Goals page. Adding a no-turn note is a
  core change.
- **One Resume at a time.** `resume` holds one PR; two Resumes sent within the
  same moment may apply only the later one, and the other goal stays paused
  until Resume is pressed again. A Resume is applied on behalf of the person
  who sent it only when that person also wrote the `resume` value being
  applied; otherwise (crossed Resumes, or a Resume whose command callback was
  lost and that a later check applies) the goal resumes for the person it was
  already running for.
- **A Stop with a newer wake waiting.** If the loop's next wake is already
  waiting when a person stops a delivered wake's turn, the session wake
  service drops the waiting wake and reports one stop. The loop takes it for a
  Stop that only dropped a waiting wake, so the stopped turn's events are not
  owed; the dropped wake's own events still come back after Resume.
- **A Stop on another replica.** The wake service's record of a delivered
  wake lives on the replica that serves the session's host. A Stop handled
  on another replica can't see it, so a wake delivered just before that Stop
  isn't counted toward the goal's budget, and its events may be reported
  again after Resume.
- **Teardown counts as a Stop.** A host stop or a CLI teardown during a wake's
  turn sends `stop_session` without an agent's marker, so the server takes it
  for a person's Stop and the session's goals pause. Resume continues them.
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

# The whole chain without GitHub: a real server, host and runner, a mock LLM
uv run pytest tests/e2e/test_goal_loop_pr_green_e2e.py
```

### Test without GitHub

`tests/_helpers/fake_gh.py` installs a fake `gh` that the host and its runner
find first on `PATH`. It answers the Pull Requests panel's calls from a JSON
scenario the test edits (head commit, checks, comments, reviews,
mergeability), and records any call it can't answer so the test fails instead
of reading "no PR". The end-to-end test above uses it to link a PR from the
session's branch, wake the agent on a failing check and meet the goal on a
green head, in under a minute.

## Credits

- The detection, dedupe and stop rules, their instructions to the agent and
  their tests are ported from Desidero's `pr-watch` series ("watch a session's
  pull requests until they're green"), which ran as a core patch with its own
  poll loop, label storage and delivery.
- Analytic Endeavors' pull-request receipts, a parallel idea; no code is taken
  from them.
