<!-- Draft PR body for the link-rules series; title: feat: chat link rules for short references -->
## Related issue

Related to #11176 (its chat-markdown part: a configurable plugin that links issue keys, skipping `a`, `code` and `pre`, on the provider's own host).

## Summary

Depends on: chat-features (the shared-preference client and Settings group pattern) and chat-item-labels/chat-item-comments (the chat markdown it extends); stacked, would be rebased or split for upstream.

Short references in chat messages (`BST-2135`, `PR #123`, `owner/repo#123`, `session:<id>`) are plain text. This adds per-user link rules that turn them into links, editable in Settings and by agents with approval. The git-reference part (git hosts per provider, the issue/PR instruction) overlaps a separate proposal from `feat/git-ref-notation`; whichever goes first, the other rebases onto it.

```text
Settings > Chat links ──PUT──┐                     ┌── GET ── transcript: remark pass after item labels
sys_link_rules (asks first) ─┴─> /v1/link-rules ──>│                      (skips links, code, pre, html)
                                 validates, stores │
                                 link_rules shared └── GET ── runner / native launch: "Chat links: ..." instruction
                                 preference
```

- **Rules.** `{name, kind, pattern, url, enabled}`; `kind` is `url`, `git` (`{provider, host}`: one git host on GitHub, GitLab or Azure DevOps, a bare host name) or `session` (`session:<id>[/<message id>]` opens the in-app `?message=` deep link). Defaults: GitHub (`github.com`), GitLab (`gitlab.com`), Azure DevOps (`dev.azure.com`) and Sessions on, a short-form and a regex example off.
- **Git references.** The session's repository (host from its URL or a known PR, never assumed) picks the `git` rule for its host, else the first enabled rule for the provider the server resolved; that rule links `#123`, `issue #123`, `PR #123` / `MR #123` and the provider's `!123`. Without a repository a bare `#123` stays text. The GitHub rule links `owner/repo#123` in every session; in a session on another host, a qualified reference stays there when it is under the session's top-level group, has more than two segments or uses `!`.
- **Pattern safety.** Rules run in every viewer's browser and agents can write them, so `omnigent/link_rules.py` validates on save and `web/src/lib/linkRules.ts` re-checks on compile: short forms (`BST-{num}`, `{key}`, `{id}`) or a `/regex/` subset with no backreferences, lookaround, named groups or inline flags (older Safari can't parse named groups or lookbehind), no repeated group containing a repeat or `|`, at most three repeats capped at 64, 200 characters. URL templates must be http(s) with a fixed scheme and host before any placeholder; captures are percent-encoded and the href is re-parsed.
- **Storage.** The `{"kind": "link_rules", "name": "default"}` shared preference (a JSON array in a string, canonicalized). `GET`/`PUT /v1/link-rules` serve the effective rules and a versioned whole-list write that refuses stale edits instead of storing a conflict.
- **Rendering.** A remark pass after item labels, like `remarkItemLabels`; never inside links (file links included), code or raw HTML; agent and user messages. The runner's GitHub, GitLab and Azure DevOps resources now report the repository URL so a session without a PR knows its host. Streamdown's memo ignores `remarkPlugins`, so a message is keyed on its matchers and re-parses when they arrive.
- **Agents.** `sys_link_rules` (list/add/update/remove, runner-proxied, native relay, `tool_groups.link_rules`). Changes ASK through `__ask_on_link_rule_change`, injected like the scheduled-task approval. A short framework instruction lists the enabled syntaxes, plus, only in a git checkout, a sentence asking for `issue #123` / `PR #123` and `owner/repo#123` (and `!123` where the workspace remote's rule uses it): per turn for SDK harnesses, at launch for native ones.
- Docs: `docs/chat-link-rules.md`, `omnigent/server/API.md`, `docs/shared-preferences-api.md`, `docs/AGENT_YAML_SPEC.md`, `feature-map/preferences.md`; `openapi.json` regenerated.

## Test Plan

- `tests/test_link_rules.py`: compiler, unsafe patterns and templates, git hosts, which git rule a session uses, the earlier `github` kind read and saved as a `git` rule, canonical storage, mutation validation.
- `tests/server/routes/test_link_rules.py`: defaults, per-user saves, stale versions, invalid rules (both write paths), no shared preferences.
- `tests/runner/test_link_rules_tool_dispatch.py`: the tool against the real routes, registration, approval policy.
- `tests/runtime/test_prompt.py` (including the git checkout gate and per-provider wording), `tests/runner/test_pr_resource.py` (the workspace remote), `tests/test_native_terminal.py`, `tests/runner/test_github_resource.py`, the GitLab and Azure DevOps payload tests, policy builder and tool-manager tests updated.
- Web: `linkRules.test.ts` (git matchers, URL shapes, which rule is in play, the GitHub qualified-reference rule), `ChatMarkdown.linkRules.test.tsx` (code/link skipping, ordering with item labels and file links, injection, re-render when rules arrive), `LinkRulesScope.test.ts`, `LinkRulesSettingsGroup.test.tsx`; `tsc -b`.
