<!-- Draft PR body for the claude-config-dir series; title: fix(claude-native): follow CLAUDE_CONFIG_DIR instead of ~/.claude -->

> Status: carried copy of upstream PR #9617; no new PR needed. Drop this series once #9617 merges.

## Related issue

Refs #9617 (the upstream PR carried here, which closes #7124)

## Summary

Claude Code picks its profile from `CLAUDE_CONFIG_DIR`, but several things Omnigent reads and writes on Claude's behalf were still hardcoded to `~/.claude`. With a non-default profile selected, Omnigent looked in the wrong place.

- Adds `omnigent/claude_paths.py` with `claude_config_dir()` and `claude_json_path()`, so the "`$CLAUDE_CONFIG_DIR`, else `~/.claude`" rule (and where `.claude.json` lives) is in one place. The session-status reader and the local session importer use it instead of their own copies.
- Routes the remaining hardcoded paths through it: the user settings behind the claude-native status line and effort level, the transcript lookup used when a session moves, the claude-sdk sandbox's writable roots and files, and the install ledger's check for the omnigent MCP entry.
- Tests clear `CLAUDE_CONFIG_DIR` by default, so a developer's own profile cannot get past the suite's tmp-HOME isolation. New tests pin the `CLAUDE_CONFIG_DIR` passthrough through both runner env strips.
- Adds an e2e_ui journey: a claude-native session started from the web UI with `CLAUDE_CONFIG_DIR` exported renders the selected profile's statusLine, while the default `~/.claude` profile holds a decoy.

The subscription-accounts series builds on this. This change is carried in the patch series on Desidero/omnigent's `patches` branch until it lands upstream.

## Test Plan

Unit and integration tests:

```sh
uv run pytest tests/test_claude_paths.py tests/test_install_ledger.py \
  tests/cli/test_host_daemon_env.py tests/inner/test_claude_sdk_executor.py \
  tests/harnesses/claude_native/test_claude_native.py \
  tests/harnesses/claude_native/test_claude_native_bridge.py \
  tests/runner/test_app_sessions_native_terminals_autocreate.py \
  tests/test_routing_model_switch_guards.py
```

Browser E2E (needs the built web UI, Playwright Chromium and the `claude` CLI; the CLI talks to the mock Anthropic endpoint):

```sh
uv run --no-sync pytest tests/e2e_ui/sessions/test_claude_native_config_dir_profile.py --ui-skip-build
```

Manual:

1. Create a second profile: `mkdir -p /tmp/claude-alt` and put a `settings.json` there with a distinctive `statusLine` command (for example `echo ALT-PROFILE`). Sign in with `CLAUDE_CONFIG_DIR=/tmp/claude-alt claude auth login`.
2. Start a host from a shell with `CLAUDE_CONFIG_DIR=/tmp/claude-alt` exported.
3. Start a claude-native session from the web UI in a folder Claude has not seen before. The Terminal view's status bar shows `ALT-PROFILE`, and the folder's trust entry is written to `/tmp/claude-alt/.claude.json`, not `~/.claude.json`.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

The e2e_ui journey above is the evidence. See upstream PR #9617 for its run.

## Type of change

- [x] Bug fix
- [ ] Feature
- [ ] UI / frontend change
- [x] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [x] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

No manual-only claims. The two-profile e2e_ui journey covers the live TUI path, and the unit tests use the same two-profile setup for the settings reader and transcript lookup.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.
