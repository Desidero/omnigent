# claude-config-dir

Needs: none
Covers: 4e0b76356613f489

claude-native and claude-sdk follow Claude Code's `CLAUDE_CONFIG_DIR` for
everything Omnigent reads and writes on Claude's behalf (settings, status line,
transcripts, trust, the sandbox's writable roots) instead of assuming
`~/.claude`.

- **Turn on:** on by default; set `CLAUDE_CONFIG_DIR` as you would for the
  Claude CLI.
- **Docs:** none of its own; the per-account login directories that rely on it
  are in [Model providers](../providers.md).
- **Upstream:** not upstream yet; tracked by issue [#7124](https://github.com/omnigent-ai/omnigent/issues/7124) (upstream PR [#9617](https://github.com/omnigent-ai/omnigent/pull/9617),
  which carried it, was closed without merging).

## Must hold

- With `CLAUDE_CONFIG_DIR` set, Claude's config directory is that path (`~` expanded) and `.claude.json` is inside it; unset or empty, they are `~/.claude` and `~/.claude.json`.
- claude-native reads the status line command and the effort level from the selected profile's `settings.json`, and only ever reads that file.
- A transcript Claude wrote under `CLAUDE_CONFIG_DIR` is found when a session moves or forks, a moved transcript lands in that profile's `projects/`, and workspace trust is written into that profile.
- The claude-sdk sandbox opens the selected profile's state directories, `.claude.json` and `.credentials.json` for writing, not the default profile's.
- The install ledger's deep backfill looks for the omnigent MCP entry in the selected profile's `.claude.json`.
- `CLAUDE_CONFIG_DIR` survives both environment strips (CLI to host daemon, daemon to runner), so a claude-native pane runs on the selected profile.

## Key code

- `omnigent/claude_paths.py`: `claude_config_dir`, `claude_json_path`
- `omnigent/harnesses/claude_native/bridge.py`: `_user_claude_settings_path`, `read_user_status_line_command`, `read_user_effort_level`
- `omnigent/inner/claude_sdk_executor.py`: `_claude_internal_write_roots`, `_claude_internal_write_files`
- `omnigent/install_ledger.py`: `observed_external_configs`
- `tests/conftest.py`: `_isolate_claude_config_dir` clears the variable for every test, so a developer's own profile cannot leak in

## Tests

- `tests/test_claude_paths.py::test_claude_json_moves_into_claude_config_dir`
- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_read_user_status_line_command_follows_claude_config_dir`
- `tests/harnesses/claude_native/test_claude_native.py::test_find_claude_transcript_follows_claude_config_dir`
- `tests/inner/test_claude_sdk_executor.py::test_claude_internal_write_files_follow_the_configured_claude_home`
- `tests/cli/test_host_daemon_env.py::test_runner_env_preserves_claude_config_dir`
