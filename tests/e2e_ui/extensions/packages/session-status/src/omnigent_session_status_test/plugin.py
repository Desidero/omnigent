"""A published status field shown as a row badge and tooltip row, set from the row menu."""

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

_EXTENSION_ID = "omnigent-test.session-status"
_STATUSES = (
    FieldValue("in-progress", "In progress", "circle-ellipsis", FieldTone.INFO),
    FieldValue("blocked", "Blocked", "octagon-alert", FieldTone.DANGER),
    FieldValue("needs-review", "Needs review", "eye", FieldTone.WARNING),
    FieldValue("parked", "Parked", "square-parking", FieldTone.NEUTRAL),
    FieldValue("done", "Done", "circle-check", FieldTone.SUCCESS),
)


def get_manifest() -> ExtensionManifest:
    """Return the test extension's declarative contribution: no pages or bundle."""
    return ExtensionManifest(
        id=_EXTENSION_ID,
        display_name="Session status",
        distribution="omnigent-session-status-test",
        version="0.1.0",
        requires_omnigent=">=0.11,<1",
        extension_api=EXTENSION_API_VERSION,
        state=StateContribution(
            fields=(
                StateField("status", StateVisibility.PUBLISHED, max_length=16, values=_STATUSES),
            )
        ),
        commands=(
            CommandContribution(
                id=f"{_EXTENSION_ID}.set",
                title="Set status",
                action=SetState(key="status", value="{status}"),
                arguments=(
                    CommandArgument("status", choices=tuple(status.value for status in _STATUSES)),
                ),
            ),
            CommandContribution(
                id=f"{_EXTENSION_ID}.clear",
                title="Clear status",
                action=ClearState(key="status"),
            ),
        ),
        slot_items=(
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.badge",
                slot=SlotId.SESSION_ROW_DECORATIONS,
                kind=SlotItemKind.DECORATION,
                label="Status",
                binding=FieldBinding("status"),
            ),
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.menu",
                slot=SlotId.SESSION_ROW_MENU,
                kind=SlotItemKind.COMMAND,
                label="Status",
                command=f"{_EXTENSION_ID}.set",
                clear_command=f"{_EXTENSION_ID}.clear",
            ),
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.hover",
                slot=SlotId.SESSION_ROW_HOVER,
                kind=SlotItemKind.ROW,
                label="Status",
                binding=FieldBinding("status"),
            ),
        ),
    )
