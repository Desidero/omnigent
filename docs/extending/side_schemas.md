# Side stores

A side store gives a feature its own database tables and its own Alembic
lineage, apart from the main chain in `omnigent/db/migrations`. Use it for a
feature that lives outside that chain, such as one carried as a patch on top
of Omnigent: its revisions never become heads of the main lineage, so the main
chain keeps upgrading as before, and a build without the feature still starts
against a database that holds its tables.

The helper is `omnigent/db/side_schemas.py`. A feature headed for the main
schema should move its tables into the main chain instead.

## Names

| What | Name |
| --- | --- |
| Store | `<name>`: lowercase letters, digits and single underscores, starting with a letter, at most 24 characters, e.g. `notes` |
| Schema (PostgreSQL, CockroachDB) | `omx_<name>` |
| Tables | `<name>_<table>`, e.g. `notes_entries`, at most 63 characters |
| Indexes | `ix_<name>_<...>` |
| Version table | `<name>_alembic_version`, in the store's schema |

SQLite and MySQL have no usable schemas, so there the tables sit beside the
main ones and the name prefix keeps them apart. A store refuses to start if a
main table already uses its prefix.

## Writing one

Tables follow [`DATABASE_BEST_PRACTICES.md`](../DATABASE_BEST_PRACTICES.md).
The store checks the parts it can see before its first migration: tables on
`side_metadata(<name>)` with the prefix, an explicit primary key, no foreign
keys, no auto-increment, no native JSON or enum columns, and string and binary
columns declared with a length of at most 16,383. Reference main rows by
value, owner first (`workspace_id`, then the conversation id).

```python
class NotesBase(DeclarativeBase):
    metadata = side_metadata("notes")

class Note(NotesBase):
    __tablename__ = "notes_entries"
    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=current_workspace_id)
    conversation_id: Mapped[str] = mapped_column(Uuid16(), primary_key=True)
    note_id: Mapped[str] = mapped_column(Uuid16(), primary_key=True)
    body: Mapped[str] = mapped_column(String(2000))

NOTES = register_side_store(SideStore("notes", NotesBase.metadata, Path(__file__).parent / "revisions", delete_notes))
sessions = NOTES.session_maker(db_uri, query_name_prefix="omnigent.note_store")
```

`session_maker` returns the same named managed sessions as
`make_named_managed_session_maker`, so name every operation:
`with sessions("add_note") as session: ...`, or
`run_write_transaction(sessions, "add_note", ...)`.

Revisions go in the store's own directory and pass `migration_schema()` as
the schema of every `op.*` call, which is `omx_<name>` on PostgreSQL and
CockroachDB and `None` elsewhere:

```python
revision = "notes0001"
down_revision = None

def upgrade() -> None:
    op.create_table("notes_entries", ..., schema=migration_schema())
```

Use `op.batch_alter_table` for column changes, so they also run on SQLite.
Start revision ids with the store's name; they only have to be unique within
the store.

## Migration

The first `session_maker` call for a database, after the main bootstrap has
run, creates the schema if it is missing and upgrades the store to its head;
later calls in the process skip the check. Concurrent first uses from several
servers are serialised: on PostgreSQL by a transaction-scoped advisory lock
keyed on the schema name, with the whole upgrade in that transaction; on
SQLite by its write lock. CockroachDB and MySQL have neither, so a start that
loses the race checks again and retries, up to five times.

`omnigent debug db-upgrade` upgrades only the main lineage.

On PostgreSQL, creating the schema needs the `CREATE` privilege on the
database. A role without it works once an operator has created `omx_<name>`
and granted it `USAGE` and `CREATE` on that schema.

## Deleted conversations

`SideStore.on_conversations_deleted(session, conversation_ids)` is called after
a conversation and its sub-sessions are deleted, with at most 100 ids per
transaction. Delete a bounded number of rows and return a true value when rows
remain; it is called again with the same ids. Register the store with
`register_side_store` at import time of a module the server imports at
startup, or it is not called.

## What holds

- The main lineage never sees a side store: the main `alembic_version`, the
  main bootstrap, the CockroachDB bootstrap's table check (it reads only
  `public`) and `omnigent debug db-upgrade` are unchanged by it.
- A build without the store, or with an older copy of it, starts and upgrades
  the main schema normally against a database that holds the store's tables.
  The rows stay as they are, unread.
- A store whose recorded revision this build doesn't know stops with an error
  on first use; the rest of the server runs.
- A cleanup that fails is logged and skipped: the conversation delete still
  succeeds, and that store keeps its rows. If the main delete fails, no
  cleanup runs and the side rows stay.

## What does not

- Rows can outlive their conversation: there are no foreign keys, a cleanup
  can fail, and a build without the store deletes conversations without
  telling it. Readers must ignore rows whose conversation is gone.
- Session export (`omnigent session export`) and import carry transcript items
  only, and forking a session copies only main rows; side rows go with none of
  them. Nothing in Omnigent copies a database table by table.
- On SQLite and MySQL, autogenerating a main revision against a database that
  holds side tables proposes dropping them. Delete those operations from the
  generated revision.
- Downgrades never run on their own.
- On CockroachDB every DDL statement commits by itself, so a revision that
  fails half way is not rolled back. Write revisions that can run again, or
  repair the schema by hand.
- During a rolling upgrade, a server still on the older build keeps using the
  store as it found it, so revisions must stay readable by the previous
  build (add, don't rename or drop). If such a server restarts after the
  upgrade, its copy of the store stops as above until it is upgraded.

## Removing a side store

Deploy a build without it first, then drop its tables. Nothing in the main
schema refers to them.

- PostgreSQL and CockroachDB: `DROP SCHEMA omx_<name> CASCADE;`
- SQLite and MySQL: `DROP TABLE <name>_<table>;` for each of the store's
  tables, then `DROP TABLE <name>_alembic_version;`

A build that has the store again recreates it, empty, on first use.
