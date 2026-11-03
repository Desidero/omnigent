"""Sweeping ``ext.*`` labels written before core reserved the prefix."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, event, insert, inspect, update

from omnigent.cli import cli
from omnigent.db.db_models import SqlConversationLabel, workspace_scope
from omnigent.db.utils import get_or_create_engine
from omnigent.server.legacy_extension_labels import (
    purge_extension_state,
    sweep_legacy_extension_labels,
)
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

_LEGACY = {
    "ext.legacy",
    "ext.clash",
    "ext.acme.status.other",
    "EXT.Variant",
    "ext.acme.status.status",  # second session: forged, no state
    "ext.acme.status.count",  # third session: state holds another value
}


@dataclass
class _Seeded:
    store: SqlAlchemyConversationStore
    first: str
    second: str
    third: str


def _write_raw_labels(db_uri: str, rows: list[tuple[int, str, str, str]]) -> None:
    """Insert labels as an older server would have, bypassing the store's check."""
    with get_or_create_engine(db_uri).begin() as connection:
        connection.execute(
            insert(SqlConversationLabel.__table__),
            [
                {
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "key": key,
                    "value": value,
                    "updated_at": 1,
                }
                for workspace_id, conversation_id, key, value in rows
            ],
        )


@pytest.fixture
def seeded(db_uri: str) -> _Seeded:
    """Sessions in two workspaces with legacy labels, mirrors and a rename clash."""
    store = SqlAlchemyConversationStore(db_uri)
    first = store.create_conversation(labels={"team": "ml", "ext-clash": "user"})
    store._put_extension_state(
        first.id, "acme.status", "status", b"done", publish=True, max_keys=64
    )
    third = store.create_conversation()
    store._put_extension_state(third.id, "acme.status", "count", b"2", publish=True, max_keys=64)
    with get_or_create_engine(db_uri).begin() as connection:
        connection.execute(
            update(SqlConversationLabel.__table__)
            .where(SqlConversationLabel.__table__.c.key == "ext.acme.status.count")
            .values(value="9")
        )
    with workspace_scope(5):
        second = store.create_conversation()
    _write_raw_labels(
        db_uri,
        [
            (0, first.id, "ext.legacy", "a"),
            (0, first.id, "ext.clash", "b"),
            (0, first.id, "ext.acme.status.other", "c"),
            (0, first.id, "EXT.Variant", "v"),
            (5, second.id, "ext.acme.status.status", "forged"),
        ],
    )
    return _Seeded(store, first.id, second.id, third.id)


def _labels(store: SqlAlchemyConversationStore, conversation_id: str, workspace: int = 0):
    with workspace_scope(workspace):
        conversation = store.get_conversation(conversation_id)
    assert conversation is not None
    return conversation.labels


def test_list_finds_legacy_labels_and_skips_matching_mirrors(db_uri: str, seeded: _Seeded) -> None:
    found: list[str] = []

    report = sweep_legacy_extension_labels(
        get_or_create_engine(db_uri),
        batch_size=2,
        on_found=lambda address: found.append(address[2]),
    )

    assert report.found == len(_LEGACY)
    assert set(found) == _LEGACY
    assert _labels(seeded.store, seeded.first)["ext.legacy"] == "a"


def test_extension_scope_limits_the_sweep(db_uri: str, seeded: _Seeded) -> None:
    report = sweep_legacy_extension_labels(
        get_or_create_engine(db_uri), extension_id="acme.status"
    )

    assert {key for _, _, key in report.examples} == {
        "ext.acme.status.other",
        "ext.acme.status.status",
        "ext.acme.status.count",
    }


