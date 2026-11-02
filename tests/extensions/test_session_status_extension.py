"""The session status example is a valid, manifest-only package."""

from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from omnigent.extensions import (
    ClearState,
    ExtensionManifest,
    ExtensionValidationError,
    FieldValue,
    SetState,
    SlotId,
    SlotItemKind,
    StateVisibility,
    check_extension_package,
)
from omnigent.extensions.registry import APPROVED_ICONS

_REPO_ROOT = Path(__file__).parents[2]
_EXAMPLE_ROOT = _REPO_ROOT / "examples" / "extensions" / "session-status"
_PACKAGE_ROOT = _EXAMPLE_ROOT / "src" / "omnigent_session_status_extension"
_SET = "omnigent.session-status.set"
_CLEAR = "omnigent.session-status.clear"


def _load_plugin() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "omnigent_session_status_extension.plugin", _PACKAGE_ROOT / "plugin.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest() -> ExtensionManifest:
    return _load_plugin().get_manifest()


def test_package_passes_conformance_with_no_bundle() -> None:
    manifest = _manifest()
    assert (
        check_extension_package(manifest, package_root=_PACKAGE_ROOT, project_root=_EXAMPLE_ROOT)
        is None
    )
    assert manifest.entrypoints.browser is None
    assert manifest.pages == ()
    # Core runs the commands; the extension asks for no host permissions.
    assert manifest.permissions == frozenset()


def test_publishes_five_statuses_each_with_its_own_approved_icon() -> None:
    assert _manifest().state is not None
    (field,) = _manifest().state.fields
    assert (field.key, field.visibility) == ("status", StateVisibility.PUBLISHED)
    assert [value.label for value in field.values] == [
        "In progress",
        "Blocked",
        "Needs review",
        "Parked",
        "Done",
    ]
    icons = [value.icon for value in field.values]
    assert len(set(icons)) == len(icons)
    assert set(icons) <= APPROVED_ICONS


def test_commands_set_a_listed_status_and_clear_it_for_editors() -> None:
    commands = {command.id: command for command in _manifest().commands}
    assert set(commands) == {_SET, _CLEAR}
    set_status = commands[_SET]
    assert set_status.action == SetState(key="status", value="{status}")
    (argument,) = set_status.arguments
    assert argument.choices == ("in-progress", "blocked", "needs-review", "parked", "done")
    assert commands[_CLEAR].action == ClearState(key="status")
    # Edit access is the default; read-only sharees see the status only.
    assert {command.required_access.value for command in commands.values()} == {"edit"}


def test_badge_menu_and_tooltip_row_use_the_status_field_and_commands() -> None:
    items = {(item.slot, item.kind): item for item in _manifest().slot_items}
    assert set(items) == {
        (SlotId.SESSION_ROW_DECORATIONS, SlotItemKind.DECORATION),
        (SlotId.SESSION_ROW_MENU, SlotItemKind.COMMAND),
        (SlotId.SESSION_ROW_HOVER, SlotItemKind.ROW),
    }
    assert {item.binding.key for item in items.values() if item.binding} == {"status"}
    assert all(item.page is None for item in items.values())
    menu = items[(SlotId.SESSION_ROW_MENU, SlotItemKind.COMMAND)]
    assert (menu.command, menu.clear_command) == (_SET, _CLEAR)


def test_validator_rejects_a_copy_with_an_unapproved_icon() -> None:
    manifest = _manifest()
    assert manifest.state is not None
    (field,) = manifest.state.fields
    bad = dataclasses.replace(
        field, values=(*field.values[:-1], FieldValue("done", "Done", "rocket"))
    )
    with pytest.raises(ExtensionValidationError, match="unknown icon 'rocket'"):
        check_extension_package(
            dataclasses.replace(manifest, state=dataclasses.replace(manifest.state, fields=(bad,)))
        )


def test_validator_rejects_a_status_choice_the_field_does_not_list() -> None:
    manifest = _manifest()
    assert manifest.state is not None
    (field,) = manifest.state.fields
    fewer = dataclasses.replace(field, values=field.values[:-1])
    with pytest.raises(ExtensionValidationError, match="must write one of field 'status'"):
        check_extension_package(
            dataclasses.replace(
                manifest, state=dataclasses.replace(manifest.state, fields=(fewer,))
            )
        )
