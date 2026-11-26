# link-rules

Needs: chat-item-labels
Covers: 1af1d71054a781d0

Short references in chat messages (`BST-2135`, `PR #123`, `!123`,
`owner/repo#123`, `session:<id>`) render as links, from rules each user sets in
Settings and agents can change with approval. Git hosts are stored as `git`
rules (GitHub, GitLab, Azure DevOps, plus self-hosted ones); the session's
repository picks the one that links bare `#123`, and GitHub links
`owner/repo#123` in every session. In a git checkout, agents are asked to say
`issue #123` or `PR #123`. While any rule is on, the rules take the place of
upstream's built-in pull request links (`#1234`, `owner/repo#12` in github.com
sessions).

- **Turn on:** GitHub, GitLab, Azure DevOps and session references are on by
  default. Edit, add (**Add git host** for GitHub Enterprise or a self-managed
  GitLab) or turn on rules in Settings → General → **Chat links**; saving needs
  `shared_preferences_authority_id` in the server config. A saved rule of the
  old `github` kind reads as the GitHub `git` rule. Agents use
  `sys_link_rules`, and each change waits for your approval.
- **Docs:** [Chat link rules](../chat-link-rules.md),
  [Server API](../../omnigent/server/API.md) (Chat Link Rules),
  [Shared preference operations](../shared-preferences-api.md),
  [Agent YAML](../AGENT_YAML_SPEC.md) (`tool_groups.link_rules`) and
  [Preferences](../../feature-map/preferences.md) (`chat-link-rules`).
- **Upstream:** not proposed yet: no pull request is open. It is to go up from
  `feat/chat-link-rules`, the git-reference part (issue and pull request
  notation, its instruction) from `feat/git-ref-notation`; the related upstream
  issue is [#11176](https://github.com/omnigent-ai/omnigent/issues/11176) (open).

## Must hold

- Rules are one per-user shared preference (`link_rules`): the defaults apply until a list is saved, `GET /v1/link-rules` always answers, and on a server without shared preferences the defaults are read-only (`PUT` is 409). A stale `expected_version` is refused with 409 and stores no conflict, so a save from Settings or `sys_link_rules` never overwrites a newer list; `null` restores the defaults.
- The server validates every rule on both write paths (`PUT /v1/link-rules` and the shared-preference operation) and answers 422 with the rule and field at fault: a raw regex stays in the subset Python and every supported browser parse alike, a `url` template has a fixed http(s) scheme and host before any placeholder, a `git` host is a bare host name. The web client runs the same checks again when it compiles a rule.
- A saved rule of the old `github` kind reads as the GitHub `git` rule and is stored in the new form on the next write; `{"kind": "github"}` is accepted on input until 0.22.0.
- In the chat, rules link agent and user messages after item labels and file links, never inside links, inline code, code blocks or raw HTML, with every capture percent-encoded. A bare `#123` links only through the `git` rule of the session's repository host and stays text in a session without a repository; `owner/repo#123` links to GitHub in every session while the GitHub rule is on.
- Every `sys_link_rules` `add`, `update` and `remove` waits for the user's approval even when no other policy applies (`__ask_on_link_rule_change`); `list` is not gated, and `tool_groups.link_rules: false` removes the tool.
- Agents are told each enabled rule's syntax in one framework instruction, with the `issue #123` / `PR #123` sentence only when the workspace is a git checkout and no instruction when every rule is off. SDK harnesses get it per turn; native Claude and Codex get it at launch only.

## Key code

- `omnigent/link_rules.py`: `validate_link_rules`, `compile_pattern`, `check_url_template`, `DEFAULT_LINK_RULES`, `session_git_rule`, `git_reference_instruction`
- `omnigent/server/routes/preferences.py`: `create_link_rules_router`, `LINK_RULES_PREFERENCE_KEY`
- `web/src/lib/linkRules.ts`: `compileLinkRules`, `remarkLinkRules`, `findLinks`, `sessionGitRule`
- `omnigent/runner/tool_dispatch.py`: `_execute_link_rules_tool`, `_changed_link_rules` (the approval policy, ask_on_link_rule_change, is in the built-in safety policies)
- `omnigent/runtime/prompt.py`: `link_rule_instructions`, `build_native_startup_instructions`, `is_git_checkout`

## Tests

- `tests/test_link_rules.py::test_unsafe_patterns_are_rejected`
- `tests/server/routes/test_link_rules.py::test_stale_version_is_refused_without_storing_a_conflict`
- `tests/runner/test_link_rules_tool_dispatch.py::test_every_change_asks_and_listing_does_not`
- `tests/runtime/test_prompt.py::test_git_wording_only_in_a_git_checkout`
- `web/src/components/blocks/ChatMarkdown.linkRules.test.tsx` ("chat link rules": where links apply and how git references resolve)
