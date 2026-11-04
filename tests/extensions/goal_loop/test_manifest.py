"""The goal loop is a valid package: manifest, bundle and server entrypoint."""

from __future__ import annotations

import inspect
from pathlib import Path

from desidero_goal_loop import server
from desidero_goal_loop.loop import MET, PAUSED, STOPPED, UNMET, WATCHING
from desidero_goal_loop.plugin import EXTENSION_ID, get_manifest

from omnigent.extensions import CommandAccess, SlotId, StateVisibility, check_extension_package

_PROJECT = Path(__file__).parents[3] / "ext-demo" / "extensions" / "goal-loop"


def test_package_passes_the_extension_checks() -> None:
    check_extension_package(
        get_manifest(),
        project_root=_PROJECT,
        package_root=_PROJECT / "src" / "desidero_goal_loop",
    )


def test_publishes_three_fields_and_binds_the_row_and_composer_to_them() -> None:
    manifest = get_manifest()
    assert manifest.state is not None
    published = [f.key for f in manifest.state.fields if f.visibility is StateVisibility.PUBLISHED]
    assert published == ["goal", "count", "summary"]
    slots = {item.slot: item for item in manifest.slot_items}
    assert slots[SlotId.COMPOSER_ACTIONS].label_field == "summary"
    assert slots[SlotId.SESSION_ROW_DECORATIONS].binding.key == "goal"
    assert slots[SlotId.SESSION_ROW_MENU].command == f"{EXTENSION_ID}.stop"


def test_the_badge_declares_every_goal_status_the_loop_publishes() -> None:
    manifest = get_manifest()
    assert manifest.state is not None
    [goal] = [f for f in manifest.state.fields if f.key == "goal"]
    assert {value.value for value in goal.values} == {WATCHING, UNMET, MET, STOPPED, PAUSED}


def test_server_entrypoint_is_an_async_activate() -> None:
    assert manifest_entrypoint() == "desidero_goal_loop.server:activate"
    assert inspect.iscoroutinefunction(server.activate)


def manifest_entrypoint() -> str | None:
    return get_manifest().entrypoints.server


def test_only_editors_change_goals_and_readers_see_the_view() -> None:
    manifest = get_manifest()
    assert {command.required_access for command in manifest.commands} == {CommandAccess.EDIT}
    assert manifest.state is not None
    visibility = {field.key: field.visibility for field in manifest.state.fields}
    assert visibility["goals"] is StateVisibility.READERS
    assert {visibility[key] for key in ("all", "pr:*", "stop", "resume", "refresh")} == {
        StateVisibility.EDITORS
    }
    # Service keys stay undeclared, so only server code reads them.
    assert not {"enablers", "loop", "g:*"} & set(visibility)
