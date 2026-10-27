<!-- Draft PR body for the codex-native-mode-instructions series; title: fix(codex-native): let Codex apply its own Plan and Default mode instructions -->
## Related issue

Closes #TODO (issue to be opened)

## Summary

Switching a codex-native session into Plan mode silently dropped Codex's planning instructions for any agent that has its own instructions. Omnigent now leaves the mode's instructions to Codex.

Toggling Plan mode, and starting a Default-mode implementation turn, sent the agent's configured `developer_instructions` as the collaboration mode's `developer_instructions`. Codex's app-server treats that field as the mode's own instructions: a null is filled with the built-in Plan or Default preset (`normalize_collaboration_mode`, present since Codex 0.129), and any value replaces it. The configured `developer_instructions` are a separate session setting that these updates never touch. Echoing them therefore:

- dropped Plan mode's planning instructions for every agent with authored instructions, and
- repeated the authored text in the mode section of the prompt.

The fix sends `developer_instructions: null` in both places (the runner's Plan toggle and the forwarder's Default-mode turn), so Codex applies its preset. Authored instructions keep reaching Codex through the bridge's `config.toml`, which these updates leave as written. The unreadable-config guard on the Plan toggle (which returned 503) only protected the echoed value, so it is removed along with its test.

## Test Plan

Tests changed:

- `tests/harnesses/codex_native/forwarder/test_instructions.py::test_default_collaboration_mode_keeps_codex_mode_instructions`: a Default-mode turn sends `null`.
- `tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_codex_native_plan_mode_change_keeps_codex_mode_instructions`: drives the real runner HTTP path; the Plan toggle sends `null` in `thread/settings/update` and the configured `developer_instructions` in `config.toml` are unchanged. The 503-on-unreadable-config test is removed with the guard.

```sh
uv run pytest tests/harnesses/codex_native/forwarder/test_instructions.py tests/runner/test_app_sessions_native_events_lifecycle.py
```

Manual:

1. Create a codex-native agent with instructions, e.g. `instructions: "Always answer in one sentence."`, and start a session.
2. Toggle Plan mode in the web UI and ask for a plan to add a feature. Codex behaves as in Plan mode (asks clarifying questions, proposes a plan, does not edit files) and still follows the one-sentence instruction where it applies.
3. Accept the plan so Codex starts a Default-mode implementation turn; it implements normally.
4. Optional: in the Codex TUI or app-server log, the collaboration mode carries the built-in preset rather than the authored text.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: attach the `thread/settings/update` request body from an app-server log before and after (authored text vs `null`), captured on a throwaway server with a dummy agent

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
- [x] Integration tests added / updated
- [ ] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The forwarder test pins the Default-mode payload; the runner test drives the plan-mode event through the runner's HTTP app against a fake app-server client and checks the persisted config is untouched.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Codex-native Plan mode keeps Codex's built-in planning instructions for agents that set their own instructions
