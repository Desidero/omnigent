# Session status extension

An example Omnigent extension (`omnigent.session-status`). It marks sidebar
session rows with a status a person sets: a badge on the row, a **Status**
submenu in the row's menu, and a line in the row's tooltip. It is
**manifest-only**: no server code, no browser bundle and no pages. Core stores
the status as [extension session state](../../../docs/extending/extension_state.md),
draws everything through the
[session-row slots](../../../docs/extending/extension_ui_slots.md#session-rows),
and runs the two commands the manifest declares to change it.

| Status | Icon | Tone | Meaning |
| --- | --- | --- | --- |
| In progress | `circle-ellipsis` | info | Someone is actively on it |
| Blocked | `octagon-alert` | danger | Can't continue without something outside |
| Needs review | `eye` | warning | Work done; a person should look |
| Parked | `square-parking` | neutral | Set aside on purpose; not forgotten |
| Done | `circle-check` | success | Finished; nothing more expected |

These are workflow marks people set, separate from core's live run state (the
spinner, "Needs response", the unread dot), so there is no "Working" status.
Each has its own icon shape and text, so none relies on colour alone.

| Slot | What core renders |
| --- | --- |
| `session.row.decorations` | The status icon after core's "Shared with you" icon, named "Status: Blocked" for screen readers and in its tooltip |
| `session.row.menu` | A **Status** submenu in the row's ⋯ and right-click menus: the five statuses (the current one checked), then **Clear status**. On phones it replaces the menu body, with a Back row |
| `session.row.hover` | A "Status: Blocked" line in the row's tooltip; with the `sidebar_grouping_ui` feature on, a Status row among the tooltip's label/value rows |

## Who can set it

The status is a published state field, `status`, holding one of the slugs
`in-progress`, `blocked`, `needs-review`, `parked` or `done`. Core shows it on
the session as `published_fields: {"omnigent.session-status": {"status": "blocked"}}`
and mirrors it as the read-only label `ext.omnigent.session-status.status`.

- Everyone who can read a session sees its badge and tooltip line.
- Everyone sees the **Status** submenu, but it is disabled for viewers who
  can't edit the session; owners, editors and managers can use it.
- Choosing a status runs the `omnigent.session-status.set` command
  (`POST /v1/sessions/{id}/extensions/omnigent.session-status/commands/omnigent.session-status.set`
  with `{"arguments": {"status": "blocked"}}`) as the viewer, so the server
  checks edit access and accepts only the five statuses. **Clear status** runs
  `omnigent.session-status.clear`. The server records who set it.
- Nobody can write the label directly: `PATCH /v1/sessions/{id}` refuses
  `ext.` labels. While the extension is installed but not enabled, the status
  is hidden; it is deleted with the session.

## Policies

Policies read the status as the label `ext.omnigent.session-status.status`.
For example, to stop tool calls while a session is marked Blocked:

```yaml
guardrails:
  policies:
    hold-while-blocked:
      type: function
      condition:
        ext.omnigent.session-status.status: blocked
      function:
        path: myorg.policies.deny_tool_calls
```

While the extension is not enabled, the field is unavailable and such a policy
denies rather than treating the status as unset; see
[Policies](../../../docs/POLICIES.md#extension-published-fields).

## What it doesn't do

- Restrict who sets it beyond edit access: anyone who can edit the session
  can choose any status.
- Set a status by itself from run state, pull requests or a timer. "Done"
  doesn't archive anything and "Blocked" doesn't notify anyone.
- Filter, group or sort the sidebar by status.
- Give each person their own status: one status per session, shared by every
  viewer.
- Set a status on several selected rows at once.
- Take its words from server config: to use your team's own, copy the package
  and edit `STATUSES` in `plugin.py`. Keep a slug when you only rename its
  label, since sessions store the slug.

## Install and enable

There is nothing to build. Install the package into the server's environment,
enable it in the server config and restart the server:

```bash
uv pip install examples/extensions/session-status
uv run omnigent extensions doctor omnigent.session-status
```

```yaml
extensions:
  omnigent.session-status:
    enabled: true
```

Installed but not enabled, it shows nothing and its commands answer `404`;
statuses set earlier are kept, hidden, until it is enabled again.

Tests: `tests/extensions/test_session_status_extension.py` (package and
manifest checks) and `tests/e2e_ui/extensions/test_session_status.py` (the
installed wheel in a real server and browser).

## Credits

- **Analytic Endeavors**: a status icon on session rows and a Status submenu in
  the sidebar session menu, from the public `patches/README.md` (entries 0001
  and 0004) and the "Status-aware sidebar" and "Sidebar group by status"
  screenshots (`docs/media/sidebar-activity.webp`,
  `sidebar-group-by-status.webp`) of
  [omnigent-ae-public](https://github.com/analyticendeavors/omnigent-ae-public).
  Their triage states (Working, Blocked, Review, Parked) shaped this set.
  Apache-2.0; descriptions and images only, no code read.
- **randypitcherii**: user-managed labels for categories such as review status,
  and reserving `omnigent.*` keys, in
  [#5909](https://github.com/omnigent-ai/omnigent/issues/5909).
- **ychamare**: a colour on a session from the sidebar row menu, stored as a
  label, in [#2137](https://github.com/omnigent-ai/omnigent/pull/2137).
- **faaizzz**: telling completed sessions from ongoing ones in the list, in
  [#3364](https://github.com/omnigent-ai/omnigent/issues/3364).
- **hzub**: the label/value session tooltip behind `sidebar_grouping_ui`, in
  [#9792](https://github.com/omnigent-ai/omnigent/pull/9792).
- The other requests for status marks on session rows, among them
  [#861](https://github.com/omnigent-ai/omnigent/issues/861),
  [#2117](https://github.com/omnigent-ai/omnigent/issues/2117),
  [#8670](https://github.com/omnigent-ai/omnigent/issues/8670) and
  [#9610](https://github.com/omnigent-ai/omnigent/issues/9610).
