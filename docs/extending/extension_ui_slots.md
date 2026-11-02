# Extension UI slots

UI slots are stable semantic locations where Omnigent renders a small,
declarative link to an extension-owned page. Extensions do not receive DOM,
CSS-selector, React-component, or arbitrary HTML injection access.

| Slot | Kind | Context |
| --- | --- | --- |
| `chat.header.actions` | `action` | Current `conversationId`, when present |
| `composer.actions` | `action` | Current `conversationId` in an existing session |
| `session.rightRail.tabs` | `tab` | Current `conversationId` |
| `settings.sections` | `section` | No session context; stays inside the settings route family |

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

Every item references a page declared by the same extension. Core owns its
placement, icon fallback, accessibility, responsive behavior, and routing.
`order` sorts only among extension items in the same slot; it cannot reorder
core controls. `when` is reserved but not evaluated in V1.

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
