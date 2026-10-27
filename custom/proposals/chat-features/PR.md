<!-- Draft PR body for the chat-features series; title: feat: per-session chat features, starting with Run suggested commands -->
## Related issue

Closes #TODO (issue to be opened)

## Summary

Depends on: session-labels-ui, new-chat-project-prompt, chat-item-labels, subscription-accounts, gateway-request-tags (stacked; would be rebased or split for upstream).

Some chat features only work if the agent writes in a particular way, so they need both a UI piece and an instruction to the agent. This PR makes each such feature a per-session switch: turning one off removes both its UI and its instruction, and you can pick which features new sessions start with.

The first such feature is the Run button for agent-suggested shell commands. Most agent code blocks carry no language tag, so the button only finds shell commands reliably when the agent is told to tag them as `bash`. That instruction costs prompt tokens in every session, and not every user or agent wants the convention.

```text
chat_features.py registry ──> GET /v1/chat-features (titles for the web)
        │
session create: request > creator's shared-preference default > all features
        │
session_overrides ──> runner init snapshot + every forwarded turn ──> prompt.py appends enabled instructions
        └──────────> web shows Run only when run_commands is enabled
```

- **Registry.** `omnigent/runtime/chat_features.py` lists features (key, title, description, instruction). Adding a feature is one entry plus its renderer. `GET /v1/chat-features` serves titles and descriptions to the web.
- **Per-session set.** Stored in `session_overrides` (no migration) and resolved at create from the request, then the creator's saved default, then every feature. Forks copy the parent's set; sub-agent and mirrored child sessions inherit it; scheduled and imported sessions use the owner's default. Existing sessions get every feature. `PATCH /v1/sessions/{id}` takes `chat_features`; `null` resets it to the caller's default.
- **Per-user default.** A new shared-preference key, `{"kind": "chat_features", "name": "default"}`: a sorted, unique array of feature keys, where `[]` enables none and `null` removes the choice (every feature). Unknown keys are kept in storage and ignored on resolve, so builds that add features can share the value. Session create reads it server-side with the same identity as the shared routes; a failed read falls back to every feature instead of failing the create.
- **Without shared preferences.** The default needs `shared_preferences_authority_id` in the server config (or a preference store passed to `create_app`). Without it, new sessions get every feature, per-session toggles still work, and Settings > General shows the default switches disabled with a note.
- **Web preference client.** Reads and saves through `GET /v1/preferences/shared` and `POST /v1/preferences/shared/operations`: follows pagination (restarting if an edit lands between pages), sends `expected_version`, retries an unanswered edit with the same `operation_id`, and on conflict re-reads and retries once. Settings shows competing values from other devices with a Keep button each. The installation ID is stable per browser.
- **Runner and harnesses.** The runner receives the set in the session init snapshot and with every forwarded turn. SDK harnesses compose instructions per turn, so a change applies on the next turn. Native Claude and Codex take instructions only at launch (including `omnigent claude` / `omnigent codex` resumes, which now read the session's set), so the web menu notes that a change reaches the agent after a restart. Claude Code honours only the last `--append-system-prompt`, so ours is merged into a user-supplied one.
- **Web UI.** Toggles in the new-chat dialog's agent menu, the session configure menu and Settings > General > Chat features; Run is shown only when the session's set includes `run_commands`.
- Docs: `docs/shared-preferences-api.md`, `feature-map/preferences.md`, and the "Turn it on or off" section of `docs/run-suggested-commands.md`; `openapi.json` regenerated.

## Test Plan

Python tests added or changed:

- `tests/runtime/test_chat_features.py`, `tests/runtime/test_prompt.py`: registry parsing/encoding and instruction composition.
- `tests/server/integration/test_sessions_chat_features.py`: default saved through the real routes, create-time resolution, unknown keys, removal, server without the API, PATCH and reset.
- `tests/server/scheduled/test_fire.py`, `tests/server/integration/test_sessions_harness_override.py`, `tests/server/integration/test_sessions_endpoints.py`, `tests/server/routes/test_native_smart_routing_create.py`, `tests/server/conftest.py`: inheritance for scheduled, forked and routed sessions.
- `tests/stores/test_conversation_store.py`, `tests/stores/test_preference_store.py`, `tests/test_preferences.py`, `tests/test_preference_sync.py`: storage and the new preference kind.
- `tests/runner/test_session_init_protocol.py`, `tests/runner/test_runner_dispatch.py`, `tests/runner/test_app_sessions_native_terminals_autocreate.py`, `tests/runner/test_app_sessions_native_terminals_runtime.py`: wire format and per-turn forwarding.
- `tests/harnesses/claude_native/test_claude_native.py`, `tests/harnesses/claude_native/test_claude_native_bridge.py`, `tests/harnesses/codex_native/test_codex_native.py`, `tests/harnesses/codex_native/session/test_terminal_prepare.py`, `tests/test_native_terminal.py`: native launch instructions and `--append-system-prompt` merging.

Web tests added or changed: `src/lib/chatFeatures.test.ts`, `src/lib/chatFeaturesApi.test.ts`, `src/lib/sharedPreferencesApi.test.ts`, `src/lib/runnableCommands.test.ts`, `src/lib/sessionsApi.test.ts`, `src/pages/settings/ChatFeaturesSettingsGroup.test.tsx`, `src/pages/SettingsPage.test.tsx`, `src/pages/ChatPage.composer.test.tsx`, `src/shell/NewChatDialog.test.tsx`, `src/shell/NewChatDialog.flow.test.tsx`, `src/shell/NewChatDialog.projectPrefill.test.tsx`, `src/store/chatStore.test.ts`.

```sh
uv run pytest tests/runtime/test_chat_features.py tests/runtime/test_prompt.py \
  tests/server/integration/test_sessions_chat_features.py tests/server/scheduled/test_fire.py \
  tests/server/integration/test_sessions_harness_override.py tests/server/integration/test_sessions_endpoints.py \
  tests/server/routes/test_native_smart_routing_create.py tests/stores/test_conversation_store.py \
  tests/stores/test_preference_store.py tests/test_preferences.py tests/test_preference_sync.py \
  tests/runner/test_session_init_protocol.py tests/runner/test_runner_dispatch.py \
  tests/runner/test_app_sessions_native_terminals_autocreate.py tests/runner/test_app_sessions_native_terminals_runtime.py \
  tests/harnesses/claude_native/test_claude_native.py tests/harnesses/claude_native/test_claude_native_bridge.py \
  tests/harnesses/codex_native/test_codex_native.py tests/harnesses/codex_native/session/test_terminal_prepare.py \
  tests/test_native_terminal.py
cd web && pnpm exec vitest run src/lib/chatFeatures.test.ts src/lib/chatFeaturesApi.test.ts \
  src/lib/sharedPreferencesApi.test.ts src/lib/runnableCommands.test.ts src/lib/sessionsApi.test.ts \
  src/pages/settings/ChatFeaturesSettingsGroup.test.tsx src/pages/SettingsPage.test.tsx \
  src/pages/ChatPage.composer.test.tsx src/shell/NewChatDialog.test.tsx src/shell/NewChatDialog.flow.test.tsx \
  src/shell/NewChatDialog.projectPrefill.test.tsx src/store/chatStore.test.ts
cd web && pnpm exec tsc -b
```

Manual:

1. Start a server without `shared_preferences_authority_id`. Settings > General > Chat features shows the switch disabled with a note. Start an SDK-harness session and ask "How do I list files here?": the reply tags the command as `bash` and shows a Run button.
2. In that session's configure menu, turn off "Run suggested commands". On the next turn the Run button is gone and the agent no longer gets the tagging instruction (check the turn's composed instructions or ask again and see untagged blocks are not given a Run button).
3. In the new-chat dialog's agent menu, turn the feature off before creating a session; confirm `GET /v1/sessions/{id}` reports `chat_features: []`.
4. Restart the server with `shared_preferences_authority_id` set. In Settings, turn the default off; start a new session and confirm it starts with the feature off. Fork it and confirm the fork keeps the parent's set.
5. Open Settings in a second browser profile, change the default there and in the first profile at the same time: the losing side shows the competing value with a Keep button; saving resolves it.
6. In a claude-native session, toggle the feature: the menu notes it applies after restart. Restart the session and confirm the instruction is applied, including when the agent config already passes its own `--append-system-prompt`.

## Demo

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: screenshot of Settings > General > Chat features, enabled and disabled-with-note states (throwaway server)
- [ ] TODO: screenshot of the toggle in the new-chat dialog's agent menu and in the session configure menu, including the native "applies after restart" note
- [ ] TODO: recording of turning the feature off in a session and the Run button disappearing on the next turn
- [ ] TODO: screenshot of a competing-edit row with its Keep button
- [ ] TODO: curl output of `GET /v1/chat-features` and a `PATCH /v1/sessions/{id}` with `chat_features`

## Type of change

- [ ] Bug fix
- [x] Feature
- [x] UI / frontend change
- [ ] Refactor / chore
- [x] Docs
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

Server integration tests drive the default through the real shared-preference routes; web tests cover pagination restarts, retries, conflicts and the disabled Settings state with stubbed responses. No browser journey covers the toggles yet; the manual steps above cover them.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Turn chat features such as Run suggested commands on or off per session, or choose the default for new sessions in Settings, dropping both the UI and the agent instruction when off
