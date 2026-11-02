"""Manifest entry point for the review checklist extension."""

from omnigent.extensions import (
    EXTENSION_API_VERSION,
    ExtensionEntrypoints,
    ExtensionManifest,
    ExtensionPermission,
    PageContribution,
    SlotId,
    SlotItemContribution,
    SlotItemKind,
)

_EXTENSION_ID = "omnigent.review-checklist"
_REVIEW_PAGE = f"{_EXTENSION_ID}.review"
_TEMPLATES_PAGE = f"{_EXTENSION_ID}.templates"


def get_manifest() -> ExtensionManifest:
    """Return the checklist's pages and its header, composer and settings links."""
    return ExtensionManifest(
        id=_EXTENSION_ID,
        display_name="Review checklist",
        distribution="omnigent-review-checklist-extension",
        version="0.1.0",
        requires_omnigent=">=0.11,<1",
        extension_api=EXTENSION_API_VERSION,
        entrypoints=ExtensionEntrypoints(
            browser="dist/extension.js",
            browser_css="dist/extension.css",
        ),
        permissions=frozenset(
            {
                ExtensionPermission.NAVIGATION,
                ExtensionPermission.SESSIONS_READ,
                ExtensionPermission.PROJECTS_READ,
                ExtensionPermission.STORAGE_USER,
            }
        ),
        pages=(
            PageContribution(
                id=_REVIEW_PAGE, title="Review checklist", route="review", view="review"
            ),
            PageContribution(
                id=_TEMPLATES_PAGE,
                title="Review checklists",
                route="templates",
                view="templates",
            ),
        ),
        slot_items=(
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.header-action",
                slot=SlotId.CHAT_HEADER_ACTIONS,
                kind=SlotItemKind.ACTION,
                label="Review checklist",
                page=_REVIEW_PAGE,
                icon="search",
            ),
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.composer-action",
                slot=SlotId.COMPOSER_ACTIONS,
                kind=SlotItemKind.ACTION,
                label="Review checklist",
                page=_REVIEW_PAGE,
                icon="search",
            ),
            SlotItemContribution(
                id=f"{_EXTENSION_ID}.settings",
                slot=SlotId.SETTINGS_SECTIONS,
                kind=SlotItemKind.SECTION,
                label="Review checklists",
                page=_TEMPLATES_PAGE,
                icon="search",
                order=175,
            ),
        ),
    )
