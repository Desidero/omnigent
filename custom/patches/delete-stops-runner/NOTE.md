# delete-stops-runner

Needs: none
Covers: cd5e33232fd1db82

Deleting a session stops its host-launched runner once no remaining session
uses it.

- **Turn on:** on by default.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`delete`).
- **Upstream:** proposed from `fix/delete-stops-runner`.

## Must hold

- `DELETE /v1/sessions/{id}` stops each host-launched runner the deleted session tree was bound to, once no remaining session is bound to that runner.
- Deleting only a sub-agent leaves the runner it shares with its parent running; deleting the parent stops the runners the whole tree used, including one a sub-agent moved to after a relaunch.
- The stop runs as a retained background task after the rows are deleted, so a slow or silent host does not hold the DELETE response.
- A failure to check or stop one runner is logged and does not block the other runners or the delete; a runner whose remaining sessions cannot be checked is left running, and a runner that has already exited is not an error.

## Key code

- `omnigent/server/routes/_sessions/orchestration.py`: `_host_runner_bindings`, `_stop_released_host_runners`, `_spawn_released_host_runner_stop`, `_detached_stop_tasks`
- `omnigent/server/routes/sessions/routes_events.py`: `_host_runner_bindings`, `_spawn_released_host_runner_stop`

## Tests

- `tests/server/integration/test_session_host_launch.py::test_delete_session_stops_host_runner_once_no_session_uses_it`
- `tests/server/routes/test_delete_released_host_runners.py::test_stop_released_host_runners_skips_a_runner_another_session_uses`
- `tests/server/routes/test_delete_released_host_runners.py::test_host_runner_bindings_cover_the_session_tree`
- `tests/server/routes/test_delete_released_host_runners.py::test_stop_released_host_runners_keeps_going_past_failures`
- `tests/server/routes/test_delete_released_host_runners.py::test_spawned_stop_does_not_hold_the_caller`
