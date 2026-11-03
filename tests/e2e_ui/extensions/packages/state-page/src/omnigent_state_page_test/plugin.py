"""A page that runs commands and reads state, and a header action labelled by a field."""

from omnigent.extensions import (
    EXTENSION_API_VERSION,
    CommandAccess,
    CommandArgument,
    CommandContribution,
    ExtensionEntrypoints,
    ExtensionManifest,
    PageContribution,
    SetState,
    SlotId,
    SlotItemContribution,
    SlotItemKind,
    StateContribution,
    StateField,
    StateVisibility,
)

_EXTENSION_ID = "omnigent-test.state-page"
_PAGE_ID = f"{_EXTENSION_ID}.page"


def get_manifest() -> ExtensionManifest:
    """Return the test extension's manifest; the page bundle is built from ``web/``."""
    return ExtensionManifest(
        id=_EXTENSION_ID,
        display_name="State page",
        distribution="omnigent-state-page-test",
        version="0.1.0",
        requires_omnigent=">=0.11,<1",
        extension_api=EXTENSION_API_VERSION,
        entrypoints=ExtensionEntrypoints(browser="dist/extension.js"),
        pages=(PageContribution(id=_PAGE_ID, title="State page", route="goals", view="goals"),),
        state=StateContribution(
            fields=(
                StateField("summary", StateVisibility.PUBLISHED, max_length=32),
                StateField("pr:*", StateVisibility.READERS),
            )
        ),
        commands=(
            CommandContribution(
                id=f"{_EXTENSION_ID}.watch",
                title="Watch PR",
                action=SetState(key="pr:{pr}", value="watching"),
                arguments=(CommandArgument("pr", pattern="[0-9]{1,6}"),),
                required_access=CommandAccess.READ,
            ),
            CommandContribution(
                id=f"{_EXTENSION_ID}.summarize",
                title="Summarize",
                action=SetState(key="summary", value="{text}"),
                arguments=(CommandArgument("text", pattern="[A-Za-z0-9 ]{1,32}"),),
            ),
        ),
        slot_items=(
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.header-action",
                slot=SlotId.CHAT_HEADER_ACTIONS,
                kind=SlotItemKind.ACTION,
                label="Goals",
                page=_PAGE_ID,
                icon="list-checks",
                label_field="summary",
            ),
        ),
    )
