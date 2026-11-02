from __future__ import annotations

import pytest

from omnigent.extensions.enablement import (
    ExtensionConfigError,
    ExtensionEnablement,
    parse_extension_enablement,
)


@pytest.mark.parametrize(
    "config",
    [{"port": 8000}, {"extensions": None}, {"extensions": {}}],
    ids=["absent", "null", "empty"],
)
def test_no_entries_enable_no_slots(config: dict[str, object]) -> None:
    enablement = parse_extension_enablement(config)

    assert enablement == ExtensionEnablement()
    assert not enablement.allows_slots("acme.review")
    assert enablement.describe("acme.review") == (
        "installed, not enabled (pages and navigation only)"
    )


def test_enabled_true_adds_slots_and_enabled_false_turns_off() -> None:
    enablement = parse_extension_enablement(
        {
            "extensions": {
                "acme.review": {"enabled": True},
                "acme.other": {"enabled": False},
                "acme.bare": {},
            }
        }
    )

    assert enablement.enabled == frozenset({"acme.review"})
    assert enablement.disabled == frozenset({"acme.other"})
    assert enablement.errors == {}
    assert enablement.describe("acme.review") == "enabled"
    assert enablement.describe("acme.other") == "disabled"
    assert not enablement.allows_catalog("acme.other")
    assert enablement.allows_catalog("acme.bare")
    assert not enablement.allows_slots("acme.bare")


@pytest.mark.parametrize(
    ("section", "key", "error"),
    [
        (["acme.review"], "extensions", "mapping keyed by extension id"),
        ({"acme.review": True}, "acme.review", "settings must be a mapping"),
        ({"acme.review": {"enabled": "yes"}}, "acme.review", "enabled must be true or false"),
    ],
)
def test_invalid_sections_fail_closed(section: object, key: str, error: str) -> None:
    enablement = parse_extension_enablement({"extensions": section})

    assert enablement.enabled == enablement.disabled == frozenset()
    assert error in enablement.errors[key]


@pytest.mark.parametrize("setting", ["version", "permissions", "config", "required"])
def test_unsupported_settings_fail_loudly(setting: str) -> None:
    with pytest.raises(ExtensionConfigError, match=rf"extensions\.acme\.review: .*{setting}"):
        parse_extension_enablement({"extensions": {"acme.review": {"enabled": True, setting: 1}}})
