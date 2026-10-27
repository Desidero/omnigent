<!-- Draft PR body for the claude-native-delegate-idle series; title: fix(claude-native): settle a turn on the OSC status path while a background agent or teammate runs -->
> Status: the first patch is a squashed copy of upstream PR #10849. The other three extend it and are not filed upstream yet; they could go in as review changes on #10849 or as a follow-up PR once it merges.

## Related issue

Refs #10849

## Summary

When a Claude Code turn leaves a background agent or an agent-team teammate running, Claude replies and returns to its prompt, but Omnigent keeps showing Working and queues every follow-up until the user presses Steer. Upstream PR #10849 fixes this for the status-file poller. This series carries it and covers the cases it misses.

- **OSC status path.** OSC 7501 status is on by default (`claude_osc_status`), and the runner then uses `ClaudeProgramStatusPoller`, which #10849 does not change. Claude reports OSC `working` for the delegate's whole lifetime, so the session still reads running. On current `main` the poller also lacks the `note_turn_ended`, `note_turn_started` and `reports_busy` members #10849's runner code calls, so the first `Stop` with a background agent would raise `AttributeError`. The poller now implements them. After a `Stop` that left a delegate running, the `working` report seen before the `Stop` reads idle until a turn starts again: the runner delivers one, Claude submits a prompt of its own (recorded by #10849's `UserPromptSubmit` hook), or the report leaves `working` (or disappears). A message-only change does not end the holdover, because Claude may clear the turn's OSC message just after its `Stop` reaches the runner. `reports_busy` still says working, so the idle pane reaper and the runner's idle shutdown keep the delegate alive.
- **Teammates.** Claude lists an in-process teammate in the `Stop` hook's `background_tasks` as `"type": "teammate"`. It was counted as a background shell, so the shell indicator over-counted and a lead with running teammates never got the holdover. `teammate` is now a background-agent type.
- **Teammate messages start lead turns.** When a teammate messages the lead, Claude starts a lead turn without a `UserPromptSubmit` hook and without changing the OSC report, so during the holdover that turn read idle. The transcript reader now reports when a teammate message (Claude's framed delivery with no `origin`, or `origin.kind == "peer"`) reached the main thread, and the forwarder records that record's time as the session's latest prompt, which both pollers already treat as a turn start. A message delivered while the lead was still working is older than the `Stop` and leaves the holdover alone. This builds on the teammate-delivery recognition in the `claude-native-teammates` series.
- **Known limits.** Besides #10849's: a teammate-started turn reads running only once the forwarder has read the delivery record, one transcript poll after Claude writes it. A turn Claude starts with no runner delivery, `UserPromptSubmit` hook or teammate message, and without OSC leaving `working`, reads idle.

## Test Plan

- Reproduced live on Claude Code 2.1.308 under Omnigent's OSC relay (`omnigent/terminals/program_status.py`): after Claude replied to a prompt that started a background agent running a 90 s sleep, the relay's state file stayed `working` for about 80 s, until the agent finished, then reported `done`. Claude's session status file read `busy` over the same window.
- A live lead with two running teammates recorded `Stop` payloads listing `{"type": "teammate", "status": "running"}` for each. In a throwaway agent team under the same relay, OSC stayed `working` for the teammate's whole run (about 50 s), and the lead's reply to the teammate's message fired a `Stop` but no `UserPromptSubmit`.
- `tests/harnesses/claude_native/test_claude_native_program_status.py`: a `working` report after a delegate `Stop` reads idle and stays published once; a later prompt, a runner-delivered turn, an intervening `blocked` report, and OSC dropping out and returning each read running; a message-only change, including Claude clearing the turn's message after the `Stop` reached the poller, keeps the holdover until the next prompt. All six new tests fail on the unpatched poller.
- `tests/harnesses/claude_native/test_claude_native_bridge.py`: a running teammate sets `background_agent_running` and stays out of the shell tally; a framed teammate delivery with no `origin`, or with a `peer` origin, reports its time from a transcript read, while a human-origin prompt and a sidechain record do not; a recorded delivery only moves the prompt time forward. `tests/harnesses/claude_native/forwarder/test_status.py`: forwarding a transcript with a teammate delivery records it as the prompt time; fails without the forwarder change.
- Reading the live lead transcript above with the patched reader reports its latest teammate delivery at 03:39:53.536Z, the time of its last delivery record.
- `uv run pytest tests/harnesses/claude_native tests/runner tests/terminals`: same results as the base apart from the new tests and two codex side-chat tests that flake under `-n 8` and pass alone. On macOS, about 113 tests in those suites fail on the base as well. #10849's `test_claude_prompt_during_background_agent_republishes_running` fails on macOS only, because `/var` is a symlink to `/private/var`; it passes with `TMPDIR` set to a non-symlinked directory.
- Live check on a local server and host built from this series, with Claude Code 2.1.308 in the web app and OSC status on. Five background-agent runs (three fresh sessions, two later turns of existing sessions): each time the session read idle within half a second of Claude's `started` and stayed idle while the agent ran for about 90 s; in the four runs that sent "What is 2+2?" it was answered in 2 to 10 s with no queued strip or Steer; each completion turn read Working, then idle. In one run the `Stop` reached the runner about 20 ms before Claude cleared its OSC message, the ordering that used to release the holdover and leave the session Working until the agent finished; it stayed idle. Agent team: the lead read idle after `team started`, answered a follow-up in under 3 s while the teammate worked, read Working while replying to the teammate's message, then settled. No tracebacks in the runner logs.
- Not run: #10849's nightly E2E against the real Claude CLI.

## Validate the fix live

On a server and host built from this series, in a Claude Code session in the web app:

1. Ask Claude to start a background sub-agent (Agent tool with `run_in_background`) that runs `python3 -c 'import time; time.sleep(90)'` and reports back, and to reply `started` once it has started. (Claude Code blocks a standalone `sleep 90`. With agent teams enabled, ask for a plain background agent with no name or team, or Claude may start a named teammate instead.)
2. After the reply, Working clears. Send "What is 2+2?" without pressing Steer: it is answered without a queued strip.
3. When the agent finishes, the session reads Working for the completion turn and then settles.
4. Repeat with an agent team: have the lead spawn a teammate on a long task and end its turn. The lead reads idle and takes a follow-up while the teammate works, and the background-shell indicator does not count the teammate. When the teammate messages the lead, the lead reads Working while it replies, then settles.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Evidence is in the Test Plan.

## Type of change

- [x] Bug fix
- [ ] Feature
- [ ] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [ ] E2E tests added / updated
- [x] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The unit tests pin the holdover rules, including the message clear that arrives after the `Stop`; the live check covers the real hook and OSC timing through a server and host, which the unit tests only simulate.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Claude Code sessions no longer stay Working or queue follow-ups after Claude replies while a background agent or teammate is still running
