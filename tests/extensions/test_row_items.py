"""Manifest validation for session-row items bound to published fields and commands."""

from __future__ import annotations

from dataclasses import replace

import pytest

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
    validate_manifest,
)
from omnigent.extensions.registry import ExtensionValidationError

_ID = "acme.status"
_STATUS = StateField(
    "status",
    StateVisibility.PUBLISHED,
    max_length=16,
    values=(
        FieldValue("blocked", "Blocked", "octagon-alert", FieldTone.DANGER),
        FieldValue("done", "Done", "circle-check", FieldTone.SUCCESS),
    ),
)
_COUNT = StateField("count", StateVisibility.PUBLISHED, max_length=8)
_SET = CommandContribution(
    id=f"{_ID}.set",
    title="Set status",
    action=SetState(key="status", value="{status}"),
    arguments=(CommandArgument("status", choices=("blocked", "done")),),
)
_CLEAR = CommandContribution(id=f"{_ID}.clear", title="Clear status", action=ClearState("status"))
_WATCH = CommandContribution(
    id=f"{_ID}.watch",
    title="Watch",
    action=SetState(key="count", value="{n}"),
    arguments=(CommandArgument("n", pattern="[0-9]{1,3}"),),
)


def _item(slot: SlotId, kind: SlotItemKind, **changes: object) -> SlotItemContribution:
    return replace(
        SlotItemContribution(id=f"{_ID}.{kind.value}", slot=slot, kind=kind, label="Status"),
        **changes,
    )


_BADGE = _item(
    SlotId.SESSION_ROW_DECORATIONS, SlotItemKind.DECORATION, binding=FieldBinding("status")
)
_MENU = _item(
    SlotId.SESSION_ROW_MENU,
    SlotItemKind.COMMAND,
    command=_SET.id,
    clear_command=_CLEAR.id,
    icon="eye",
)
_HOVER = _item(SlotId.SESSION_ROW_HOVER, SlotItemKind.ROW, binding=FieldBinding("count"))


def _manifest(**changes: object) -> ExtensionManifest:
    """A manifest-only extension: state, commands and row items, no pages or bundle."""
    manifest = ExtensionManifest(
        id=_ID,
        display_name="Status",
        distribution="acme-status",
        version="1.0.0",
        requires_omnigent=">=0.1",
        extension_api=EXTENSION_API_VERSION,
        state=StateContribution(fields=(_STATUS, _COUNT)),
        commands=(_SET, _CLEAR, _WATCH),
        slot_items=(_BADGE, _MENU, _HOVER),
    )
    return replace(manifest, **changes)


def test_accepts_a_manifest_only_extension_with_row_items() -> None:
    validate_manifest(_manifest())
    # A plain menu entry runs a command that takes no arguments.
    validate_manifest(
        _manifest(slot_items=(replace(_MENU, command=_CLEAR.id, clear_command=None),))
    )


def _fields(*fields: StateField) -> dict[str, object]:
    return {"state": StateContribution(fields=fields)}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            _fields(replace(_STATUS, values=(FieldValue("Done!", "Done", "eye"),)), _COUNT),
            "lowercase slug",
        ),
        (
            _fields(
                replace(_STATUS, values=(FieldValue("much-too-long-value", "Long", "eye"),)),
                _COUNT,
            ),
            "within max_length",
        ),
        (
            _fields(replace(_STATUS, values=(FieldValue("done", "Done", "constructor"),)), _COUNT),
            "unknown icon 'constructor'",
        ),
        (
            _fields(
                replace(_STATUS, values=(FieldValue("done", "Done", "eye", "red"),)),  # type: ignore[arg-type]
                _COUNT,
            ),
            "unsupported tone",
        ),
        (_fields(replace(_STATUS, values=_STATUS.values * 2), _COUNT), "duplicate field"),
        (
            _fields(_STATUS, _COUNT, StateField("note", values=_STATUS.values)),
            "values apply only to published fields",
        ),
        ({"slot_items": (replace(_BADGE, binding=FieldBinding("count")),)}, "declares no values"),
        (
            {"slot_items": (replace(_BADGE, binding=FieldBinding("note")),)},
            "not a published field",
        ),
        ({"slot_items": (replace(_BADGE, binding=None),)}, "must bind a published field"),
        ({"slot_items": (replace(_BADGE, page="x.y"),)}, "cannot reference a page"),
        ({"slot_items": (replace(_BADGE, command=_SET.id),)}, "cannot name a command"),
        ({"slot_items": (replace(_MENU, command=f"{_ID}.missing"),)}, "must name a command"),
        ({"slot_items": (replace(_MENU, binding=FieldBinding("status")),)}, "cannot bind a field"),
        ({"slot_items": (replace(_MENU, command=_WATCH.id, clear_command=None),)}, "one argument"),
        ({"slot_items": (replace(_MENU, clear_command=_SET.id),)}, "clear_command must name"),
        (
            {"slot_items": (replace(_MENU, command=_CLEAR.id, clear_command=_CLEAR.id),)},
            "lists no choices",
        ),
        ({"slot_items": (replace(_MENU, icon="nope"),)}, "unknown icon 'nope'"),
        (
            {"slot_items": (_BADGE, replace(_BADGE, id=f"{_ID}.badge-2"))},
            "the limit is 1",
        ),
        (
            {"slot_items": (replace(_MENU, kind=SlotItemKind.DECORATION),)},
            "kind must be 'command'",
        ),
    ],
)
def test_rejects_invalid_field_values_and_row_items(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ExtensionValidationError, match=message):
        validate_manifest(_manifest(**changes))


@pytest.mark.parametrize(
    "command",
    [
        replace(_SET, action=SetState(key="status", value="parked"), arguments=()),
        replace(
            _SET,
            arguments=(CommandArgument("status", choices=("blocked", "parked")),),
        ),
        replace(
            _SET,
            action=SetState(key="status", value="x{status}"),
            arguments=(CommandArgument("status", choices=("blocked",)),),
        ),
    ],
    ids=["literal", "choices", "template"],
)
def test_commands_write_only_listed_values(command: CommandContribution) -> None:
    with pytest.raises(ExtensionValidationError, match="must write one of field 'status'"):
        validate_manifest(_manifest(commands=(command, _CLEAR, _WATCH), slot_items=()))


def test_page_backed_items_cannot_bind_a_field_or_name_a_command() -> None:
    action = SlotItemContribution(
        id=f"{_ID}.action",
        slot=SlotId.CHAT_HEADER_ACTIONS,
        kind=SlotItemKind.ACTION,
        label="Status",
        page=f"{_ID}.page",
    )
    for changes, message in (
        ({"binding": FieldBinding("status")}, "cannot bind a field"),
        ({"command": _SET.id}, "cannot name a command"),
    ):
        with pytest.raises(ExtensionValidationError, match=message):
            validate_manifest(_manifest(slot_items=(replace(action, **changes),)))
