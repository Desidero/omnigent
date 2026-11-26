"""Side stores: feature tables with a migration lineage of their own.

A side store keeps a feature's tables apart from the main Alembic lineage in
``omnigent/db/migrations``. Its tables are named ``<name>_<table>``, its
revisions live in a directory only it owns, and its version table is
``<name>_alembic_version``. On PostgreSQL and CockroachDB all of that sits in
the schema ``omx_<name>``; other backends have no usable schemas, so the name
prefix alone keeps it apart. The main lineage never sees a side store, and a
build without the feature starts against a database that holds one.

Side tables carry no foreign keys. They reference main rows by value, and
:func:`delete_conversation_rows` tells each store which conversations were
deleted. Usage: ``docs/extending/side_schemas.md``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import weakref
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Engine, Enum, LargeBinary, MetaData, String, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.types import TypeEngine

from omnigent.db.cockroachdb import _crdb_server_version, _prepare_crdb_schema_transaction
from omnigent.db.query_context import query_name_scope
from omnigent.db.utils import (
    NamedManagedSessionMaker,
    _engine_lock,
    get_or_create_engine,
    is_cockroachdb,
    is_postgresql_family,
    make_named_managed_session_maker,
    run_write_transaction,
)

if TYPE_CHECKING:
    from alembic.config import Config

_logger = logging.getLogger(__name__)

SIDE_SCHEMA_PREFIX = "omx_"
_NAME_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_MAX_NAME_LENGTH = 24
# PostgreSQL truncates longer identifiers silently.
_MAX_TABLE_NAME_LENGTH = 63
# Column values stay below 16 KiB (docs/DATABASE_BEST_PRACTICES.md).
_MAX_DECLARED_LENGTH = 16_383
_ENV_DIRECTORY = Path(__file__).parent / "side_migrations"
# Backends where a database lock serializes a store's migration.
_LOCKING_DIALECTS = frozenset({"postgresql", "sqlite"})
_UNLOCKED_MIGRATE_ATTEMPTS = 5
_CLEANUP_BATCH_SIZE = 100
# Stops a cleanup callable that keeps asking for another round.
_MAX_CLEANUP_ROUNDS = 1000

# Deletes one bounded batch of a store's rows for the given conversation ids.
# A true return value asks for another transaction over the same ids.
ConversationCleanup = Callable[[Session, Sequence[str]], object]


def side_schema_name(name: str) -> str:
    """Return the schema that holds side store *name* on PostgreSQL-family backends."""
    return f"{SIDE_SCHEMA_PREFIX}{name}"


def side_metadata(name: str) -> MetaData:
    """Return the ``MetaData`` a side store's declarative base must use.

    Its tables are declared in the side schema; on backends without schemas
    the store's sessions and migrations map that schema to none.

    :param name: The side store's name, e.g. ``"notes"``.
    """
    _validate_name(name)
    return MetaData(schema=side_schema_name(name))


@dataclass(frozen=True)
class SideStore:
    """One feature's tables, revisions and cleanup.

    :ivar name: Lowercase identifier, e.g. ``"notes"``; prefixes every table.
    :ivar metadata: The feature's own metadata, from :func:`side_metadata`.
    :ivar migrations: Directory holding only this store's Alembic revisions.
    :ivar on_conversations_deleted: Called with the ids of deleted
        conversations, at most 100 per transaction; ``None`` for a store that
        keeps nothing per conversation.
    """

    name: str
    metadata: MetaData
    migrations: Path
    on_conversations_deleted: ConversationCleanup | None = None

    def __post_init__(self) -> None:
        _validate_name(self.name)

    @property
    def schema(self) -> str:
        """The store's schema on PostgreSQL-family backends."""
        return side_schema_name(self.name)

    @property
    def version_table(self) -> str:
        """The table that records this store's Alembic revision."""
        return f"{self.name}_alembic_version"

    def schema_on(self, dialect_name: str) -> str | None:
        """Return the schema the store's tables really live in, or ``None``."""
        return self.schema if is_postgresql_family(dialect_name) else None

    def session_maker(
        self, db_uri: str, *, query_name_prefix: str, immediate: bool = False
    ) -> NamedManagedSessionMaker:
        """Return named managed sessions for this store, migrating it first.

        The first call per database creates the schema if it is missing and
        upgrades the store's lineage to head; later calls only build the maker.

        :param db_uri: The main database URI, as given to the other stores.
        :param query_name_prefix: Namespace of the feature's operation names,
            e.g. ``"omnigent.note_store"``.
        :param immediate: Forwarded to :func:`make_named_managed_session_maker`.
        :raises RuntimeError: If the store's tables break the naming rules or
            its migration fails.
        """
        return _session_maker(
            self, get_or_create_engine(db_uri), query_name_prefix, immediate=immediate
        )


def _validate_name(name: str) -> None:
    if len(name) > _MAX_NAME_LENGTH or _NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(
            f"side store name {name!r} must be lowercase letters, digits and single "
            f"underscores, start with a letter, and be at most {_MAX_NAME_LENGTH} characters"
        )


