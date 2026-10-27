# [Bug] Deleting a session leaves its host-launched runner process running until the idle timeout

### Description

`DELETE /v1/sessions/{id}` tears down the session inside its runner (the runner-side `DELETE /v1/sessions/{id}` frees terminals, forwarders and caches) but never asks the host to stop the runner process. Stop (`stop_session`) and Archive (`_archive_stop`) both send `host.stop_runner`; Delete does not. A host-launched runner (one per session, shared by its sub-agents) therefore stays connected, holding its native pane and harness process, until `runner.idle_timeout_s` (default 3600 s) reaps it. SDK and native harnesses are affected alike.

Cause: `omnigent/server/routes/sessions/routes_events.py` (the delete route) and `omnigent/server/routes/_sessions/orchestration.py` have no delete-time counterpart of the runner stop that Stop and Archive perform.

Proposed fix: before the rows are deleted, record the `(host_id, runner_id)` pairs bound to the session and its sub-agent descendants (the ids `_best_effort_stop` already looks up). After the delete, ask the host to stop each runner that no remaining session is bound to (`list_runner_session_statuses(runner_id, limit=1)` is empty). A sub-agent rides its parent's runner, so deleting only the sub-agent leaves that runner up; deleting the parent cascades to the tree and releases it, including a runner a sub-agent moved to after a relaunch. Every step is best-effort: an offline host, a failed lookup or an already-exited runner never fails the delete. Patch ready on `fix/delete-stops-runner`.

Prior art checked: #8033 / #9304 cancel the leaked runner-side transcript forwarders after a delete, but still leave the runner process itself running; #8077 reports finished native sessions leaving panes and helper processes behind (the idle reaper), not the delete route; #10195 / #10317 / #10251 are about Archive and Stop stopping a sub-agent's shared runner, which this fix deliberately avoids for Delete.

### Steps to reproduce

1. Start `omnigent host`, create a session on it from the web UI and note the runner PID the host prints (`Runner started: … (pid=N)`).
2. Delete the session from the sidebar (or `DELETE /v1/sessions/{id}`).
3. `ps -p N` a few seconds later; compare with Stop or Archive on another session.

Expected: the runner exits within a few seconds and the host prints `Runner stopped`, as it does for Stop and Archive.

Actual: the runner stays alive and online (with its native pane and harness process for claude-native/codex-native) for up to `runner.idle_timeout_s` (default one hour). On `main` the PID was still alive 15 s after the delete for both an `openai-agents` SDK session and a `claude-native` session; with the fix it exited within 0.6 s (top-level) and 1.0–1.3 s (parent with sub-agents).

Automated: `tests/server/integration/test_session_host_launch.py::test_delete_session_stops_host_runner_once_no_session_uses_it` fails on `main` (no `host.stop_runner` frame arrives) and passes with the fix.

### Version

main @ 39611f812

### Harness

Not applicable

### Harness mode

Not applicable

### Platform or device

Linux

### Observed impact

Most users or sessions

### Authentication type

Not authentication-related
