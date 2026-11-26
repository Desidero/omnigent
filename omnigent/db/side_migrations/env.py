"""Alembic environment shared by every side store (``omnigent.db.side_schemas``).

It holds no revisions. Each run is pointed at one side store's own revision
directory and version table, on a connection whose transaction the caller owns.
"""

from __future__ import annotations

from alembic import context

from omnigent.db.side_schemas import SideStore

store: SideStore = context.config.attributes["side_store"]
connection = context.config.attributes["connection"]
schema = store.schema_on(connection.dialect.name)

context.configure(
    connection=connection,
    target_metadata=store.metadata,
    version_table=store.version_table,
    version_table_schema=schema,
    render_as_batch=True,  # required for SQLite ALTER TABLE support
    side_schema=schema,
)
with context.begin_transaction():
    context.run_migrations()
