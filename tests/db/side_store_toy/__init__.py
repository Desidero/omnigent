"""A toy side store for the side-schema tests: notes kept per conversation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import BigInteger, SmallInteger, String, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from omnigent.db.db_models import Uuid16, current_workspace_id
from omnigent.db.side_schemas import ConversationCleanup, SideStore, side_metadata

REVISIONS = Path(__file__).parent / "revisions"
QUERY_NAME_PREFIX = "omnigent.toy_note_store"
# Set in a process that should hold its migration open, so a second one overlaps it.
MIGRATION_DELAY_ENV = "OMNIGENT_TEST_TOY_MIGRATION_DELAY"


class ToyBase(DeclarativeBase):
    metadata = side_metadata("toy")


class ToyNote(ToyBase):
    """A note on a conversation; ``pinned`` arrives with the second revision."""

    __tablename__ = "toy_notes"

    workspace_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=current_workspace_id
    )
    conversation_id: Mapped[str] = mapped_column(Uuid16(), primary_key=True)
    note_id: Mapped[str] = mapped_column(
        Uuid16(), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    body: Mapped[str] = mapped_column(String(256))
    pinned: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


def delete_notes(session: Session, conversation_ids: Sequence[str]) -> None:
    session.execute(
        delete(ToyNote).where(
            ToyNote.workspace_id == current_workspace_id(),
            ToyNote.conversation_id.in_(conversation_ids),
        )
    )


def make_toy_store(
    migrations: Path = REVISIONS, cleanup: ConversationCleanup | None = delete_notes
) -> SideStore:
    return SideStore(
        name="toy",
        metadata=ToyBase.metadata,
        migrations=migrations,
        on_conversations_deleted=cleanup,
    )


def add_note(db_uri: str, conversation_id: str, body: str) -> None:
    sessions = make_toy_store().session_maker(db_uri, query_name_prefix=QUERY_NAME_PREFIX)
    with sessions("add_note") as session:
        session.add(ToyNote(conversation_id=conversation_id, body=body))


def note_bodies(db_uri: str) -> list[str]:
    sessions = make_toy_store().session_maker(db_uri, query_name_prefix=QUERY_NAME_PREFIX)
    with sessions("list_notes") as session:
        return sorted(session.scalars(select(ToyNote.body)))


def first_use_in_new_process(db_uri: str, gate: Path, conversation_id: str, body: str) -> None:
    """Stand in for a starting server: open the database, wait at the gate, use the store."""
    from omnigent.db.utils import get_or_create_engine
    from tests._helpers.polling import poll_until

    get_or_create_engine(db_uri)
    (gate / f"ready-{body}").touch()
    poll_until(lambda: (gate / "go").exists(), timeout_s=60, interval_s=0.01)
    add_note(db_uri, conversation_id, body)
