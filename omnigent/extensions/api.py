"""Public manifest types for installed Omnigent extensions.

The extension API is versioned independently from the Omnigent package. Entry
points should return these lightweight, declarative values without importing
extension runtime implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

EXTENSION_API_VERSION = 1


class SlotId(StrEnum):
    """Stable semantic UI locations open to declarative contributions."""

    CHAT_HEADER_ACTIONS = "chat.header.actions"
    COMPOSER_ACTIONS = "composer.actions"
    SESSION_RIGHT_RAIL_TABS = "session.rightRail.tabs"
    SETTINGS_SECTIONS = "settings.sections"
    SESSION_ROW_DECORATIONS = "session.row.decorations"
    SESSION_ROW_MENU = "session.row.menu"


class SlotItemKind(StrEnum):
    """Core-rendered presentation for one slot contribution."""

    ACTION = "action"
    TAB = "tab"
    SECTION = "section"
    DECORATION = "decoration"
    SET_LABEL = "set-label"


class ExtensionPermission(StrEnum):
    """Host capabilities an extension may request."""

    NAVIGATION = "navigation"
    PROJECTS_READ = "projects.read"
    PROJECTS_WRITE = "projects.write"
    SESSIONS_READ = "sessions.read"
    SESSIONS_LABELS_WRITE = "sessions.labels.write"
    STORAGE_USER = "storage.user"


class LabelTone(StrEnum):
    """Named colour tone core maps to its own status theme tokens."""

    NEUTRAL = "neutral"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"


@dataclass(frozen=True)
class ExtensionEntrypoints:
    """Lazy runtime assets declared by an extension."""

    browser: str | None = None
    browser_css: str | None = None


@dataclass(frozen=True)
class PageContribution:
    """A page rendered below the extension's namespaced route."""

    id: str
    title: str
    route: str
    view: str


@dataclass(frozen=True)
class PrimaryNavigationContribution:
    """A link contributed to the application's primary sidebar navigation."""

    id: str
    label: str
    page: str
    icon: str | None = None
    order: int = 500
    when: str | None = None


@dataclass(frozen=True)
class LabelValue:
    """One allowed value of a declared session label, with its presentation."""

    value: str
    label: str
    icon: str
    tone: LabelTone = LabelTone.NEUTRAL


@dataclass(frozen=True)
class LabelDeclaration:
    """An ordinary session label whose key and values an extension declares.

    The key is ``ext.<extension id>.<name>``. Anyone who may edit the session
    may change it; the server only accepts the declared values.
    """

    key: str
    title: str
    values: tuple[LabelValue, ...]


@dataclass(frozen=True)
class LabelBinding:
    """Binds a session-row slot item to a declared label of the same extension."""

    key: str
    source: Literal["label"] = "label"


@dataclass(frozen=True)
class SlotItemContribution:
    """A core-rendered slot item: a link to an extension page, or a bound label.

    Page-backed kinds (action, tab, section) set ``page``; session-row kinds
    (decoration, set-label, row) set ``binding`` instead.
    """

    id: str
    slot: SlotId
    kind: SlotItemKind
    label: str
    page: str | None = None
    icon: str | None = None
    order: int = 500
    when: str | None = None
    binding: LabelBinding | None = None
    #: A set-label item's clear entry, e.g. ``"Clear status"``; core shows "Clear" without it.
    clear_label: str | None = None


@dataclass(frozen=True)
class CommandContribution:
    """Reserved command metadata; V1 does not execute contributed commands."""

    id: str
    title: str


@dataclass(frozen=True)
class ExtensionManifest:
    """One installed package's declarative extension contribution."""

    id: str
    display_name: str
    distribution: str
    version: str
    requires_omnigent: str
    extension_api: int
    entrypoints: ExtensionEntrypoints = field(default_factory=ExtensionEntrypoints)
    permissions: frozenset[ExtensionPermission] = frozenset()
    activation_events: tuple[str, ...] = ()
    pages: tuple[PageContribution, ...] = ()
    primary_navigation: tuple[PrimaryNavigationContribution, ...] = ()
    slot_items: tuple[SlotItemContribution, ...] = ()
    labels: tuple[LabelDeclaration, ...] = ()
    commands: tuple[CommandContribution, ...] = ()


@dataclass(frozen=True)
class ExtensionPluginState:
    """Validated manifests plus non-fatal discovery errors."""

    manifests: tuple[ExtensionManifest, ...]
    load_errors: dict[str, str] = field(default_factory=dict)
    asset_packages: dict[str, str] = field(default_factory=dict)

    def get(self, extension_id: str) -> ExtensionManifest | None:
        """Return one accepted manifest by ID."""
        return next((item for item in self.manifests if item.id == extension_id), None)

    def asset_package(self, extension_id: str) -> str | None:
        """Return the verified package holding an extension's browser assets."""
        return self.asset_packages.get(extension_id)
