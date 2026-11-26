"""Side stores keep their tables and migration lineage apart from the main schema."""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from omnigent.db import side_schemas
from omnigent.db.db_models import ConversationBase, OmnigentBase, Uuid16
from omnigent.db.side_schemas import SideStore, side_metadata
from omnigent.db.utils import (
    _create_engine,
    _get_current_db_revision,
    _get_head_db_revision,
    _initialize_or_verify_schema,
    _run_migrations,
    get_or_create_engine,
)
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests._helpers.live_server import terminate_process
from tests._helpers.polling import poll_until
from tests.db.side_store_toy import (
    MIGRATION_DELAY_ENV,
    REVISIONS,
    add_note,
    delete_notes,
    make_toy_store,
    note_bodies,
)

_SIDE_TABLES = {"toy_notes", "toy_alembic_version"}


def _restart() -> None:
    """Forget which stores this process migrated, as a restarted server has."""
    side_schemas._migrated.clear()


def _qualified(engine: Engine, store: SideStore, table: str) -> str:
    schema = store.schema_on(engine.dialect.name)
    return f'"{schema}".{table}' if schema else table


def _remove(engine: Engine, store: SideStore) -> None:
    """Remove a side store with the statements docs/extending/side_schemas.md gives."""
    schema = store.schema_on(engine.dialect.name)
    statements = (
        [f'DROP SCHEMA IF EXISTS "{schema}" CASCADE']
        if schema
        else [f"DROP TABLE IF EXISTS {table}" for table in sorted(_SIDE_TABLES)]
    )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(text(statement))


def _side_revision(engine: Engine, store: SideStore) -> str | None:
    with engine.connect() as connection:
        return side_schemas._current_revision(connection, store)


def _start_build_without_side_stores(db_uri: str) -> None:
    """Run the main bootstrap and upgrade exactly as a build without side stores does."""
    engine = _create_engine(db_uri)
    try:
        _initialize_or_verify_schema(engine, db_uri)  # server start
        _run_migrations(engine, db_uri)  # `omnigent debug db-upgrade`
        assert _get_current_db_revision(engine) == _get_head_db_revision(db_uri)
    finally:
        engine.dispose()


@pytest.fixture()
def toy(db_uri: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[SideStore]:
    """The toy store, registered for this test and removed from the database after it."""
    store = make_toy_store()
    monkeypatch.setattr(side_schemas, "_registry", {store.name: store})
    yield store
    _restart()
    _remove(get_or_create_engine(db_uri), store)


@pytest.fixture()
def conversations(db_uri: str) -> SqlAlchemyConversationStore:
    return SqlAlchemyConversationStore(db_uri)


# ── Naming and lineage ─────────────────────────────────


def test_first_use_creates_the_store_apart_from_the_main_schema(
    db_uri: str, toy: SideStore
) -> None:
    add_note(db_uri, uuid.uuid4().hex, "first")
    assert note_bodies(db_uri) == ["first"]

    engine = get_or_create_engine(db_uri)
    inspector = inspect(engine)
    schema = toy.schema_on(engine.dialect.name)
    if schema is None:
        assert set(inspector.get_table_names()) >= _SIDE_TABLES
    else:
        assert schema == "omx_toy"
        assert set(inspector.get_table_names(schema=schema)) == _SIDE_TABLES
        assert not _SIDE_TABLES & set(inspector.get_table_names())
    assert _side_revision(engine, toy) == "toy0002"
    assert _get_current_db_revision(engine) == _get_head_db_revision(db_uri)


def test_a_newer_build_upgrades_from_the_first_revision(
    db_uri: str, toy: SideStore, tmp_path: Path
) -> None:
    first_only = tmp_path / "revisions"
    first_only.mkdir()
    shutil.copy(REVISIONS / "toy0001_create_notes.py", first_only)
    engine = get_or_create_engine(db_uri)
    side_schemas.ensure_side_store(make_toy_store(migrations=first_only), engine)
    assert _side_revision(engine, toy) == "toy0001"
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {_qualified(engine, toy, 'toy_notes')} "
                "(workspace_id, conversation_id, note_id, body) "
                "VALUES (0, :conversation, :note, :body)"
            ),
            {"conversation": uuid.uuid4().bytes, "note": uuid.uuid4().bytes, "body": "kept"},
        )

    _restart()

    assert note_bodies(db_uri) == ["kept"]
    assert _side_revision(engine, toy) == "toy0002"


