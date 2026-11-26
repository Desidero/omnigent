"""Persistent store of each session's open items, kept in the ``open_items`` side store.

Items are rows of ``open_items_entries``, keyed by session, kind and number,
so an item's label is part of its key. ``open_items_heads`` holds one row per
session and kind with the next number to allocate, plus a session row (kind
0) counting the session's items. A raise locks the session row, then the
kind's row, so two raises in one session never get the same label while
other sessions don't wait. A raise carries an idempotency key per item, so a
retried raise returns the labels its first attempt allocated.
``open_items_chat_notes`` holds, per session, what the server recorded from
labels the agent wrote only in chat and has not told it about yet
(:mod:`omnigent.server.open_items_auto`).

The tables live apart from the main migration chain
(``docs/extending/side_schemas.md``); deleting a session deletes its rows,
and a fork starts with none.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    delete,
    func,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from omnigent.db.db_models import (
    MAX_STORED_VALUE_BYTES,
    SqlConversationMetadata,
    Uuid16,
    current_workspace_id,
)
from omnigent.db.envelope import EnvelopedJSON, seal
from omnigent.db.side_schemas import SideStore, register_side_store, side_metadata
from omnigent.db.utils import now_epoch, run_write_transaction
from omnigent.entities.open_items import (
    ANSWERS_KEPT,
    IDEMPOTENCY_KEY_MAX_CHARS,
    ITEMS_PER_SESSION,
    KIND_BY_CODE,
    KINDS,
    NUMBER_MAX,
    RAISED_FROM_CHAT,
    SESSION_HEAD_KIND,
    STATUS_BY_CODE,
    STATUSES,
    NewOpenItem,
    OpenItem,
    OpenItemChange,
    OpenItemError,
    apply_link_changes,
    format_label,
    parse_label,
)

# Session deletion removes at most this many rows per transaction.
DELETE_BATCH = 200
_QUERY_NAME_PREFIX = "omnigent.open_items"


class OpenItemsBase(DeclarativeBase):
    metadata = side_metadata("open_items")


class SqlOpenItem(OpenItemsBase):
    """One item; its label is the kind's letter and ``number``."""

    __tablename__ = "open_items_entries"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Uuid16(), primary_key=True)
    # KINDS code: question, risk, finding, follow-up or link.
    kind: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # The session's root, for lists across a session tree.
    root_conversation_id: Mapped[str] = mapped_column(Uuid16(), nullable=False)
    # The root session's owner when the item was raised.
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # STATUSES code: open, answered or closed.
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Names the write that raised it, e.g. "tool:<call id>:0".
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # A link item's canonical URL hash, so pinning it twice returns one item.
    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Unix epoch seconds.
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    closed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # What the agent raised, which a deployment may encrypt:
    # {"title", "detail", "topic", "links", "url", "raised_by"}.
    content: Mapped[dict[str, Any]] = mapped_column(
        EnvelopedJSON(max_stored_bytes=MAX_STORED_VALUE_BYTES), nullable=False
    )
    # How it went, written apart from the content:
    # {"resolution", "closed_by", "closed_ref", "answers"}.
    outcome: Mapped[dict[str, Any] | None] = mapped_column(
        EnvelopedJSON(max_stored_bytes=MAX_STORED_VALUE_BYTES), nullable=True
    )

    __table_args__ = (
        CheckConstraint("status IN (1, 2, 3)", name="ck_open_items_entries_status"),
        CheckConstraint("kind IN (1, 2, 3, 4, 5)", name="ck_open_items_entries_kind"),
        # The open count and status filters.
        Index(
            "ix_open_items_entries_status",
            "workspace_id",
            "conversation_id",
            "status",
            "kind",
            "number",
        ),
        # Finds what a retried raise wrote.
        Index(
            "ix_open_items_entries_idem",
            "workspace_id",
            "conversation_id",
            "idempotency_key",
            "kind",
            "number",
        ),
    )


