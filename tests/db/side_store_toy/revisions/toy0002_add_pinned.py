"""add pinned to toy notes

Revision ID: toy0002
Revises: toy0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from omnigent.db.side_schemas import migration_schema

revision: str = "toy0002"
down_revision: str | None = "toy0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("toy_notes", schema=migration_schema()) as batch:
        batch.add_column(sa.Column("pinned", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("toy_notes", schema=migration_schema()) as batch:
        batch.drop_column("pinned")
