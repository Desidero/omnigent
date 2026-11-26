# side-schemas

Needs: none
Covers: 8417c10193880322

Infrastructure for other series, nothing a user sees: a feature outside the
main Alembic chain can keep its own tables as a side store, with its own
revisions and version table, in the schema `omx_<name>` on PostgreSQL and
CockroachDB and as `<name>_<table>` tables on SQLite and MySQL. The store
migrates itself on first use, after the main bootstrap, and deleting a
conversation tells each registered store which conversations went. No series
uses it yet; it adds no tables of its own.

- **Turn on:** nothing to turn on; a series registers a store.
- **Docs:** [side stores](../extending/side_schemas.md).
- **Upstream:** not proposed; upstream adds tables through its own chain.

## Must hold

- Upgrade safety: a build without this series, or without a given store,
  starts and upgrades the main schema (server bootstrap, the CockroachDB
  bootstrap check, `omnigent debug db-upgrade`) against a database that holds
  side stores, including one at a revision newer than any build knows, and
  leaves their rows alone.
- The main `alembic_version` and the main chain's heads never change because
  of a side store.
- A side store at a revision this build doesn't know stops only that store,
  with an error naming the revision; the rest of the server runs.
- First use creates the store and upgrades it to head once; servers starting
  together migrate it once (lock on PostgreSQL and SQLite, retry on
  CockroachDB).
- Delete isolation: a side store's cleanup runs only after the conversation
  delete has committed. A cleanup that fails is logged, keeps that store's
  rows and neither fails nor rolls back the delete; if the delete fails, no
  side rows are touched.
- A store whose tables break the database guide's rules (foreign keys,
  auto-increment, JSON, enums, unbounded columns, unprefixed names) refuses
  to start.

## Key code

- `omnigent/db/side_schemas.py`: `SideStore`, `side_metadata`, `register_side_store`, `migration_schema`, `ensure_side_store`, `delete_conversation_rows`
- `omnigent/db/side_migrations/env.py`
- `omnigent/stores/conversation_store/sqlalchemy_store.py`: `delete_conversation`

## Tests

- `tests/db/test_migration_side_schemas.py`
- `tests/db/side_store_toy/__init__.py`