class SqlOpenItemHead(OpenItemsBase):
    """The next number per session and kind; kind 0 counts the session's items."""

    __tablename__ = "open_items_heads"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Uuid16(), primary_key=True)
    kind: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False)


class SqlOpenItemChatNote(OpenItemsBase):
    """Per session: how far its chat was read for labels, and what to tell the agent."""

    __tablename__ = "open_items_chat_notes"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Uuid16(), primary_key=True)
    # The newest conversation item read; None until the first read.
    scanned_through: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # How many notes the agent was given.
    notes_sent: Mapped[int] = mapped_column(Integer, nullable=False)
    # {"added": [{"label", "title"}], "closed": [label]} not yet told; None when nothing is.
    pending: Mapped[dict[str, Any] | None] = mapped_column(
        EnvelopedJSON(max_stored_bytes=MAX_STORED_VALUE_BYTES), nullable=True
    )
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


def delete_open_items_batch(session: Session, conversation_ids: Sequence[str]) -> bool:
    """Delete deleted sessions' heads and up to :data:`DELETE_BATCH` of their items.

    The side-store cleanup callback. Heads go first, so a raise that starts
    afterwards finds its session gone; items are read in key order and
    deleted by key.

    :returns: Whether items may remain, so the cleanup runs again.
    """
    workspace_id = current_workspace_id()
    session.execute(
        delete(SqlOpenItemHead).where(
            SqlOpenItemHead.workspace_id == workspace_id,
            SqlOpenItemHead.conversation_id.in_(conversation_ids),
        )
    )
    session.execute(
        delete(SqlOpenItemChatNote).where(
            SqlOpenItemChatNote.workspace_id == workspace_id,
            SqlOpenItemChatNote.conversation_id.in_(conversation_ids),
        )
    )
    keys: list[Any] = []
    for conversation_id in sorted(set(conversation_ids)):
        if len(keys) == DELETE_BATCH:
            break
        keys.extend(
            session.execute(
                select(SqlOpenItem.conversation_id, SqlOpenItem.kind, SqlOpenItem.number)
                .where(
                    SqlOpenItem.workspace_id == workspace_id,
                    SqlOpenItem.conversation_id == conversation_id,
                )
                .order_by(SqlOpenItem.kind, SqlOpenItem.number)
                .limit(DELETE_BATCH - len(keys))
            ).all()
        )
    if keys:
        session.execute(
            delete(SqlOpenItem)
            .where(
                SqlOpenItem.workspace_id == workspace_id,
                tuple_(SqlOpenItem.conversation_id, SqlOpenItem.kind, SqlOpenItem.number).in_(
                    [tuple(key) for key in keys]
                ),
            )
            .execution_options(synchronize_session=False)
        )
    return len(keys) == DELETE_BATCH


OPEN_ITEMS_SIDE_STORE = register_side_store(
    SideStore(
        "open_items",
        OpenItemsBase.metadata,
        Path(__file__).parent / "open_items_migrations",
        delete_open_items_batch,
    )
)


@dataclass(frozen=True)
class RaisedItem:
    """What one raised item came to: its item, or the error that stopped it."""

    item: OpenItem | None = None
    duplicate: bool = False
    error: OpenItemError | None = None
    #: The raise took over an item the server had recorded from the chat.
    took_over: bool = False

    @property
    def added(self) -> bool:
        """Whether the raise added an item to the session."""
        return self.item is not None and not self.duplicate and not self.took_over


@dataclass(frozen=True)
class ChangedItem:
    """What one change came to: the item after it, or the error that stopped it."""

    label: str
    item: OpenItem | None = None
    error: OpenItemError | None = None


@dataclass(frozen=True)
class ChatRecord:
    """What one read of a session's chat changed: the items it added and closed."""

    added: list[OpenItem]
    closed: list[OpenItem]


@dataclass(frozen=True)
class ChatNote:
    """What the agent has not been told yet, taken for its next turn."""

    added: list[dict[str, str]]
    closed: list[str]
    open_count: int


class OpenItemsSessionNotFoundError(Exception):
    """The session doesn't exist, or was deleted while the write ran."""


