# subscription-accounts

Needs: claude-config-dir
Covers: 526bf480b599a52f

Several Claude or Codex subscription accounts on one host: pick the account a
new session runs on, give a project a default account, switch a running Claude
session to another account, keep Claude token accounts that share one
`~/.claude`, and let agents start a child session on another account.

- **Turn on:** add entries to `providers:` in `~/.omnigent/config.yaml` with
  `config_dir` (own login) or `token_ref` (shared login), or run
  `omnigent setup` and add another account. The **Account** menu appears once
  a harness has more than one provider.
- **Docs:** [Model providers](../providers.md); the menu in
  [Composer](../../feature-map/composer.md) (`account`) and child accounts in
  [Native harnesses](../../feature-map/native-harnesses.md) (`child-account`).
- **Upstream:** proposed from `feat/subscription-accounts` (design on upstream
  issue [#503](https://github.com/omnigent-ai/omnigent/issues/503)).

## Must hold

- A `claude` or `codex` subscription provider with `config_dir` runs on that directory's login (`CLAUDE_CONFIG_DIR` for Claude, the source `CODEX_HOME` for Codex); an entry without it keeps the CLI's default login, and a host exports its default accounts' directories to every runner it launches.
- A `claude` subscription provider with `token_ref` shares the host's `~/.claude`; its token reaches only the Claude process as `CLAUDE_CODE_OAUTH_TOKEN`, never the runner's environment or the host launch frame, and removing the account deletes the token without signing out the shared login.
- A session created with `provider_override` (stored and returned on the session, carried on forks that keep model settings) runs on that provider of its host and never on a fallback: the API rejects the choice where the host cannot apply it or the agent pins another credential in `executor.auth`, and the launch fails, naming the account, when the provider is unknown, cannot serve the harness, is not signed in, or the launch env would start Claude on another login directory or token.
- `GET /v1/hosts/{host_id}/providers?harness=...` returns names, labels, the default, signed-in state and an opaque `switch_group`, never credentials or directory paths; the web **Account** section is hidden with one choice, and a project's default account falls back to the host default with a visible reason.
- `POST /v1/sessions/{id}/provider` (owner only, Claude harnesses only) saves the provider and restarts the runner at once when every session on it is idle, otherwise when their turns end; it refuses a target that is not configured, not signed in, or in another `switch_group`.
- A sub-agent in the same provider family on the same host inherits its parent's provider; `sys_session_create` with `provider` (with `agent_id` only; `sys_list_models` lists the choices under `host_providers`) keeps the child on the parent's runner when that runner already uses the provider and otherwise gives it its own runner on the same host and workspace, and such a child does not wake its parent.
- Smart Routing never treats a session on its own account (`provider_override`, or a child whose account differs from its parent's) as gateway-backed: the workspace router and the static gateway model table stay out, and the built-in judge answers from the catalog that session's own runner resolved (a native create on a chosen account routes on its first prompt instead). Sessions without an override are routed as before.

## Key code

- `omnigent/onboarding/subscription_accounts.py`: `session_runner_env`, `provider_choices`, `claude_account_env`, `require_session_account_dir`, `host_provider_summary`
- `omnigent/onboarding/provider_config.py`: `SESSION_PROVIDER_ENV`, `SUBSCRIPTION_CONFIG_DIR_ENV`, `SUBSCRIPTION_TOKEN_ENV`
- `omnigent/server/routes/_sessions/helpers.py`: `_validated_provider_override`, `_inherited_provider_override`
- `omnigent/server/routes/sessions/routes_provider.py`: `switch_session_provider`, `_SWITCHABLE_HARNESSES`
- `omnigent/runner/child_account.py`: `choose_child_account`, `require_child_harness`
- `omnigent/server/routes/_sessions/orchestration.py`: `_gateway_backed`, `_on_own_account`, `_own_runner_catalog`

## Tests

- `tests/onboarding/test_subscription_accounts.py::test_session_runner_env_fails_loudly`
- `tests/runner/test_app_claude_native_launch_args.py::test_auto_create_claude_terminal_hands_claude_the_account_token`
- `tests/server/routes/test_session_provider_switch.py::test_busy_session_switches_once_its_turn_ends`
- `tests/runner/test_runner_dispatch.py::test_sys_session_create_on_another_account_gets_its_own_runner`
- `tests/server/routes/test_native_smart_routing_create.py::test_a_chosen_provider_is_never_counted_as_gateway_backed`
- `tests/server/integration/test_routing_integration.py::test_a_child_on_a_chosen_account_is_routed_within_that_account`
- `web/src/components/composer/accountSection.test.tsx`
