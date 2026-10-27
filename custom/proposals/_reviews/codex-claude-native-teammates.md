# Codex review: claude-native-teammates (two branches)

Reviewed 2026-10-23 after rebasing onto `upstream/main` = 3f2ccf56e.

Command: `codex review --base upstream/main "<prompt>"` is rejected by codex-cli 0.159.2 (`--base` cannot be combined with a prompt), and `codex exec --sandbox read-only` cannot run commands in this environment (bubblewrap: `loopback: Failed RTM_NEWADDR: Operation not permitted`). Fallback used: `codex exec --sandbox read-only` with the prompt, the repo `CLAUDE.md` and `git diff -U40 upstream/main...HEAD` piped on stdin, instructed not to run commands. Model: gpt-6.1-sol (OpenAI Codex v0.159.2).

## Branch 1: fix/claude-native-teammate-children

### Raw review

```
codex
I found no confirmed correctness bugs or convention violations in the supplied diff. The change preserves Task/Agent correlation, registers teammates without spawn records, and tests teammate parenting, nested children, labels, malformed metadata, and restart deduplication.

One validation gap remains: all new registration tests mock the server accepting `tool_use_id="teammate:…"`. The supplied material does not establish whether the real event handler accepts an ID without a matching parent tool call. That is an uncertainty, not a demonstrated bug.

To verify manually, start a native Claude team, have a teammate spawn a Task subagent, and confirm Omnigent displays lead → teammate → subagent with transcript updates. Restart the forwarder and confirm no duplicate children appear.

Review was limited to the provided material; no commands or tests were run.

Findings:

- **None confirmed** from the supplied diff.
```

### Disposition

- No findings. The one uncertainty raised (does the real server accept `tool_use_id="teammate:<id>"` with no matching parent tool call?) is answered by the server: `omnigent/server/routes/_sessions/helpers.py` (`_persist_external_subagent_start`) only rejects a missing or empty `data.tool_use_id`; nothing correlates it with a tool result at registration. The PR text already states that a teammate therefore never gets a Completed notice. Manually verified against a real agent team on a 0.18-based deployment. Not changed.

## Branch 2: fix/claude-native-teammate-delivery

### Raw review

```
codex
I’ll review the supplied diff for correctness, coverage gaps, and repository conventions, without running commands.
codex
I found one issue that warrants changes. This review uses only the supplied material; I ran no commands or tests.

To verify, parse an origin-less user record containing `_FRAMED_TEAMMATE_DELIVERY + "\n\nPlease explain this message."`, both as string content and a text block. The human question should remain visible and start a user turn. Add the same regression case for a queued prompt.

- **P2 — `omnigent/harnesses/claude_native/bridge.py:9167` — Prefix matching can silently discard human input.** `_teammate_envelope_shape()` accepts everything after `_TEAMMATE_DELIVERY_GUIDANCE` because it uses `startswith()` without validating the remainder. Previously this permissive match only marked a message as a candidate; the new `_is_unattributed_teammate_delivery()` uses it to classify content as internal. On older Claude builds that omit `origin`, pasting a complete delivery followed by a question therefore hides the entire prompt—queued prompts are dropped outright—and preserves the previous response grouping. This contradicts the helper’s “nothing but” framing guarantee. Validate the complete allowed guidance suffix and add coverage for human text appended **after the guidance**; the existing `"What now?"` case only tests text immediately after the envelope.
```

### Disposition

- P2 (guidance matched by `startswith`, so text appended after the guidance paragraph was hidden on a build that omits `origin`): **fixed**. `_teammate_envelope_shape` now returns `framed` only when the remainder after the guidance prefix has no line break (Claude's guidance is a single paragraph; the real 2.1.304 record has none). Added `_FRAMED_TEAMMATE_DELIVERY + "\n\nPlease explain this message."` as a visible case on the string, blocks and queued-prompt paths (`test_claude_framed_delivery_without_origin_is_internal`, `test_queued_framed_delivery_from_a_human_stays_visible`). Text appended on the same line as the guidance is still accepted; that is not a shape a person types, and on 2.1.303+ the human origin protects it anyway.
