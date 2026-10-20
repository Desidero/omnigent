# The custom patch series

This branch is upstream Omnigent plus a series of patches that are waiting to
land upstream or are kept locally. Each section below is one series, by name:
what it changes for you, how to turn it on, and where its usage docs live.
"Proposed from `<branch>`" names the contribution branch the patch goes
upstream from; "carried" means a copy of someone else's upstream pull request.
This page exists only on this branch; the build writes it from the notes of
the series it holds.

## antigravity-cooldown

The `antigravity` extra locks `google-antigravity` 0.1.23 instead of 0.1.2:
`uv.toml` no longer holds the SDK at a fixed `exclude-newer-package` date,
and the antigravity harness reads a turn's token usage from
`conversation.last_turn_usage`, which the newer SDK fills in place of
`Step.usage_metadata`.

- **Turn on:** on by default for installs that take the extra
  (`pip install "omnigent[antigravity]"` with the build's constraints).
- **Docs:** none (dependency re-lock and a fix). When a refresh conflicts in
  this patch's `uv.lock` hunk, do not merge it by hand: take the new base's
  `uv.lock` (`git checkout --ours uv.lock` during the rebase), keep the
  patch's `uv.toml` change, and run
  `uv lock --upgrade-package google-antigravity`.
- **Upstream:** proposed from `fix/antigravity-cooldown` (upstream PR [#14704](https://github.com/omnigent-ai/omnigent/pull/14704)).

## antigravity-shell

The Gemini (`harness: antigravity`) agent can run shell commands. The SDK's
default policy denied its `run_command` tool outright and the harness turned
that into a failed turn. Now each shell call passes Omnigent's own gate: the
agent's `tool_call` policies first (DENY refuses, ASK asks), then
`executor.config.permission_mode` (`auto`, the default, and
`bypassPermissions` run it; any other value, e.g. `default`, asks on an
approval card). A refused call fails as a tool call with its reason and the
model carries on; rejecting the card ends the turn, as on the other SDK
harnesses. Approval cards say "Antigravity wants to use run_command".

- **Turn on:** on by default; set `executor.config.permission_mode: default`
  to be asked before every command.
- **Docs:** [Agent YAML](../AGENT_YAML_SPEC.md) (Antigravity (Gemini)).
- **Upstream:** not proposed yet. Bug report
  [#8484](https://github.com/omnigent-ai/omnigent/issues/8484); the open
  [#8497](https://github.com/omnigent-ai/omnigent/pull/8497) routes the SDK's
  ask-user handler to the card instead and does not apply Omnigent policies.

## app-error-boundary

Upstream's render error fallback ("Unable to display …" with Try again) also
shows the error, the component stack and the path, with Copy details and
Reload.

- **Turn on:** on by default; shown only when rendering crashes.
- **Docs:** none (error screen).
- **Upstream:** drafted, not on a contribution branch yet.

## chat-item-comments

Comment on labelled items and send the comments together as one structured
message the agent answers item by item. The composer's ordinary send takes the
unsent drafts along with the typed message; commands and `!` shell inputs go
alone, and the tray's menu sends only the comments or only the message.

- **Turn on:** on by default; choose **Comment** in an item's popover.
- **Docs:** [Item labels in chat](../chat-item-labels.md) (Comment on items).
- **Upstream:** not proposed yet: there is no upstream issue or pull request.
  It is prepared on `feat/chat-item-comments`, to go up together with the
  labelled-items renderer of `chat-item-labels`.

## chat-item-labels

Bracketed labels such as `[Q2]` in chat become chips that preview the item
they refer to; `~~[Q2]~~` closes it, and an Open items bar lists what is still
open, puts the items the latest reply mentions first, and lets you dismiss
items. Agents get an instruction to label and close items.

- **Turn on:** on by default; labels render once a transcript uses them.
- **Docs:** [Item labels in chat](../chat-item-labels.md).
- **Upstream:** not proposed yet: there is no upstream issue or pull request.
  The first patch is prepared on `feat/chat-item-citations`; the latest-reply
  emphasis and dismissing items are kept here only.

## claude-config-dir

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

## claude-native-coordinator-messages

A parent agent's follow-ups to a running Claude sub-agent appear in the
sub-agent's chat as "Message from parent agent".

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/claude-native-coordinator-messages`.

## claude-native-delegate-idle

A Claude lead session stops showing Working, and takes follow-ups without
Steer, once its turn ends while agent-team teammates keep running. Upstream's
background-agent hold ([#12561](https://github.com/omnigent-ai/omnigent/pull/12561)) does this for sub-agents; this series counts
teammates as background agents too.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed as an extension of upstream's [#12561](https://github.com/omnigent-ai/omnigent/pull/12561).

## claude-native-subagent-status

A Claude sub-agent that is still shown as working when its parent records its
result is settled then: idle for a completed result, failed for a failed one.
Without it, a sub-agent killed in the middle of a tool call stays "running"
until the forwarder's ten-minute mid-turn window runs out.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** not proposed. Upstream fixed the other half of this series
  (a sub-agent in a long tool call stays "running") in PR [#13811](https://github.com/omnigent-ai/omnigent/pull/13811), so that half
  was dropped; the open upstream PR [#12411](https://github.com/omnigent-ai/omnigent/pull/12411) also touches this code.

## claude-native-tall-draft

A web message sent to a Claude Code (native) session gets delivered even when
its pasted draft is taller than Claude Code's input box. Claude Code caps the
box's height. A taller draft keeps its last rows in view, the box's opening
rule reads `↑ N more`, and the `❯` row scrolls out of view. The bridge read
that screen as having no input box, so delivery waited for a prompt row that
never came, failed the turn with `ClaudePromptTimeout` and closed the
terminal. Upstream's end-of-draft marker
([#13325](https://github.com/omnigent-ai/omnigent/pull/13325)) only matches a
box whose `❯` row is still on screen.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/claude-native-tall-draft-ready` (pull request not opened yet).

## claude-native-teammates

Claude Code agent-team teammates show up as child sessions titled
"<name>: <description>", and their deliveries no longer appear as raw
`<teammate-message>` bubbles in the lead's chat.

- **Turn on:** on by default.
- **Docs:** none (fixes).
- **Upstream:** proposed from `fix/claude-native-teammate-children` and
  `fix/claude-native-teammate-delivery`.

## claude-sdk-web-tools

claude-sdk agents can use Claude Code's own WebSearch and WebFetch.

- **Turn on:** `native_tools: [WebSearch, WebFetch]` under the agent's
  `executor` (`executor.config.native_tools` in a directory bundle).
- **Docs:** [Agent YAML spec](../AGENT_YAML_SPEC.md) (Claude SDK built-in web
  tools).
- **Upstream:** not proposed yet: there is no upstream issue or pull request.
  It is prepared on `feat/claude-sdk-native-tools`.

## codex-native-mode-instructions

A Default-mode Codex turn keeps Codex's own Default mode instructions instead
of having them replaced by the agent's developer instructions (the Plan toggle
already does this upstream).

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/codex-native-default-mode-instructions`.

## composer-send-tap

On touch screens, one tap on Send sends even while the on-screen keyboard is
up, instead of sometimes doing nothing until the keyboard is dismissed.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** not proposed yet; no pull request or pushed branch.

## credential-local-key

A trial or single-machine server with neither AWS KMS nor Vault can turn on
the credential store, and so the per-user connections built on it, with a key
the operator keeps in a file (AES-256-GCM). It is an explicit choice and never
a fallback. The trade-off: anyone who can read the key file and the database
can read every stored token, no decrypt is logged or revocable, and changing
the key means every user reconnects.

- **Turn on:** create the key (`(umask 077 && openssl rand -base64 32 > <file>)`),
  then set `OMNIGENT_CREDENTIAL_CIPHER=local` and
  `OMNIGENT_CREDENTIAL_LOCAL_KEY_FILE=<file>`, with no KMS or Vault key set.
- **Docs:** "Local key file (explicit opt-in)" in the
  [credential store design](../../designs/CREDENTIAL_STORE.md#local-key-file-explicit-opt-in);
  a pointer in the [MCP registry README](../../examples/mcp-registry/README.md#administrator-configuration).
- **Upstream:** not proposed, no contribution branch. Upstream's design says
  "There is no non-KMS fallback", so this needs a maintainer's agreement before
  a proposal; no open issue or pull request asks for a local key (searched
  2026-11-26). Open neighbours on the same builder:
  [#9887](https://github.com/omnigent-ai/omnigent/pull/9887) (Azure Key Vault),
  [#14901](https://github.com/omnigent-ai/omnigent/pull/14901) (KMS envelope
  encryption), [#13868](https://github.com/omnigent-ai/omnigent/pull/13868) (KMS region).

## delete-stops-runner

Deleting a session stops its host-launched runner once no remaining session
uses it.

- **Turn on:** on by default.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`delete`).
- **Upstream:** proposed from `fix/delete-stops-runner`.

## history-prefetch

The next older page of history is fetched as soon as a scroll-up comes near
the top, ahead of the moment it is shown, so paging back through a long
transcript stalls less. One gesture can page in at most 600 items with your
hands off.

- **Turn on:** on by default.
- **Docs:** none (performance).
- **Upstream:** proposed from `fix/history-prefetch` (upstream PR [#13257](https://github.com/omnigent-ai/omnigent/pull/13257)).

## lean-history-items

History pages carry only the head of long tool outputs, and expanding a tool
row fetches the full result. Needs `history-prefetch`.

- **Turn on:** on by default in the web app; API clients opt in with
  `tool_output=preview` on `GET /v1/sessions/{id}/items`.
- **Docs:** `omnigent/server/API.md` (List Session Items, Get Session Item).
- **Upstream:** proposed from `feat/lean-history-items` (upstream PR [#13259](https://github.com/omnigent-ai/omnigent/pull/13259)).

## link-rules

Short references in chat messages (`BST-2135`, `PR #123`, `!123`,
`owner/repo#123`, `session:<id>`) render as links, from rules each user sets in
Settings and agents can change with approval. Git hosts are stored as `git`
rules (GitHub, GitLab, Azure DevOps, plus self-hosted ones); the session's
repository picks the one that links `issue #123`, `PR #123` and `!123`, and
GitHub links `owner/repo#123` in every session. In a git checkout, agents are
asked to say `issue #123` or `PR #123`. A bare `#123` is left to upstream's
built-in pull request links, which link it only to a pull request the session
already links; while any rule is on, the rules take the place of the built-in
`owner/repo#12` links.

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

## mcp-registry-tool-patterns

An entry in an MCP registry service's `tools` allowlist can be a pattern in
which `*` stands for any run of characters (`search_*`, `*_read`,
`get_*_by_id`), or `"*"` alone for every tool, so the registry file no longer
has to be regenerated each time a service adds a tool. The match is literal,
case-sensitive and anchored; exact names work as before. A pattern is checked
on every listing and call, not expanded once, so a tool the service adds later
is callable as soon as its name matches.

- **Turn on:** write a pattern in `tools` in the `OMNIGENT_MCP_REGISTRY` file
  and restart the server. Replace patterns with names before rolling back: a
  build without this series reads a pattern as an exact name that matches
  nothing, without an error.
- **Docs:** "Tool allowlist patterns" in the
  [registry README](../../examples/mcp-registry/README.md#tool-allowlist-patterns);
  one line in the [gateway design](../../designs/MCP_REGISTRY_GATEWAY.md).
- **Upstream:** not proposed, no contribution branch. No open upstream issue or
  pull request asks for patterns (searched 2026-11-26); upstream's design
  treats the exact allowlist as the administrator's review step. Neighbours on
  the same model: [#13295](https://github.com/omnigent-ai/omnigent/pull/13295)
  (icons, draft) and [#14064](https://github.com/omnigent-ai/omnigent/issues/14064)
  (Basic auth).

## mobile-landing-project-chip

On phones the new-session landing leads its controls with a chip naming the
project (or "No project"); its menu lists No project and every project with no
search field, and switching keeps the draft.

- **Turn on:** on by default in the mobile layout (phones, and windows narrower than the desktop layout).
- **Docs:** [Composer](../../feature-map/composer.md) (`mobile-project-chip`).
- **Upstream:** proposed from `feat/mobile-landing-project-chip`, [#13487](https://github.com/omnigent-ai/omnigent/pull/13487).

## mobile-settings-nav

Where the Settings menu covers the page (phones, and tablets held upright),
Settings opens as a list of pages on its own: full width, with no page open
behind it, a Back row, a large Settings title, the search field, then sections
as rounded inset groups of 44px rows with a chevron. Like a phone settings
list, no row is highlighted. Choosing a page shows it with the menu closed,
and a Back chevron in the page's header returns to the list. The desktop
layout, and a window wide enough to show the menu beside the page, are
unchanged.

- **Turn on:** on by default on the mobile layout wherever the menu covers the page.
- **Docs:** none (phone Settings navigation; nothing to configure).
- **Upstream:** the list's look is proposed from `feat/mobile-settings-nav`, [#13484](https://github.com/omnigent-ai/omnigent/pull/13484) (draft). Opening on the list instead of General (patch 02) changes upstream's own phone behaviour, which upstream opens on General under the menu; it is not proposed upstream yet.

## mobile-sidebar-nav-strip

On phones the drawer's New session, Automations, Workflows and Inbox rows fold
into one strip of icon-over-label cells, which leaves more room for the session
list. The strip doesn't scroll; Canvas, Usage and extension pages stay rows
below it. The desktop layout, and a window that shows the sidebar beside the
chat, keep the rows.

- **Turn on:** on by default in the phone drawer.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`mobile-primary-nav-strip`).
- **Upstream:** proposed from `feat/mobile-sidebar-nav-strip`, [#13488](https://github.com/omnigent-ai/omnigent/pull/13488) (draft); issue [#13482](https://github.com/omnigent-ai/omnigent/issues/13482).

## new-chat-project-prompt

Starting a new session asks which project it belongs to: the new-session hotkey,
the sidebar's New session links and ⌘K's New chat (either palette) open a
"Start a new session in…" picker with No project first, then every project.
Picking one opens the composer with that project's defaults. On a project's
home page they don't ask: the session starts in that project. Below the `md`
breakpoint the prompt is a bottom sheet without a search field.

- **Turn on:** on by default once you have a project; turn it off with
  Settings → General → Sessions → **Ask for a project when starting a session**
  (kept per device).
- **Docs:** [Composer](../../feature-map/composer.md) (`new-session-project-prompt`).
- **Upstream:** proposed from `feat/new-chat-project-prompt`,
  [#11397](https://github.com/omnigent-ai/omnigent/pull/11397) (draft, written
  when the prompt was a step of the one command palette); issue
  [#11083](https://github.com/omnigent-ai/omnigent/issues/11083). It no longer
  builds on `palette-new-chat-in-project`: the prompt is its own picker, so the
  two only meet in the feature map and the palette's test file.

## open-items-answers

Comments on stored open items join each item's thread: just before a
"Comments on N items" message is sent, the browser that sends it records each
stored item's comments as the user's replies, so the item shows as answered
in the Open items panel and to the agent in `sys_open_items_list` when its
turn starts. A stored item's chip previews its thread from the store, each
reply once, instead of sentences found in the chat; a chip of a label written
only in the chat offers **Record**. An expanded item in the panel also offers
Comment. **Comment and close**, chosen per item in comment mode, also closes
the item, as the user, with the comment as its resolution.

- **Turn on:** on by default with `open-items-panel` and
  `chat-item-comments`, on a server that stores open items.
- **Docs:** [Open items](../open-items.md) (In the web UI: Comments join
  the thread, The item card, Record, Comment and close), [Item labels in chat](../chat-item-labels.md) (Comment on items).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639, like the store.

## open-items-filters

The Open items panel gets a search box and one row of chips (Open,
Answered and Closed with counts, the kinds present, the topics in use) once
it holds five items or more, and groups items by status, topic or kind. The
grouping is remembered per browser; the search, chips and folds survive
closing the panel. On a phone the search stays first in the sheet and the
chips scroll sideways in one row.

- **Turn on:** on by default with `open-items-panel`, on a server that stores
  open items; the chat-only panel is unchanged.
- **Docs:** [Open items](../open-items.md) (In the web UI: Groups, Search and
  filters).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639, like the store.

## open-items-links-compact

The Open items bar of `chat-item-labels` becomes a compact button in the
session header, beside Agent info, with the number of open items as a badge;
it opens a popover on desktop and a sheet on phones. The panel also lists the
session's links: pages the agent's messages link to (first version:
`claude.ai` artifact links), collected without the agent doing anything, and
links pinned with a link label, `[L1] **Title** https://…`. A first version,
meant to be tried and revised.

- **Turn on:** on by default with the series; there is no setting, so leave
  the series out of a build to keep the bar.
- **Docs:** [Item labels in chat](../chat-item-labels.md) (Open items, Links,
  Loaded history only).
- **Upstream:** not proposed yet: there is no upstream issue or pull request,
  and `chat-item-labels`, which it extends, is not upstream either.

## open-items-panel

The Open items panel behind the session header's button, its badge and the
chat's label chips read the session's stored open items, kept live by
`session.open_items.changed`, instead of only the loaded chat text. A stored
item's label in the chat is only its anchor: the store alone decides its
state, and an expanded row shows its stored thread. A label the chat has but
the store does not is listed as "chat only". People with edit access close
(one tap, or with a resolution), reopen and retopic stored items from the
panel, and import the chat's own labels into the store.

- **Turn on:** on by default on a server with `open-items-store`
  (`/v1/info` `open_items`); without it the panel reads the chat as before.
- **Docs:** [Open items](../open-items.md) (In the web UI, HTTP API),
  [Item labels in chat](../chat-item-labels.md) (Loaded history only).
- **Upstream:** not proposed yet; it follows
  https://github.com/omnigent-ai/omnigent/issues/14639, like the store.

## open-items-store

Open items (the questions, risks, findings, follow-ups and pinned links an agent raises) become
records of their session, in the `open_items` side store, with labels such as `Q7` that the server
allocates. Each item is a thread: the agent creates it with `sys_open_items_raise` (the only way to
create one) and writes it once in chat, where the label only points at it; the user's comments and
the agent's replies (`reply` on `sys_open_items_update`) and the resolution are stored on it. Agents
with the tools get one instruction for them in place of the text-label one. People read items
through `/v1/sessions/{id}/open-items` and may reply, close, reopen or retopic. Every write
publishes `session.open_items.changed`. Codex-native sessions run the three tools without an
approval prompt. The web does not read the store yet: label chips and the Open items bar still
follow the chat text.

- **Turn on:** on by default; an agent opts out with `tool_groups.open_items: false`.
- **Docs:** [Open items](../open-items.md).
- **Upstream:** not proposed yet; it follows https://github.com/omnigent-ai/omnigent/issues/14639.

## palette-new-chat-in-project

Typing in the ⌘K command palette lists a "New chat in <project>" row for every
project; choosing one opens the new-session composer with that project's
defaults (`/?project=<name>`). Both palettes list the rows: the classic one and
the QuickPick one (`quick_pick_palette`).

- **Turn on:** on by default; the rows appear once you type in ⌘K.
- **Docs:** [Composer](../../feature-map/composer.md) (`palette-new-chat-in-project`).
- **Upstream:** proposed from `feat/palette-new-chat-in-project`,
  [#11394](https://github.com/omnigent-ai/omnigent/pull/11394) (draft, written
  before the QuickPick palette existed); its issue
  [#4409](https://github.com/omnigent-ai/omnigent/issues/4409) was closed by the
  stale bot. Upstream's draft
  [#14806](https://github.com/omnigent-ai/omnigent/pull/14806) (not ours) adds
  "New session in <name>" to QuickPick for the project in view only, as a
  registry command under **Project**. The two do not share code: this series
  lists every project, only while typing, in its own group, and touches none of
  the files that draft adds. If it merges, leave the project in view to its row
  (skip that project here) and take its `newSessionInProjectPath` in place of
  `newChatInProjectPath`.

## pr-refresh-main-checkout

A session started in a repository's main checkout (not a worktree) keeps
looking for pull requests at every turn end, so one opened after its first,
empty refresh shows up without anyone opening the Pull Requests panel.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** carried from another contributor's open pull request, https://github.com/omnigent-ai/omnigent/pull/14515 (closes https://github.com/omnigent-ai/omnigent/issues/12844); drop the series once it merges.

## pr-watch

A session watches its pull requests: while it is idle, the server wakes it with
one message about failed checks, comments and reviews from the repository's
owners, members and collaborators, and merge conflicts, until each PR is green,
merged or closed. Chosen from **Watch PRs** in the composer bar (all of the
session's PRs, or single ones) or **Watch until green** in the Pull Requests
panel.

- **Turn on:** `OMNIGENT_FEATURES=pr_watch` on the server (off by default). `OMNIGENT_PR_WATCH_INTERVAL_S` (90, at least 15) and `OMNIGENT_PR_WATCH_MAX_WAKES` (10, at most 50) tune it.
- **Docs:** [PR watch](../../feature-map/pr-watch.md).
- **Upstream:** not proposed upstream yet. Upstream has the turn-end PR refresh, owner-only PR changes (https://github.com/omnigent-ai/omnigent/pull/14896), trigger automations and timers (https://github.com/omnigent-ai/omnigent/pull/14760); none of them tells a session about its own PRs.

## queue-combine

When two or more adjacent queued messages can merge, the queue strip offers
**Combine** (one message: texts joined by a blank line, attachments kept) and,
where rows can be steered, **Send all** (combine, then steer the queue). Side
chats have the same actions.

- **Turn on:** on by default.
- **Docs:** [Queue and steer design](../QUEUE_STEER_DESIGN.md) ("Queue-wide actions") and [Composer](../../feature-map/composer.md) (`queue-combine`).
- **Upstream:** not proposed upstream yet.

## session-history-paging

Agents can list sessions by recent activity, and page through a session's
whole history, forward from the start or from a saved cursor.

- **Turn on:** on by default; new optional arguments on `sys_session_list`
  (`updated_after`, `order_by`) and `sys_session_get_history`, and
  `updated_after` on `GET /v1/sessions`. The older `ownership` argument is an
  alias of upstream's `visibility` until 0.24.0.
- **Docs:** [Agent YAML spec](../AGENT_YAML_SPEC.md) (session read tools) and
  `omnigent/server/API.md` (List Sessions).
- **Upstream:** not proposed yet: the feature request is not opened and there
  is no pull request. It is prepared on `feat/session-history-paging`.

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

## side-schemas

Infrastructure for other series, nothing a user sees: a feature outside the
main Alembic chain can keep its own tables as a side store, with its own
revisions and version table, in the schema `omx_<name>` on PostgreSQL and
CockroachDB and as `<name>_<table>` tables on SQLite and MySQL. The store
migrates itself on first use, after the main bootstrap, and deleting a
conversation tells each registered store which conversations went. No series
uses it yet; it adds no tables of its own.

- **Turn on:** nothing to turn on; a series registers a store.
- **Docs:** [side stores](../extending/side_schemas.md).
- **Upstream:** not proposed; upstream adds tables through its own chain.

## sidebar-sticky-toolbar

The sidebar's filter, Select sessions and bulk-action bar sit in a toolbar row
above the session list, so they stay in view however far the list scrolls.

- **Turn on:** on by default.
- **Docs:** [Sessions](../../feature-map/sessions.md) (Sidebar filter menu).
- **Upstream:** not proposed yet; no pull request or pushed branch.

## sidebar-updated-filter

A sidebar filter for sessions updated recently (**Updated**: 24 hours, 3, 7
or 30 days), with a chip beside the filter button while it is on.

- **Turn on:** on by default; choose a window under **Updated** in the
  sidebar's filter menu. Saved per device.
- **Docs:** [Sessions](../../feature-map/sessions.md) (`updated-filter`).
- **Upstream:** not proposed yet; no pull request or pushed branch. Upstream's
  filters behind `sidebar_saved_views` are not wired into the sidebar yet and
  have no update-time field.

## subagent-only-routing

A Claude Code or Codex session keeps the model you picked and lets Smart
Routing choose the model of each sub-agent it starts. Before, the CLI's own
sub-agents (Claude Code's `Agent`/`Task`, Codex's `spawn_agent`) were routed
only on a session launched on Smart Routing, which also routes the session's
own model.

- **Turn on:** needs Smart Routing on the server. In the new-session composer,
  pick a Claude Code or Codex model and check **Route sub-agents** in the model
  menu, or create the session with `subagent_routing_override: "on"`. The same
  row in the session's model menu turns it off and on. The gate is installed
  by the host when the session launches, so hosts need this build; a session
  created without the option routes child sessions only if its switch is
  turned on later. Refused on a session with a bound inference profile.
- **Docs:** [Composer](../../feature-map/composer.md) (`route-sub-agents`) and
  `subagent_routing_override` in the [API reference](../../omnigent/server/API.md).
- **Upstream:** not upstream yet; tracked by issue [#14897](https://github.com/omnigent-ai/omnigent/issues/14897).

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
- **Upstream:** not proposed yet: carried here while the design is discussed on
  upstream issue [#503](https://github.com/omnigent-ai/omnigent/issues/503) (open). The contribution branch is
  `feat/subscription-accounts`; no pull request is open from it.

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

## terminal-touch

The terminal on phones and tablets: an extra-keys row under it sends the keys
a soft keyboard lacks (Esc, Tab, Shift+Tab, arrows, Home/End, PgUp/PgDn, and
sticky Ctrl, Alt and Shift), and a long-press selects terminal text, with a
menu to Copy, Paste and Select screen. In the iOS app, Paste reads the
clipboard natively, so the app's paste permission applies instead of a prompt
on every paste. Upstream's one-finger swipe scrolling works as before.

- **Turn on:** on by default on touch devices. Settings → Appearance → Touch &
  mobile → **Extra keys row** chooses Auto (touch devices), Always or Never;
  the long-press has no setting. Native paste needs an iOS app built with the
  series.
- **Docs:** [Terminals](../../feature-map/terminals.md) (`touch-keys`,
  `touch-select`, and the iOS Paste gotcha).
- **Upstream:** the extra-keys row is carried from
  [#6136](https://github.com/omnigent-ai/omnigent/pull/6136) (not ours, open),
  squashed from its head `2a68aafb59`; the second patch is what that head
  lacks to pass main's web tests. The long-press and native paste are not
  proposed upstream yet (an issue and a pull request are drafted, not
  filed).

## tolerate-retired-preferences

A stored shared preference of a kind this build doesn't know, such as one a
parked or newer series saved, no longer makes every read of that user's
preferences fail with a 500. Reads skip it and log the kind once; the row
stays stored for a build that knows it, and writing an unknown kind is still
refused.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** not proposed upstream yet.

## transcript-hold-position

Scrolled up in a transcript, you keep your place while rows above you change
height: a reply still streaming, a tool group settling, an image loading,
rows measured as you scroll back. The transcript holds the row you are
reading itself instead of leaving it to the virtual list's own correction,
which skips rows crossing the top of the view, skips upward scrolls and, on
an iPhone, waits until the touch has ended.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/transcript-hold-position`.

## web-reconnect-shell-inputs

A queued `!command` no longer stays stuck at the bottom of the chat after the
connection drops and recovers.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/web-reconnect-settles-shell-inputs`.
