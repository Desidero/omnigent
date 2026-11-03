"""HTTP access to extension session state and state commands.

Callers act with their own share level on the session. A read returns only
keys whose declared visibility the caller's level allows; ``service`` keys
are never returned. A command writes as the extension and records the caller
as ``updated_by``.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from typing import Literal, TypeVar

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from omnigent.db.account_authority import account_generation
from omnigent.db.db_models import current_workspace_id
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.extensions.published_fields import published_field_view
from omnigent.server.auth import LEVEL_EDIT, LEVEL_READ, AuthProvider
from omnigent.server.extension_state import (
    CommandEvent,
    ExtensionCommandArgumentError,
    ExtensionStateAccessError,
    ExtensionStateService,
    ExtensionStateUnavailableError,
    effective_level,
)
from omnigent.server.routes._auth_helpers import (
    get_user_id,
    require_access,
    require_access_and_level,
)
from omnigent.server.routes._errors import session_not_found
from omnigent.stores.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
    ExtensionStateConflictError,
    ExtensionStateEntry,
    ExtensionStateQuotaError,
)
from omnigent.stores.permission_store import PermissionStore

_T = TypeVar("_T")


class ExtensionStateEntryResponse(BaseModel):
    """One state key an extension keeps about a session."""

    object: Literal["extension_state"] = "extension_state"
    key: str
    value: str | None = Field(description="The value as UTF-8 text; null when it is not text.")
    value_base64: str = Field(description="The stored bytes, base64-encoded.")
    version: int = Field(description="Compare-and-set version: 1 on insert, +1 per write.")
    updated_at: int
    updated_by: str | None = Field(
        description=(
            "The user whose command made the last write; null for the extension's own "
            "writes, and for callers without edit access."
        )
    )


class ExtensionStateListResponse(BaseModel):
    """One page of the keys the caller may read, in key order."""

    object: Literal["list"] = "list"
    data: list[ExtensionStateEntryResponse]
    next_after: str | None = Field(
        description=(
            "Pass as `after` for the next page; null on the last page. A page can hold "
            "fewer entries than `limit` while later pages exist."
        )
    )


class ExtensionCommandRequest(BaseModel):
    """Arguments for one declared command."""

    arguments: dict[str, str] = Field(default_factory=dict)
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="Write only if the key is at this version; 0 means it must be unset.",
    )


class ExtensionCommandResponse(BaseModel):
    """What a command wrote, and the session's published fields afterwards."""

    object: Literal["extension_command_result"] = "extension_command_result"
    command: str
    key: str
    entry: ExtensionStateEntryResponse | None = Field(
        description="The written entry; null after a ClearState command."
    )
    deleted: bool = Field(description="Whether a ClearState command removed a value.")
    published_fields: dict[str, dict[str, str]]


def _entry_response(
    entry: ExtensionStateEntry, *, show_updated_by: bool
) -> ExtensionStateEntryResponse:
    try:
        text: str | None = entry.value.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    return ExtensionStateEntryResponse(
        key=entry.key,
        value=text,
        value_base64=base64.b64encode(entry.value).decode("ascii"),
        version=entry.version,
        updated_at=entry.updated_at,
        # Who wrote it is for editors; readers see only the state.
        updated_by=entry.updated_by if show_updated_by else None,
    )


async def _call(function: Callable[[], _T]) -> _T:
    """Run a service call off the event loop, mapping its errors to HTTP errors.

    A stored value this server cannot read stays a server error.
    """
    try:
        return await asyncio.to_thread(function)
    except ExtensionStateUnavailableError as exc:
        raise OmnigentError("Extension not found", code=ErrorCode.NOT_FOUND) from exc
    except ExtensionStateAccessError as exc:
        raise OmnigentError(
            "This command needs more access to the session", code=ErrorCode.FORBIDDEN
        ) from exc
    except (ExtensionStateConflictError, ExtensionStateQuotaError) as exc:
        raise OmnigentError(str(exc), code=ErrorCode.CONFLICT) from exc
    except ConversationNotFoundError as exc:
        raise session_not_found() from exc
    except (ExtensionCommandArgumentError, ValueError) as exc:
        raise OmnigentError(str(exc), code=ErrorCode.INVALID_INPUT) from exc


