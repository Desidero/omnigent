# [Bug] claude-native: teammate deliveries recorded without an `origin` render as raw user bubbles in the lead's chat

## Description

When a Claude Code agent-team teammate sends a message to the lead, Claude Code delivers it to the lead as a plain `role=user` transcript record: `Another Claude session sent a message:` (or `... while you were working:` when it is queued mid-turn), followed by a `<teammate-message teammate_id="...">...</teammate-message>` envelope and Claude's own guidance paragraph (`This came from another Claude session — not typed by your user, ...`). Omnigent shows each of these in the lead's chat as a raw user bubble containing the markup and, for idle teammates, their `{"type":"idle_notification",...}` JSON.

Expected: these deliveries are internal agent traffic, like the peer messages that are already hidden, and do not render as something the user typed.

**Cause.** Claude Code 2.1.304 stamps `origin: {"kind": "human"}` on typed and pasted prompts and `origin: {"kind": "peer", ...}` on in-process sub-agent replies, but it writes no `origin` at all on teammate deliveries. The bridge (`omnigent/harnesses/claude_native/bridge.py`) only trusts explicit provenance: `_is_trusted_agent_notification_text` hides a record when `origin.kind == "peer"` or when it is a `<task-notification>` (#8588). For the teammate shape it only sets `agent_message_candidate`, and the server (`omnigent/server/routes/_sessions/orchestration.py`) resolves a candidate with no matching pending web input to `user_authored: True`. So every teammate delivery is persisted as a user message and rendered verbatim. The same happens on the mid-turn path, where the delivery arrives as a `queued_command` prompt attachment (`_attachment_transcript_items_from_entry`).

**History.** #7690 reported this together with the missing-teammates-in-the-rail problem and was closed after #8588 landed; #8588 hides messages explicitly marked `peer` and does not cover deliveries with no `origin`. #8779 fixed both halves and was closed unmerged when #7690 closed. The rail half is tracked in #10745; this issue is the chat half.

**Proposed fix** (ready as a PR). Treat a record (or queued prompt) that has no `origin` key and whose text is entirely Claude's framing as internal: an optional delivery prefix, one or more `<teammate-message>`/`<agent-message>` envelopes, and optionally Claude's trailing guidance, with nothing else. Anything else keeps today's behaviour: a record with `origin.kind == "human"` renders as the user's message even if it contains the framing, and framing followed by extra text (e.g. a user who pasted a teammate message and added a question) still renders. The lead's first `<teammate-message>` in the teammate's own child chat is a separate, smaller gap and is not addressed by this.

## Steps to reproduce

1. Start a Claude-native session with Claude Code 2.1.304 and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.
2. Ask Claude to create an agent team with one in-process teammate and have the teammate report back (or just go idle; Claude delivers an `idle_notification` to the lead).
3. In the lead's transcript (`~/.claude/projects/<project>/<session>.jsonl`), find the delivery: a `role=user` record starting with `Another Claude session sent a message:` and a `<teammate-message ...>` envelope, with no `origin` field. A prompt you typed in the same session has `origin: {"kind": "human"}`.
4. Open the lead's chat in the Omnigent web UI: the delivery is rendered as a user bubble with the raw `<teammate-message>` markup / `idle_notification` JSON. Send a message to the lead while a teammate is reporting to also see the queued (`while you were working`) variant.

## Version

`main` (d7783c38, 0.19.0.dev0); also 0.18.0. Claude Code 2.1.304.

## OS

Linux

## Harness

Claude

## Harness mode

Native

## Platform or device

Linux, Desktop app

## Observed impact

Some users or sessions

## Authentication type

Not authentication-related
