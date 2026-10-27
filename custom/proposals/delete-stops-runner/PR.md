# fix(server): stop a deleted session's host-launched runner

## Related issue

Closes #<to be filed>

## Summary

ELI5: deleting a session cleaned up its work inside the runner but never told the host to end the runner process, so the process kept running for up to an hour.

- **Cause.** `DELETE /v1/sessions/{id}` sends the runner-side `DELETE /v1/sessions/{id}`, which frees the session's terminals, forwarders and caches, but never sends `host.stop_runner`. Stop (`stop_session`) and Archive (`_archive_stop`) both do. A host-launched runner (one per session, shared by its sub-agents) therefore stayed connected, holding its native pane and harness process, until `runner.idle_timeout_s` (default 3600 s) reaped it. This affects SDK and native harnesses alike.
- **Fix.** Before the rows are deleted, the route records the `(host_id, runner_id)` pairs bound to the session and its sub-agent descendants (the ids `_best_effort_stop` already looks up, read with one batched `get_conversations`). After the delete, it asks the host to stop each runner that no remaining session is bound to (`list_runner_session_statuses(runner_id, limit=1)` is empty).
- **Sub-agents.** A sub-agent inherits its parent's runner, so deleting only the sub-agent leaves the runner up for the parent and siblings. Deleting the parent cascades to the tree and releases the runner, as well as any runner a sub-agent moved to after a relaunch.
- Every step is best-effort: an offline host, a failed lookup, or a runner that already exited (an "unknown runner" reply, logged at debug) never fails the delete.

## Test Plan

- New `tests/server/integration/test_session_host_launch.py::test_delete_session_stops_host_runner_once_no_session_uses_it` (real host tunnel, fake host): inline-launches a host session with three sub-agents on its runner and moves one sub-agent to a runner of its own. Deleting one sub-agent sends no `host.stop_runner`; deleting the parent sends one for the parent's runner and one for the moved sub-agent's runner, and the remaining sub-agents are gone.
  - Fails on `main` (no stop frame arrives).
  - Mutation checks: it fails when the "still bound" check is removed (deleting the sub-agent stops the shared runner) and when descendant bindings are ignored (the moved sub-agent's runner is not stopped).
- Real-process check with a real server, host daemon and host-launched runners, for `openai-agents` (SDK) and `claude-native` (real `claude` in tmux). Each case deletes a top-level session, deletes a sub-agent of a second session, then deletes that parent with another sub-agent still attached:

  | | `main` | this branch |
  |---|---|---|
  | Top-level session deleted | runner PID alive 15 s later, runner online | runner exits within 0.6 s |
  | Sub-agent deleted | parent's runner alive | parent's runner alive |
  | Parent with sub-agent deleted | runner PID alive 15 s later, runner online | runner exits within 1.0 s (SDK), 1.3 s (native) |

  No server errors were logged in either run.
- On this rebase onto `main` @ 39611f812: `uv run pytest tests/server/integration/test_session_host_launch.py -q` (85 passed, includes the new test) and `pre-commit run --files <changed files>` are clean. Earlier, on the base the patch was written against, nearby suites also passed: `test_host_session_binding.py`, `test_sessions_endpoints.py`, `test_sessions_crud.py`, `test_session_worktree_delete*.py`, `test_routes_sessions_aliases.py`, `test_managed_startup_inputs.py`, `test_sessions_deleted_cursor_truncation_e2e.py`, `test_default_public_sessions.py`, `test_sessions_archive.py`, `tests/runner/test_delete_session_bridge_cleanup.py`, `tests/dev/test_verify_omnigent_feature_map.py`.

```sh
uv run pytest tests/server/integration/test_session_host_launch.py -k delete_session_stops_host_runner
```

Manual: start `omnigent host`, create a session on it from the web UI, note the runner PID the host prints (`Runner started: … (pid=N)`), delete the session, and check that the PID exits within a few seconds (`ps -p N`) and the host prints `Runner stopped`.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

N/A: backend change; the before/after process table is in Test Plan.

## Type of change

- [x] Bug fix
- [ ] Feature
- [ ] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [ ] Unit tests added / updated
- [x] Integration tests added / updated
- [ ] E2E tests added / updated
- [x] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The integration test drives the real delete route against a real host tunnel with a fake host. The real-process check above (server, host daemon, host-launched SDK and claude-native runners) was run by hand with a throwaway test; it is not added to the suite because the integration test already covers the server's decision, and the host's handling of `host.stop_runner` is covered by the existing Stop and Archive tests. A host that is offline when the session is deleted still leaves its runner to the idle timeout, as Stop and Archive do.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
