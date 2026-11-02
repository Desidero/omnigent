"""Manifest entry point for the session status extension.

The whole extension is this manifest: one published state field, two commands
that set and clear it, and three session-row items bound to them. Core stores
the status, draws the badge, the menu and the tooltip row, and runs the
commands; no extension code runs. To use your team's own words, edit
``STATUSES`` (values are stored, so keep existing slugs when renaming).
"""

from omnigent.extensions import (
    EXTENSION_API_VERSION,
    ClearState,
    CommandArgument,
    CommandContribution,
    ExtensionManifest,
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

EXTENSION_ID = "omnigent.session-status"
STATUS_FIELD = "status"
# The read-only label core mirrors the published field into, for policies.
STATUS_LABEL = f"ext.{EXTENSION_ID}.{STATUS_FIELD}"
SET_COMMAND = f"{EXTENSION_ID}.set"
CLEAR_COMMAND = f"{EXTENSION_ID}.clear"

# Menu order is table order. Each status has its own icon shape, so it never
# relies on colour alone.
STATUSES = (
    FieldValue("in-progress", "In progress", "circle-ellipsis", FieldTone.INFO),
    FieldValue("blocked", "Blocked", "octagon-alert", FieldTone.DANGER),
    FieldValue("needs-review", "Needs review", "eye", FieldTone.WARNING),
    FieldValue("parked", "Parked", "square-parking", FieldTone.NEUTRAL),
    FieldValue("done", "Done", "circle-check", FieldTone.SUCCESS),
)


def get_manifest() -> ExtensionManifest:
    """Return the status field, its commands, and its row badge, row menu and tooltip row."""
    binding = FieldBinding(STATUS_FIELD)
    return ExtensionManifest(
        id=EXTENSION_ID,
        display_name="Session status",
        distribution="omnigent-session-status-extension",
        version="0.1.0",
        requires_omnigent=">=0.11,<1",
        extension_api=EXTENSION_API_VERSION,
        state=StateContribution(
            fields=(
                StateField(
                    STATUS_FIELD,
                    StateVisibility.PUBLISHED,
                    max_length=16,
                    values=STATUSES,
                ),
            )
        ),
        commands=(
            CommandContribution(
                id=SET_COMMAND,
                title="Set status",
                action=SetState(key=STATUS_FIELD, value="{status}"),
                arguments=(
                    CommandArgument("status", choices=tuple(item.value for item in STATUSES)),
                ),
            ),
            CommandContribution(
                id=CLEAR_COMMAND,
                title="Clear status",
                action=ClearState(key=STATUS_FIELD),
            ),
        ),
        slot_items=(
            SlotItemContribution(
                id=f"{EXTENSION_ID}.badge",
                slot=SlotId.SESSION_ROW_DECORATIONS,
                kind=SlotItemKind.DECORATION,
                label="Status",
                binding=binding,
            ),
            SlotItemContribution(
                id=f"{EXTENSION_ID}.menu",
                slot=SlotId.SESSION_ROW_MENU,
                kind=SlotItemKind.COMMAND,
                label="Status",
                command=SET_COMMAND,
                clear_command=CLEAR_COMMAND,
            ),
            SlotItemContribution(
                id=f"{EXTENSION_ID}.hover",
                slot=SlotId.SESSION_ROW_HOVER,
                kind=SlotItemKind.ROW,
                label="Status",
                binding=binding,
            ),
        ),
    )
