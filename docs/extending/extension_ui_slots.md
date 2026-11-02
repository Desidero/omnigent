# Extension UI slots

UI slots are stable semantic locations where Omnigent renders a small,
declarative item: a link to an extension-owned page, or a session-row item bound
to a label the extension declares. Extensions do not receive DOM,
CSS-selector, React-component, or arbitrary HTML injection access.

| Slot | Kind | Limit | Context |
| --- | --- | --- | --- |
| `chat.header.actions` | `action` | 2 | Current `conversationId`, when present |
| `composer.actions` | `action` | 2 | Current `conversationId` in an existing session |
| `session.rightRail.tabs` | `tab` | 2 | Current `conversationId` |
| `settings.sections` | `section` | 3 | No session context; stays inside the settings route family |
| `session.row.decorations` | `decoration` | 1 | A sidebar session row; binds a declared label |
| `session.row.menu` | `set-label` | 1 | A sidebar session row; binds a declared label |
| `session.row.hover` | `row` | 1 | A sidebar session row; binds a declared label |

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
Their items have no page and run no extension code: each binds a label the
extension declares, and core draws it from the manifest.

| Kind | What core renders |
| --- | --- |
| `decoration` | The current value's icon, in its tone, after core's "Shared with you" icon. Its accessible name and tooltip are `<item label>: <value label>`. |
| `set-label` | A submenu in the row's menu and right-click menu, after core's Mark as read / Mark as unread, listing the declared values (the current one checked) and a clear entry (`clear_label`, or "Clear"). On phones it replaces the menu body, with a Back row. |
| `row` | A `<item label>: <value label>` line in the row's tooltip, in the tooltip of either `sidebar_grouping_ui` state. Tooltips are desktop-only, so phones show the value through the badge alone. |

Nothing renders for an absent, empty or undeclared value. A row shows items from
at most two extensions per slot. An item's `icon`, if set, must be an approved
icon; core draws these without a fallback.

Core's own entries in these slots ("Shared with you", and the Mark as read /
Mark as unread pair) go through the same resolver as extension items: core's
entries first, then extension items, each by `order` and then id. Core entries
carry a visibility check the web app evaluates; extension items don't, and
`when` stays unevaluated.

The set-label menu needs the `sessions.labels.write` permission and appears only
to viewers with edit access to the session (owners, editors and managers). Viewers
with read access see decorations and tooltip rows but no menu.

```python
from omnigent.extensions import (
    ExtensionPermission,
    LabelBinding,
    LabelDeclaration,
    LabelTone,
    LabelValue,
    SlotId,
    SlotItemContribution,
    SlotItemKind,
)

STATUS = "ext.acme.status.status"

ExtensionManifest(
    id="acme.status",
    # ...
    permissions=frozenset({ExtensionPermission.SESSIONS_LABELS_WRITE}),
    labels=(
        LabelDeclaration(
            key=STATUS,
            title="Status",
            values=(
                LabelValue("blocked", "Blocked", "octagon-alert", LabelTone.DANGER),
                LabelValue("done", "Done", "circle-check", LabelTone.SUCCESS),
            ),
        ),
    ),
    slot_items=(
        SlotItemContribution(
            id="acme.status.badge",
            slot=SlotId.SESSION_ROW_DECORATIONS,
            kind=SlotItemKind.DECORATION,
            label="Status",
            binding=LabelBinding(STATUS),
        ),
        SlotItemContribution(
            id="acme.status.menu",
            slot=SlotId.SESSION_ROW_MENU,
            kind=SlotItemKind.SET_LABEL,
            label="Status",
            binding=LabelBinding(STATUS),
        ),
    ),
)
```

## Declared labels

A declared label is an ordinary session label whose key and values an extension
declares, not extension-owned state:

- The key is `ext.<extension id>.<name>`, with one lowercase name segment and at
  most 128 characters. An extension declares at most four labels.
- Each label lists 1 to 12 values. A value is a lowercase slug with a display
  label, an icon and a tone. Icons come from the approved set (`circle-check`,
  `circle-ellipsis`, `dashboard`, `eye`, `list-checks`, `octagon-alert`,
  `panels-top-left`, `puzzle`, `search`, `square-parking`), since the icon
  carries the value's meaning. Tones (`neutral`, `info`, `success`, `warning`,
  `danger`) map to core's status colours, so values never rely on colour alone.
- The server only accepts declared values under an installed extension's
  `ext.<extension id>.` prefix. `PATCH /v1/sessions/{id}` and session creation
  reject an undeclared key or value; policy label writes drop one, like other
  invalid policy writes; a fork leaves behind copied labels the declaration no
  longer accepts. An empty value deletes the label, as it does for the project
  label. Keys under `ext.` whose extension isn't installed, or is turned off,
  stay ordinary labels.
- Writes go through `PATCH /v1/sessions/{id}` as the viewer, so the session's
  normal edit check applies. Anyone with edit access can also change the label
  through the API or CLI, and it stays when the extension is disabled or
  uninstalled; only its badge, menu and tooltip row stop rendering.