def _main_table_names() -> set[str]:
    from omnigent.db.db_models import ConversationBase, OmnigentBase

    return {
        table.name
        for metadata in (OmnigentBase.metadata, ConversationBase.metadata)
        for table in metadata.tables.values()
    } | {"alembic_version"}


def _validate_tables(store: SideStore) -> None:
    """Reject tables that could collide with, or bind to, the main schema."""
    problems: list[str] = []
    prefix = f"{store.name}_"
    taken = sorted(name for name in _main_table_names() if name.startswith(prefix))
    if taken:
        problems.append(f"the main schema already uses the prefix {prefix!r} ({taken[0]})")
    for table in store.metadata.tables.values():
        if table.schema != store.schema:
            problems.append(f"{table.name}: declare it on side_metadata({store.name!r})")
        if not table.name.startswith(prefix) or table.name == store.version_table:
            problems.append(f"{table.name}: name it {prefix}<table>")
        if len(table.name) > _MAX_TABLE_NAME_LENGTH:
            problems.append(f"{table.name}: longer than {_MAX_TABLE_NAME_LENGTH} characters")
        if table.foreign_key_constraints:
            problems.append(f"{table.name}: foreign keys are not allowed; reference ids by value")
        if not table.primary_key.columns:
            problems.append(f"{table.name}: needs an explicit primary key")
        if table.autoincrement_column is not None:
            problems.append(f"{table.name}: auto-increment keys are not allowed")
        # SQLite index names share one namespace with the main schema's.
        problems.extend(
            f"{table.name}: name index {index.name!r} ix_{prefix}<...>"
            for index in table.indexes
            if not (index.name or "").startswith(f"ix_{prefix}")
        )
        problems.extend(
            f"{table.name}.{column.name}: {problem}"
            for column in table.columns
            if (problem := _column_type_problem(column.type)) is not None
        )
    if problems:
        raise RuntimeError(f"Side store {store.name!r} is not valid: " + "; ".join(problems))


def _column_type_problem(column_type: TypeEngine[object]) -> str | None:
    """Name a column type ``docs/DATABASE_BEST_PRACTICES.md`` rules out, if any."""
    if isinstance(column_type, JSON):
        return "native JSON columns are not allowed"
    if isinstance(column_type, Enum):
        return "native enums are not allowed; store integer codes"
    if isinstance(column_type, (String, LargeBinary)) and (
        column_type.length is None or column_type.length > _MAX_DECLARED_LENGTH
    ):
        return f"declare a length of at most {_MAX_DECLARED_LENGTH}"
    return None


# ── Registry ───────────────────────────────────────────

_registry: dict[str, SideStore] = {}


def register_side_store(store: SideStore) -> SideStore:
    """Register *store* so conversation deletes reach its cleanup.

    Call it once, at import time of the feature's store module.

    :raises ValueError: If another store already uses the name.
    """
    existing = _registry.setdefault(store.name, store)
    if existing is not store:
        raise ValueError(f"side store {store.name!r} is already registered")
    return store


# ── Migration ──────────────────────────────────────────

# The stores already at head, per engine.
_migrated: weakref.WeakKeyDictionary[Engine, set[str]] = weakref.WeakKeyDictionary()


def migration_schema() -> str | None:
    """Return the schema to pass to ``op.*`` calls in a side store's revision.

    ``omx_<name>`` on PostgreSQL-family backends and ``None`` elsewhere.
    """
    from alembic import op

    return op.get_context().opts["side_schema"]


def _alembic_config(store: SideStore) -> Config:
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(_ENV_DIRECTORY))
    # One location per line, so a path may hold spaces, commas or colons.
    config.set_main_option("path_separator", "newline")
    config.set_main_option("version_locations", str(store.migrations))
    return config


def _current_revision(connection: Connection, store: SideStore) -> str | None:
    from alembic.runtime.migration import MigrationContext

    schema = store.schema_on(connection.dialect.name)
    if not inspect(connection).has_table(store.version_table, schema=schema):
        return None
    context = MigrationContext.configure(
        connection, opts={"version_table": store.version_table, "version_table_schema": schema}
    )
    return context.get_current_revision()


