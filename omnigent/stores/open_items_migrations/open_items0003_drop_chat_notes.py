"""drop the chat notes table

Revision ID: open_items0003
Revises: open_items0002

Items are created only by the agent's tools and changed only by the tools and
people, so nothing reads the chat for labels or keeps notes for the agent any
more. A database that ran open_items0002 holds the table; a new one creates
and drops it on its way to head.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import VARBINARY

from omnigent.db.db_models import Uuid16
from omnigent.db.side_schemas import migration_schema

revision: str = "open_items0003"
down_revision: str | None = "open_items0002"
branch_labels: str | None = None
depends_on: str | None = None

# The table as open_items0002 creates it, for the downgrade.
_ENVELOPE = sa.LargeBinary().with_variant(VARBINARY(16_383), "mysql")
_SQLITE_FAMILY = frozenset({"sqlite", "cloudflare_d1"})
_SQLITE_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "scanned_through IS NULL OR length(CAST(scanned_through AS BLOB)) <= 512",
        "ck_open_items_chat_notes_scanned_through_bytes",
    ),
    (
        "pending IS NULL OR length(CAST(pending AS BLOB)) <= 16383",
        "ck_open_items_chat_notes_pending_bytes",
    ),
    ("typeof(notes_sent) = 'integer'", "ck_open_items_chat_notes_notes_sent_integer"),
)


def _sqlite_checks() -> list[sa.CheckConstraint]:
    if op.get_bind().dialect.name not in _SQLITE_FAMILY:
        return []
    return [sa.CheckConstraint(expr, name=name) for expr, name in _SQLITE_CHECKS]


def upgrade() -> None:
    op.drop_table("open_items_chat_notes", schema=migration_schema())


def downgrade() -> None:
    op.create_table(
        "open_items_chat_notes",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", Uuid16(), nullable=False),
        sa.Column("scanned_through", sa.String(128), nullable=True),
        sa.Column("notes_sent", sa.Integer(), nullable=False),
        sa.Column("pending", _ENVELOPE, nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id", "conversation_id", name="pk_open_items_chat_notes"
        ),
        *_sqlite_checks(),
        schema=migration_schema(),
    )
