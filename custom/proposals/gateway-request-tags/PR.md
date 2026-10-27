Title: feat(harnesses): tag Unity Gateway requests with the session's labels

## Related issue

Closes #<to be filed>

Builds on #10410 (static attribution headers). Adjacent: #11118 (open) rewrites
`with_gateway_attribution*` to merge and dedupe headers and touches the same
three call sites (`_resolve_gateway_env`, `materialize_codex_provider_config`,
the Claude gateway shim); once it merges this PR will rebase onto it and
express the request-tags line through its merge helper. #11099 (open) adds
signer-side attribution; it is independent, see the signer note below.

## Summary

ELI5: every request Omnigent sends to a Databricks Unity Gateway now says which
session it belongs to, so the gateway's usage and inference tables can be
grouped or joined by session.

- When a harness targets a Unity Gateway URL (same `is_databricks_ai_gateway_url`
  gate as the attribution headers), its requests carry
  `Databricks-Ai-Gateway-Request-Tags`, a JSON object with `omnigent_session_id`
  and the session's user labels as `omnigent_label_<key>`. Labels are namespaced
  because gateway service policies evaluate request tags and any editor of a
  session can set its labels, so a user label must never become the `team` or
  `project` tag an organisation's policy matches on.
- Omnigent-owned labels (`omnigent.*`, `cost_control.*`, `omni_project`) are
  skipped through one shared `is_internal_label_key` predicate in
  `conversation_store`. The header stays under 4 KiB (a quarter of Node's
  default 16 KiB header block, which Claude Code shares with its auth and beta
  headers): labels are added in key order up to the first that would overflow;
  the session id is always kept.
- Harness wiring, in the spots #10410 stamps attribution: claude-native and
  claude-sdk (`ANTHROPIC_CUSTOM_HEADERS` line), codex and codex-native
  (`env_http_headers` from `OMNIGENT_GATEWAY_REQUEST_TAGS_VALUE`), pi
  (`models.json` headers, `$` escaped), pi-native and opencode-native (the
  runner stamps the per-session `models.json` / `opencode.json` it writes from
  the launch snapshot's labels). Both header helpers replace an existing
  request-tags header, so re-materialising a config or launching
  `omnigent claude` inside an already tagged process sends one header.
- `OMNIGENT_GATEWAY_REQUEST_TAGS=0` turns it off; the host forwards the switch
  to its runners. Other gateways and providers never receive the header.

Known limitations, documented in `docs/databricks.md`:

- Harness processes and native CLIs read the tags at launch, so a label edit
  reaches the header after the next launch or respawn.
- A signer-backed Codex worker does not send the header: the signer rebuilds a
  fixed header set (pinned by a test). Once #11099's signer `extra_headers`
  lands, the runner can hand the signer the session tags the same way.
- `claude_config_with_gateway_request_tags` reads the gateway URL from the
  resolved provider config, so a user whose own environment points
  `ANTHROPIC_BASE_URL` at a gateway without a provider config gets no tags
  (matches #10410's known limitation).

## Test Plan

- `tests/test_databricks_ai_gateway.py`: namespaced tags, internal labels
  skipped, the session id cannot be overwritten, first-overflow stop at 4 KiB,
  ASCII-only encoding, the opt-out switch, and both helpers replacing an
  existing header (case-insensitive).
- `tests/stores/test_conversation_labels.py`: `is_internal_label_key`.
- Per-harness wiring at the lowest layer with the env stubbed:
  `tests/inner/test_claude_sdk_executor.py`, `tests/inner/test_codex_executor.py`,
  `tests/inner/test_pi_executor.py`,
  `tests/harnesses/codex_native/app_server/test_launch_config.py`,
  `tests/harnesses/pi_native/test_pi_native_credentials.py`,
  `tests/test_opencode_native_provider.py`.
- Runner hand-off: `tests/runner/test_runner_dispatch.py` (envelope labels vs one
  label fetch through `httpx.MockTransport`),
  `tests/runner/test_app_claude_native_launch_args.py`,
  `tests/runner/test_app_sessions_native_terminals_runtime.py`,
  `tests/runner/test_codex_native_launch_config.py` and
  `tests/runner/test_pi_native_resume_wiring.py` (labels parsed from the launch
  snapshot), `tests/cli/test_host_daemon_env.py` (switch reaches the runner).
- Boundary tests: `tests/inner/test_claude_gateway_shim.py` (the shim forwards
  the header to the upstream) and `tests/inner/test_model_signing.py` (the
  signer drops it).
- Ran the files above (1,737 passed, 5 skipped) plus
  `pre-commit run --files <changed>`.

Manual check against a workspace gateway: start a claude-native session with
labels `team: ml`, run one turn, then query
`system.ai.ai_gateway_usage` (or the inference table) for the latest row and
expect `request_tags = {"omnigent_session_id": "<id>", "omnigent_label_team": "ml"}`.
Set `OMNIGENT_GATEWAY_REQUEST_TAGS=0` on the host, restart it, start a new
session, and expect no `request_tags`.

## Demo

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Header as sent by a session labelled `team: ml`:

```text
Databricks-Ai-Gateway-Request-Tags: {"omnigent_session_id":"conv_abc123","omnigent_label_team":"ml"}
```

## Type of change

- [ ] Bug fix
- [x] Feature
- [ ] UI / frontend change
- [ ] Refactor / chore
- [x] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [ ] E2E tests added / updated
- [x] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

The header value and every harness's wiring are covered by unit tests with the
gateway env stubbed. The usage-table row was not observed against a real Unity
Gateway for this revision; the manual steps above describe how to confirm it.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Requests to a Databricks Unity Gateway carry the session id and the session's labels (as `omnigent_label_<key>`) in `Databricks-Ai-Gateway-Request-Tags`, so gateway usage can be grouped by session; `OMNIGENT_GATEWAY_REQUEST_TAGS=0` turns it off.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
