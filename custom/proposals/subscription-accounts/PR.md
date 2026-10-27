<!-- Draft PR body for the subscription-accounts series; title: feat(providers): several subscription accounts per host, chosen per session -->

## Related issue

Refs #503

## Summary

Depends on: claude-config-dir (stacked; would be rebased or split for upstream).

One host can hold several Claude or Codex subscription accounts side by side, and each session picks the account it runs on. For example: two Claude Max accounts and a Databricks workspace on one host, a different one for each session, and a running Claude session moved to another account when the first runs out.

Before this, a `kind: subscription` provider always used the CLI's single login (`~/.claude` or `~/.codex`), and every session ran on its family's default provider. The design is still under discussion on #503. The series is eight commits and would go upstream as several smaller PRs in this order:

1. **Per-account login directory.** A `claude`/`codex` subscription entry accepts `config_dir`, exported as `CLAUDE_CONFIG_DIR` or as the source `CODEX_HOME`. SDK harnesses get it in the spawn env. Hosts export the default account's directory into every runner, and `omnigent claude` / `omnigent codex` apply it at startup. A spec that pins an account whose directory differs from the native CLI's fails instead of running on the wrong login. Readiness checks read that account's own login. `omnigent setup` can add another account and sign it into its own directory.
2. **Provider per session (server and host).** `POST /v1/sessions` accepts `provider_override`, the name of a `providers:` entry on the session's host. It is stored with the other session overrides, carried on forks that keep model settings, and inherited by same-family sub-agents on the same host. The host resolves the name at runner launch. An unknown provider, one that cannot serve the harness, or an account that is not signed in fails the launch with the command that signs it in, and Omnigent never falls back to another account. A claude-native runner also refuses to start Claude when the agent env or the host's startup command points it at a different login. `GET /v1/hosts/{host_id}/providers?harness=...` lists the choices with non-secret labels, the default and signed-in state.
3. **Account picker (web).** An Account section in the harness menu, next to Model and Effort, lists the host's providers for the harness. It appears only when there is more than one choice, preselects the default, and disables accounts that are not signed in. Project settings gain an Account field (stored as `provider` in the project config) that new sessions start on. When the host can't use it, the session falls back to the host default and the composer says why.
4. **Token accounts that share sessions.** A claude subscription entry accepts `token_ref` (`env:` or `keychain:`) pointing at a `claude setup-token` token. Claude reads it from `CLAUDE_CODE_OAUTH_TOKEN`, so token accounts share one `~/.claude` (transcripts, settings, skills, plugins) and differ only in which subscription pays. The runner resolves the token and passes it only to the Claude process. It never enters the runner env or the host launch frame. Removing a token account deletes its token and never runs `claude auth logout`.
5. **Switch a running Claude session (server).** `POST /v1/sessions/{id}/provider` saves the new provider and restarts the runner: immediately when every session on it is idle, otherwise after the current turns end, so no turn or pending question is cut off. Moves are limited to providers that share a Claude config directory. The listing reports an opaque `switch_group` (a hash, never the path). Owner-only, Claude harnesses only.
6. **Switch from the harness menu (web).** The in-session harness menu shows the same Account section with the current account checked, and disables accounts with the reason (not signed in, separate login).
7. **Child sessions on another account.** `sys_session_create` takes an optional `provider`. A provider the parent's runner already uses keeps the child co-located. Any other provider gets the child its own runner on the same host and workspace. The provider is validated before anything is created, and a mismatch with the child's harness deletes the child before its first message. `sys_list_models` reports `host_providers`.
8. **Docs.** New `docs/providers.md` describes the `providers:` block, both ways to add accounts, choosing and switching, and child sessions. It is linked from `docs/AGENT_YAML_SPEC.md`, and `feature-map/composer.md` gains an `account` entry for the Account menu.

Example config:

```yaml
providers:
  claude-max1: {kind: subscription, cli: claude, default: true}
  claude-max2: {kind: subscription, cli: claude, token_ref: keychain:claude-max2}
  claude-alt:  {kind: subscription, cli: claude, config_dir: ~/.claude-alt}
```

## Test Plan