def create_extension_state_router(
    service: ExtensionStateService,
    conversation_store: ConversationStore,
    auth_provider: AuthProvider | None = None,
    permission_store: PermissionStore | None = None,
) -> APIRouter:
    """Build the routes under ``/sessions/{session_id}/extensions/{extension_id}``.

    :param service: Access rules and commands for extension state.
    :param conversation_store: The store, for session lookups.
    :param auth_provider: Identifies callers; ``None`` in single-user mode.
    :param permission_store: Share levels; ``None`` disables enforcement and
        treats the caller as the owner.
    """
    router = APIRouter()

    async def caller_level(user_id: str | None, session_id: str) -> int | None:
        """The caller's share level, at least READ; ``None`` when permissions are off."""
        if permission_store is None:
            if await asyncio.to_thread(conversation_store.get_conversation, session_id) is None:
                raise session_not_found()
            return None
        access = await require_access_and_level(
            user_id, session_id, LEVEL_READ, permission_store, conversation_store
        )
        level = access.level or LEVEL_READ
        if level >= LEVEL_EDIT:
            return level
        # A sub-agent session's access comes from its parent, which the displayed
        # level does not walk.
        try:
            await require_access(
                user_id, session_id, LEVEL_EDIT, permission_store, conversation_store
            )
        except OmnigentError as exc:
            if exc.code != ErrorCode.FORBIDDEN:
                raise
            return level
        return LEVEL_EDIT

    @router.get(
        "/sessions/{session_id}/extensions/{extension_id}/state",
        response_model=ExtensionStateListResponse,
    )
    async def list_extension_state(
        request: Request,
        session_id: str,
        extension_id: str,
        after: str | None = Query(default=None, description="The previous page's next_after."),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> ExtensionStateListResponse:
        """List the extension's state keys on a session that the caller may read."""
        level = await caller_level(get_user_id(request, auth_provider), session_id)
        entries, cursor = await _call(
            lambda: service.list_readable(
                session_id, extension_id, level, after=after, limit=limit
            )
        )
        return ExtensionStateListResponse(
            data=[
                _entry_response(entry, show_updated_by=effective_level(level) >= LEVEL_EDIT)
                for entry in entries
            ],
            next_after=cursor,
        )

    @router.get(
        "/sessions/{session_id}/extensions/{extension_id}/state/{key:path}",
        response_model=ExtensionStateEntryResponse,
    )
    async def get_extension_state(
        request: Request,
        session_id: str,
        extension_id: str,
        key: str,
    ) -> ExtensionStateEntryResponse:
        """Read one state key. Unset keys and keys the caller may not read are 404."""
        level = await caller_level(get_user_id(request, auth_provider), session_id)
        entry = await _call(lambda: service.read(session_id, extension_id, key, level))
        if entry is None:
            raise OmnigentError("State key not found", code=ErrorCode.NOT_FOUND)
        return _entry_response(entry, show_updated_by=effective_level(level) >= LEVEL_EDIT)

    @router.post(
        "/sessions/{session_id}/extensions/{extension_id}/commands/{command_id}",
        response_model=ExtensionCommandResponse,
    )
    async def run_extension_command(
        request: Request,
        session_id: str,
        extension_id: str,
        command_id: str,
        body: ExtensionCommandRequest,
    ) -> ExtensionCommandResponse:
        """Run one of the extension's declared state commands on a session."""
        user_id = get_user_id(request, auth_provider)
        level = await caller_level(user_id, session_id)
        result = await _call(
            lambda: service.run_command(
                session_id,
                extension_id,
                command_id,
                body.arguments,
                level=level,
                user_id=user_id,
                expected_version=body.expected_version,
            )
        )
        # Before answering, so the extension has recorded who turned it on.
        await service.notify_command(
            CommandEvent(
                extension_id=extension_id,
                session_id=session_id,
                workspace_id=current_workspace_id(),
                command_id=command_id,
                key=result.key,
                deleted=result.entry is None,
                user_id=user_id,
                generation=account_generation(user_id) if user_id is not None else None,
            )
        )
        conversation = await asyncio.to_thread(conversation_store.get_conversation, session_id)
        if conversation is None:
            raise session_not_found()
        return ExtensionCommandResponse(
            command=command_id,
            key=result.key,
            # The caller made this write, so they may see their own attribution.
            entry=(
                _entry_response(result.entry, show_updated_by=True)
                if result.entry is not None
                else None
            ),
            deleted=result.deleted,
            published_fields=published_field_view().published_fields(
                conversation.labels, conversation.verified_extension_labels
            ),
        )

    return router
