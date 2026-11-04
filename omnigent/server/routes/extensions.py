"""Read-only catalog and diagnostics for installed extensions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Literal, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.extensions import (
    CommandAccess,
    CommandContribution,
    ExtensionManifest,
    ExtensionPluginState,
    FieldTone,
    SetState,
    SlotId,
    SlotItemKind,
    StateContribution,
    StateVisibility,
)
from omnigent.extensions.assets import ASSET_SCRIPT, ASSET_STYLES, ResolvedBundle
from omnigent.extensions.enablement import ExtensionEnablement
from omnigent.extensions.state_fields import pinned_field
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.stores.permission_store import PermissionStore

if TYPE_CHECKING:
    from omnigent.server.extension_activation import ActivationRecord


class ExtensionPageResponse(BaseModel):
    """One namespaced page contribution."""

    id: str
    title: str
    route: str
    view: str


class ExtensionPrimaryNavigationResponse(BaseModel):
    """One primary-sidebar navigation contribution."""

    id: str
    label: str
    page: str
    icon: str | None
    order: int
    when: str | None


class ExtensionFieldBindingResponse(BaseModel):
    """The published state field a session-row slot item renders."""

    source: Literal["published_field"]
    key: str


class ExtensionSlotItemResponse(BaseModel):
    """One core-rendered item contributed to a semantic UI slot."""

    id: str
    slot: SlotId
    kind: SlotItemKind
    label: str
    page: str | None
    icon: str | None
    order: int
    when: str | None
    binding: ExtensionFieldBindingResponse | None
    command: str | None = Field(
        description="The command a session.row.menu item runs, or whose choices it lists."
    )
    clear_command: str | None = Field(
        description="A no-argument command listed after a menu item's choices."
    )
    label_field: str | None = Field(
        description=(
            "A published field whose value, when set, a header or composer action "
            "shows as its label."
        )
    )


class ExtensionFieldValueResponse(BaseModel):
    """One value of a published field, with its presentation."""

    value: str
    label: str
    icon: str
    tone: FieldTone


class ExtensionStateFieldResponse(BaseModel):
    """A declared state key, or key prefix ending in ``*``, and who may read it."""

    key: str
    visibility: StateVisibility
    max_length: int | None
    values: list[ExtensionFieldValueResponse]


class ExtensionCommandArgumentResponse(BaseModel):
    """One argument a command takes: one of ``choices``, or a full match of ``pattern``."""

    name: str
    choices: list[str]
    pattern: str | None
    max_length: int


class ExtensionCommandActionResponse(BaseModel):
    """What a command does to the extension's session state."""

    type: Literal["set_state", "clear_state"]
    field: str = Field(description="The declared state field the command writes.")
    value: str | None = Field(
        description="A set_state command's value template; `{name}` is an argument."
    )


class ExtensionDeclaredCommandResponse(BaseModel):
    """A command users can run on a session through its commands route."""

    id: str
    title: str
    arguments: list[ExtensionCommandArgumentResponse]
    required_access: CommandAccess
    confirm: str | None = Field(
        description="A prompt clients show before running it; the server does not enforce it."
    )
    action: ExtensionCommandActionResponse


class ExtensionBrowserBundleResponse(BaseModel):
    """Opaque browser-bundle availability and content-addressed asset URLs."""

    declared: bool
    has_styles: bool
    digest: str | None = None
    script_url: str | None = None
    style_url: str | None = None


class ExtensionResponse(BaseModel):
    """Public metadata for one accepted extension."""

    object: Literal["extension"] = "extension"
    id: str
    display_name: str
    distribution: str
    version: str
    extension_api: int
    status: Literal["enabled", "unavailable"]
    permissions: list[str]
    pages: list[ExtensionPageResponse]
    primary_navigation: list[ExtensionPrimaryNavigationResponse]
    slot_items: list[ExtensionSlotItemResponse]
    state_fields: list[ExtensionStateFieldResponse] = Field(
        description="Published state fields; empty unless the extension's state is enabled."
    )
    commands: list[ExtensionDeclaredCommandResponse] = Field(
        description="Commands with an action; empty unless the extension's state is enabled."
    )
    browser: ExtensionBrowserBundleResponse


class ExtensionListResponse(BaseModel):
    """Public catalog of accepted extensions."""

    object: Literal["list"] = "list"
    data: list[ExtensionResponse]


class ExtensionLoadErrorResponse(BaseModel):
    """Concise diagnostic for one rejected entry point."""

    entry_point: str
    status: Literal["rejected"] = "rejected"
    error: str


class ExtensionAssetErrorResponse(BaseModel):
    """Concise diagnostic for one unresolved browser bundle."""

    extension_id: str
    status: Literal["unresolved"] = "unresolved"
    error: str


