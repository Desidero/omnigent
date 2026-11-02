"""Operator enablement for extension UI slot items.

The server config's ``extensions`` section maps extension ids to settings::

    extensions:
      omnigent.hello-page:
        enabled: true

``enabled: true`` turns everything on, including UI slot items.
``enabled: false`` turns the extension fully off: pages, navigation, browser
bundle and slot items. An extension that is not listed (the section absent,
null or empty) keeps its V1 pages, navigation and bundle but adds no slot items.
Malformed or invalid entries count as not listed. ``enabled`` is the only
supported setting.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from omnigent.extensions.api import ExtensionPluginState

EXTENSIONS_CONFIG_KEY = "extensions"
_SUPPORTED_SETTINGS = frozenset({"enabled"})


class ExtensionConfigError(ValueError):
    """The ``extensions`` section uses a setting this server does not support."""


@dataclass(frozen=True)
class ExtensionEnablement:
    """Which installed extensions the operator has enabled for UI slots."""

    enabled: frozenset[str] = frozenset()
    disabled: frozenset[str] = frozenset()
    errors: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def allows_catalog(self, extension_id: str) -> bool:
        """Whether the extension's pages, navigation and bundle are served."""
        return extension_id not in self.disabled

    def allows_slots(self, extension_id: str) -> bool:
        """Whether the extension's UI slot items are served."""
        return extension_id in self.enabled

    def describe(self, extension_id: str) -> str:
        """Return a short operator-facing status for one installed extension."""
        if self.allows_slots(extension_id):
            return "enabled"
        if not self.allows_catalog(extension_id):
            return "disabled"
        return "installed, not enabled (pages and navigation only)"


def _entry_error(extension_id: str, settings: object) -> str | None:
    if not isinstance(settings, Mapping):
        return "settings must be a mapping such as {enabled: true}"
    unsupported = sorted(str(key) for key in settings if key not in _SUPPORTED_SETTINGS)
    if unsupported:
        raise ExtensionConfigError(
            f"extensions.{extension_id}: unsupported setting(s) {', '.join(unsupported)}; "
            "this server accepts only 'enabled'"
        )
    if not isinstance(settings.get("enabled", False), bool):
        return "enabled must be true or false"
    return None


def parse_extension_enablement(config: Mapping[str, object]) -> ExtensionEnablement:
    """Parse a server config's ``extensions`` section, failing closed.

    :param config: The whole server config.
    :returns: The enablement. Invalid entries stay disabled and are reported in
        ``errors``; a section that is not a mapping enables nothing.
    :raises ExtensionConfigError: An entry uses a setting other than ``enabled``.
    """
    raw = config.get(EXTENSIONS_CONFIG_KEY)
    if raw is None:
        return ExtensionEnablement()
    if not isinstance(raw, Mapping):
        return ExtensionEnablement(
            errors=MappingProxyType(
                {EXTENSIONS_CONFIG_KEY: "must be a mapping keyed by extension id"}
            ),
        )
    enabled: set[str] = set()
    disabled: set[str] = set()
    errors: dict[str, str] = {}
    for extension_id, settings in raw.items():
        if not isinstance(extension_id, str):
            errors[str(extension_id)] = "extension ids must be strings"
            continue
        error = _entry_error(extension_id, settings)
        if error is not None:
            errors[extension_id] = error
        elif settings.get("enabled") is True:
            enabled.add(extension_id)
        elif settings.get("enabled") is False:
            disabled.add(extension_id)
    return ExtensionEnablement(
        enabled=frozenset(enabled),
        disabled=frozenset(disabled),
        errors=MappingProxyType(errors),
    )


def apply_extension_enablement(
    state: ExtensionPluginState,
    enablement: ExtensionEnablement,
) -> ExtensionPluginState:
    """Drop extensions the operator turned off, so nothing of theirs is served."""
    return dataclasses.replace(
        state,
        manifests=tuple(
            manifest for manifest in state.manifests if enablement.allows_catalog(manifest.id)
        ),
    )
