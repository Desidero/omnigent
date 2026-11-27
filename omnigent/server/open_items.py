"""Open items API: the questions, risks, findings, follow-ups and links a session raises.

A session's agent raises and updates items through its ``sys_open_items_*``
tools, which its runner sends here; people read them and may close, reopen,
retopic or reply to them. Items live in the ``open_items`` side store
(:mod:`omnigent.stores.open_items_store`). Every write publishes
``session.open_items.changed`` on the session's stream.

Routes, under ``/v1``:

* ``GET /sessions/{session_id}/open-items`` lists items with filters and
  counts (read access).
* ``POST /sessions/{session_id}/open-items`` raises items. Only the session's
  runner writes, for an agent with the ``open_items`` tool group: the source
  header names the session, and a shared server verifies its bound runner's
  tunnel token (edit access).
* ``PATCH /sessions/{session_id}/open-items`` changes items: from the session's
  runner as above, or from a person with edit access.
* ``POST /sessions/{session_id}/open-items/replies`` records a person's replies,
  such as their comments on items (edit access); an open item becomes answered.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from omnigent.entities import Conversation
from omnigent.entities.open_items import (
    BATCH_KEY_MAX_CHARS,
    IDEMPOTENCY_KEY_MAX_CHARS,
    LIST_PAGE_MAX,
    RAISE_BATCH_MAX,
    REPLY_MAX_CHARS,
    UPDATE_BATCH_MAX,
    OpenItemError,
    OpenItemFilter,
    item_to_json,
    normalize_change,
    normalize_new_item,
    normalize_topic_slug,
    page_items,
)
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runner.identity import (
    ORCHESTRATION_SOURCE_HEADER,
    RUNNER_TUNNEL_TOKEN_HEADER,
    token_bound_runner_id,
)
from omnigent.runtime import session_stream
from omnigent.server.auth import LEVEL_EDIT, LEVEL_READ, RESERVED_USER_LOCAL, AuthProvider
from omnigent.server.routes._auth_helpers import get_user_id, require_access_and_level
from omnigent.server.routes._errors import session_not_found
from omnigent.stores import AgentStore, ConversationStore
from omnigent.stores.open_items_store import (
    ChangedItem,
    OpenItemsSessionNotFoundError,
    OpenItemsStore,
    open_items_store_for,
)
from omnigent.stores.permission_store import PermissionStore
from omnigent.util.uuid import InvalidUuidError, uuid_to_bytes

_logger = logging.getLogger(__name__)

OPEN_ITEMS_CHANGED_EVENT = "session.open_items.changed"
_unavailable_logged = threading.Event()


def open_store(conversation_store: object) -> OpenItemsStore | None:
    """Return the open items store beside the session metadata, or ``None`` without SQL.

    :param conversation_store: The server's conversation store; items live in
        the database at its ``storage_location``.
    """
    location = getattr(conversation_store, "storage_location", None)
    if not isinstance(location, str) or not location:
        return None
    try:
        return open_items_store_for(location)
    except Exception:
        if not _unavailable_logged.is_set():
            _unavailable_logged.set()
            _logger.warning("Open items storage is unavailable", exc_info=True)
        return None


class OpenItemsRaiseRequest(BaseModel):
    """Items the session's agent raises; see ``sys_open_items_raise``."""

    items: list[dict[str, Any]] = Field(min_length=1, max_length=RAISE_BATCH_MAX)
    # Names the call, e.g. "tool:<call id>"; item i is written as "<key>:<i>".
    idempotency_key: str = Field(min_length=1, max_length=BATCH_KEY_MAX_CHARS)


