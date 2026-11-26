# pr-refresh-main-checkout

Needs: none
Covers: c8455284294ddeca

A session started in a repository's main checkout (not a worktree) keeps
looking for pull requests at every turn end, so one opened after its first,
empty refresh shows up without anyone opening the Pull Requests panel.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** carried from another contributor's open pull request, https://github.com/omnigent-ai/omnigent/pull/14515 (closes https://github.com/omnigent-ai/omnigent/issues/12844); drop the series once it merges.

## Must hold

- A turn end refreshes a session's pull requests from its runner or host even when the session has no `git_branch` and its stored list is synced and empty.
- Nothing else about the turn-end refresh changes: it still runs only on the replica that holds the session's tunnel, after the refresher's delay, at most one at a time per session.
- The patch stays the upstream pull request's change under its author's name; only the place of its test moves when upstream adds tests at the same spot.

## Key code

- `omnigent/server/routes/sessions/routes_resources.py`: `_refresh_session_pull_requests`

## Tests

- `tests/server/routes/test_session_resources.py::test_a_main_checkout_session_synced_without_prs_keeps_refreshing`
