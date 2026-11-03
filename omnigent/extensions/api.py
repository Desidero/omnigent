"""Public manifest types for installed Omnigent extensions.

The extension API is versioned independently from the Omnigent package. Entry
points should return these lightweight, declarative values without importing
extension runtime implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

EXTENSION_API_VERSION = 1


class ExtensionPermission(StrEnum):
    """Host capabilities an extension may request."""

    NAVIGATION = "navigation"
    PROJECTS_READ = "projects.read"
    PROJECTS_WRITE = "projects.write"
    SESSIONS_READ = "sessions.read"
    STORAGE_USER = "storage.user"


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


class StateVisibility(StrEnum):
    """Who can read a session state key besides the extension's server code."""

    SERVICE = "service"
    EDITORS = "editors"
    READERS = "readers"
    PUBLISHED = "published"


class CommandAccess(StrEnum):
    """The share level a caller needs on the session to run a command."""

    READ = "read"
    EDIT = "edit"


@dataclass(frozen=True)
class StateField:
    """Declares who can read one session state key, or a family of keys.

    ``key`` is an exact key, or a key prefix when it ends with ``*``. Keys that
    no field declares are ``service``: readable only by server code.
    ``published`` fields must be exact keys holding UTF-8 text of at most
    ``max_length`` characters; core mirrors them as read-only
    ``ext.<extension id>.<key>`` session labels. ``max_keys`` caps how many
    keys of a prefix family commands may create on one session (16 when
    unset); the extension's own server code is not limited by it.
    """

    key: str
    visibility: StateVisibility = StateVisibility.SERVICE
    max_length: int | None = None
    max_keys: int | None = None


@dataclass(frozen=True)
class StateContribution:
    """The session state keys an extension declares."""

    fields: tuple[StateField, ...] = ()


@dataclass(frozen=True)
class CommandArgument:
    """One caller-supplied command argument, bound into the command's templates.

    An argument needs ``choices`` or a full-match ``pattern``; values longer
    than ``max_length`` characters are rejected.
    """

    name: str
    choices: tuple[str, ...] = ()
    pattern: str | None = None
    max_length: int = 64


@dataclass(frozen=True)
class SetState:
    """Write ``value`` to ``key``; both may contain ``{argument}`` placeholders."""

    key: str
    value: str


@dataclass(frozen=True)
class ClearState:
    """Delete ``key``, which may contain ``{argument}`` placeholders."""

    key: str


@dataclass(frozen=True)
class CommandContribution:
    """A command users invoke on a session.

    A command without an ``action`` is reserved metadata. ``SetState`` and
    ``ClearState`` run on the server as the extension, for callers with at
    least ``required_access`` on the session. Their key template must start
    with one declared field: an exact key, or a ``prefix*`` whose prefix is
    literal text before any placeholder. Writing a ``service`` field needs
    ``writes_service_state``. ``confirm`` is a prompt for clients to show
    first; the server does not enforce it.
    """

    id: str
    title: str
    action: SetState | ClearState | None = None
    arguments: tuple[CommandArgument, ...] = ()
    required_access: CommandAccess = CommandAccess.EDIT
    confirm: str | None = None
    writes_service_state: bool = False


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
    commands: tuple[CommandContribution, ...] = ()
    state: StateContribution | None = None


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
