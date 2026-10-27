# The custom patch series

This branch is upstream Omnigent plus a series of patches that are waiting to
land upstream or are kept locally. Each section below is one series, in apply
order: what it changes for you, how to turn it on, and where its usage docs
live. "Proposed from `<branch>`" names the contribution branch the patch goes
upstream from; "carried" means a copy of someone else's upstream pull request.
This page exists only on this branch.

## claude-config-dir

claude-native and claude-sdk follow Claude Code's `CLAUDE_CONFIG_DIR` for
everything Omnigent reads and writes on Claude's behalf (settings, status line,
transcripts, trust, the sandbox's writable roots) instead of assuming
`~/.claude`.

- **Turn on:** on by default; set `CLAUDE_CONFIG_DIR` as you would for the
  Claude CLI.
- **Docs:** none of its own; the per-account login directories that rely on it
  are in [Model providers](../providers.md).
- **Upstream:** carried from upstream PR #9617.

## subscription-accounts

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
  issue #503).

## toast-safe-area

Toasts stay below the iOS status bar and Dynamic Island.

- **Turn on:** on by default.
- **Docs:** none (layout fix).
- **Upstream:** proposed from `fix/toast-safe-area`.

## session-history-paging

Agents can list sessions by recent activity and ownership, and page through a
session's whole history, forward from the start or from a saved cursor.

- **Turn on:** on by default; new optional arguments on `sys_session_list` and
  `sys_session_get_history`, and `updated_after` on `GET /v1/sessions`.
- **Docs:** [Agent YAML spec](../AGENT_YAML_SPEC.md) (session read tools) and
  `omnigent/server/API.md` (List Sessions).
- **Upstream:** proposed from `feat/session-history-paging`.

## terminal-touch

The terminal on phones and tablets: a Termux-style extra-keys row, long-press
select with Copy, Paste and Select screen, and native clipboard reads for Paste
in the iOS app.

- **Turn on:** on by default on touch devices. Settings → Appearance → Touch &
  mobile → **Extra keys row** chooses Auto, Always or Never.
- **Docs:** [Terminals](../../feature-map/terminals.md) (`touch-keys`,
  `touch-select`).
- **Upstream:** the extra-keys row is carried from upstream PR #6136; long-press
  selection and the iOS clipboard are not proposed yet.

## telemetry-attribution

Exported spans carry the runner (`omnigent.runner.id`), the host
(`omnigent.host.id`, a resource attribute) and, when you opt in, the acting
user (`enduser.id`).

- **Turn on:** with telemetry on (`OMNIGENT_TELEMETRY_ENABLED`), runner and
  host need nothing more; set `OMNIGENT_OTEL_CAPTURE_USER=true` for the user.
- **Docs:** `designs/OBSERVABILITY.md` (Configuration: the variable table and
  actor attribution) and [Databricks](../databricks.md) (Reference: env var
  summary).
- **Upstream:** proposed from `feat/span-attribution`.

## sidebar-attention-filter

Sidebar filters for sessions that need you (**Needs me**) or changed recently
(**Updated**: 24 hours, 3, 7 or 30 days), with a chip per active filter.

- **Turn on:** on by default; choose them in the sidebar's filter menu.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`attention-filters`).
- **Upstream:** proposed from `feat/sidebar-attention-filters`.

## claude-sdk-web-tools

claude-sdk agents can use Claude Code's own WebSearch and WebFetch.

- **Turn on:** `native_tools: [WebSearch, WebFetch]` under the agent's
  `executor` (`executor.config.native_tools` in a directory bundle).
- **Docs:** [Agent YAML spec](../AGENT_YAML_SPEC.md) (Claude SDK built-in web
  tools).
- **Upstream:** proposed from `feat/claude-sdk-native-tools`.

## run-suggested-commands

A Run button on shell commands an agent suggests in claude-native and
codex-native chats, which queues each as a `!command` shell input after a
confirmation. A `!command` typed in a codex-native web composer runs as a shell
command too (brought up to its pull request by `codex-native-shell-input`
below).

- **Turn on:** on by default; the `chat-features` series below makes it a
  per-session toggle.
- **Docs:** [Run suggested commands](../run-suggested-commands.md) and
  [Native harnesses](../../feature-map/native-harnesses.md)
  (`run-suggested-commands`).