ActivationStatus = Literal["active", "quarantined", "stopped"]


class ExtensionActivationResponse(BaseModel):
    """This server process's activation of one extension's server code (experimental)."""

    extension_id: str
    status: ActivationStatus
    error: str | None = None


class ExtensionDiagnosticsResponse(BaseModel):
    """Administrator view of accepted and rejected extensions."""

    object: Literal["extension_diagnostics"] = "extension_diagnostics"
    extensions: list[ExtensionResponse]
    load_errors: list[ExtensionLoadErrorResponse]
    asset_errors: list[ExtensionAssetErrorResponse]
    activations: list[ExtensionActivationResponse] = []


def _serialize_command(
    command: CommandContribution, state: StateContribution | None
) -> ExtensionDeclaredCommandResponse | None:
    action = command.action
    if action is None:
        return None
    target = pinned_field(state, action.key)
    if target is None:  # Validated manifests always pin a field.
        return None
    return ExtensionDeclaredCommandResponse(
        id=command.id,
        title=command.title,
        arguments=[
            ExtensionCommandArgumentResponse(
                name=argument.name,
                choices=list(argument.choices),
                pattern=argument.pattern,
                max_length=argument.max_length,
            )
            for argument in command.arguments
        ],
        required_access=command.required_access,
        confirm=command.confirm,
        action=ExtensionCommandActionResponse(
            type="set_state" if isinstance(action, SetState) else "clear_state",
            field=target.key,
            value=action.value if isinstance(action, SetState) else None,
        ),
    )


def _serialize_state(
    manifest: ExtensionManifest,
) -> tuple[list[ExtensionStateFieldResponse], list[ExtensionDeclaredCommandResponse]]:
    fields = [
        ExtensionStateFieldResponse(
            key=field.key,
            visibility=field.visibility,
            max_length=field.max_length,
            values=[
                ExtensionFieldValueResponse(
                    value=value.value, label=value.label, icon=value.icon, tone=value.tone
                )
                for value in field.values
            ],
        )
        for field in (manifest.state.fields if manifest.state is not None else ())
        # Clients render only published fields; a page knows its own manifest.
        if field.visibility is StateVisibility.PUBLISHED
    ]
    commands = [
        serialized
        for command in manifest.commands
        if (serialized := _serialize_command(command, manifest.state)) is not None
    ]
    return fields, commands


def _serialize_manifest(
    manifest: ExtensionManifest,
    bundle: ResolvedBundle | None = None,
    *,
    slots_enabled: bool = False,
    state_enabled: bool = False,
) -> ExtensionResponse:
    """Convert a validated manifest into stable JSON-safe catalog metadata."""
    unavailable = manifest.entrypoints.browser is not None and bundle is None
    pages = (
        []
        if unavailable
        else [
            ExtensionPageResponse(id=page.id, title=page.title, route=page.route, view=page.view)
            for page in sorted(manifest.pages, key=lambda item: item.id)
        ]
    )
    navigation = (
        []
        if unavailable
        else [
            ExtensionPrimaryNavigationResponse(
                id=item.id,
                label=item.label,
                page=item.page,
                icon=item.icon,
                order=item.order,
                when=item.when,
            )
            for item in sorted(manifest.primary_navigation, key=lambda item: (item.order, item.id))
        ]
    )
    # Slot items need explicit operator enablement, even for installed extensions.
    slot_items = (
        []
        if unavailable or not slots_enabled
        else [
            ExtensionSlotItemResponse(
                id=item.id,
                slot=item.slot.value,
                kind=item.kind.value,
                label=item.label,
                page=item.page,
                icon=item.icon,
                order=item.order,
                when=item.when,
                binding=(
                    ExtensionFieldBindingResponse(source=item.binding.source, key=item.binding.key)
                    if item.binding is not None
                    else None
                ),
                command=item.command,
                clear_command=item.clear_command,
                label_field=item.label_field,
            )
            for item in sorted(
                manifest.slot_items,
                key=lambda item: (item.slot.value, item.order, item.id),
            )
        ]
    )
    # The same switch as the state routes, so the catalog offers only what runs.
    state_fields, commands = _serialize_state(manifest) if state_enabled else ([], [])
    return ExtensionResponse(
        id=manifest.id,
        display_name=manifest.display_name,
        distribution=manifest.distribution,
        version=manifest.version,
        extension_api=manifest.extension_api,
        status="unavailable" if unavailable else "enabled",
        permissions=sorted(permission.value for permission in manifest.permissions),
        pages=pages,
        primary_navigation=navigation,
        slot_items=slot_items,
        state_fields=state_fields,
        commands=commands,
        browser=ExtensionBrowserBundleResponse(
            declared=manifest.entrypoints.browser is not None,
            has_styles=manifest.entrypoints.browser_css is not None,
            digest=bundle.digest if bundle is not None else None,
            script_url=bundle.url(ASSET_SCRIPT) if bundle is not None else None,
            style_url=(
                bundle.url(ASSET_STYLES)
                if bundle is not None and ASSET_STYLES in bundle.assets
                else None
            ),
        ),
    )