class OpenItemsUpdateRequest(BaseModel):
    """Changes to items; see ``sys_open_items_update``."""

    updates: list[dict[str, Any]] = Field(min_length=1, max_length=UPDATE_BATCH_MAX)
    # What made the change, e.g. "tool:<call id>"; recorded on a close and a reply.
    ref: str | None = Field(default=None, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


class OpenItemReply(BaseModel):
    """A person's reply to one item."""

    label: str = Field(min_length=2, max_length=4)
    text: str = Field(min_length=1, max_length=REPLY_MAX_CHARS)


class OpenItemsReplyRequest(BaseModel):
    """Replies to record, one per item."""

    replies: list[OpenItemReply] = Field(min_length=1, max_length=UPDATE_BATCH_MAX)
    # Names the write, e.g. "comment:<id>", so a retry records each reply once.
    ref: str | None = Field(default=None, max_length=IDEMPOTENCY_KEY_MAX_CHARS)


def _require_store(conversation_store: ConversationStore) -> OpenItemsStore:
    store = open_store(conversation_store)
    if store is None:
        raise OmnigentError(
            "Open items are not available on this server", code=ErrorCode.NOT_FOUND
        )
    return store


@contextmanager
def _item_errors() -> Iterator[None]:
    try:
        yield
    except OpenItemsSessionNotFoundError as exc:
        raise session_not_found() from exc
    except OpenItemError as exc:
        raise OmnigentError(str(exc), code=ErrorCode.INVALID_INPUT) from exc


def _same_session(left: str, right: str) -> bool:
    try:
        return uuid_to_bytes(left.strip()) == uuid_to_bytes(right)
    except InvalidUuidError:
        return False


def _error_json(error: OpenItemError) -> dict[str, str]:
    return {"code": error.code, "message": error.message}


def _changed_json(results: Sequence[ChangedItem]) -> list[dict[str, Any]]:
    return [
        {"label": result.label, "item": item_to_json(result.item)}
        if result.item is not None
        else {"label": result.label, "error": _error_json(result.error)}  # type: ignore[arg-type]
        for result in results
    ]


def create_open_items_router(
    conversation_store: ConversationStore,
    *,
    agent_store: AgentStore,
    agent_cache: Any,
    auth_provider: AuthProvider | None = None,
    permission_store: PermissionStore | None = None,
) -> APIRouter:
    """Build the open items router, mounted under ``/v1``.

    :param conversation_store: The server's conversation store. Items are
        stored in its database; without a SQL backend every route answers 404.
    :param agent_store: Loads the session's agent, whose spec must keep the
        ``open_items`` tool group for its runner to write.
    :param agent_cache: Loads that agent's spec.
    :param auth_provider: Identifies the caller; ``None`` in single-user mode.
    :param permission_store: Session grants; ``None`` disables enforcement.
    """
    from omnigent.runtime.workflow import _find_spec_by_name

    router = APIRouter()

    async def _session(request: Request, session_id: str, level: int) -> Conversation:
        user_id = get_user_id(request, auth_provider)
        access = await require_access_and_level(
            user_id, session_id, level, permission_store, conversation_store
        )
        conversation = access.conversation or await asyncio.to_thread(
            conversation_store.get_conversation, session_id
        )
        if conversation is None:
            raise session_not_found()
        return conversation

    def _agent_keeps_open_items(session: Conversation) -> bool:
        """Whether the session's agent (or its named sub-agent) has the tool group."""
        agent = agent_store.get(session.agent_id) if session.agent_id else None
        if agent is None:
            return False
        spec = agent_cache.load(
            agent.id, agent.bundle_location, expand_env=agent.operator_authored
        ).spec
        if session.sub_agent_name:
            spec = _find_spec_by_name(spec, session.sub_agent_name)
        return spec is not None and spec.tool_groups.open_items

    async def _agent_session(request: Request, session_id: str) -> Conversation:
        """The session, when the call comes from its own runner for an agent with the group."""
        session = await _session(request, session_id, LEVEL_EDIT)
        source = request.headers.get(ORCHESTRATION_SOURCE_HEADER)
        if source is None or not _same_session(source, session.id):
            raise OmnigentError(
                "Only the session's own agent writes its open items", code=ErrorCode.FORBIDDEN
            )
        user_id = get_user_id(request, auth_provider)
        if permission_store is not None and user_id not in (None, RESERVED_USER_LOCAL):
            token = (request.headers.get(RUNNER_TUNNEL_TOKEN_HEADER) or "").strip()
            if (
                not token
                or not session.runner_id
                or token_bound_runner_id(token) != session.runner_id
            ):
                raise OmnigentError(
                    "Only the session's bound runner writes its open items",
                    code=ErrorCode.FORBIDDEN,
                )
        if not await asyncio.to_thread(_agent_keeps_open_items, session):
            raise OmnigentError(
                "Open items need an agent with the open_items tool group",
                code=ErrorCode.FORBIDDEN,
            )
        return session

    def _owner(session: Conversation, user_id: str | None) -> str:
        if permission_store is None:
            return RESERVED_USER_LOCAL
        root = session.root_conversation_id or session.id
        owner = conversation_store.get_session_owner(root, owner_only=True)
        return owner or user_id or RESERVED_USER_LOCAL

    async def _publish(store: OpenItemsStore, session_id: str, labels: list[str]) -> None:
        if not labels:
            return
        open_count = await asyncio.to_thread(store.open_count, session_id)
        session_stream.publish(
            session_id,
            {
                "type": OPEN_ITEMS_CHANGED_EVENT,
                "conversation_id": session_id,
                "labels": labels,
                "open_count": open_count,
            },
        )

    @router.get("/sessions/{session_id}/open-items")
    async def list_open_items(
        request: Request,
        session_id: str,
        status: list[Literal["open", "answered", "closed", "all"]] = Query(  # noqa: B008
            default=["open", "answered"]
        ),
        kind: list[Literal["question", "risk", "finding", "follow_up", "link"]] = Query(  # noqa: B008
            default=[]
        ),
        topic: str | None = None,
        raised_by: str | None = None,
        has_links: bool | None = None,
        q: str | None = Query(default=None, max_length=200),
        limit: int = Query(100, ge=1, le=LIST_PAGE_MAX),
        after: str | None = Query(default=None, max_length=4),
    ) -> dict[str, Any]:
        """One page of the session's items in label order, with counts over all of them."""
        session = await _session(request, session_id, LEVEL_READ)
        store = _require_store(conversation_store)
        with _item_errors():
            wanted = OpenItemFilter(
                statuses=() if "all" in status else tuple(status),
                kinds=tuple(kind),
                topic=normalize_topic_slug(topic),
                raised_by=raised_by,
                has_links=has_links,
                query=q.strip() if q and q.strip() else None,
                after=after,
                limit=limit,
            )
            items = await asyncio.to_thread(store.list_items, session.id)
            page = page_items(items, wanted)
        data = [item_to_json(item) for item in page.items]
        return {
            "data": data,
            "has_more": page.has_more,
            "next_after": data[-1]["label"] if page.has_more else None,
            "counts": {"status": page.status_counts, "kind": page.kind_counts},
            "topics": page.topics,
        }

    @router.post("/sessions/{session_id}/open-items")
    async def raise_open_items(
        request: Request, session_id: str, body: OpenItemsRaiseRequest
    ) -> dict[str, Any]:
        """Raise items for the session's agent; only its runner calls this."""
        session = await _agent_session(request, session_id)
        store = _require_store(conversation_store)
        user_id = get_user_id(request, auth_provider)
        with _item_errors():
            if any("label" in item for item in body.items):
                raise OpenItemError(
                    "invalid_input", "labels are allocated here; raise items without a label"
                )
            items = [normalize_new_item(item) for item in body.items]
            owner = await asyncio.to_thread(_owner, session, user_id)
            results = await asyncio.to_thread(
                lambda: store.raise_items(
                    session.id,
                    items,
                    idempotency_key=body.idempotency_key,
                    root_conversation_id=session.root_conversation_id or session.id,
                    user_id=owner,
                )
            )
        rows: list[dict[str, Any]] = []
        for result in results:
            if result.item is None:
                rows.append({"error": _error_json(result.error)})  # type: ignore[arg-type]
            else:
                rows.append({"item": item_to_json(result.item), "duplicate": result.duplicate})
        everything = await asyncio.to_thread(store.list_items, session.id)
        await _publish(store, session.id, [row["item"]["label"] for row in rows if "item" in row])
        return {
            "items": rows,
            "open_count": sum(item.status != "closed" for item in everything),
            "topics": sorted({t for item in everything if (t := item.content.get("topic"))}),
        }

    @router.patch("/sessions/{session_id}/open-items")
    async def update_open_items(
        request: Request, session_id: str, body: OpenItemsUpdateRequest
    ) -> dict[str, Any]:
        """Change items, from the session's runner or a person with edit access."""
        if request.headers.get(ORCHESTRATION_SOURCE_HEADER) is not None:
            session = await _agent_session(request, session_id)
            actor, user_id = "agent", None
        else:
            session = await _session(request, session_id, LEVEL_EDIT)
            actor, user_id = "user", get_user_id(request, auth_provider)
        store = _require_store(conversation_store)
        with _item_errors():
            changes = [normalize_change(update) for update in body.updates]
            results = await asyncio.to_thread(
                lambda: store.change_items(
                    session.id, changes, actor=actor, ref=body.ref, user_id=user_id
                )
            )
        await _publish(store, session.id, [r.label for r in results if r.item is not None])
        return {"items": _changed_json(results)}

    @router.post("/sessions/{session_id}/open-items/replies")
    async def reply_to_open_items(
        request: Request, session_id: str, body: OpenItemsReplyRequest
    ) -> dict[str, Any]:
        """Record a person's replies; needs edit access."""
        session = await _session(request, session_id, LEVEL_EDIT)
        store = _require_store(conversation_store)
        user_id = get_user_id(request, auth_provider)
        with _item_errors():
            replies = [(reply.label, reply.text.strip()) for reply in body.replies]
            if not all(text for _, text in replies):
                raise OpenItemError("invalid_input", "a reply needs text")
            results = await asyncio.to_thread(
                lambda: store.record_replies(session.id, replies, user_id=user_id, ref=body.ref)
            )
        await _publish(store, session.id, [r.label for r in results if r.item is not None])
        return {"items": _changed_json(results)}

    return router
