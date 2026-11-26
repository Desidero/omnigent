"""create the open items tables

Revision ID: open_items0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import VARBINARY

from omnigent.db.db_models import Uuid16
from omnigent.db.side_schemas import migration_schema

revision: str = "open_items0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

# A BLOB on PostgreSQL and SQLite, a VARBINARY of the cap on MySQL; the
# application checks the cap on every write.
_ENVELOPE = sa.LargeBinary().with_variant(VARBINARY(16_383), "mysql")
_SQLITE_FAMILY = frozenset({"sqlite", "cloudflare_d1"})
# SQLite enforces neither declared lengths nor types; these bound what it stores.
_SQLITE_CHECKS: tuple[tuple[str, str], ...] = (
    ("length(CAST(user_id AS BLOB)) <= 512", "ck_open_items_entries_user_id_bytes"),
    (
        "length(CAST(idempotency_key AS BLOB)) <= 512",
        "ck_open_items_entries_idempotency_key_bytes",
    ),
    (
        "dedupe_key IS NULL OR length(CAST(dedupe_key AS BLOB)) <= 256",
        "ck_open_items_entries_dedupe_key_bytes",
    ),
    ("length(CAST(content AS BLOB)) <= 16383", "ck_open_items_entries_content_bytes"),
    (
        "outcome IS NULL OR length(CAST(outcome AS BLOB)) <= 16383",
        "ck_open_items_entries_outcome_bytes",
    ),
    ("typeof(number) = 'integer'", "ck_open_items_entries_number_integer"),
    ("typeof(created_at) = 'integer'", "ck_open_items_entries_created_at_integer"),
)


def _sqlite_checks() -> list[sa.CheckConstraint]:
    if op.get_bind().dialect.name not in _SQLITE_FAMILY:
        return []
    return [sa.CheckConstraint(expr, name=name) for expr, name in _SQLITE_CHECKS]


def upgrade() -> None:
    schema = migration_schema()
    op.create_table(
        "open_items_entries",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", Uuid16(), nullable=False),
        sa.Column("kind", sa.SmallInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("root_conversation_id", Uuid16(), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("closed_at", sa.BigInteger(), nullable=True),
        sa.Column("content", _ENVELOPE, nullable=False),
        sa.Column("outcome", _ENVELOPE, nullable=True),
        sa.CheckConstraint("status IN (1, 2, 3)", name="ck_open_items_entries_status"),
        sa.CheckConstraint("kind IN (1, 2, 3, 4, 5)", name="ck_open_items_entries_kind"),
        sa.PrimaryKeyConstraint(
            "workspace_id", "conversation_id", "kind", "number", name="pk_open_items_entries"
        ),
        *_sqlite_checks(),
        schema=schema,
    )
    op.create_index(
        "ix_open_items_entries_status",
        "open_items_entries",
        ["workspace_id", "conversation_id", "status", "kind", "number"],
        schema=schema,
    )
    op.create_index(
        "ix_open_items_entries_idem",
        "open_items_entries",
        ["workspace_id", "conversation_id", "idempotency_key", "kind", "number"],
        schema=schema,
    )
    op.create_table(
        "open_items_heads",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", Uuid16(), nullable=False),
        sa.Column("kind", sa.SmallInteger(), nullable=False),
        sa.Column("next_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id", "conversation_id", "kind", name="pk_open_items_heads"
        ),
        schema=schema,
    )


def downgrade() -> None:
    schema = migration_schema()
    op.drop_table("open_items_heads", schema=schema)
    op.drop_index("ix_open_items_entries_idem", "open_items_entries", schema=schema)
    op.drop_index("ix_open_items_entries_status", "open_items_entries", schema=schema)
    op.drop_table("open_items_entries", schema=schema)
