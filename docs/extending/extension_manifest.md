# Extension manifest

An extension registers a lightweight factory under the
`omnigent.extensions` Python entry-point group:

```toml
[project.entry-points."omnigent.extensions"]
review = "acme_review.plugin:get_manifest"
```

The factory returns immutable values from `omnigent.extensions` and should not
import runtime or UI implementation modules.

```python
from omnigent.extensions import (
    EXTENSION_API_VERSION,
    ExtensionEntrypoints,
    ExtensionManifest,
    ExtensionPermission,
    PageContribution,
    PrimaryNavigationContribution,
    SlotId,
    SlotItemContribution,
    SlotItemKind,
)


def get_manifest() -> ExtensionManifest:
    return ExtensionManifest(
        id="acme.review",
        display_name="Acme Review",
        distribution="omnigent-acme-review",
        version="1.0.0",
        requires_omnigent=">=0.11,<1",
        extension_api=EXTENSION_API_VERSION,
        entrypoints=ExtensionEntrypoints(
            browser="dist/extension.js",
            browser_css="dist/extension.css",
        ),
        permissions=frozenset({ExtensionPermission.NAVIGATION}),
        pages=(
            PageContribution(
                id="acme.review.dashboard",
                title="Reviews",
                route="reviews",
                view="dashboard",
            ),
        ),
        primary_navigation=(
            PrimaryNavigationContribution(
                id="acme.review.primary-nav",
                label="Reviews",
                page="acme.review.dashboard",
                icon="search",
                order=500,
            ),
        ),
        slot_items=(
            SlotItemContribution(
                id="acme.review.composer-action",
                slot=SlotId.COMPOSER_ACTIONS,
                kind=SlotItemKind.ACTION,
                label="Review session",
                page="acme.review.dashboard",
            ),
        ),
    )
```

## Rules

- IDs are lowercase, publisher-qualified, immutable, and globally collision
  checked. Contribution IDs begin with the owning extension ID. The `core.`
  prefix is reserved for Omnigent's own slot entries.
- Page routes contain exactly one safe segment and are always namespaced.
- The manifest distribution/version must match installed package metadata.
- `requires_omnigent` is a PEP 440 release-line range.
- Browser paths are fixed to `dist/extension.js` and optional
  `dist/extension.css` inside the entry point's verified import package.
- Slot items use a supported slot/kind pairing, reference a page owned by the
  same extension (or, for session-row kinds, bind one of its declared labels),
  stay within each slot's per-extension limit, and cannot reorder core UI.
- Declared `labels` use keys under `ext.<extension id>.`, approved icons and
  known tones; a `set-label` item requires the `sessions.labels.write`
  permission. See
  [Extension UI slots](extension_ui_slots.md).
- Built-ins are reserved. All community extensions participating in a collision
  are disabled deterministically.
- One invalid field rejects the whole extension; one rejected extension does not
  prevent others from loading.

## Compatibility

The extension API major is independent of the Omnigent package version. V1
changes are additive; authors must ignore unknown catalog fields. Breaking
changes require a new extension API major. Deprecations name the Omnigent
release in which removal is planned and remain supported through the stated
window.

Extension packages can run the same manifest and bundle checks in their own
focused tests without starting a server:

```python
from pathlib import Path
from omnigent.extensions import check_extension_package

check_extension_package(
    get_manifest(),
    project_root=Path(__file__).parents[2],
    package_root=Path(__file__).parent,
)
```

`activation_events` and `when` are reserved metadata only in V1. Do not rely on
them until a later API explicitly documents execution.

## Session state and commands

`state` declares the keys an extension keeps about a session and who may read
them; a command with a `SetState` or `ClearState` action writes them on the
server for users with enough access to the session:

```python
from omnigent.extensions import (
    CommandArgument,
    CommandContribution,
    SetState,
    StateContribution,
    StateField,
    StateVisibility,
)

state = StateContribution(
    fields=(
        StateField("status", StateVisibility.PUBLISHED, max_length=32),
        StateField("pr:*", StateVisibility.READERS),
    ),
)
commands = (
    CommandContribution(
        id="acme.review.set-status",
        title="Set status",
        action=SetState(key="status", value="{status}"),
        arguments=(CommandArgument("status", choices=("blocked", "done")),),
    ),
)
```

- Keys are 1-128 characters from letters, digits and `._:=+/@-`. A field key
  ending in `*` declares every key with that prefix.
- Visibility is `service` (the default for undeclared keys: server code only),
  `editors`, `readers`, or `published`. Published fields are exact lowercase
  keys of UTF-8 text up to `max_length` (at most 256) characters; at most three
  per extension, and `ext.<extension id>.<key>` must fit in 128 characters.
- Command arguments need `choices` or a full-match `pattern`, and every
  declared argument must appear in the key or value template. Commands without
  an action stay reserved metadata.
- A command's key template writes to exactly one declared field: an exact key,
  or a `prefix*` field whose prefix is literal text before the first
  placeholder (`pr:{pr}` under `pr:*`, never `{name}`). A bound key that
  another declaration covers is refused. Writing a `service` field needs
  `writes_service_state=True` on the command.
- Commands create at most `max_keys` keys under one prefix field (16 by
  default) and 48 keys per extension in total, leaving room for the
  extension's server code.
- `confirm` is a prompt for clients to show before running the command; the
  server does not enforce it.

See [Extension session state](extension_state.md) for storage limits, access
rules and the HTTP API.