def test_rename_moves_labels_and_reports_clashes(db_uri: str, seeded: _Seeded) -> None:
    report = sweep_legacy_extension_labels(
        get_or_create_engine(db_uri), action="rename", batch_size=3
    )

    assert (report.renamed, report.unresolved, report.conflict_count) == (5, 1, 1)
    assert report.conflicts == [(0, seeded.first, "ext.clash")]
    first = _labels(seeded.store, seeded.first)
    assert first["ext-legacy"] == "a"
    assert first["ext-Variant"] == "v"
    assert first["ext-acme.status.other"] == "c"
    assert first["ext-clash"] == "user" and first["ext.clash"] == "b"
    assert first["ext.acme.status.status"] == "done"
    assert _labels(seeded.store, seeded.second, workspace=5) == {
        "ext-acme.status.status": "forged"
    }


def test_delete_removes_every_legacy_label(db_uri: str, seeded: _Seeded) -> None:
    report = sweep_legacy_extension_labels(get_or_create_engine(db_uri), action="delete")

    assert (report.deleted, report.unresolved) == (len(_LEGACY), 0)
    assert _labels(seeded.store, seeded.first) == {
        "team": "ml",
        "ext-clash": "user",
        "ext.acme.status.status": "done",
    }
    assert sweep_legacy_extension_labels(get_or_create_engine(db_uri)).found == 0


def test_cli_lists_everything_and_needs_the_count_to_delete(db_uri: str, seeded: _Seeded) -> None:
    runner = CliRunner()

    dry_run = runner.invoke(cli, ["extensions", "legacy-labels", db_uri, "--delete"])
    both = runner.invoke(cli, ["extensions", "legacy-labels", db_uri, "--rename", "--delete"])
    unconfirmed = runner.invoke(
        cli, ["extensions", "legacy-labels", db_uri, "--delete", "--commit"]
    )
    wrong = runner.invoke(
        cli, ["extensions", "legacy-labels", db_uri, "--delete", "--commit", "--yes", "2"]
    )

    assert dry_run.exit_code == 0, dry_run.output
    assert f"legacy ext. labels: {len(_LEGACY)}" in dry_run.output
    assert all(key in dry_run.output for key in _LEGACY)
    assert "Dry run" in dry_run.output
    for result in (both, unconfirmed, wrong):
        assert result.exit_code != 0
    assert "ext.legacy" in _labels(seeded.store, seeded.first)

    applied = runner.invoke(
        cli,
        [
            "extensions",
            "legacy-labels",
            db_uri,
            "--delete",
            "--commit",
            "--yes",
            str(len(_LEGACY)),
        ],
    )

    assert applied.exit_code == 0, applied.output
    assert "No legacy labels remain" in applied.output
    assert "ext.legacy" not in _labels(seeded.store, seeded.first)


