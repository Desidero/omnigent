"""Open items an agent labels only in chat: record them, and tell the agent once.

An agent with the ``open_items`` tools is asked to record every item it
raises with ``sys_open_items_raise``. When it writes a label such as
``[Q3] **Title** detail`` in chat without doing so, the item would exist only
in the transcript. So when a session's turn ends, the server reads the agent
messages written since it last looked, with the chat's own label rules
(:mod:`omnigent.entities.item_labels`), off the turn's path:

* a label the store does not have, written where an item starts, is recorded
  under that label with ``raised_by: "auto"``, its title, its block as the
  detail and the block's links; a tool raise of the same label later takes the
  item over;
* a struck label (``~~[Q3]~~``) closes its item if it is still open, with the
  sentence that struck it as the resolution and ``closed_by: "auto"``.

Labels the store has are left alone, so a repeated read, a retry or an edited
message adds nothing, and no label a tool raised is ever taken. When a read
changes something, the agent's next message carries one framework notice
(:func:`chat_note_text`), at most :data:`NOTE_LIMIT` times per session.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from typing import Any

from omnigent.db.db_models import current_workspace_id
from omnigent.entities import ConversationItem, MessageData
from omnigent.entities.item_labels import (
    defines_label,
    extract_item_block,
    extract_label_sentence,
    item_label_title_parts,
    item_labels_in,
    links_in_markdown,
    struck_item_labels_in,
    without_links,
)
from omnigent.entities.open_items import (
    DETAIL_MAX_CHARS,
    LINKS_PER_ITEM,
    RAISED_FROM_CHAT,
    RESOLUTION_MAX_CHARS,
    TITLE_MAX_CHARS,
    NewOpenItem,
    OpenItemChange,
    OpenItemError,
    normalize_change,
    normalize_new_item,
    parse_label,
)
from omnigent.errors import StaleCursorError
from omnigent.inner.native_attachments import framework_text_notice_block
from omnigent.stores import AgentStore, ConversationStore
from omnigent.stores.open_items_store import ChatNote, ChatRecord, OpenItemsSessionNotFoundError
from omnigent.stores.permission_store import PermissionStore

_logger = logging.getLogger(__name__)

NOTE_PREFIX = "[Open items]"
# An agent that keeps labelling in chat is told this many times per session, then not again.
NOTE_LIMIT = 3
# At most this many labels are recorded or closed per read, beyond the store's own caps.
MAX_CHANGES_PER_READ = 20
# The note names this many items, then counts the rest.
_NOTE_NAMES = 6
_NOTE_TITLE_CHARS = 60
# A native harness mirrors its reply a moment after the turn ends.
SETTLE_SECONDS = 2.0
_PAGE = 100
_PAGES_PER_READ = 3


def _chat_item(label: str, markdown: str) -> NewOpenItem | None:
    """The item ``label`` stands for in ``markdown``, or ``None`` if the store can't hold it."""
    try:
        kind, number = parse_label(label)
    except OpenItemError:
        return None
    if not defines_label(markdown, label):
        return None
    block = extract_item_block(markdown, label) or ""
    title, _ = item_label_title_parts(markdown, label)
    links = [
        {"url": link.url, **({"label": link.text[:120]} if link.text else {})}
        for link in links_in_markdown(block)
    ]
    fields: dict[str, Any] = {
        "kind": kind,
        "label": label,
        "detail": block[:DETAIL_MAX_CHARS],
        "raised_by": RAISED_FROM_CHAT,
    }
    if kind == "link":
        if not links:
            return None
        # Titled as the chat's Links list titles a pin; the store names an untitled one.
        fields["url"] = links[0]["url"]
        fields["title"] = without_links(title) or links[0].get("label", "")
    else:
        fields["title"] = title
        if links:
            fields["links"] = links[:LINKS_PER_ITEM]
    fields["title"] = fields["title"][:TITLE_MAX_CHARS]
    try:
        item = normalize_new_item(fields)
    except OpenItemError:
        # A bad link or an empty title: keep what still makes an item.
        fields.pop("links", None)
        try:
            item = normalize_new_item(fields)
        except OpenItemError:
            return None
    assert item.number == number
    return item