Python:

```sh
uv run pytest tests/onboarding/test_subscription_accounts.py tests/onboarding/test_harness_install.py \
  tests/cli/test_configure_models.py tests/runtime/test_provider_spawn_env.py \
  tests/host/test_frames.py tests/server/test_host_registry.py \
  tests/server/routes/test_host_providers.py tests/server/routes/test_session_provider_override.py \
  tests/server/routes/test_session_provider_switch.py \
  tests/server/routes/test_subagent_status_forward_recovery.py \
  tests/server/integration/test_session_host_launch.py tests/stores/test_conversation_store.py \
  tests/runner/test_app_claude_native_launch_args.py tests/runner/test_runner_dispatch.py \
  tests/runner/test_native_subagent_inbox_delivery.py tests/tools/builtins/test_list_models.py \
  tests/harnesses/claude_native/test_claude_native_bridge.py
```

Web:

```sh
cd web && pnpm exec vitest run src/components/composer/accountSection.test.tsx \
  src/lib/sessionProvider.test.ts src/shell/NewChatDialog.test.tsx \
  src/shell/NewChatDialog.flow.test.tsx src/shell/NewChatDialog.projectCreate.test.tsx \
  src/shell/NewChatDialog.projectPrefill.test.tsx src/shell/ProjectSettingsDialog.test.tsx \
  src/pages/ChatPage.composer.test.tsx src/pages/ChatPage.mention.test.tsx \
  src/pages/ChatPage.statusLine.test.tsx src/store/chatStore.test.ts
cd web && pnpm exec tsc -b
```

Manual, on a throwaway host with test accounts:

1. Run `omnigent setup`, open Claude and add a second subscription with **Add another account (token, shares sessions)**, pasting a `claude setup-token` token. Add a third with **Add another account (own login directory)**. Check `omnigent config list` shows all three, with no token in the output.
2. `curl -s "$SERVER/v1/hosts/$HOST_ID/providers?harness=claude-native"` lists the three with labels, the default and signed-in state, and no credentials or paths.
3. In the web UI, open the new-session dialog, choose the host and claude-native, and open the harness menu. The Account section lists the three. Pick the token account and start the session, then run `/status` in the Terminal view to see which account Claude reports.
4. Sign the separate-login account out (`CLAUDE_CONFIG_DIR=~/.claude-alt claude auth logout`). The account shows as disabled in the picker. Creating a session on it over the API fails with the sign-in command.
5. In a running claude-native session on the default account, pick the token account from the in-session harness menu while idle. The toast says Claude is restarting now and the terminal comes back with the conversation intact. Repeat mid-turn: the toast says it switches after the current turn. The separate-login account is listed but disabled ("separate login").
6. Set **Project settings › Account** to the token account. A new session in that project starts with it preselected.
7. In a session whose agent has `spawn: true`, ask it to call `sys_list_models` and then `sys_session_create` with `provider` set to another account. The child appears with its own runner on that account. An unknown name returns `provider_not_found`.

## Demo

- [x] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

To capture on a clean throwaway server with dummy account names:

- [ ] TODO: screenshot of the new-session harness menu with the Account section (one account disabled as not signed in)
- [ ] TODO: screenshot of Project settings with the Account field, and the composer note when the project's account can't be used on the chosen host
- [ ] TODO: recording of switching a running claude-native session to another account from the in-session harness menu, showing the restart toast and the resumed terminal
- [ ] TODO: curl output of `GET /v1/hosts/{host_id}/providers?harness=claude-native` (no secrets or paths)
- [ ] TODO: the launch error text for an account that is not signed in

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

Signing in real subscription accounts and switching a live Claude TUI between them can't run in CI. TODO before opening: run steps 1, 3 and 5 above by hand with test accounts, then tick Manual verification. Unit and integration tests cover config parsing, launch validation (unknown, wrong-harness and signed-out providers, conflicting startup env or token), the host provider listing, the switch timing (idle vs after the turn), the owner-only check, and child-session provider routing.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Keep several Claude or Codex subscription accounts on one host, pick the account per session from the harness menu, and move a running Claude session to another account
