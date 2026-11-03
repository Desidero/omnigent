# Extension UI slots

UI slots are stable semantic locations where Omnigent renders a small,
declarative item: a link to an extension-owned page, or a session-row item that
shows one of the extension's published state fields or runs one of its
commands. Extensions do not receive DOM,
CSS-selector, React-component, or arbitrary HTML injection access.

| Slot | Kind | Limit | Context |
| --- | --- | --- | --- |
| `chat.header.actions` | `action` | 2 | Current `conversationId`, when present |
| `composer.actions` | `action` | 2 | Current `conversationId` in an existing session |
| `session.rightRail.tabs` | `tab` | 2 | Current `conversationId` |
| `settings.sections` | `section` | 3 | No session context; stays inside the settings route family |
| `session.row.decorations` | `decoration` | 1 | A sidebar session row; binds a published field |
| `session.row.menu` | `command` | 1 | A sidebar session row; names a command |
| `session.row.hover` | `row` | 1 | A sidebar session row; binds a published field |

The limit is per extension and slot; a manifest over it is rejected like any
other invalid field.

```python
from omnigent.extensions import SlotId, SlotItemContribution, SlotItemKind

SlotItemContribution(
    id="acme.review.composer-action",
    slot=SlotId.COMPOSER_ACTIONS,
    kind=SlotItemKind.ACTION,
    label="Review session",
    page="acme.review.dashboard",
    icon="search",
    order=500,
)
```

Slot items render only for extensions the operator enables in the server
config's `extensions` section; installation alone serves pages and navigation
but no slot items. See [Extensions](extensions.md#installation-and-diagnostics).

Every page-backed item (`action`, `tab`, `section`) references a page declared
by the same extension. Core owns its
placement, icon fallback, accessibility, responsive behavior, and routing.
`order` sorts only among extension items in the same slot; it cannot reorder
core controls. Settings sections are listed at the end of the General group,
after core's entries. `when` is reserved but not evaluated in V1.

Session-scoped links add `conversationId` to the parent route. The browser SDK
exposes it after activation as `context.invocation.conversationId`; extension
code never reads the parent URL directly. On hosts without slots,
`context.invocation` is empty. The value comes from the URL, so treat
it as a hint, not a grant: read the session through the permission-checked SDK,
which applies the viewer's own access. The composer slot passes it only once the
session exists.

A header or composer action can show one of its extension's published fields
as a visible label, such as "Watching 2 PRs", by naming it as `label_field`:

```python
SlotItemContribution(
    id="acme.goals.composer",
    slot=SlotId.COMPOSER_ACTIONS,
    kind=SlotItemKind.ACTION,
    label="Goals",
    page="acme.goals.page",
    icon="list-checks",
    label_field="summary",
)
```

While the session's field is set, the button shows the icon and the field's
text (truncated), with `<label>: <text>` as its accessible name and `label` as
its tooltip; otherwise it stays an icon button. The extension writes the whole
text, so it can pluralize. Core reads the field with the viewer's access when
the action renders, repaints it after a command from this browser or when the
session-updates stream sends the session's row, and otherwise refetches it when
the action next mounts once it is 30 seconds old. The
new-session composer has no session, so it always shows the icon.

Settings items route through `/settings/extensions/{extension}/{page}`, so the
settings sidebar remains visible. Action and rail items route through the normal
`/extensions/{extension}/{page}` namespace. On mobile, settings and action links
use the owning surface's normal close/navigation behavior.

A rail contribution is intentionally a page link pinned with the Workspace
panel's trailing controls, not a fake ARIA tab and not persisted as a `RightRailTab`. Inline rich
rail panels require a future contribution contract with explicit lifecycle and
persistence semantics.

## Session rows

The three `session.row.*` slots render on every session row in the sidebar.
Their items have no page and run no extension code: core draws them from the
manifest and the session's `published_fields`, and runs the extension's
declared commands through the server. See
[Extension session state](extension_state.md) for fields and commands.

| Kind | What core renders |
| --- | --- |
| `decoration` | The bound field's current value as its listed icon, in its tone, after core's "Shared with you" icon. Its accessible name and tooltip are `<item label>: <value label>`. The field must list its `values`. |
| `command` | An entry in the row's menu and right-click menu, after core's Mark as read / Mark as unread. A command without arguments is a plain entry that runs it. A command with one `choices` argument opens a submenu of the choices, then `clear_command`'s title if set; on phones it replaces the menu body, with a Back row. |
| `row` | A `<item label>: <value>` line in the row's tooltip, in the tooltip of either `sidebar_grouping_ui` state: the value's listed label and icon, or the field's text when it lists no values. Tooltips are desktop-only, so phones show the value through the badge alone. |

Nothing renders for an absent or empty field, and a badge shows nothing for an
unlisted value. A row shows items from at most two extensions per slot. An
item's `icon`, if set, must be an approved icon; core draws these without a
fallback.

When a command writes the bare argument (`value="{status}"`) to a published
field that lists its values, its choices show those values' labels, icons and
tones, and the current one is checked; the clear entry is disabled while the
field is unset. Otherwise choices show as their text.

Core's own entries in these slots ("Shared with you", and the Mark as read /
Mark as unread pair) go through the same resolver as extension items: core's
entries first, then extension items, each by `order` and then id. Core entries
carry a visibility check the web app evaluates; extension items don't, and
`when` stays unevaluated.

