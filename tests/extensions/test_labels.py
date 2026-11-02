"""Declared session labels: manifest validation and the server's write check."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

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
    validate_manifest,
)
from omnigent.extensions.labels import ExtensionLabelError, ExtensionLabelPolicy
from omnigent.extensions.registry import ExtensionValidationError

_ID = "acme.status"
_KEY = f"ext.{_ID}.status"
_STATUS = LabelDeclaration(
    key=_KEY,
    title="Status",
    values=(
        LabelValue("blocked", "Blocked", "octagon-alert", LabelTone.DANGER),
        LabelValue("done", "Done", "circle-check", LabelTone.SUCCESS),
    ),
)


def _item(slot: SlotId, kind: SlotItemKind, **changes: object) -> SlotItemContribution:
    item = SlotItemContribution(
        id=f"{_ID}.{kind.value}", slot=slot, kind=kind, label="Status", binding=LabelBinding(_KEY)
    )
    return replace(item, **changes)


_ROW_ITEMS = (
    _item(SlotId.SESSION_ROW_DECORATIONS, SlotItemKind.DECORATION),
    _item(SlotId.SESSION_ROW_MENU, SlotItemKind.SET_LABEL),
)


def _manifest(**changes: object) -> ExtensionManifest:
    """A manifest-only extension: labels and row items, no pages or bundle."""
    manifest = ExtensionManifest(
        id=_ID,
        display_name="Status",
        distribution="acme-status",
        version="1.0.0",
        requires_omnigent=">=0.1",
        extension_api=EXTENSION_API_VERSION,
        permissions=frozenset({ExtensionPermission.SESSIONS_LABELS_WRITE}),
        labels=(_STATUS,),
        slot_items=_ROW_ITEMS,
    )
    return replace(manifest, **changes)


def test_accepts_a_manifest_only_extension_with_row_items() -> None:
    validate_manifest(_manifest())
    menu = _item(
        SlotId.SESSION_ROW_MENU, SlotItemKind.SET_LABEL, icon="eye", clear_label="Clear status"
    )
    validate_manifest(_manifest(slot_items=(menu,)))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"labels": (replace(_STATUS, key="status"),)}, "must be ext.acme.status.<name>"),
        ({"labels": (replace(_STATUS, key="ext.other.status"),)}, "must be ext.acme.status."),
        ({"labels": (replace(_STATUS, key=f"ext.{_ID}.a.b"),)}, "one lowercase name segment"),
        ({"labels": (replace(_STATUS, key=f"ext.{_ID}.{'x' * 120}"),)}, "at most 128"),
        ({"labels": (replace(_STATUS, values=()),)}, "values must be a tuple"),
        (
            {"labels": (replace(_STATUS, values=(LabelValue("Done!", "Done", "eye"),)),)},
            "lowercase slug",
        ),
        (
            {"labels": (replace(_STATUS, values=(LabelValue("done", "Done", "constructor"),)),)},
            "unknown icon 'constructor'",
        ),
        (
            {"labels": (replace(_STATUS, values=(LabelValue("done", "Done", "eye", "red"),)),)},  # type: ignore[arg-type]
            "unsupported tone",
        ),
        ({"labels": (replace(_STATUS, values=_STATUS.values * 2),)}, "duplicate label"),
        ({"labels": (_STATUS, _STATUS)}, "duplicate label keys"),
        ({"labels": ()}, "must bind a label its extension declares"),
        ({"permissions": frozenset()}, "does not request 'sessions.labels.write'"),
        (
            {"slot_items": (_item(SlotId.SESSION_ROW_MENU, SlotItemKind.SET_LABEL, page="x.y"),)},
            "cannot reference a page",
        ),
        (
            {
                "slot_items": (
                    _item(SlotId.SESSION_ROW_DECORATIONS, SlotItemKind.DECORATION, binding=None),
                )
            },
            "must bind a label",
        ),
        (
            {
                "slot_items": (
                    _item(SlotId.SESSION_ROW_DECORATIONS, SlotItemKind.DECORATION),
                    _item(
                        SlotId.SESSION_ROW_DECORATIONS,
                        SlotItemKind.DECORATION,
                        id=f"{_ID}.badge-2",
                    ),
                )
            },
            "the limit is 1",
        ),
        (
            {"slot_items": (_item(SlotId.SESSION_ROW_MENU, SlotItemKind.DECORATION),)},
            "kind must be 'set-label'",
        ),
        (
            {"slot_items": (_item(SlotId.SESSION_ROW_MENU, SlotItemKind.SET_LABEL, icon="nope"),)},
            "unknown icon 'nope'",
        ),
        (
            {
                "slot_items": (
                    _item(
                        SlotId.SESSION_ROW_DECORATIONS, SlotItemKind.DECORATION, clear_label="X"
                    ),
                )
            },
            "cannot set clear_label",
        ),
    ],
)
def test_rejects_invalid_label_declarations_and_row_items(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ExtensionValidationError, match=message):
        validate_manifest(_manifest(**changes))


def test_page_backed_items_cannot_bind_a_label() -> None:
    item = SlotItemContribution(
        id=f"{_ID}.action",
        slot=SlotId.CHAT_HEADER_ACTIONS,
        kind=SlotItemKind.ACTION,
        label="Status",
        page=f"{_ID}.page",
        binding=LabelBinding(_KEY),
    )
    with pytest.raises(ExtensionValidationError, match="cannot bind a label"):
        validate_manifest(_manifest(slot_items=(item,)))


def test_policy_accepts_declared_values_clears_and_unowned_keys() -> None:
    policy = ExtensionLabelPolicy([_manifest()])

    policy.check({_KEY: "blocked", "team": "ml"})
    policy.check({_KEY: ""})
    # No installed extension owns these, so they stay ordinary labels.
    policy.check({"ext.other.status": "anything", "ext.acme.status-two.x": "y", "ext.acme.x": "y"})
    policy.check(None)
    assert policy.declares(_KEY)
    assert not policy.declares("ext.other.status")


@pytest.mark.parametrize(
    ("labels", "message"),
    [
        ({_KEY: "bogus"}, "does not accept 'bogus'"),
        ({f"ext.{_ID}.priority": "high"}, "is not declared by extension 'acme.status'"),
        # Extra segments stay inside the installed extension's namespace.
        ({f"ext.{_ID}.status.extra": "done"}, "is not declared by extension 'acme.status'"),
    ],
)
def test_policy_rejects_writes_outside_the_declaration(
    labels: dict[str, str], message: str
) -> None:
    with pytest.raises(ExtensionLabelError, match=message):
        ExtensionLabelPolicy([_manifest()]).check(labels)


def test_overlapping_extension_ids_each_own_their_declared_keys() -> None:
    nested = _manifest(
        id=f"{_ID}.team",
        labels=(replace(_STATUS, key=f"ext.{_ID}.team.status"),),
        slot_items=(),
    )
    policy = ExtensionLabelPolicy([_manifest(), nested])

    policy.check({_KEY: "done", f"ext.{_ID}.team.status": "blocked"})
    with pytest.raises(
        ExtensionLabelError, match=re.escape("'acme.status' or 'acme.status.team'")
    ):
        policy.check({f"ext.{_ID}.team.other": "x"})


def test_drop_cleared_removes_only_declared_empty_values() -> None:
    labels = {_KEY: "", "team": "", "ext.other.note": ""}

    ExtensionLabelPolicy([_manifest()]).drop_cleared(labels)

    assert labels == {"team": "", "ext.other.note": ""}
