"""Find, rename or delete ``ext.*`` labels written before the namespace was reserved.

Core now writes ``ext.<extension id>.<key>`` labels only as mirrors of
extensions' published state, and refuses every other ``ext.`` write. Labels
users or policies wrote under ``ext.`` earlier stay: hidden under an enabled
extension's prefix, read-only elsewhere. This sweep lets an operator list,
rename or delete them.

It walks ``conversation_labels`` across all workspaces in primary-key order,
one bounded batch per transaction (retried on serialization failures and
deadlocks). It also matches spellings a case- or accent-insensitive collation
equates with ``ext.``. A label backed by an extension state row with the same
value is a mirror and is left alone. Renaming moves ``ext.x`` to ``ext-x`` (no
longer, so it still fits the key column) as a delete and an insert; a session
that already has the target label keeps both, and the report counts it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from sqlalchemy import Table, and_, delete, insert, or_, select, tuple_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from omnigent.db.db_models import SqlConversationLabel, SqlExtensionSessionState
from omnigent.db.utils import make_named_managed_session_maker, run_write_transaction
from omnigent.extensions.state_keys import (
    EXTENSION_LABEL_PREFIX,
    fold_label_key,
    is_extension_label,
    validate_extension_id,
)

LegacyLabelAction = Literal["list", "rename", "delete"]
LabelAddress = tuple[int, str, str]
RENAMED_LABEL_PREFIX = "ext-"
_REPORT_LIMIT = 20
_ENVELOPE_PLAINTEXT_V1 = b"\x01"

_labels = cast(Table, SqlConversationLabel.__table__)
_state = cast(Table, SqlExtensionSessionState.__table__)
_label_pk = (_labels.c.workspace_id, _labels.c.conversation_id, _labels.c.key)


@dataclass
class LegacyLabelReport:
    """What a sweep found and changed.

    :param found: Legacy ``ext.*`` labels (not mirrors of state).
    :param renamed: Labels moved to the ``ext-`` prefix.
    :param deleted: Labels deleted.
    :param conflict_count: Labels left in place because the session already
        has the renamed key.
    :param conflicts: The first 20 of those.
    :param examples: The first 20 legacy labels found.
    """

    found: int = 0
    renamed: int = 0
    deleted: int = 0
    conflict_count: int = 0
    conflicts: list[LabelAddress] = field(default_factory=list)
    examples: list[LabelAddress] = field(default_factory=list)

    @property
    def unresolved(self) -> int:
        """Legacy labels still in place after this sweep."""
        return self.found - self.renamed - self.deleted


def renamed_label_key(key: str) -> str:
    """``ext.x`` (or a variant spelling of ``ext.``) becomes ``ext-x``."""
    rest = key.split(".", 1)[1] if "." in key else fold_label_key(key)[4:]
    return RENAMED_LABEL_PREFIX + rest


def _after(cursor: LabelAddress) -> Any:
    """Rows after ``cursor`` in primary-key order, written out so MySQL uses the index."""
    workspace_id, conversation_id, key = cursor
    return or_(
        _labels.c.workspace_id > workspace_id,
        and_(
            _labels.c.workspace_id == workspace_id,
            or_(
                _labels.c.conversation_id > conversation_id,
                and_(_labels.c.conversation_id == conversation_id, _labels.c.key > key),
            ),
        ),
    )


def _mirrors(session: Session, rows: list[Any]) -> set[LabelAddress]:
    """The labels among ``rows`` that a state row backs with the same value."""
    addresses: dict[tuple[int, str, str, str], Any] = {}
    for row in rows:
        if not row.key.startswith(EXTENSION_LABEL_PREFIX):
            continue
        extension_id, _, key = row.key.removeprefix(EXTENSION_LABEL_PREFIX).rpartition(".")
        if extension_id and key:
            addresses[(row.workspace_id, row.conversation_id, extension_id, key)] = row
    if not addresses:
        return set()
    found = session.execute(
        select(
            _state.c.workspace_id,
            _state.c.conversation_id,
            _state.c.extension_id,
            _state.c.key,
            _state.c.value,
        ).where(
            tuple_(
                _state.c.workspace_id,
                _state.c.conversation_id,
                _state.c.extension_id,
                _state.c.key,
            ).in_(list(addresses))
        )
    ).all()
    mirrors: set[LabelAddress] = set()
    for workspace_id, conversation_id, extension_id, key, stored in found:
        row = addresses[(workspace_id, conversation_id, extension_id, key)]
        if bytes(stored) == _ENVELOPE_PLAINTEXT_V1 + row.value.encode("utf-8"):
            mirrors.add((row.workspace_id, row.conversation_id, row.key))
    return mirrors


def sweep_legacy_extension_labels(
    engine: Engine,
    *,
    action: LegacyLabelAction = "list",
    extension_id: str | None = None,
    batch_size: int = 500,
    on_found: Callable[[LabelAddress], None] | None = None,
    include_mirrors: bool = False,
) -> LegacyLabelReport:
    """Walk every label once and list, rename or delete the legacy ``ext.*`` ones.

    :param engine: The database holding ``conversation_labels`` (the
        conversation database when it is configured separately).
    :param action: ``"list"`` changes nothing.
    :param extension_id: Only labels under ``ext.<extension_id>.`` (and its
        variant spellings).
    :param batch_size: Labels scanned per transaction.
    :param on_found: Called with each legacy label as it is found.
    :param include_mirrors: Also count labels that state backs, for an
        uninstall that purges the state too.
    :returns: What was found and changed.
    """
    scope = fold_label_key(f"{EXTENSION_LABEL_PREFIX}{extension_id}.") if extension_id else None

    def in_scope(key: str) -> bool:
        if scope is not None:
            return fold_label_key(key).startswith(scope)
        return is_extension_label(key)

    sessions = make_named_managed_session_maker(
        engine, query_name_prefix="omnigent.legacy_extension_labels"
    )
    report = LegacyLabelReport()
    cursor: LabelAddress | None = None

    def sweep_batch(session: Session) -> _Batch:
        statement = select(*_label_pk, _labels.c.value, _labels.c.updated_at)
        if cursor is not None:
            statement = statement.where(_after(cursor))
        rows = session.execute(statement.order_by(*_label_pk).limit(batch_size)).all()
        if not rows:
            return _Batch(cursor=None)
        candidates = [row for row in rows if in_scope(row.key)]
        mirrors = set() if include_mirrors else _mirrors(session, candidates)
        legacy = [row for row in candidates if tuple(row[:3]) not in mirrors]
        batch = _Batch(
            cursor=tuple(rows[-1][:3]),
            legacy=[(row.workspace_id, row.conversation_id, row.key) for row in legacy],
        )
        if action == "rename" and legacy:
            batch.renamed, batch.conflicts = _rename(session, legacy)
        elif action == "delete" and legacy:
            _delete(session, batch.legacy)
            batch.deleted = len(legacy)
        return batch

    while True:
        # Counts are applied only after a batch commits, so a retried batch
        # never counts twice.
        batch = run_write_transaction(sessions, "sweep_batch", sweep_batch)
        if batch.cursor is None:
            return report
        cursor = batch.cursor
        report.found += len(batch.legacy)
        report.renamed += batch.renamed
        report.deleted += batch.deleted
        report.conflict_count += len(batch.conflicts)
        room = _REPORT_LIMIT - len(report.conflicts)
        report.conflicts.extend(batch.conflicts[: max(room, 0)])
        for address in batch.legacy:
            if len(report.examples) < _REPORT_LIMIT:
                report.examples.append(address)
            if on_found is not None:
                on_found(address)


@dataclass
class _Batch:
    cursor: LabelAddress | None
    legacy: list[LabelAddress] = field(default_factory=list)
    renamed: int = 0
    deleted: int = 0
    conflicts: list[LabelAddress] = field(default_factory=list)


def _delete(session: Session, keys: list[LabelAddress]) -> None:
    session.execute(delete(_labels).where(tuple_(*_label_pk).in_(keys)))


def _rename(session: Session, legacy: list[Any]) -> tuple[int, list[LabelAddress]]:
    """Move labels to the ``ext-`` prefix; returns the count and the clashes left in place.

    Two labels renaming onto the same folded key are clashes. Existing targets
    are looked up by exact key, which a case- or accent-insensitive collation
    (MySQL) answers with any spelling it treats as equal; that is the only
    database where another spelling would collide. Clashes stay where they are.
    """
    by_target: dict[tuple[int, str, str], list[Any]] = {}
    for row in legacy:
        folded = fold_label_key(renamed_label_key(row.key))
        by_target.setdefault((row.workspace_id, row.conversation_id, folded), []).append(row)
    exact_targets = sorted(
        {(row.workspace_id, row.conversation_id, renamed_label_key(row.key)) for row in legacy}
    )
    taken = {
        (workspace_id, conversation_id, fold_label_key(key))
        for workspace_id, conversation_id, key in session.execute(
            select(*_label_pk).where(tuple_(*_label_pk).in_(exact_targets))
        ).all()
    }
    moves: list[tuple[LabelAddress, Any]] = []
    conflicts: list[LabelAddress] = []
    for target, rows in by_target.items():
        if len(rows) > 1 or target in taken:
            conflicts.extend((row.workspace_id, row.conversation_id, row.key) for row in rows)
            continue
        row = rows[0]
        moves.append(((row.workspace_id, row.conversation_id, renamed_label_key(row.key)), row))
    if moves:
        _delete(session, [tuple(row[:3]) for _, row in moves])
        session.execute(
            insert(_labels),
            [
                {
                    "workspace_id": target[0],
                    "conversation_id": target[1],
                    "key": target[2],
                    "value": row.value,
                    "updated_at": row.updated_at,
                }
                for target, row in moves
            ],
        )
    return len(moves), conflicts


def _after_state(cursor: LabelAddress) -> Any:
    """State rows after ``cursor`` within one extension, in index order."""
    workspace_id, conversation_id, key = cursor
    return or_(
        _state.c.workspace_id > workspace_id,
        and_(
            _state.c.workspace_id == workspace_id,
            or_(
                _state.c.conversation_id > conversation_id,
                and_(_state.c.conversation_id == conversation_id, _state.c.key > key),
            ),
        ),
    )


def purge_extension_state(
    engine: Engine,
    extension_id: str,
    *,
    remove: bool = False,
    batch_size: int = 500,
) -> int:
    """Count, or delete, one extension's state rows in every session and workspace.

    Walks ``ix_extension_session_state_extension`` (extension id, then the
    primary key) in bounded batches, one transaction each. Meant for an
    uninstalled extension; its mirror labels are then unbacked, and
    :func:`sweep_legacy_extension_labels` removes them.

    :param engine: The database holding ``extension_session_state``.
    :param extension_id: The extension whose state goes.
    :param remove: ``False`` only counts.
    :param batch_size: Rows per transaction.
    :returns: How many rows were found (and deleted, with ``remove``).
    """
    validate_extension_id(extension_id)
    sessions = make_named_managed_session_maker(
        engine, query_name_prefix="omnigent.legacy_extension_labels"
    )
    pk = (_state.c.workspace_id, _state.c.conversation_id, _state.c.key)
    cursor: LabelAddress | None = None
    total = 0

    def purge_batch(session: Session) -> list[LabelAddress]:
        statement = select(*pk).where(_state.c.extension_id == extension_id)
        if cursor is not None:
            statement = statement.where(_after_state(cursor))
        rows = [tuple(row) for row in session.execute(statement.order_by(*pk).limit(batch_size))]
        if remove and rows:
            session.execute(
                delete(_state).where(_state.c.extension_id == extension_id, tuple_(*pk).in_(rows))
            )
        return rows

    while True:
        rows = run_write_transaction(sessions, "purge_extension_state_batch", purge_batch)
        if not rows:
            return total
        total += len(rows)
        cursor = rows[-1]