Commands run as the viewer. Every viewer sees the menu entry, but it is
disabled for viewers without the command's `required_access` (edit by
default), and the server refuses them anyway. A sub-agent session's access can
come from its parent session, so core leaves its entries enabled and lets the
server decide. A command's `confirm` text is
shown in a dialog before it runs; the server does not enforce it. The command's
response carries the session's published fields, so the row repaints at once;
other open clients show the change when the session-updates stream next sends
the row, or on their next fetch of the list.

```python
from omnigent.extensions import (
    ClearState,
    CommandArgument,
    CommandContribution,
    FieldBinding,
    FieldTone,
    FieldValue,
    SetState,
    SlotId,
    SlotItemContribution,
    SlotItemKind,
    StateContribution,
    StateField,
    StateVisibility,
)

ExtensionManifest(
    id="acme.status",
    # ...
    state=StateContribution(
        fields=(
            StateField(
                "status",
                StateVisibility.PUBLISHED,
                max_length=16,
                values=(
                    FieldValue("blocked", "Blocked", "octagon-alert", FieldTone.DANGER),
                    FieldValue("done", "Done", "circle-check", FieldTone.SUCCESS),
                ),
            ),
        ),
    ),
    commands=(
        CommandContribution(
            id="acme.status.set",
            title="Set status",
            action=SetState(key="status", value="{status}"),
            arguments=(CommandArgument("status", choices=("blocked", "done")),),
        ),
        CommandContribution(
            id="acme.status.clear", title="Clear status", action=ClearState("status")
        ),
    ),
    slot_items=(
        SlotItemContribution(
            id="acme.status.badge",
            slot=SlotId.SESSION_ROW_DECORATIONS,
            kind=SlotItemKind.DECORATION,
            label="Status",
            binding=FieldBinding("status"),
        ),
        SlotItemContribution(
            id="acme.status.menu",
            slot=SlotId.SESSION_ROW_MENU,
            kind=SlotItemKind.COMMAND,
            label="Status",
            command="acme.status.set",
            clear_command="acme.status.clear",
        ),
    ),
)
```

Field values use approved icons (`circle-check`, `circle-ellipsis`,
`dashboard`, `eye`, `list-checks`, `octagon-alert`, `panels-top-left`,
`puzzle`, `search`, `square-parking`), since the icon carries the value's
meaning, and tones (`neutral`, `info`, `success`, `warning`, `danger`) that
map to core's status colours, so values never rely on colour alone.

Published fields are extension state, not ordinary labels: their
`ext.<extension id>.<key>` mirrors are read-only, and only the extension's
commands (or its server code) change them. They stop rendering, and are hidden
from responses and policies, while the extension is installed but not
enabled.

## Migrating from declared labels

An earlier, unreleased version of the session-row slots let extensions declare
page-writable labels under `ext.<extension id>.`. That prefix now belongs to
core's read-only mirrors of published fields, so those manifests no longer
load; the load error points here. To move one over:

- Replace each `LabelDeclaration(key="ext.<id>.<name>", values=(LabelValue(...), ...))`
  in `labels=` with a published `StateField("<name>", StateVisibility.PUBLISHED,
  max_length=..., values=(FieldValue(...), ...))` in `state=`. `LabelTone` is now
  `FieldTone`.
- Replace `LabelBinding(key)` with `FieldBinding("<name>")` on decorations and
  hover rows.
- Replace a `SlotItemKind.SET_LABEL` menu item with `SlotItemKind.COMMAND`,
  naming a `SetState("<name>", "{<argument>}")` command with one `choices`
  argument, and a `ClearState("<name>")` command as `clear_command` in place of
  `clear_label`.
- Drop `ExtensionPermission.SESSIONS_LABELS_WRITE`. Pages that called
  `sessions.labels.set` or `clear` call `commands.invoke` instead.
- Enable the extension in the server config; state needs operator enablement.

Labels written under the old scheme stay in the database but are hidden once
the extension declares published fields, because no state row backs them.
Find, rename or delete them with `omni extensions legacy-labels` (see
[Extension session state](extension_state.md#labels-no-extension-state-backs)).
