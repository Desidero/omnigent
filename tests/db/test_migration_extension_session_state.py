"""Tests for the ``extension_session_state`` schema and its migration."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine

from omnigent.db.db_models import (
    EXTENSION_STATE_VALUE_MAX_BYTES,
    SqlExtensionSessionState,
)
from omnigent.db.utils import _build_alembic_config, clear_engine_cache, get_or_create_engine

_TABLE = "extension_session_state"
_INDEX = "ix_extension_session_state_extension"
_REVISION = "dbd0a8305ee3"
_PREVIOUS = "d0a1f879a01d"
_SCHEMA_PATHS = [
    "migration",
    "metadata",
    pytest.param(
        "configured",
        marks=pytest.mark.skipif(
            not os.environ.get("OMNIGENT_TEST_DB_URI"), reason="needs a configured database"
        ),
    ),
]
_state = SqlExtensionSessionState.__table__


@pytest.fixture(params=_SCHEMA_PATHS)
def db_engine(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Engine]:
    """A head-migrated SQLite file, the model-built tables, or the configured database."""
    if request.param == "configured":
        yield get_or_create_engine(request.getfixturevalue("db_uri"))
        return
    uri = f"sqlite:///{tmp_path / 'test.db'}"
    if request.param == "metadata":
        engine = sa.create_engine(uri)
        _state.create(engine)
    else:
        engine = get_or_create_engine(uri)
    try:
        yield engine
    finally:
        engine.dispose()
        clear_engine_cache()


@pytest.fixture
def fresh_engine(tmp_path: Path) -> Iterator[Engine]:
    """A head-migrated database of its own, so a downgrade cannot disturb other tests."""
    root_uri = os.environ.get("OMNIGENT_TEST_DB_URI")
    admin = sa.create_engine(root_uri, isolation_level="AUTOCOMMIT") if root_uri else None
    uri = f"sqlite:///{tmp_path / 'round_trip.db'}"
    name = f"ext_state_{uuid4().hex}"
    engine = None
    database_created = False
    try:
        if admin is not None:
            quoted = admin.dialect.identifier_preparer.quote(name)
            with admin.connect() as conn:
                conn.execute(sa.text(f"CREATE DATABASE {quoted}"))
            database_created = True
            uri = admin.url.set(database=name).render_as_string(hide_password=False)
        engine = get_or_create_engine(uri)
        if engine.dialect.name == "cockroachdb":
            engine = engine.execution_options(isolation_level="SERIALIZABLE")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        clear_engine_cache()
        if admin is not None:
            try:
                if database_created:
                    cascade = " CASCADE" if admin.dialect.name == "cockroachdb" else ""
                    with admin.connect() as conn:
                        conn.execute(sa.text(f"DROP DATABASE {quoted}{cascade}"))
            finally:
                admin.dispose()


def _state_row(workspace_id: int, conversation_id: str, key: str, value: bytes = b"v") -> dict:
    return {
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "extension_id": "acme.pr-watch",
        "key": key,
        "value": value,
        "version": 1,
        "updated_at": 1_700_000_000,
        "updated_by": None,
    }


def _assert_table_shape(engine: Engine) -> None:
    inspector = sa.inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE)}
    assert {name: column["nullable"] for name, column in columns.items()} == {
        "workspace_id": False,
        "conversation_id": False,
        "extension_id": False,
        "key": False,
        "value": False,
        "version": False,
        "updated_at": False,
        "updated_by": True,
    }
    if engine.dialect.name == "mysql":
        # The index leads with extension_id, so its ordering is binary too.
        assert {columns[name]["type"].collation for name in ("extension_id", "key")} == {
            "utf8mb4_bin"
        }
    # New tables declare no database defaults; writers supply every value.
    assert all(column["default"] is None for column in columns.values())
    assert inspector.get_pk_constraint(_TABLE)["constrained_columns"] == [
        "workspace_id",
        "conversation_id",
        "extension_id",
        "key",
    ]
    assert inspector.get_foreign_keys(_TABLE) == []
    assert [
        (index["name"], index["column_names"], bool(index["unique"]))
        for index in inspector.get_indexes(_TABLE)
    ] == [(_INDEX, ["extension_id", "workspace_id", "conversation_id", "key"], False)]
    try:
        checks = inspector.get_check_constraints(_TABLE)
    except NotImplementedError:
        return
    assert [check["name"] for check in checks] == ["ck_extension_session_state_value_size"]


def test_table_shape(db_engine: Engine) -> None:
    _assert_table_shape(db_engine)


def test_value_size_is_capped_below_16_kib(db_engine: Engine) -> None:
    largest = _state_row(0, uuid4().hex, "largest", b"x" * EXTENSION_STATE_VALUE_MAX_BYTES)
    with db_engine.begin() as conn:
        conn.execute(_state.insert().values(largest))
    too_large = _state_row(0, uuid4().hex, "too-large", b"x" * 16384)
    # MySQL reports CHECK violations as OperationalError (3819).
    with pytest.raises((sa.exc.IntegrityError, sa.exc.OperationalError)):
        with db_engine.begin() as conn:
            conn.execute(_state.insert().values(too_large))


def test_keys_compare_case_and_accent_sensitively(db_engine: Engine) -> None:
    session = uuid4().hex
    rows = [_state_row(0, session, key) for key in ("pr.Main", "pr.main", "café", "cafe")]
    rows.append({**_state_row(0, session, "pr.main"), "extension_id": "Acme.pr-watch"})
    with db_engine.begin() as conn:
        conn.execute(_state.insert(), rows)
    with db_engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(_state)).scalar_one() == 5


def _explain(conn: sa.Connection, query: str) -> str:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(sa.text(f"EXPLAIN QUERY PLAN {query}")).all()
        return "\n".join(str(row[-1]) for row in rows)
    if dialect == "mysql":
        rows = conn.execute(sa.text(f"EXPLAIN {query}")).mappings().all()
        return "\n".join(f"{row['type']} {row['key']}" for row in rows)
    if dialect == "postgresql":
        # Tiny test tables favour a sequential scan; check the index can serve.
        conn.execute(sa.text("SET LOCAL enable_seqscan = off"))
    return "\n".join(str(row[0]) for row in conn.execute(sa.text(f"EXPLAIN {query}")).all())


def test_per_extension_lookup_is_an_index_range(db_engine: Engine) -> None:
    rows = [
        {**_state_row(workspace, uuid4().hex, f"k{index}"), "extension_id": extension}
        for extension in ("acme.a", "acme.b", "acme.c")
        for workspace in (0, 7)
        for index in range(40)
    ]
    with db_engine.begin() as conn:
        conn.execute(_state.insert(), rows)
    key = "`key`" if db_engine.dialect.name == "mysql" else "key"
    query = (
        f"SELECT workspace_id, conversation_id, {key} FROM {_TABLE} "
        f"WHERE extension_id = 'acme.b' ORDER BY workspace_id, conversation_id, {key} LIMIT 50"
    )
    with db_engine.begin() as conn:
        plan = _explain(conn, query)

    assert _INDEX in plan, plan
    dialect = db_engine.dialect.name
    if dialect == "sqlite":
        assert "extension_id=?" in plan, plan
    elif dialect == "mysql":
        assert plan.split()[0] in {"ref", "range"}, plan
    elif dialect == "postgresql":
        assert "Index Cond: (extension_id = 'acme.b'::text)" in plan, plan
    else:  # cockroachdb
        assert "spans: [/'acme.b' - /'acme.b']" in plan, plan


def test_migration_round_trips(fresh_engine: Engine) -> None:
    config = _build_alembic_config(fresh_engine.url.render_as_string(hide_password=False))
    with fresh_engine.begin() as conn:
        conn.execute(_state.insert().values(_state_row(0, uuid4().hex, "k")))
    with fresh_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, _PREVIOUS)
    assert _TABLE not in sa.inspect(fresh_engine).get_table_names()
    with fresh_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, _REVISION)
    _assert_table_shape(fresh_engine)
    with fresh_engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(_state)).scalar_one() == 0