def test_rename_compares_targets_as_the_database_would(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    conv = store.create_conversation(labels={"EXT-foo": "user"})
    mysql = db_uri.startswith("mysql")
    rows = [(0, conv.id, "ext.foo", "a")]
    if not mysql:
        # Both rename onto ``ext-Bar``; MySQL can't even hold the pair.
        rows += [(0, conv.id, "ext.Bar", "b"), (0, conv.id, "EXT.Bar", "c")]
    _write_raw_labels(db_uri, rows)

    report = sweep_legacy_extension_labels(get_or_create_engine(db_uri), action="rename")

    # ``ext-foo`` collides with ``EXT-foo`` only where the collation equates them.
    clashes = {"ext.foo"} if mysql else {"ext.Bar", "EXT.Bar"}
    assert {key for _, _, key in report.conflicts} == clashes
    assert (report.renamed, report.conflict_count) == (len(rows) - len(clashes), len(clashes))
    labels = _labels(store, conv.id)
    assert labels["EXT-foo"] == "user"
    assert ("ext-foo" in labels) is not mysql


def test_sweep_pages_without_row_value_comparisons(db_uri: str, seeded: _Seeded) -> None:
    engine = get_or_create_engine(db_uri)
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        if "FROM conversation_labels" in statement and "ORDER BY" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        sweep_legacy_extension_labels(engine, batch_size=2)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    paged = [statement for statement in statements if " OR " in statement]
    assert paged, statements
    # A row-value comparison ``(a, b, c) > (...)`` can't use MySQL's index.
    assert not any(re.search(r"\)\s*>\s*\(", statement) for statement in statements)


def test_cli_never_creates_tables(tmp_path: Path) -> None:
    missing = tmp_path / "typo.db"
    empty = tmp_path / "empty.db"
    empty.touch()

    for path, message in ((missing, "No database at"), (empty, "no conversation_labels")):
        result = CliRunner().invoke(cli, ["extensions", "legacy-labels", f"sqlite:///{path}"])
        assert result.exit_code != 0
        assert message in result.output
    assert not missing.exists()
    assert inspect(create_engine(f"sqlite:///{empty}")).get_table_names() == []


def test_cli_dry_run_leaves_the_schema_alone(db_uri: str, seeded: _Seeded) -> None:
    def schema() -> list[str]:
        return sorted(inspect(get_or_create_engine(db_uri)).get_table_names())

    before = schema()
    result = CliRunner().invoke(cli, ["extensions", "legacy-labels", db_uri])

    assert result.exit_code == 0, result.output
    assert schema() == before


def test_cli_warns_when_the_database_holds_no_sessions(db_uri: str) -> None:
    SqlAlchemyConversationStore(db_uri)  # tables, but no sessions

    result = CliRunner().invoke(cli, ["extensions", "legacy-labels", db_uri])

    assert result.exit_code == 0, result.output
    assert "holds no sessions" in result.output


def test_include_state_purges_an_uninstalled_extensions_state(
    db_uri: str, seeded: _Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omnigent.extensions import registry

    monkeypatch.setattr(registry, "extension_manifest", lambda _extension_id: None)
    runner = CliRunner()
    other = seeded.store.create_conversation()
    seeded.store._put_extension_state(other.id, "acme.other", "status", b"x", max_keys=64)
    with workspace_scope(5):
        seeded.store._put_extension_state(seeded.second, "acme.status", "k", b"x", max_keys=64)
    base = ["extensions", "legacy-labels", db_uri, "--extension", "acme.status"]

    dry_run = runner.invoke(cli, [*base, "--include-state", "--delete"])
    # State: first's status, third's count, second's k. Labels: first's other
    # and status (a mirror), second's forged status, third's unbacked count.
    assert dry_run.exit_code == 0, dry_run.output
    assert "state rows of acme.status: 3" in dry_run.output
    assert "--yes 7" in dry_run.output
    assert seeded.store.get_extension_state(seeded.first, "acme.status", "status") is not None

    applied = runner.invoke(cli, [*base, "--include-state", "--delete", "--commit", "--yes", "7"])

    assert applied.exit_code == 0, applied.output
    assert seeded.store.get_extension_state(seeded.first, "acme.status", "status") is None
    assert seeded.store.get_extension_state(seeded.third, "acme.status", "count") is None
    with workspace_scope(5):
        assert seeded.store.get_extension_state(seeded.second, "acme.status", "k") is None
    assert not any(
        key.startswith("ext.acme.status.") for key in _labels(seeded.store, seeded.first)
    )
    assert seeded.store.get_extension_state(other.id, "acme.other", "status") is not None


def test_include_state_refuses_an_installed_extension(
    db_uri: str, seeded: _Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omnigent.extensions import registry

    monkeypatch.setattr(registry, "extension_manifest", lambda _extension_id: object())
    args = ["extensions", "legacy-labels", db_uri, "--extension", "acme.status"]

    result = CliRunner().invoke(cli, [*args, "--include-state", "--delete"])

    assert result.exit_code != 0
    assert "uninstall it" in result.output
    assert seeded.store.get_extension_state(seeded.first, "acme.status", "status") is not None


def test_state_purge_walks_the_extension_index(db_uri: str, seeded: _Seeded) -> None:
    engine = get_or_create_engine(db_uri)
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        if "FROM extension_session_state" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert purge_extension_state(engine, "acme.status", batch_size=1) == 2
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert statements and all("extension_session_state.extension_id =" in s for s in statements)
    assert not any(re.search(r"\)\s*>\s*\(", statement) for statement in statements)