def test_repeated_and_restarted_use_does_not_migrate_again(
    db_uri: str, toy: SideStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_note(db_uri, uuid.uuid4().hex, "one")
    upgrades: list[object] = []
    monkeypatch.setattr("alembic.command.upgrade", lambda *args, **kwargs: upgrades.append(args))

    add_note(db_uri, uuid.uuid4().hex, "two")
    _restart()
    add_note(db_uri, uuid.uuid4().hex, "three")

    assert upgrades == []
    assert note_bodies(db_uri) == ["one", "three", "two"]


def test_two_servers_starting_together_migrate_once(
    db_uri: str, toy: SideStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The first server holds its migration open, so the second starts inside it:
    # it waits on the lock, or on CockroachDB fails, checks again and retries.
    monkeypatch.setenv(MIGRATION_DELAY_ENV, "1")
    bodies = ["server-0", "server-1"]
    servers = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.db.side_store_toy",
                db_uri,
                tmp_path,
                uuid.uuid4().hex,
                body,
            ],
            cwd=Path(__file__).parents[2],
        )
        for body in bodies
    ]
    try:
        poll_until(
            lambda: (
                all((tmp_path / f"ready-{body}").exists() for body in bodies)
                or any(server.poll() is not None for server in servers)
            ),
            timeout_s=60,
            interval_s=0.05,
        )
        (tmp_path / "go").touch()
        assert [server.wait(timeout=120) for server in servers] == [0, 0]
    finally:
        for server in servers:
            terminate_process(server)

    assert note_bodies(db_uri) == bodies
    assert _side_revision(get_or_create_engine(db_uri), toy) == "toy0002"


def test_a_failed_upgrade_leaves_nothing_behind_and_can_be_retried(
    db_uri: str, toy: SideStore, tmp_path: Path
) -> None:
    engine = get_or_create_engine(db_uri)
    if engine.dialect.name not in ("postgresql", "sqlite"):
        pytest.skip("this backend commits each DDL statement on its own")
    broken = tmp_path / "revisions"
    shutil.copytree(REVISIONS, broken)
    (broken / "toy0003_fails.py").write_text(
        "revision = 'toy0003'\ndown_revision = 'toy0002'\n\n\n"
        "def upgrade() -> None:\n    raise OSError('revision failed')\n"
    )

    with pytest.raises(RuntimeError, match="could not be migrated"):
        side_schemas.ensure_side_store(make_toy_store(migrations=broken), engine)

    assert _side_revision(engine, toy) is None
    assert "toy_notes" not in inspect(engine).get_table_names(
        schema=toy.schema_on(engine.dialect.name)
    )
    add_note(db_uri, uuid.uuid4().hex, "after the fix")
    assert note_bodies(db_uri) == ["after the fix"]


# ── The main lineage never sees a side store ───────────


def test_a_build_without_side_stores_starts_and_upgrades(
    db_uri: str, toy: SideStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_note(db_uri, uuid.uuid4().hex, "kept")
    monkeypatch.setattr(side_schemas, "_registry", {})

    _start_build_without_side_stores(db_uri)

    assert note_bodies(db_uri) == ["kept"]


def test_a_side_revision_from_a_newer_build_stops_only_that_store(
    db_uri: str, toy: SideStore
) -> None:
    add_note(db_uri, uuid.uuid4().hex, "kept")
    engine = get_or_create_engine(db_uri)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {_qualified(engine, toy, 'toy_alembic_version')} "
                "SET version_num = 'toy9999'"
            )
        )
    _restart()

    _start_build_without_side_stores(db_uri)
    with pytest.raises(RuntimeError, match="'toy9999', which this build does not know"):
        note_bodies(db_uri)