- **Upstream:** proposed from `feat/run-suggested-commands`.

## claude-native-teammates

Claude Code agent-team teammates show up as child sessions titled
"<name>: <description>", and their deliveries no longer appear as raw
`<teammate-message>` bubbles in the lead's chat.

- **Turn on:** on by default.
- **Docs:** none (fixes).
- **Upstream:** proposed from `fix/claude-native-teammate-children` and
  `fix/claude-native-teammate-delivery`.

## claude-native-subagent-status

A Claude sub-agent running a long tool call stays "running" until its turn
actually ends.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/claude-native-subagent-quiet-status`.

## claude-native-coordinator-messages

A parent agent's follow-ups to a running Claude sub-agent appear in the
sub-agent's chat as "Message from parent agent".

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/claude-native-coordinator-messages`.

## skip-gzip-binary-files

Images and PDFs load in the file viewer again instead of failing with a 500.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** carried from upstream PR #10585.

## codex-native-mode-instructions

Codex keeps its own Plan and Default mode instructions instead of having them
replaced by the agent's developer instructions.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/codex-native-mode-instructions`.

## chat-item-labels

Bracketed labels such as `[Q2]` in chat become chips that preview the item
they refer to; `~~[Q2]~~` closes it, and an Open items bar lists what is still
open, puts the items the latest reply mentions first, and lets you dismiss
items. Agents get an instruction to label and close items.

- **Turn on:** on by default; labels render once a transcript uses them.
- **Docs:** [Item labels in chat](../chat-item-labels.md).
- **Upstream:** proposed from `feat/chat-item-citations`; the latest-reply
  emphasis and dismissing items are kept here only.

## web-reconnect-shell-inputs

A queued `!command` no longer stays stuck at the bottom of the chat after the
connection drops and recovers.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/web-reconnect-settles-shell-inputs`.

## chat-item-comments

Comment on labelled items and send the comments together as one structured
message the agent answers item by item.

- **Turn on:** on by default; choose **Comment** in an item's popover.
- **Docs:** [Item labels in chat](../chat-item-labels.md) (Comment on items).
- **Upstream:** proposed from `feat/chat-item-comments`.

## palette-new-chat-in-project

Typing in the command palette lists **New chat in <project>** rows that open
the composer with that project's defaults.

- **Turn on:** on by default.
- **Docs:** [Composer](../../feature-map/composer.md)
  (`palette-new-chat-in-project`).
- **Upstream:** proposed from `feat/palette-new-chat-in-project`.

## new-chat-project-prompt

When projects exist, starting a new session first asks which project to start
it in.

- **Turn on:** on by default; Settings → General → Sessions → **Ask for a
  project when starting a session** turns it off.
- **Docs:** [Composer](../../feature-map/composer.md)
  (`new-session-project-prompt`).
- **Upstream:** proposed from `feat/new-chat-project-prompt`.

## session-labels-ui

View and edit a session's labels in the web UI, delete labels through the API
(a `null` value), and give projects default labels for the sessions created in
them; a `null` label on create leaves that project default off.

- **Turn on:** on by default; the Labels section of the session info popover,
  Project settings → **Default labels**, and the new-session composer's **+**
  menu → Labels.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`labels`) and
  `omnigent/server/API.md` (Create From Existing Agent, Bind Session Runner).
- **Upstream:** proposed from `feat/session-labels-api` and
  `feat/session-labels-ui`.

## gateway-request-tags

Requests to a Databricks Unity Gateway carry the session id and the session's
labels in the `Databricks-Ai-Gateway-Request-Tags` header.

- **Turn on:** on by default for gateway providers;
  `OMNIGENT_GATEWAY_REQUEST_TAGS=0` in the host's (or CLI's) environment turns
  it off.
- **Docs:** [Databricks](../databricks.md) (Session request tags).
- **Upstream:** proposed from `feat/gateway-request-tags`.

## chat-features

Per-session toggles for chat features that need both an agent instruction and
a renderer, starting with Run suggested commands, plus a per-user default.

- **Turn on:** every feature is on by default. Toggle one session in the
  **Chat features** section of the agent or configure menu; save a default in
  Settings → General → **Chat features**, which needs
  `shared_preferences_authority_id` in the server config.
- **Docs:** [Run suggested commands](../run-suggested-commands.md) (Turn it on
  or off), [Shared preference operations](../shared-preferences-api.md) and
  [Preferences](../../feature-map/preferences.md)
  (`chat-features-default`).
- **Upstream:** proposed from `feat/run-suggested-commands`.

## pr-watch

Watch a session's pull requests and wake the agent on failed checks, merge
conflicts and trusted reviews until they are green.

- **Turn on:** off by default. Start the server with
  `OMNIGENT_FEATURES=pr_watch`; `OMNIGENT_PR_WATCH_INTERVAL_S` (default 90)
  and `OMNIGENT_PR_WATCH_MAX_WAKES` (default 10) tune it. Then use **Watch
  PRs** in the composer bar.
- **Docs:** [PR watch](../../feature-map/pr-watch.md).
- **Upstream:** drafted, not on a contribution branch yet (it builds on
  subscription-accounts).

## claude-native-delegate-idle

A Claude session stops showing Working, and takes follow-ups without Steer,
once its turn ends while a background agent or teammate keeps running, on both
the status-file and OSC status paths.

- **Turn on:** on by default.
- **Docs:** none (fixes).
- **Upstream:** the status-file part is carried from upstream PR #10849; the
  OSC and teammate parts are proposed alongside it.

## delete-stops-runner

Deleting a session stops its host-launched runner once no remaining session
uses it.

- **Turn on:** on by default.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`delete`).
- **Upstream:** proposed from `fix/delete-stops-runner`.

## transcript-hold-position

Scrolling up to re-read a reply that is still streaming keeps your place
instead of jumping when the reply's first tool call lands.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/transcript-hold-position`.