def _lock_and_create_schema(connection: Connection, store: SideStore) -> None:
    """Serialize concurrent migrations of *store* and make sure its schema exists."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        # Take the write lock before reading the revision; other processes wait.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    elif is_cockroachdb(dialect):
        # No advisory locks: a losing concurrent start fails and is retried.
        version = _crdb_server_version(connection.engine)
        _prepare_crdb_schema_transaction(connection, version)
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{store.schema}"'))
        connection.commit()
        _prepare_crdb_schema_transaction(connection, version)
    elif dialect == "postgresql":
        digest = hashlib.sha256(store.schema.encode()).digest()
        key = int.from_bytes(digest[:8], "big", signed=True)
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        # CREATE SCHEMA needs CREATE on the database even with IF NOT EXISTS,
        # so a schema an operator created beforehand is left alone.
        if not inspect(connection).has_schema(store.schema):
            connection.execute(text(f'CREATE SCHEMA "{store.schema}"'))


def _upgrade_to_head(store: SideStore, engine: Engine) -> None:
    from alembic import command
    from alembic.script import ScriptDirectory
    from alembic.util import CommandError

    config = _alembic_config(store)
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError(f"Side store {store.name!r} has no revisions in {store.migrations}.")

    with engine.connect() as connection:
        if _current_revision(connection, store) == head:
            return
    with engine.connect() as connection:
        _lock_and_create_schema(connection, store)
        current = _current_revision(connection, store)
        if current is not None and current != head:
            try:
                script.get_revision(current)
            except CommandError as exc:
                raise RuntimeError(
                    f"Side store {store.name!r} is at revision {current!r}, which this "
                    f"build does not know (its latest is {head!r}). Upgrade Omnigent, "
                    "or remove the side store as docs/extending/side_schemas.md describes."
                ) from exc
        if current != head:
            _logger.info("Migrating side store %r from %r to %r", store.name, current, head)
            config.attributes["connection"] = connection
            config.attributes["side_store"] = store
            command.upgrade(config, "head")
        if connection.in_transaction():
            connection.commit()


def ensure_side_store(store: SideStore, engine: Engine) -> None:
    """Bring *store* to head on *engine*'s database, once per engine.

    Safe to call from several threads, and from several servers starting at
    once: PostgreSQL serializes them on an advisory lock and SQLite on its
    write lock, with the whole upgrade in one transaction. Other backends
    have neither, so there a failed attempt is retried after checking whether
    another server finished the work.

    :raises RuntimeError: If the store is invalid, newer than this build, or
        its migration fails.
    """
    if store.name in _migrated.get(engine, ()):
        return
    attempts = 1 if engine.dialect.name in _LOCKING_DIALECTS else _UNLOCKED_MIGRATE_ATTEMPTS
    # Alembic's context is process-global, so side migrations take the lock
    # the main migrations run under.
    with _engine_lock:
        if store.name in _migrated.get(engine, ()):
            return
        _validate_tables(store)
        with query_name_scope(f"omnigent.side_store.{store.name}.migrate"):
            for attempt in range(1, attempts + 1):
                try:
                    _upgrade_to_head(store, engine)
                    break
                except RuntimeError:
                    raise
                except Exception as exc:
                    if attempt == attempts:
                        raise RuntimeError(
                            f"Side store {store.name!r} could not be migrated."
                        ) from exc
                    _logger.warning(
                        "Side store %r migration attempt %d failed; retrying",
                        store.name,
                        attempt,
                        exc_info=True,
                    )
                    time.sleep(0.5 * attempt)
        _migrated.setdefault(engine, set()).add(store.name)


def _session_maker(
    store: SideStore, engine: Engine, query_name_prefix: str, *, immediate: bool
) -> NamedManagedSessionMaker:
    ensure_side_store(store, engine)
    if store.schema_on(engine.dialect.name) is None:
        # No schemas here: the declared side schema maps to the default one.
        engine = engine.execution_options(schema_translate_map={store.schema: None})
    return make_named_managed_session_maker(
        engine, query_name_prefix=query_name_prefix, immediate=immediate
    )


# ── Conversation cleanup ───────────────────────────────


def delete_conversation_rows(engine: Engine, conversation_ids: Sequence[str]) -> None:
    """Tell every registered side store that these conversations are gone.

    Runs after the main delete has committed and never raises: a store whose
    cleanup fails is logged and skipped, and keeps its rows.

    :param engine: The main database engine.
    :param conversation_ids: Ids of the deleted conversation and its descendants.
    """
    for store in list(_registry.values()):
        if store.on_conversations_deleted is None:
            continue
        try:
            _run_cleanup(store, store.on_conversations_deleted, engine, conversation_ids)
        except Exception:
            _logger.exception(
                "Side store %r cleanup failed; its rows for %d deleted conversation(s) remain",
                store.name,
                len(conversation_ids),
            )


def _run_cleanup(
    store: SideStore,
    cleanup: ConversationCleanup,
    engine: Engine,
    conversation_ids: Sequence[str],
) -> None:
    sessions = _session_maker(store, engine, f"omnigent.side_store.{store.name}", immediate=True)
    for batch in batched(conversation_ids, _CLEANUP_BATCH_SIZE):
        for _ in range(_MAX_CLEANUP_ROUNDS):
            more = run_write_transaction(
                sessions,
                "delete_conversation_rows",
                lambda session, ids=batch: cleanup(session, ids),
            )
            if not more:
                break
        else:
            _logger.warning(
                "Side store %r cleanup did not finish in %d rounds",
                store.name,
                _MAX_CLEANUP_ROUNDS,
            )