def chat_changes(
    messages: Sequence[tuple[str, str]],
) -> tuple[list[tuple[str, NewOpenItem]], list[tuple[str, OpenItemChange]]]:
    """What a run of agent messages raises and closes by label alone.

    :param messages: ``(item id, markdown)`` of agent messages, oldest first.
    :returns: ``(idempotency key, item)`` per label first written as an item,
        and ``(closed_ref, close)`` per label struck through, the newest strike
        giving the resolution; at most :data:`MAX_CHANGES_PER_READ` in all.
    """
    raises: dict[str, tuple[str, NewOpenItem]] = {}
    closes: dict[str, tuple[str, OpenItemChange]] = {}
    for item_id, markdown in messages:
        struck = struck_item_labels_in(markdown)
        for label in item_labels_in(markdown):
            if label in raises or label in struck:
                continue
            item = _chat_item(label, markdown)
            if item is not None:
                raises[label] = (f"chat:{item_id}:{label}", item)
        for label in struck:
            sentence = extract_label_sentence(markdown, label) or f"~~[{label}]~~"
            try:
                change = normalize_change(
                    {
                        "label": label,
                        "status": "closed",
                        "resolution": sentence[:RESOLUTION_MAX_CHARS],
                    }
                )
            except OpenItemError:
                continue
            closes[label] = (f"chat:{item_id}", change)
    ordered_raises = list(raises.values())[:MAX_CHANGES_PER_READ]
    ordered_closes = list(closes.values())[: MAX_CHANGES_PER_READ - len(ordered_raises)]
    return ordered_raises, ordered_closes


def _joined(names: Sequence[str]) -> str:
    shown = list(names[:_NOTE_NAMES])
    if len(names) > _NOTE_NAMES:
        shown.append(f"{len(names) - _NOTE_NAMES} more")
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def chat_note_text(note: ChatNote) -> str:
    """The framework notice for the agent's next turn, e.g.

    ``[Open items] Q3 "Title" and R1 "Title" were labelled in chat without being
    recorded, so they were added for you. Next time record items with
    sys_open_items_raise; set a topic or close them with sys_open_items_update
    if needed. Closed from chat: Q1. Open now: 4.``
    """
    parts = [NOTE_PREFIX]
    if note.added:
        names = [
            f'{entry["label"]} "{entry["title"][:_NOTE_TITLE_CHARS]}"' for entry in note.added
        ]
        one = len(names) == 1
        parts.append(
            f"{_joined(names)} {'was' if one else 'were'} labelled in chat without being "
            f"recorded, so {'it was' if one else 'they were'} added for you. Next time record "
            "items with sys_open_items_raise; set a topic or close them with "
            "sys_open_items_update if needed."
        )
    if note.closed:
        parts.append(f"Closed from chat: {_joined(note.closed)}.")
        if not note.added:
            parts.append("Next time close items with sys_open_items_update.")
    parts.append(f"Open now: {note.open_count}.")
    return " ".join(parts)


def _agent_text(item: ConversationItem) -> str | None:
    from omnigent.server.routes._sessions.helpers import _message_text

    data = item.data
    if not isinstance(data, MessageData) or data.role != "assistant" or data.is_meta:
        return None
    return _message_text(data.content)


def _is_user_input(item: ConversationItem) -> bool:
    data = item.data
    return isinstance(data, MessageData) and data.role == "user" and not data.is_meta