def _to_item(row: SqlOpenItem) -> OpenItem:
    return OpenItem(
        conversation_id=row.conversation_id,
        kind=KIND_BY_CODE[row.kind],
        number=row.number,
        status=STATUS_BY_CODE[row.status],
        created_at=row.created_at,
        updated_at=row.updated_at,
        closed_at=row.closed_at,
        content=dict(row.content),
        outcome=dict(row.outcome or {}),
    )


def _recorded_from_chat(row: SqlOpenItem) -> bool:
    """Whether the server recorded the item from a label the agent wrote only in chat."""
    return (row.content or {}).get("raised_by") == RAISED_FROM_CHAT


def _check_size(content: dict[str, Any], label: str) -> None:
    if len(seal(content)) > MAX_STORED_VALUE_BYTES:
        raise OpenItemError(
            "too_large", f"{label} is over {MAX_STORED_VALUE_BYTES} bytes stored; shorten it"
        )


class OpenItemsStore:
    """SQLAlchemy-backed store of each session's open items."""

    def __init__(self, storage_location: str) -> None:
        """Open the store, creating or upgrading its tables on first use.

        :param storage_location: SQLAlchemy URI of the database holding the
            session metadata, e.g. ``"sqlite:///omnigent.db"``.
        :raises RuntimeError: If the side store cannot be migrated.
        """
        self.storage_location = storage_location
        self._reads = OPEN_ITEMS_SIDE_STORE.session_maker(
            storage_location, query_name_prefix=_QUERY_NAME_PREFIX
        )
        self._writes = OPEN_ITEMS_SIDE_STORE.session_maker(
            storage_location, query_name_prefix=_QUERY_NAME_PREFIX, immediate=True
        )
        self._dialect = self._writes.engine.dialect.name

    # ── Locks and checks ──────────────────────────────

    def _lock_head(self, session: Session, conversation_id: str, kind: int) -> int:
        """Lock a heads row, creating it on first use; returns its ``next_number``."""
        values = {
            "workspace_id": current_workspace_id(),
            "conversation_id": conversation_id,
            "kind": kind,
            "next_number": 0 if kind == SESSION_HEAD_KIND else 1,
        }
        if self._dialect == "mysql":
            statement: Any = (
                mysql_insert(SqlOpenItemHead)
                .values(**values)
                .on_duplicate_key_update(next_number=SqlOpenItemHead.next_number)
            )
        elif self._dialect == "sqlite":
            statement = sqlite_insert(SqlOpenItemHead).values(**values).on_conflict_do_nothing()
        else:
            statement = pg_insert(SqlOpenItemHead).values(**values).on_conflict_do_nothing()
        session.execute(statement)
        # SQLite has no FOR UPDATE; its immediate transaction already holds the write lock.
        return session.execute(
            select(SqlOpenItemHead.next_number)
            .where(
                SqlOpenItemHead.workspace_id == current_workspace_id(),
                SqlOpenItemHead.conversation_id == conversation_id,
                SqlOpenItemHead.kind == kind,
            )
            .with_for_update()
        ).scalar_one()

    @staticmethod
    def _set_head(session: Session, conversation_id: str, kind: int, next_number: int) -> None:
        session.execute(
            update(SqlOpenItemHead)
            .where(
                SqlOpenItemHead.workspace_id == current_workspace_id(),
                SqlOpenItemHead.conversation_id == conversation_id,
                SqlOpenItemHead.kind == kind,
            )
            .values(next_number=next_number)
        )

    @staticmethod
    def _require_session(session: Session, conversation_id: str) -> None:
        exists = session.execute(
            select(SqlConversationMetadata.id).where(
                SqlConversationMetadata.workspace_id == current_workspace_id(),
                SqlConversationMetadata.id == conversation_id,
            )
        ).first()
        if exists is None:
            raise OpenItemsSessionNotFoundError(f"session {conversation_id!r} not found")

    @staticmethod
    def _row(
        session: Session, conversation_id: str, kind: int, number: int, *, lock: bool = False
    ) -> SqlOpenItem | None:
        statement = select(SqlOpenItem).where(
            SqlOpenItem.workspace_id == current_workspace_id(),
            SqlOpenItem.conversation_id == conversation_id,
            SqlOpenItem.kind == kind,
            SqlOpenItem.number == number,
        )
        return session.execute(statement.with_for_update() if lock else statement).scalar()

    # ── Writes ────────────────────────────────────────

    def raise_items(
        self,
        conversation_id: str,
        items: Sequence[NewOpenItem],
        *,
        idempotency_key: str,
        root_conversation_id: str,
        user_id: str,
    ) -> list[RaisedItem]:
        """Raise items in a session, allocating their labels.

        Item ``i`` is written under ``<idempotency_key>:<i>``; a retry with the
        same key returns the items the first attempt wrote. A link whose URL
        the session already pinned returns that item as a duplicate. An item
        with its own number adopts that label if it is free, or takes over the
        item the server recorded under it from the chat.

        :param items: Checked items, see
            :func:`~omnigent.entities.open_items.normalize_new_item`.
        :param user_id: The root session's owner.
        :returns: One result per item, in order; an item the session can't
            take carries ``session_full`` or ``label_taken``.
        :raises OpenItemsSessionNotFoundError: If the session doesn't exist.
        """
        keys = [f"{idempotency_key}:{index}" for index in range(len(items))]
        if any(len(key) > IDEMPOTENCY_KEY_MAX_CHARS for key in keys):
            raise OpenItemError("invalid_input", "idempotency_key is too long")
        for item in items:
            _check_size(item.content, f"the {item.kind} {item.content.get('title')!r}")

        def write(session: Session) -> list[RaisedItem]:
            count = self._lock_head(session, conversation_id, SESSION_HEAD_KIND)
            self._require_session(session, conversation_id)
            results = []
            for item, key in zip(items, keys, strict=True):
                result = self._raise_one(
                    session, conversation_id, item, key, count, root_conversation_id, user_id
                )
                if result.added:
                    count += 1
                results.append(result)
            self._set_head(session, conversation_id, SESSION_HEAD_KIND, count)
            return results

        return run_write_transaction(self._writes, "raise_open_items", write)

    def _raise_one(
        self,
        session: Session,
        conversation_id: str,
        item: NewOpenItem,
        key: str,
        count: int,
        root_conversation_id: str,
        user_id: str,
    ) -> RaisedItem:
        workspace_id = current_workspace_id()
        earlier = session.execute(
            select(SqlOpenItem).where(
                SqlOpenItem.workspace_id == workspace_id,
                SqlOpenItem.conversation_id == conversation_id,
                SqlOpenItem.idempotency_key == key,
            )
        ).scalar()
        if earlier is not None:
            return RaisedItem(item=_to_item(earlier))
        kind = KINDS[item.kind][0]
        if item.dedupe_key is not None:
            # A session's links are bounded by the per-kind cap.
            pinned = session.execute(
                select(SqlOpenItem).where(
                    SqlOpenItem.workspace_id == workspace_id,
                    SqlOpenItem.conversation_id == conversation_id,
                    SqlOpenItem.kind == kind,
                    SqlOpenItem.dedupe_key == item.dedupe_key,
                )
            ).scalar()
            if pinned is not None:
                return RaisedItem(item=_to_item(pinned), duplicate=True)
        if item.number is not None and item.content.get("raised_by") != RAISED_FROM_CHAT:
            existing = self._row(session, conversation_id, kind, item.number, lock=True)
            if existing is not None and _recorded_from_chat(existing):
                # The agent raising a label the server recorded from its chat takes it over.
                existing.content = item.content
                existing.idempotency_key = key
                existing.updated_at = now_epoch()
                return RaisedItem(item=_to_item(existing), took_over=True)
        if count >= ITEMS_PER_SESSION:
            return RaisedItem(
                error=OpenItemError(
                    "session_full",
                    f"this session holds {ITEMS_PER_SESSION} items; close and reuse topics, "
                    "or label further items in chat",
                )
            )
        next_number = self._lock_head(session, conversation_id, kind)
        number = next_number if item.number is None else item.number
        if number > NUMBER_MAX:
            return RaisedItem(
                error=OpenItemError(
                    "session_full", f"this session has used every {item.kind} label"
                )
            )
        if item.number is not None and self._row(session, conversation_id, kind, number):
            return RaisedItem(
                error=OpenItemError(
                    "label_taken",
                    f"{format_label(item.kind, number)} is already an item in this session; "
                    "raise without a label to get a new one",
                )
            )
        now = now_epoch()
        row = SqlOpenItem(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            kind=kind,
            number=number,
            root_conversation_id=root_conversation_id,
            user_id=user_id,
            status=STATUSES["open"],
            idempotency_key=key,
            dedupe_key=item.dedupe_key,
            created_at=now,
            updated_at=now,
            closed_at=None,
            content=item.content,
            outcome=None,
        )
        session.add(row)
        session.flush()
        self._set_head(session, conversation_id, kind, max(next_number, number + 1))
        return RaisedItem(item=_to_item(row))

    def record_from_chat(
        self,
        conversation_id: str,
        raises: Sequence[tuple[str, NewOpenItem]],
        closes: Sequence[tuple[str, OpenItemChange]],
        *,
        scanned_through: str | None,
        root_conversation_id: str,
        user_id: str,
        note_limit: int,
    ) -> ChatRecord:
        """Record items the agent labelled only in chat, and close the ones it struck.

        A label any item already has is left alone, so nothing a tool raised
        changes and a read repeated over the same messages adds nothing. A
        struck label closes its item if it is still open. What changes is kept
        to tell the agent, unless it was told ``note_limit`` times already.

        :param raises: ``(idempotency key, item)`` pairs; each item carries its
            chat label as ``number``.
        :param closes: ``(closed_ref, close)`` pairs.
        :param scanned_through: The newest conversation item read.
        :raises OpenItemsSessionNotFoundError: If the session doesn't exist.
        """
        for _, item in raises:
            _check_size(item.content, f"the {item.kind} {item.content.get('title')!r}")

        def write(session: Session) -> ChatRecord:
            count = self._lock_head(session, conversation_id, SESSION_HEAD_KIND)
            self._require_session(session, conversation_id)
            note = self._lock_chat_note(session, conversation_id)
            added: list[OpenItem] = []
            for key, item in raises:
                assert item.number is not None
                if self._row(session, conversation_id, KINDS[item.kind][0], item.number):
                    continue
                result = self._raise_one(
                    session, conversation_id, item, key, count, root_conversation_id, user_id
                )
                if result.added:
                    count += 1
                    added.append(result.item)  # type: ignore[arg-type]
            closed: list[OpenItem] = []
            for ref, change in closes:
                row = self._row(session, conversation_id, KINDS[change.kind][0], change.number)
                if row is None or row.status == STATUSES["closed"]:
                    continue
                changed = self._change_one(session, conversation_id, change, RAISED_FROM_CHAT, ref)
                if changed.item is not None:
                    closed.append(changed.item)
            self._set_head(session, conversation_id, SESSION_HEAD_KIND, count)
            if scanned_through is not None:
                note.scanned_through = scanned_through
            if (added or closed) and note.notes_sent < note_limit:
                pending = dict(note.pending or {})
                pending["added"] = [
                    *(pending.get("added") or []),
                    *({"label": item.label, "title": item.content["title"]} for item in added),
                ]
                pending["closed"] = [*(pending.get("closed") or []), *(i.label for i in closed)]
                _check_size(pending, "the note for the agent")
                note.pending = pending
            note.updated_at = now_epoch()
            return ChatRecord(added=added, closed=closed)

        return run_write_transaction(self._writes, "record_open_items_from_chat", write)

    def _lock_chat_note(self, session: Session, conversation_id: str) -> SqlOpenItemChatNote:
        """Lock a session's chat note row, creating it on first use."""
        values = {
            "workspace_id": current_workspace_id(),
            "conversation_id": conversation_id,
            "scanned_through": None,
            "notes_sent": 0,
            "pending": None,
            "updated_at": now_epoch(),
        }
        if self._dialect == "mysql":
            statement: Any = (
                mysql_insert(SqlOpenItemChatNote)
                .values(**values)
                .on_duplicate_key_update(notes_sent=SqlOpenItemChatNote.notes_sent)
            )
        elif self._dialect == "sqlite":
            statement = sqlite_insert(SqlOpenItemChatNote).values(**values)
            statement = statement.on_conflict_do_nothing()
        else:
            statement = pg_insert(SqlOpenItemChatNote).values(**values).on_conflict_do_nothing()
        session.execute(statement)
        return session.execute(
            select(SqlOpenItemChatNote)
            .where(
                SqlOpenItemChatNote.workspace_id == current_workspace_id(),
                SqlOpenItemChatNote.conversation_id == conversation_id,
            )
            .with_for_update()
        ).scalar_one()

    def chat_scanned_through(self, conversation_id: str) -> tuple[bool, str | None]:
        """Whether the session's chat was read before, and the newest item read."""
        with self._reads("read_open_items_chat_cursor") as session:
            row = session.execute(
                select(SqlOpenItemChatNote.scanned_through).where(
                    SqlOpenItemChatNote.workspace_id == current_workspace_id(),
                    SqlOpenItemChatNote.conversation_id == conversation_id,
                )
            ).first()
            return (row is not None, row[0] if row is not None else None)

    def take_chat_note(self, conversation_id: str) -> ChatNote | None:
        """Take what the agent has not been told yet, counting it as told; ``None`` if nothing."""
        workspace_id = current_workspace_id()

        def write(session: Session) -> ChatNote | None:
            note = session.execute(
                select(SqlOpenItemChatNote)
                .where(
                    SqlOpenItemChatNote.workspace_id == workspace_id,
                    SqlOpenItemChatNote.conversation_id == conversation_id,
                )
                .with_for_update()
            ).scalar()
            if note is None or not note.pending:
                return None
            pending = dict(note.pending)
            note.pending = None
            note.notes_sent += 1
            note.updated_at = now_epoch()
            open_count = session.execute(
                select(func.count())
                .select_from(SqlOpenItem)
                .where(
                    SqlOpenItem.workspace_id == workspace_id,
                    SqlOpenItem.conversation_id == conversation_id,
                    SqlOpenItem.status.in_([STATUSES["open"], STATUSES["answered"]]),
                )
            ).scalar_one()
            return ChatNote(
                added=list(pending.get("added") or []),
                closed=list(pending.get("closed") or []),
                open_count=open_count,
            )

        return run_write_transaction(self._writes, "take_open_items_chat_note", write)

    def change_items(
        self,
        conversation_id: str,
        changes: Sequence[OpenItemChange],
        *,
        closed_by: str,
        closed_ref: str | None = None,
    ) -> list[ChangedItem]:
        """Change items: status, resolution, title, detail, topic and links.

        Closing records the resolution and who closed it; reopening clears
        them and keeps the answers.

        :param closed_by: ``"agent"`` or ``"user"``, recorded on a close.
        :param closed_ref: What closed it, e.g. ``"tool:<call id>"``.
        :returns: One result per change, in order; a label the session lacks
            carries ``not_found``.
        """

        def write(session: Session) -> list[ChangedItem]:
            return [
                self._change_one(session, conversation_id, change, closed_by, closed_ref)
                for change in changes
            ]

        return run_write_transaction(self._writes, "change_open_items", write)

    def _change_one(
        self,
        session: Session,
        conversation_id: str,
        change: OpenItemChange,
        closed_by: str,
        closed_ref: str | None,
    ) -> ChangedItem:
        label = format_label(change.kind, change.number)
        row = self._row(session, conversation_id, KINDS[change.kind][0], change.number, lock=True)
        if row is None:
            return ChangedItem(label, error=OpenItemError("not_found", f"no item {label}"))
        content = dict(row.content)
        outcome = dict(row.outcome or {})
        try:
            for name, value in change.fields.items():
                if value is None:
                    content.pop(name, None)
                else:
                    content[name] = value
            if change.add_links or change.remove_links:
                links = apply_link_changes(content.get("links") or [], change)
                content["links"] = links
                if not links:
                    content.pop("links")
            _check_size(content, label)
        except OpenItemError as exc:
            return ChangedItem(label, error=exc)
        now = now_epoch()
        if change.resolution is not None:
            outcome["resolution"] = change.resolution
        if change.status == "closed":
            if row.status != STATUSES["closed"]:
                row.closed_at = now
            row.status = STATUSES["closed"]
            outcome["closed_by"] = closed_by
            if closed_ref is not None:
                outcome["closed_ref"] = closed_ref
        elif change.status == "open":
            row.status = STATUSES["open"]
            row.closed_at = None
            for name in ("resolution", "closed_by", "closed_ref"):
                outcome.pop(name, None)
        row.content = content
        row.outcome = outcome or None
        row.updated_at = now
        return ChangedItem(label, item=_to_item(row))

    def record_answers(
        self, conversation_id: str, answers: Sequence[tuple[str, str]], *, user_id: str | None
    ) -> list[ChangedItem]:
        """Record the user's replies; an open item becomes answered.

        :param answers: ``(label, text)`` pairs, checked by the caller.
        :param user_id: Who replied, or ``None`` in single-user mode.
        """

        def write(session: Session) -> list[ChangedItem]:
            results = []
            for label, text in answers:
                kind, number = parse_label(label)
                label = format_label(kind, number)
                row = self._row(session, conversation_id, KINDS[kind][0], number, lock=True)
                if row is None:
                    results.append(
                        ChangedItem(label, error=OpenItemError("not_found", f"no item {label}"))
                    )
                    continue
                now = now_epoch()
                outcome = dict(row.outcome or {})
                answer = {"text": text, "at": now, "by": user_id}
                outcome["answers"] = [*(outcome.get("answers") or []), answer][-ANSWERS_KEPT:]
                row.outcome = outcome
                if row.status == STATUSES["open"]:
                    row.status = STATUSES["answered"]
                row.updated_at = now
                results.append(ChangedItem(label, item=_to_item(row)))
            return results

        return run_write_transaction(self._writes, "record_open_item_answers", write)

    # ── Reads ─────────────────────────────────────────

    def list_items(self, conversation_id: str) -> list[OpenItem]:
        """Every item of the session in label order; the session cap bounds them."""
        with self._reads("list_open_items") as session:
            rows = session.execute(
                select(SqlOpenItem)
                .where(
                    SqlOpenItem.workspace_id == current_workspace_id(),
                    SqlOpenItem.conversation_id == conversation_id,
                )
                .order_by(SqlOpenItem.kind, SqlOpenItem.number)
                .limit(ITEMS_PER_SESSION + 1)
            ).scalars()
            return [_to_item(row) for row in rows]

    def open_count(self, conversation_id: str) -> int:
        """How many of the session's items are open or answered."""
        with self._reads("count_open_items") as session:
            return session.execute(
                select(func.count())
                .select_from(SqlOpenItem)
                .where(
                    SqlOpenItem.workspace_id == current_workspace_id(),
                    SqlOpenItem.conversation_id == conversation_id,
                    SqlOpenItem.status.in_([STATUSES["open"], STATUSES["answered"]]),
                )
            ).scalar_one()


# custom-lint: disable-next=workspace-scoped-cache -- keyed by database URL; queries scope rows
_stores: dict[str, OpenItemsStore] = {}
_stores_lock = threading.Lock()


def open_items_store_for(storage_location: str) -> OpenItemsStore:
    """Return the process's store for a database, opening it once.

    :raises RuntimeError: If the side store cannot be migrated.
    """
    with _stores_lock:
        store = _stores.get(storage_location)
        if store is None:
            store = _stores[storage_location] = OpenItemsStore(storage_location)
        return store