## history-prefetch

Older history loads ahead of the scroll, in larger pages, so paging back
through a long transcript stalls less.

- **Turn on:** on by default.
- **Docs:** none (performance).
- **Upstream:** proposed from `fix/history-prefetch`.

## lean-history-items

History pages carry only the head of long tool outputs, and expanding a tool
row fetches the full result.

- **Turn on:** on by default in the web app; API clients opt in with
  `tool_output=preview` on `GET /v1/sessions/{id}/items`.
- **Docs:** `omnigent/server/API.md` (List Session Items, Get Session Item).
- **Upstream:** proposed from `feat/lean-history-items`.

## app-error-boundary

A rendering error shows the error, its stack and a Reload button instead of a
blank window.

- **Turn on:** on by default.
- **Docs:** none (error screen).
- **Upstream:** drafted, not on a contribution branch yet.

## jump-to-latest

A labelled Jump-to-latest pill that counts new replies arriving below a reader
who scrolled up.

- **Turn on:** on by default; it appears when you scroll up in a transcript.
- **Docs:** none (self-explanatory control).
- **Upstream:** proposed from `feat/transcript-jump-to-latest`.

## session-telemetry

Every span of a turn carries session metadata (title, labels, project, agent,
git branch and remote, workspace, host name), and the agent span records the
model and reasoning effort the turn asked for and ran with, falling back to
the session's and the agent's configured model when the harness reports none.

- **Turn on:** with telemetry on (`OMNIGENT_TELEMETRY_ENABLED`); the session
  title also needs `OMNIGENT_OTEL_CAPTURE_CONTENT`.
- **Docs:** `designs/OBSERVABILITY.md` (Model and effort attributes, Session
  attributes) and [Databricks](../databricks.md) (Which model and effort a
  turn ran with).
- **Upstream:** proposed from `feat/turn-model-effort` and, stacked on it,
  `feat/session-telemetry`.

## codex-native-shell-input

A `!command` typed in a codex-native session's web composer runs as a Codex
shell command instead of reaching the model as a prompt, without a follow-up
message starting a second turn, and keeps a trailing escaped space or a
heredoc body.

- **Turn on:** on by default; type `!` and a command in the composer.
- **Docs:** [Run suggested commands](../run-suggested-commands.md) (What Run
  does) and [Native harnesses](../../feature-map/native-harnesses.md)
  (`run-suggested-commands`).
- **Upstream:** proposed from `fix/codex-native-shell-input`; on this branch
  it follows up on `run-suggested-commands`.

## custom-docs-index

This page.

- **Turn on:** nothing to turn on.
- **Docs:** this file.
- **Upstream:** kept here only.