class ChatItemRecorder:
    """Records a session's chat-only labels when its turn ends, one read per session at a time."""

    def __init__(
        self,
        conversation_store: ConversationStore,
        *,
        agent_store: AgentStore,
        agent_cache: Any,
        permission_store: PermissionStore | None = None,
        settle_seconds: float = SETTLE_SECONDS,
    ) -> None:
        self._conversations = conversation_store
        self._agents = agent_store
        self._agent_cache = agent_cache
        self._permissions = permission_store
        self._settle_seconds = settle_seconds
        self._running: dict[tuple[int, str], asyncio.Task[None]] = {}
        self._again: set[tuple[int, str]] = set()

    def store(self) -> Any:
        """The open items store beside the session metadata, or ``None``."""
        from omnigent.server.open_items import open_store

        return open_store(self._conversations)

    def turn_ended(self, session_id: str) -> None:
        """Read the session's new agent messages soon, off the caller's path."""
        key = (current_workspace_id(), session_id)
        if key in self._running:
            self._again.add(key)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        # The task copies this context, so the store reads the session's workspace.
        self._running[key] = loop.create_task(self._run(key))

    async def _run(self, key: tuple[int, str]) -> None:
        try:
            while True:
                self._again.discard(key)
                await asyncio.sleep(self._settle_seconds)
                try:
                    await self.record(key[1])
                except Exception:
                    _logger.warning("Recording open items from chat failed", exc_info=True)
                if key not in self._again:
                    return
        finally:
            self._running.pop(key, None)

    async def record(self, session_id: str) -> ChatRecord | None:
        """Read the agent messages since the last read and record what they label.

        :returns: What changed, or ``None`` when the session is not one whose
            agent keeps the tools, or there is no store.
        """
        from omnigent.server.open_items import (
            agent_keeps_open_items,
            item_owner,
            publish_open_items_changed,
        )

        store = self.store()
        if store is None:
            return None
        session = await asyncio.to_thread(self._conversations.get_conversation, session_id)
        if session is None:
            return None
        keeps = await asyncio.to_thread(
            agent_keeps_open_items, session, self._agents, self._agent_cache
        )
        if not keeps:
            return None
        read_before, cursor = await asyncio.to_thread(store.chat_scanned_through, session.id)
        messages, newest = await asyncio.to_thread(self._new_messages, session.id, cursor)
        if newest is None and read_before:
            return ChatRecord(added=[], closed=[])
        raises, closes = chat_changes(messages)
        owner = (
            await asyncio.to_thread(
                item_owner, self._conversations, self._permissions, session, None
            )
            if raises
            else ""
        )
        try:
            record = await asyncio.to_thread(
                lambda: store.record_from_chat(
                    session.id,
                    raises,
                    closes,
                    scanned_through=newest,
                    root_conversation_id=session.root_conversation_id or session.id,
                    user_id=owner,
                    note_limit=NOTE_LIMIT,
                )
            )
        except OpenItemsSessionNotFoundError:
            return None
        labels = [item.label for item in [*record.added, *record.closed]]
        await publish_open_items_changed(store, session.id, labels)
        return record

    def _new_messages(
        self, session_id: str, cursor: str | None
    ) -> tuple[list[tuple[str, str]], str | None]:
        """Agent messages after ``cursor``, oldest first, and the newest item id read.

        Without a cursor (the first read, or one whose item is gone) only the
        latest turn is read: labels in older history are not backfilled.
        """
        if cursor is not None:
            with contextlib.suppress(StaleCursorError):
                return self._messages_after(session_id, cursor)
        return self._latest_turn(session_id)

    def _messages_after(
        self, session_id: str, cursor: str
    ) -> tuple[list[tuple[str, str]], str | None]:
        messages: list[tuple[str, str]] = []
        newest: str | None = None
        after = cursor
        for _ in range(_PAGES_PER_READ):
            page = self._conversations.list_items(
                session_id, limit=_PAGE, after=after, order="asc"
            )
            for item in page.data:
                newest = item.id
                if (text := _agent_text(item)) is not None:
                    messages.append((item.id, text))
            if not page.has_more or page.last_id is None:
                break
            after = page.last_id
        return messages, newest

    def _latest_turn(self, session_id: str) -> tuple[list[tuple[str, str]], str | None]:
        page = self._conversations.list_items(session_id, limit=_PAGE, order="desc")
        newest = page.data[0].id if page.data else None
        messages: list[tuple[str, str]] = []
        for item in page.data:
            if _is_user_input(item):
                break
            if (text := _agent_text(item)) is not None:
                messages.append((item.id, text))
        messages.reverse()
        return messages, newest

    async def take_note(self, session_id: str) -> str | None:
        """Take the note the agent's next message should carry, or ``None``."""
        store = self.store()
        if store is None:
            return None
        note = await asyncio.to_thread(store.take_chat_note, session_id)
        return chat_note_text(note) if note is not None else None

    async def aclose(self) -> None:
        """Cancel reads in flight; later turn ends are still accepted."""
        tasks = list(self._running.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# The app's recorder, for turn ends and messages handled outside a request's scope.
_installed: ChatItemRecorder | None = None


def install_recorder(recorder: ChatItemRecorder | None) -> None:
    """Make ``recorder`` the one :func:`notify_turn_end` and :func:`with_pending_note` use."""
    global _installed
    _installed = recorder


def notify_turn_end(session_id: str) -> None:
    """Record the session's chat-only labels after its turn ended."""
    if _installed is not None:
        _installed.turn_ended(session_id)


async def with_pending_note(session_id: str, content: object) -> object:
    """Message content with the open items note appended, when one is waiting.

    The note is a framework notice block, which harnesses give the model as
    context for this turn and never show as the user's text. Taking it counts
    it as told, so a message that then fails to reach the runner drops it.
    """
    if _installed is None or not isinstance(content, list):
        return content
    try:
        text = await _installed.take_note(session_id)
    except Exception:
        _logger.warning("Reading the open items note failed", exc_info=True)
        return content
    return content if text is None else [*content, framework_text_notice_block(text)]
