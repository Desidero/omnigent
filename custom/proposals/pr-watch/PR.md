<!-- Draft PR body for the pr-watch series; title: feat(sessions): watch a session's pull requests until they're green -->
## Related issue

Closes #TODO (issue to be opened)

## Summary

Depends on: subscription-accounts (stacked; would be rebased or split for upstream).

After an agent opens a pull request, someone still has to keep an eye on it and tell the agent when CI fails or a reviewer comments. This adds an opt-in watcher that does that: it checks the session's PRs in the background and wakes the agent when there is something to fix, until the PR is green. It is behind the default-off `pr_watch` feature flag and works with any harness.

- **Composer control.** A "Watch PRs" chip in the composer bar, next to the PR link, opens a popover with "All PRs in this session" (every PR it tracks now and any it opens later) and one box per open PR with its title, CI state and wake-ups used. Unchecking one PR while All is on keeps the rest. The chip reads "Watching N PRs" while active. The Pull Requests panel gains a "Watch until green" switch bound to the same state.
- **Poller.** `omnigent/server/pr_watch.py` runs one poller per server. It reads each watched PR through the same path as the Pull Requests panel (runner, else host, running the provider CLI with the host's account), so it adds no credentials. It reports failed checks on the head commit, comments and reviews from other accounts, and merge conflicts, each once, coalesced across PRs into one `[System: PR watch ...]` message sent through the normal message path (so input policies apply to it, as to a typed message), only while the session is idle. In All mode it enrols PRs as the session's tracked list grows, skipping merged and closed ones.
- **Prompt-injection guard.** Only comments and reviews from the repository's owners, members and collaborators count; anyone else's text never reaches the agent.
- **Stopping.** Each PR's watch ends with a transcript note that starts no turn when its checks pass with no changes requested, it is merged or closed, its wake-up budget (default 10) is spent, checks cannot be read, or five wake-ups in a row could not be delivered. The ended state is kept so All mode does not pick the PR up again.
- **State without a migration.** Watch state lives in server-reserved session labels (`omnigent.pr_watch.mode` for All, plus a URL and a state label per PR keyed by a hash of its URL, values capped at 256 characters), so it survives restarts. Forks drop the whole family, and clients can only change it through `GET`/`PUT`/`PATCH`/`DELETE /v1/sessions/{id}/pr-watch`, which require edit access.
- **Provider payload.** The GitHub payload gains `mergeable`, each reviewer's `submitted_at`, and comment and review `author_association`, so conflicts, repeat reviews and trusted authors can be detected.
- Tuning: `OMNIGENT_PR_WATCH_INTERVAL_S` (default 90) and `OMNIGENT_PR_WATCH_MAX_WAKES` (default 10).
- `feature-map/pr-watch.md` documents the sub-features, entry points and gotchas, including the `pr_watch` flag and both tuning variables with their defaults and bounds; `openapi.json` is regenerated.

## Test Plan

Tests added or changed:

- `tests/server/test_pr_watch.py`: event detection, dedupe, coalescing across PRs, All-mode pick-up, idle-only delivery, trusted-author filtering, stop rules.
- `tests/server/routes/test_session_pr_watch.py`: route permissions, feature gate, modes, baseline, reserved labels.
- `tests/server/test_feature_flags.py`, `tests/server/integration/test_utility_endpoints.py`: the new `pr_watch` flag.
- `tests/server/integration/test_policy_deny_lifecycle_e2e.py`: a server-sent wake-up is checked by input policies and a DENY refuses it.
- `tests/stores/test_conversation_store.py`: store support for the watcher's reserved labels.
- `tests/runner/test_github_resource.py`, `tests/runner/test_github_reviewers.py`: new payload fields.
- `web/src/components/composer/ComposerPrWatch.test.tsx`, `web/src/shell/PullRequestWatch.test.tsx`: composer popover modes and per-PR toggles, panel switch, refusal messages, flag gating.

```sh
uv run pytest tests/server/test_pr_watch.py tests/server/routes/test_session_pr_watch.py \
  tests/server/test_feature_flags.py tests/server/integration/test_utility_endpoints.py \
  tests/server/integration/test_policy_deny_lifecycle_e2e.py tests/stores/test_conversation_store.py \
  tests/runner/test_github_resource.py tests/runner/test_github_reviewers.py
cd web && pnpm exec vitest run src/components/composer/ComposerPrWatch.test.tsx src/shell/PullRequestWatch.test.tsx
cd web && pnpm exec tsc -b
```

Manual (use a scratch GitHub repository the host's `gh` account can read and push to):

1. Start the server with `OMNIGENT_FEATURES=pr_watch OMNIGENT_PR_WATCH_INTERVAL_S=15`. Open a session whose workspace is a checkout of the scratch repo.
2. Have the agent open two PRs, one with a deliberately failing check. Click "Watch PRs" and turn on "All PRs in this session"; the chip reads "Watching 2 PRs".
3. Wait one interval: one `[System: PR watch ...]` message lists only the red PR and the agent starts a turn; the green PR gets a "stopped" note that starts no turn.
4. Attach or open a third PR and confirm the next poll picks it up.
5. From an account that is not a collaborator, comment on a watched PR: no wake-up. Comment as a collaborator: a wake-up quotes it.
6. In another session select two red PRs, uncheck one, and confirm the wake-up lists only the other. Toggle "Watch until green" in the Pull Requests panel and confirm the chip updates.
7. As a view-only collaborator, confirm the boxes are disabled with a reason.
8. Restart the server without the flag: the chip and panel switch are gone and the `/pr-watch` routes return 404.

## Demo

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: screenshot of the "Watch PRs" popover with All and per-PR boxes (throwaway server, scratch repo PRs)
- [ ] TODO: screenshot of the Pull Requests panel's "Watch until green" switch
- [ ] TODO: recording of a failing check producing one wake-up message and the agent's turn, then a stop note when the PR turns green
- [ ] TODO: curl output of `GET`/`PUT /v1/sessions/{id}/pr-watch`, including the 404 with the flag off

## Type of change

- [ ] Bug fix
- [x] Feature
- [x] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [x] Integration tests added / updated
- [ ] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Poller and route tests use stubbed provider payloads; a live drive against real PRs and CI needs a scratch repository and is described in the manual steps and `feature-map/pr-watch.md`.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.