def test_a_removed_side_store_leaves_the_main_schema_and_can_return(
    db_uri: str, toy: SideStore
) -> None:
    add_note(db_uri, uuid.uuid4().hex, "gone")
    _remove(get_or_create_engine(db_uri), toy)
    _restart()

    _start_build_without_side_stores(db_uri)
    assert note_bodies(db_uri) == []


def _proposed_table_changes(engine: Engine) -> set[tuple[str, str]]:
    """The tables autogenerate would add to or drop from the main lineage."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as connection:
        differences = compare_metadata(
            MigrationContext.configure(connection),
            [OmnigentBase.metadata, ConversationBase.metadata],
        )
    return {
        (difference[0], difference[1].name)
        for difference in differences
        if isinstance(difference, tuple) and difference[0] in ("add_table", "remove_table")
    }


def test_main_autogenerate_sees_side_tables_only_where_schemas_are_missing(
    db_uri: str, toy: SideStore
) -> None:
    engine = get_or_create_engine(db_uri)
    before = _proposed_table_changes(engine)
    add_note(db_uri, uuid.uuid4().hex, "first")

    proposed = _proposed_table_changes(engine) - before

    if toy.schema_on(engine.dialect.name) is None:
        # Nothing hides the tables here: leave these out of an autogenerated revision.
        assert proposed == {("remove_table", table) for table in _SIDE_TABLES}
    else:
        assert proposed == set()


# ── Rules a store must follow ──────────────────────────


@pytest.mark.parametrize("name", ["Toy", "toy-notes", "toy__notes", "_toy", "9toy", "t" * 25])
def test_names_that_cannot_prefix_tables_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="side store name"):
        side_metadata(name)


@pytest.mark.parametrize(
    ("define", "problem"),
    [
        (
            lambda m: sa.Table("notes", m, sa.Column("id", Uuid16(), primary_key=True)),
            "bad_<table>",
        ),
        (
            lambda m: sa.Table(
                "bad_notes", m, sa.Column("id", Uuid16(), primary_key=True), schema=sa.BLANK_SCHEMA
            ),
            r"side_metadata\('bad'\)",
        ),
        (
            lambda m: sa.Table(
                "bad_notes",
                m,
                sa.Column("id", Uuid16(), primary_key=True),
                sa.Column("conversation_id", Uuid16(), sa.ForeignKey("conversations.id")),
            ),
            "foreign keys are not allowed",
        ),
        (
            lambda m: sa.Table("bad_notes", m, sa.Column("body", sa.String(8))),
            "explicit primary key",
        ),
        (
            lambda m: sa.Table("bad_notes", m, sa.Column("id", sa.Integer, primary_key=True)),
            "auto-increment keys are not allowed",
        ),
        (
            lambda m: sa.Table(
                "bad_notes",
                m,
                sa.Column("id", Uuid16(), primary_key=True),
                sa.Column("data", sa.JSON),
            ),
            "native JSON columns are not allowed",
        ),
        (
            lambda m: sa.Table(
                "bad_notes",
                m,
                sa.Column("id", Uuid16(), primary_key=True),
                sa.Column("kind", sa.Enum("a", "b", name="bad_kind")),
            ),
            "native enums are not allowed",
        ),
        (
            lambda m: sa.Table(
                "bad_notes",
                m,
                sa.Column("id", Uuid16(), primary_key=True),
                sa.Column("body", sa.Text),
            ),
            "declare a length of at most 16383",
        ),
        (
            lambda m: sa.Table(
                "bad_notes",
                m,
                sa.Column("id", Uuid16(), primary_key=True),
                sa.Column("body", sa.String(64)),
                sa.Index("ix_notes_body", "body"),
            ),
            "name index 'ix_notes_body' ix_bad_",
        ),
    ],
)
def test_tables_that_break_the_rules_are_refused(
    define: Callable[[sa.MetaData], object], problem: str
) -> None:
    metadata = side_metadata("bad")
    define(metadata)
    with pytest.raises(RuntimeError, match=problem):
        side_schemas._validate_tables(SideStore("bad", metadata, REVISIONS))


def test_a_name_the_main_schema_already_prefixes_is_refused() -> None:
    store = SideStore("conversation", side_metadata("conversation"), REVISIONS)
    with pytest.raises(RuntimeError, match="already uses the prefix 'conversation_'"):
        side_schemas._validate_tables(store)


def test_a_name_is_registered_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(side_schemas, "_registry", {})
    store = make_toy_store()
    assert side_schemas.register_side_store(store) is store
    assert side_schemas.register_side_store(store) is store
    with pytest.raises(ValueError, match="already registered"):
        side_schemas.register_side_store(make_toy_store(cleanup=None))


# ── Cleanup when a conversation is deleted ─────────────


@pytest.mark.asyncio
async def test_deleting_a_conversation_cleans_its_subtree_in_batches(
    db_uri: str,
    toy: SideStore,
    conversations: SqlAlchemyConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = conversations.create_conversation()
    child = conversations.create_conversation(kind="sub_agent", parent_conversation_id=parent.id)
    other = conversations.create_conversation()
    for conversation, body in ((parent, "parent"), (child, "child"), (other, "other")):
        add_note(db_uri, conversation.id, body)
    batches: list[tuple[str, ...]] = []
    more_rows = iter([True, False, False])

    def cleanup(session: Session, conversation_ids: Sequence[str]) -> bool:
        batches.append(tuple(conversation_ids))
        delete_notes(session, conversation_ids)
        return next(more_rows)

    monkeypatch.setattr(side_schemas, "_registry", {"toy": make_toy_store(cleanup=cleanup)})
    monkeypatch.setattr(side_schemas, "_CLEANUP_BATCH_SIZE", 1)

    assert await conversations.delete_conversation(parent.id) is True

    assert note_bodies(db_uri) == ["other"]
    # One id per transaction, and the first batch again because it reported more rows.
    assert len(batches) == 3
    assert batches[0] == batches[1]
    assert {batch[0] for batch in batches} == {parent.id, child.id}


@pytest.mark.asyncio
async def test_a_failing_side_store_does_not_fail_the_delete(
    db_uri: str,
    toy: SideStore,
    conversations: SqlAlchemyConversationStore,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = conversations.create_conversation()
    second = conversations.create_conversation()
    add_note(db_uri, first.id, "first")
    add_note(db_uri, second.id, "second")

    def refuse(session: Session, conversation_ids: Sequence[str]) -> None:
        raise OSError("side store is broken")

    # A store whose migration fails is skipped and the next store still runs.
    without_revisions = SideStore("empty", side_metadata("empty"), tmp_path, refuse)
    monkeypatch.setattr(side_schemas, "_registry", {"empty": without_revisions, "toy": toy})
    assert await conversations.delete_conversation(first.id) is True
    assert note_bodies(db_uri) == ["second"]
    assert "Side store 'empty' cleanup failed" in caplog.text

    # A store whose cleanup raises keeps its rows; the conversation is gone all the same.
    monkeypatch.setattr(side_schemas, "_registry", {"toy": make_toy_store(cleanup=refuse)})
    assert await conversations.delete_conversation(second.id) is True
    assert conversations.get_conversation(second.id) is None
    assert note_bodies(db_uri) == ["second"]
    assert "Side store 'toy' cleanup failed" in caplog.text


@pytest.mark.asyncio
async def test_a_failed_delete_keeps_side_rows(
    db_uri: str,
    toy: SideStore,
    conversations: SqlAlchemyConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = conversations.create_conversation()
    add_note(db_uri, conversation.id, "kept")

    def fail(*args: object) -> None:
        raise OSError("main delete failed")

    monkeypatch.setattr(
        "omnigent.stores.conversation_store.sqlalchemy_store.delete_fts_by_conversation_ids", fail
    )
    with pytest.raises(OSError, match="main delete failed"):
        await conversations.delete_conversation(conversation.id)

    assert conversations.get_conversation(conversation.id) is not None
    assert note_bodies(db_uri) == ["kept"]