async def _require_admin(
    request: Request,
    auth_provider: AuthProvider | None,
    permission_store: PermissionStore | None,
) -> None:
    """Require an administrator in multi-user mode."""
    user_id = require_user(request, auth_provider)
    if permission_store is None:
        return
    if user_id is None:
        raise OmnigentError("Authentication required", code=ErrorCode.UNAUTHORIZED)
    is_admin = await asyncio.to_thread(permission_store.is_admin, user_id)
    if not is_admin:
        raise OmnigentError(
            "Admin privileges required to inspect extension diagnostics",
            code=ErrorCode.FORBIDDEN,
        )


def _diagnostic_message(error: str) -> str:
    """Bound and flatten plugin errors before returning them through the API."""
    printable = "".join(character if character.isprintable() else " " for character in error)
    return " ".join(printable.split())[:512]


def create_extensions_router(
    state: ExtensionPluginState,
    *,
    bundles: Mapping[str, ResolvedBundle] | None = None,
    asset_errors: Mapping[str, str] | None = None,
    auth_provider: AuthProvider | None = None,
    permission_store: PermissionStore | None = None,
    enablement: ExtensionEnablement | None = None,
    state_enabled: Callable[[str], bool] | None = None,
    activations: Callable[[], Mapping[str, ActivationRecord]] | None = None,
) -> APIRouter:
    """Build the installed-extension catalog router, mounted under ``/v1``.

    :param state_enabled: The predicate that gates extension state and
        commands on the server; defaults to the slot enablement.
    :param activations: This process's server-code activations, read per request.
    """
    router = APIRouter()
    resolved_bundles = bundles or {}
    resolved_enablement = enablement or ExtensionEnablement()
    catalog = tuple(
        _serialize_manifest(
            manifest,
            resolved_bundles.get(manifest.id),
            slots_enabled=resolved_enablement.allows_slots(manifest.id),
            state_enabled=(state_enabled or resolved_enablement.allows_slots)(manifest.id),
        )
        for manifest in sorted(state.manifests, key=lambda item: item.id)
    )
    by_id = {item.id: item for item in catalog}
    diagnostics = tuple(
        ExtensionLoadErrorResponse(entry_point=entry_point, error=_diagnostic_message(error))
        for entry_point, error in sorted(state.load_errors.items())
    )
    asset_diagnostics = tuple(
        ExtensionAssetErrorResponse(extension_id=extension_id, error=_diagnostic_message(error))
        for extension_id, error in sorted((asset_errors or {}).items())
    )

    @router.get("/extensions", response_model=ExtensionListResponse)
    async def list_extensions(request: Request) -> ExtensionListResponse:
        """List extensions installed and enabled when the server started.

        Installed extensions serve pages and navigation unless the server
        config's ``extensions`` section disables them; only enabled ones also
        serve UI slot items. Changing packages or that section requires a server
        restart to refresh this snapshot.
        """
        require_user(request, auth_provider)
        return ExtensionListResponse(data=list(catalog))

    # Keep this static path above ``/{extension_id}`` so it cannot be consumed
    # as an extension identifier.
    @router.get("/extensions/diagnostics", response_model=ExtensionDiagnosticsResponse)
    async def extension_diagnostics(request: Request) -> ExtensionDiagnosticsResponse:
        """Show accepted extensions, discovery failures and activations to administrators."""
        await _require_admin(request, auth_provider, permission_store)
        return ExtensionDiagnosticsResponse(
            extensions=list(catalog),
            load_errors=list(diagnostics),
            asset_errors=list(asset_diagnostics),
            activations=[
                ExtensionActivationResponse(
                    extension_id=record.extension_id,
                    status=cast(ActivationStatus, record.state.value),
                    error=_diagnostic_message(record.error) if record.error else None,
                )
                for _, record in sorted((activations() if activations else {}).items())
            ],
        )

    @router.get("/extensions/{extension_id}", response_model=ExtensionResponse)
    async def get_extension(request: Request, extension_id: str) -> ExtensionResponse:
        """Return one installed extension's public contribution metadata."""
        require_user(request, auth_provider)
        extension = by_id.get(extension_id)
        if extension is None:
            raise OmnigentError("Extension not found", code=ErrorCode.NOT_FOUND)
        return extension

    return router
