# claude-native-subagent-status

Needs: none
Covers: 85c6e302ce142cfc

A Claude sub-agent that is still shown as working when its parent records its
result is settled then: idle for a completed result, failed for a failed one.
Without it, a sub-agent killed in the middle of a tool call stays "running"
until the forwarder's ten-minute mid-turn window runs out.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** not proposed. Upstream fixed the other half of this series
  (a sub-agent in a long tool call stays "running") in PR [#13811](https://github.com/omnigent-ai/omnigent/pull/13811), so that half
  was dropped; the open upstream PR [#12411](https://github.com/omnigent-ai/omnigent/pull/12411) also touches this code.

## Must hold

- When a parent records a Claude sub-agent's result while that child still shows as running or waiting, the server sets the child to idle for a completed result and to failed for a failed one.
- A child that is not running or waiting keeps its status.
- A retried (deduplicated) result settles nothing, so a child that was resumed after the first delivery is not cut short; neither does a result whose child is only discovered later.

## Key code

- `omnigent/server/subagent_activity.py`: `_settle_returned_claude_child_status`, `_record_claude_subagent_return`

## Tests

- `tests/server/routes/test_subagent_activity.py::test_claude_completion_survives_retries_and_late_child_discovery`
