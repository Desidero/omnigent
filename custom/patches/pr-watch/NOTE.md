# pr-watch

Needs: none
Covers: b19a4904fa7d51ed

A session watches its pull requests: while it is idle, the server wakes it with
one message about failed checks, comments and reviews from the repository's
owners, members and collaborators, and merge conflicts, until each PR is green,
merged or closed. Chosen from **Watch PRs** in the composer bar (all of the
session's PRs, or single ones) or **Watch until green** in the Pull Requests
panel.

- **Turn on:** `OMNIGENT_FEATURES=pr_watch` on the server (off by default). `OMNIGENT_PR_WATCH_INTERVAL_S` (90, at least 15) and `OMNIGENT_PR_WATCH_MAX_WAKES` (10, at most 50) tune it.
- **Docs:** [PR watch](../../feature-map/pr-watch.md).
- **Upstream:** not proposed upstream yet. Upstream has the turn-end PR refresh, owner-only PR changes (https://github.com/omnigent-ai/omnigent/pull/14896), trigger automations and timers (https://github.com/omnigent-ai/omnigent/pull/14760); none of them tells a session about its own PRs.

## Must hold

- A wake-up is sent only while the session is idle: not during a turn and not while it waits on an approval or a question. Events found meanwhile wait and are coalesced, across PRs, into one message.
- It is sent as the session's owner through the normal message path, so input policies apply; a refused or failed delivery is retried, and five in a row end the watch.
- Each failed check (per head commit), comment, review and conflict is reported once. Text from anyone who is not an owner, member or collaborator of the repository never reaches the agent.
- Each PR has a wake-up budget; green, merged, closed, budget spent, unreadable checks or undeliverable wake-ups end its watch with a transcript note that starts no turn, and "all" mode does not pick it up again.
- The session's PRs come from the server's stored list: an unlink ends the watch, a PR stored as merged or closed is never read, and "all" mode enrols nothing until the list is imported. The watcher asks the upstream refresher for a read instead of listing PRs itself.
- Only the session's owner changes a watch (403 for editors and viewers); anyone with read access sees it. Clients cannot write the `omnigent.pr_watch` labels, and a fork does not copy them.
- With the feature off the routes return 404, the controls are absent and no poller runs.
- TODO(owner): in a main checkout, "all" mode sees a PR opened outside the session only with `pr-refresh-main-checkout` in the build; PRs the agent opens are reported by its runner either way, so that series is not a need.

## Key code

- `omnigent/server/pr_watch.py`: `PullRequestWatcher`, `evaluate`, `baseline_state`, `wake_message`, `stop_note`, `build_pr_watcher`, `append_note`
- `omnigent/server/routes/sessions/routes_pr_watch.py`: `register_pr_watch_routes`, `OWNER_ONLY_WATCH_MESSAGE`
- `omnigent/server/routes/sessions/routes_events.py`: `_ServerEventContext`, `send_server_message`
- `omnigent/server/routes/sessions/routes_resources.py`: `read_pr_info`
- `omnigent/server/routes/_sessions/helpers.py`: `is_pr_watch_label`
- `omnigent/stores/conversation_store/sqlalchemy_store.py`: `list_label_family_conversations_all_workspaces`
- `omnigent/runner/github_resource.py`: `_mergeable`, `_optional_text`
- `omnigent/server/feature_flags.py`: `PR_WATCH`
- `web/src/components/composer/ComposerPrWatch.tsx`: `ComposerPrWatch`
- `web/src/shell/PullRequestWatch.tsx`: `PullRequestWatchSwitch`
- `web/src/hooks/usePullRequestWatch.ts`: `usePullRequestWatch`

## Tests

- `tests/server/test_pr_watch.py`
- `tests/server/routes/test_session_pr_watch.py`
- `tests/server/routes/test_session_pr_watch.py::test_a_server_sent_message_acts_as_the_user_it_is_sent_for`
- `tests/server/routes/test_session_resources.py::test_the_pr_watch_reader_reads_like_the_panel`
- `tests/server/routes/test_session_resources.py::test_a_server_sent_message_reaches_the_runner_like_a_typed_one`
- `tests/server/integration/test_policy_deny_lifecycle_e2e.py::test_server_message_goes_through_input_policy`
- `tests/runner/test_github_reviewers.py`
- `web/src/components/composer/ComposerPrWatch.test.tsx`
- `web/src/shell/PullRequestWatch.test.tsx`
