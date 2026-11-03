"""Add extension_session_state for small per-session extension state.

Revision ID: dbd0a8305ee3
Revises: d0a1f879a01d

One row per (session, extension, key) holding an opaque value of at most
16,383 bytes, a compare-and-set ``version`` and the user, if any, whose action
made the last write. Nothing reads or writes the table yet; the extension
state store is the first writer.

Session-only ownership is a scope choice, not a requirement of the schema
rules: a generic table with nullable typed subject columns was the
alternative, deferred until something other than a session needs state.

There is no foreign key: application code deletes a deleted session subtree's
rows by the ``(workspace_id, conversation_id)`` primary-key prefix, which also
serves per-session reads. ``ix_extension_session_state_extension`` (extension
id, then the full primary key) serves per-extension work across sessions and
workspaces: enumerating an extension's state, and purging it when the
extension is uninstalled. On MySQL the string key columns use ``utf8mb4_bin``
so keys differing in case or accents stay distinct. The change is additive and
can ship before its writer; downgrade drops the table and any state in it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import VARCHAR

from omnigent.db.db_models import Uuid16

revision: str = "dbd0a8305ee3"
down_revision: str | None = "d0a1f879a01d"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_KEY = sa.String(128).with_variant(
    VARCHAR(128, charset="utf8mb4", collation="utf8mb4_bin"), "mysql"
)


def upgrade() -> None:
    """Create the extension_session_state table."""
    op.create_table(
        "extension_session_state",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", Uuid16(), nullable=False),
        sa.Column("extension_id", _KEY, nullable=False),
        sa.Column("key", _KEY, nullable=False),
        sa.Column("value", sa.LargeBinary(16383), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "conversation_id", "extension_id", "key"),
        sa.CheckConstraint("length(value) <= 16383", name="ck_extension_session_state_value_size"),
    )
    op.create_index(
        "ix_extension_session_state_extension",
        "extension_session_state",
        ["extension_id", "workspace_id", "conversation_id", "key"],
    )


def downgrade() -> None:
    """Drop the extension_session_state table, its index and its rows."""
    op.drop_index("ix_extension_session_state_extension", table_name="extension_session_state")
    op.drop_table("extension_session_state")
