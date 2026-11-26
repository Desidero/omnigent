"""create toy notes

Revision ID: toy0001
Revises:
"""

from __future__ import annotations

import os
import time

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16
from omnigent.db.side_schemas import migration_schema

revision: str = "toy0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "toy_notes",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", Uuid16(), nullable=False),
        sa.Column("note_id", Uuid16(), nullable=False),
        sa.Column("body", sa.String(length=256), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "conversation_id", "note_id", name="pk_toy_notes"),
        schema=migration_schema(),
    )
    # Lets the concurrency test hold the migration open (see MIGRATION_DELAY_ENV).
    time.sleep(float(os.environ.get("OMNIGENT_TEST_TOY_MIGRATION_DELAY", "0")))


def downgrade() -> None:
    op.drop_table("toy_notes", schema=migration_schema())
