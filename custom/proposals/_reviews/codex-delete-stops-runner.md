# Codex review: delete-stops-runner

Command: `codex exec -C <worktree> --sandbox read-only -` with the maintainer-review prompt, the repo's CLAUDE.md and `git diff -U40 <base>...HEAD` piped on stdin (`codex review --base` rejects a custom prompt, and the bundled bubblewrap sandbox cannot run commands in this environment, so the diff was supplied inline). Model: gpt-6.1-sol (codex-cli 0.159.2). Reviewed at the rebase onto upstream/main 3f2ccf56e.

## Disposition

1. [P2] Missing unit coverage for the failure handling of `_host_runner_bindings` and `_stop_released_host_runners` — **fixed**: added `tests/server/routes/test_delete_released_host_runners.py` (4 tests, fakes only): tree bindings collected, descendant lookup failure keeps the session's own binding, a still-bound runner is skipped and a free one stopped with `expect_already_stopped=True`, and a failing "still bound" check or a raising host stop does not stop the loop or raise. Amended into the commit.

## Raw output

```
I’ll review the supplied diff against CLAUDE.md, focusing on runner ownership, deletion ordering, and test coverage. I won’t run shell commands.
I’m GPT-6 (Codex). Reviewed only the supplied diff; no commands or tests run.

- **[P2] Missing unit coverage for the new teardown helpers — `omnigent/server/routes/_sessions/orchestration.py:787–854`.** CLAUDE.md explicitly requires unit tests for non-trivial functions. The integration test covers successful subtree cleanup and preserving a shared runner, but neither helper has focused coverage for its failure handling. Add tests proving that a failed binding lookup preserves the runner, a failed host stop does not prevent stopping subsequent runners, and teardown failure does not turn an already-completed deletion into an HTTP error. These are important contracts because the conversation rows have already been irreversibly deleted when teardown runs.

I found no definite correctness bug in the supplied context. The implementations of `list_runner_session_statuses` and `_stop_session_host_runner` were not included, so their filtering, timeout, and rejection behavior remain unverified.

To verify manually: create a host session with a sub-agent, delete the sub-agent and confirm the parent still works; then delete the parent and confirm its runner process exits within seconds. Repeat with the host disconnected and confirm deletion still succeeds.
```
