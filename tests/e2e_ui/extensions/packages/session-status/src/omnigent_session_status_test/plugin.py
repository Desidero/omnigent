"""A status label shown as a row badge and set from the row menu."""

from omnigent.extensions import (
    EXTENSION_API_VERSION,
    ExtensionManifest,
    ExtensionPermission,
    LabelBinding,
    LabelDeclaration,
    LabelTone,
    LabelValue,
    SlotId,
    SlotItemContribution,
    SlotItemKind,
)

_EXTENSION_ID = "omnigent-test.session-status"
_KEY = f"ext.{_EXTENSION_ID}.status"


def get_manifest() -> ExtensionManifest:
    """Return the test extension's declarative contribution: no pages or bundle."""
    binding = LabelBinding(_KEY)
    return ExtensionManifest(
        id=_EXTENSION_ID,
        display_name="Session status",
        distribution="omnigent-session-status-test",
        version="0.1.0",
        requires_omnigent=">=0.11,<1",
        extension_api=EXTENSION_API_VERSION,
        permissions=frozenset({ExtensionPermission.SESSIONS_LABELS_WRITE}),
        labels=(
            LabelDeclaration(
                key=_KEY,
                title="Status",
                values=(
                    LabelValue("in-progress", "In progress", "circle-ellipsis", LabelTone.INFO),
                    LabelValue("blocked", "Blocked", "octagon-alert", LabelTone.DANGER),
                    LabelValue("needs-review", "Needs review", "eye", LabelTone.WARNING),
                    LabelValue("parked", "Parked", "square-parking", LabelTone.NEUTRAL),
                    LabelValue("done", "Done", "circle-check", LabelTone.SUCCESS),
                ),
            ),
        ),
        slot_items=(
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.badge",
                slot=SlotId.SESSION_ROW_DECORATIONS,
                kind=SlotItemKind.DECORATION,
                label="Status",
                binding=binding,
            ),
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.menu",
                slot=SlotId.SESSION_ROW_MENU,
                kind=SlotItemKind.SET_LABEL,
                label="Status",
                binding=binding,
                clear_label="Clear status",
            ),
        ),
    )
