# antigravity-cooldown

Needs: none
Covers: cf653d6a2dcd3762

The `antigravity` extra locks `google-antigravity` 0.1.23 instead of 0.1.2:
`uv.toml` no longer holds the SDK at a fixed `exclude-newer-package` date,
and the antigravity harness reads a turn's token usage from
`conversation.last_turn_usage`, which the newer SDK fills in place of
`Step.usage_metadata`.

- **Turn on:** on by default for installs that take the extra
  (`pip install "omnigent[antigravity]"` with the build's constraints).
- **Docs:** none (dependency re-lock and a fix). When a refresh conflicts in
  this patch's `uv.lock` hunk, do not merge it by hand: take the new base's
  `uv.lock` (`git checkout --ours uv.lock` during the rebase), keep the
  patch's `uv.toml` change, and run
  `uv lock --upgrade-package google-antigravity`.
- **Upstream:** proposed from `fix/antigravity-cooldown` (upstream PR [#14704](https://github.com/omnigent-ai/omnigent/pull/14704)).

## Must hold

- `uv.toml` holds no fixed `exclude-newer-package` date for `google-antigravity`, so the SDK follows the normal 7-day cooldown like other packages.
- `uv.lock` locks `google-antigravity` at 0.1.23, not 0.1.2, and the re-lock changes no other package.
- A turn on the antigravity harness reports its token usage from `conversation.last_turn_usage` when the SDK sets it, so usage is not lost on SDKs that leave `Step.usage_metadata` unset.
- On an SDK that reports usage only on steps, the per-step value is still used.

## Key code

- `omnigent/inner/antigravity_executor.py`: `last_turn_usage`, `AntigravityExecutor`
- `uv.toml`: `exclude-newer-package`
- `uv.lock`: `google-antigravity`

## Tests

- `tests/inner/test_antigravity_executor.py::test_turn_usage_comes_from_conversation_when_steps_carry_none`
- `tests/inner/test_antigravity_executor.py::test_streaming_maps_text_reasoning_and_usage`
