"""Manifest validation for extension session state and state commands."""

from __future__ import annotations

from dataclasses import replace

import pytest

from omnigent.extensions import (
    EXTENSION_API_VERSION,
    ClearState,
    CommandAccess,
    CommandArgument,
    CommandContribution,
    ExtensionManifest,
    SetState,
    StateContribution,
    StateField,
    StateVisibility,
    validate_manifest,
)
from omnigent.extensions.registry import ExtensionValidationError

_STATUS = StateField("status", StateVisibility.PUBLISHED, max_length=32)


def _manifest(
    *,
    fields: tuple[StateField, ...] = (_STATUS,),
    commands: tuple[CommandContribution, ...] = (),
    extension_id: str = "acme.status",
) -> ExtensionManifest:
    return ExtensionManifest(
        id=extension_id,
        display_name="Acme Status",
        distribution="omnigent-acme-status",
        version="1.0.0",
        requires_omnigent=">=0",
        extension_api=EXTENSION_API_VERSION,
        state=StateContribution(fields=fields),
        commands=commands,
    )


def _set_status(**changes: object) -> CommandContribution:
    command = CommandContribution(
        id="acme.status.set",
        title="Set status",
        action=SetState(key="status", value="{status}"),
        arguments=(CommandArgument("status", choices=("blocked", "done")),),
    )
    return replace(command, **changes)


def test_accepts_state_fields_and_bound_commands() -> None:
    manifest = _manifest(
        fields=(
            _STATUS,
            StateField("goal:*", StateVisibility.READERS),
            StateField("secret", StateVisibility.SERVICE),
        ),
        commands=(
            _set_status(),
            CommandContribution(
                id="acme.status.watch",
                title="Watch PR",
                action=SetState(key="goal:{pr}", value="on"),
                arguments=(CommandArgument("pr", pattern=r"[0-9]{1,9}"),),
                required_access=CommandAccess.READ,
                confirm="Watch this pull request?",
            ),
            CommandContribution(
                id="acme.status.clear", title="Clear", action=ClearState("status")
            ),
            CommandContribution(id="acme.status.reserved", title="Reserved"),
        ),
    )

    validate_manifest(manifest)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ((StateField("status", StateVisibility.PUBLISHED),), "max_length"),
        ((StateField("status", StateVisibility.PUBLISHED, max_length=257),), "max_length"),
        ((StateField("Status", StateVisibility.PUBLISHED, max_length=8),), "exact lowercase"),
        ((StateField("goal:*", StateVisibility.PUBLISHED, max_length=8),), "exact lowercase"),
        ((StateField("status ", StateVisibility.READERS),), "state key"),
        ((StateField("", StateVisibility.READERS),), "state key"),
        ((StateField("x" * 129, StateVisibility.READERS),), "state key"),
        ((StateField("goal", StateVisibility.READERS, max_length=4),), "only to published"),
        ((StateField("goal", "public"),), "unsupported visibility"),  # type: ignore[arg-type]
        ((_STATUS, _STATUS), "duplicate state field keys"),
        (
            tuple(
                StateField(f"f{index}", StateVisibility.PUBLISHED, max_length=8)
                for index in range(4)
            ),
            "more than 3 published fields",
        ),
    ],
)
def test_rejects_invalid_state_fields(fields: tuple[StateField, ...], message: str) -> None:
    with pytest.raises(ExtensionValidationError, match=message):
        validate_manifest(_manifest(fields=fields))


def test_rejects_published_field_whose_label_exceeds_the_key_column() -> None:
    long_id = "acme." + "a" * 110
    fields = (StateField("status-field", StateVisibility.PUBLISHED, max_length=8),)

    with pytest.raises(ExtensionValidationError, match="longer than 128"):
        validate_manifest(_manifest(fields=fields, extension_id=long_id))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"arguments": (CommandArgument("status"),)}, "needs choices or a pattern"),
        ({"arguments": (CommandArgument("status", pattern="("),)}, "pattern is invalid"),
        (
            {"arguments": (CommandArgument("Status", choices=("done",)),)},
            "lowercase name",
        ),
        (
            {"arguments": (CommandArgument("status", choices=("x" * 65,)),)},
            "exceeds max_length",
        ),
        (
            {"arguments": (CommandArgument("status", choices=("a",), max_length=0),)},
            "max_length",
        ),
        ({"action": SetState(key="status", value="{other}")}, "undeclared arguments"),
        ({"action": SetState(key="status", value="done")}, "unused arguments"),
        ({"action": SetState(key="status", value="{status!r}")}, "plain {argument}"),
        ({"action": SetState(key="st atus", value="{status}")}, "valid state key template"),
        ({"action": SetState(key="{status", value="x")}, "not a valid template"),
        ({"action": "status"}, "SetState, ClearState or None"),
        ({"required_access": "edit"}, "CommandAccess"),
        ({"confirm": ""}, "confirm"),
        ({"action": None}, "arguments but no action"),
        (
            {
                "arguments": (
                    CommandArgument("status", choices=("done",)),
                    CommandArgument("status", choices=("done",)),
                )
            },
            "duplicate",
        ),
    ],
)
def test_rejects_invalid_commands(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ExtensionValidationError, match=message):
        validate_manifest(_manifest(commands=(_set_status(**changes),)))


def test_rejects_literal_value_longer_than_its_published_field() -> None:
    command = CommandContribution(
        id="acme.status.long",
        title="Long",
        action=SetState(key="status", value="x" * 33),
    )

    with pytest.raises(ExtensionValidationError, match="exceeds published field"):
        validate_manifest(_manifest(commands=(command,)))


@pytest.mark.parametrize(
    ("action", "writes_service_state", "message"),
    [
        # No literal prefix: an argument could reach any declared field.
        (SetState(key="{status}", value="x"), False, "must start with a declared"),
        (SetState(key="other", value="{status}"), False, "must start with a declared"),
        (SetState(key="secret", value="{status}"), False, "writes_service_state"),
        (SetState(key="status", value="{status}"), True, "writes_service_state"),
    ],
)
def test_command_keys_pin_to_one_declared_field(
    action: SetState, writes_service_state: bool, message: str
) -> None:
    fields = (_STATUS, StateField("secret", StateVisibility.SERVICE))
    command = _set_status(action=action, writes_service_state=writes_service_state)

    with pytest.raises(ExtensionValidationError, match=message):
        validate_manifest(_manifest(fields=fields, commands=(command,)))


def test_service_field_command_needs_the_explicit_flag() -> None:
    fields = (_STATUS, StateField("secret", StateVisibility.SERVICE))
    command = _set_status(
        action=SetState(key="secret", value="{status}"), writes_service_state=True
    )

    validate_manifest(_manifest(fields=fields, commands=(command,)))


@pytest.mark.parametrize(
    "field_decl",
    [
        StateField("goal", StateVisibility.READERS, max_keys=4),
        StateField("goal:*", StateVisibility.READERS, max_keys=0),
        StateField("goal:*", StateVisibility.READERS, max_keys=49),
        StateField("status", StateVisibility.PUBLISHED, max_length=8, max_keys=1),
    ],
)
def test_max_keys_only_caps_prefix_fields(field_decl: StateField) -> None:
    with pytest.raises(ExtensionValidationError, match="max_keys"):
        validate_manifest(_manifest(fields=(field_decl,)))
