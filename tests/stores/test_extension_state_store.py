"""Store contract for extension session state and its mirrored labels."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import event, insert, select, update

from omnigent.db.db_models import (
    SqlConversationLabel,
    SqlExtensionSessionState,
    workspace_scope,
)
from omnigent.stores.conversation_store import (
    ConversationNotFoundError,
    ExtensionStateConflictError,
    ExtensionStateFormatError,
    ExtensionStateQuotaError,
)
from omnigent.stores.conversation_store import sqlalchemy_store as store_module
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

_EXT = "acme.watch"
_LABEL = "ext.acme.watch.status"
_MAX_PAYLOAD = 16_382


def _put(store: SqlAlchemyConversationStore, conv_id: str, key: str, value: bytes, **kwargs: Any):
    kwargs.setdefault("max_keys", 64)
    return store._put_extension_state(conv_id, _EXT, key, value, **kwargs)


def _write_raw_label(
    store: SqlAlchemyConversationStore, conv_id: str, key: str, value: str
) -> None:
    """Write a label as an older server could have, bypassing the store's checks."""
    with store._conv_engine.begin() as connection:
        connection.execute(
            insert(SqlConversationLabel.__table__).values(
                workspace_id=0, conversation_id=conv_id, key=key, value=value, updated_at=1
            )
        )


def _raw_label_keys(store: SqlAlchemyConversationStore, conv_id: str) -> set[str]:
    with store._conv_engine.connect() as connection:
        return set(
            connection.execute(
                select(SqlConversationLabel.key).where(
                    SqlConversationLabel.conversation_id == conv_id
                )
            ).scalars()
        )


def _labels(store: SqlAlchemyConversationStore, conv_id: str) -> dict[str, str]:
    conv = store.get_conversation(conv_id)
    assert conv is not None
    return dict(conv.labels)


def _run_concurrently(calls: list[Callable[[], object]]) -> list[object]:
    """Start every call together and return each result or raised exception."""
    barrier = threading.Barrier(len(calls))
    results: list[object] = [None] * len(calls)

    def run(index: int) -> None:
        barrier.wait()
        try:
            results[index] = calls[index]()
        except Exception as exc:
            results[index] = exc

    threads = [threading.Thread(target=run, args=(index,)) for index in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def test_put_get_and_update_track_versions(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()

    first = _put(conversation_store, conv.id, "pr:1", b"\x00\xffwatch", updated_by="u1")
    second = _put(conversation_store, conv.id, "pr:1", b"stop")

    assert (first.version, first.updated_by) == (1, "u1")
    stored = conversation_store.get_extension_state(conv.id, _EXT, "pr:1")
    assert stored is not None
    assert (stored.value, stored.version, stored.updated_by) == (b"stop", 2, None)
    assert second.version == 2
    assert conversation_store.get_extension_state(conv.id, _EXT, "missing") is None


def test_compare_and_set_rejects_stale_versions(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "k", b"a", expected_version=0)

    with pytest.raises(ExtensionStateConflictError) as conflict:
        _put(conversation_store, conv.id, "k", b"b", expected_version=0)
    assert conflict.value.current_version == 1
    with pytest.raises(ExtensionStateConflictError):
        _put(conversation_store, conv.id, "k", b"b", expected_version=2)
    with pytest.raises(ExtensionStateConflictError):
        conversation_store._delete_extension_state(conv.id, _EXT, "k", expected_version=5)

    assert _put(conversation_store, conv.id, "k", b"b", expected_version=1).version == 2
    assert conversation_store._delete_extension_state(conv.id, _EXT, "k", expected_version=2)
    assert not conversation_store._delete_extension_state(conv.id, _EXT, "k")


def test_value_byte_limit_includes_the_envelope(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    # Multibyte text: the limit counts bytes, not characters.
    largest = ("é" * (_MAX_PAYLOAD // 2)).encode()
    assert len(largest) == _MAX_PAYLOAD

    _put(conversation_store, conv.id, "big", largest)
    stored = conversation_store.get_extension_state(conv.id, _EXT, "big")
    assert stored is not None and stored.value == largest
    with pytest.raises(ValueError, match="16382"):
        _put(conversation_store, conv.id, "big", largest + b"x")
    with pytest.raises(TypeError):
        _put(conversation_store, conv.id, "big", "text")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("extension_id", "key"),
    [
        (_EXT, "status "),
        (_EXT, ""),
        (_EXT, "a" * 129),
        (_EXT, "two words"),
        ("Acme.Watch", "status"),
        ("acme", "status"),
    ],
)
def test_rejects_invalid_addressing(
    conversation_store: SqlAlchemyConversationStore, extension_id: str, key: str
) -> None:
    conv = conversation_store.create_conversation()

    with pytest.raises(ValueError, match="invalid"):
        conversation_store._put_extension_state(conv.id, extension_id, key, b"x", max_keys=64)


def test_write_to_missing_session_fails(conversation_store: SqlAlchemyConversationStore) -> None:
    with pytest.raises(ConversationNotFoundError):
        _put(conversation_store, "conv_" + "0" * 32, "k", b"x")


def test_quota_counts_keys_not_writes(conversation_store: SqlAlchemyConversationStore) -> None:
    conv = conversation_store.create_conversation()
    for index in range(3):
        _put(conversation_store, conv.id, f"k{index}", b"x", max_keys=3)

    with pytest.raises(ExtensionStateQuotaError):
        _put(conversation_store, conv.id, "k3", b"x", max_keys=3)
    _put(conversation_store, conv.id, "k0", b"updated", max_keys=3)
    other = conversation_store._put_extension_state(conv.id, "acme.other", "k3", b"x", max_keys=3)
    assert other.version == 1
    conversation_store._delete_extension_state(conv.id, _EXT, "k1")
    _put(conversation_store, conv.id, "k3", b"x", max_keys=3)


def test_list_pages_by_key(conversation_store: SqlAlchemyConversationStore) -> None:
    conv = conversation_store.create_conversation()
    for key in ("c", "a", "e", "b", "d"):
        _put(conversation_store, conv.id, key, key.encode())
    conversation_store._put_extension_state(conv.id, "acme.other", "z", b"z", max_keys=64)

    keys: list[str] = []
    cursor = None
    pages = 0
    while True:
        page, cursor = conversation_store.list_extension_state(
            conv.id, _EXT, after=cursor, limit=2
        )
        keys.extend(entry.key for entry in page)
        pages += 1
        if cursor is None:
            break

    assert keys == ["a", "b", "c", "d", "e"]
    assert pages == 3
    with pytest.raises(ValueError, match="limit"):
        conversation_store.list_extension_state(conv.id, _EXT, limit=101)


def test_workspaces_are_isolated(conversation_store: SqlAlchemyConversationStore) -> None:
    with workspace_scope(7):
        conv = conversation_store.create_conversation()
        _put(conversation_store, conv.id, "k", b"seven")

    with workspace_scope(8):
        assert conversation_store.get_extension_state(conv.id, _EXT, "k") is None
        assert conversation_store.list_extension_state(conv.id, _EXT) == ([], None)
        with pytest.raises(ConversationNotFoundError):
            _put(conversation_store, conv.id, "k", b"eight")
    with workspace_scope(7):
        stored = conversation_store.get_extension_state(conv.id, _EXT, "k")
        assert stored is not None and stored.value == b"seven"


def _walk_sessions(
    store: SqlAlchemyConversationStore, *, limit: int, key_prefix: str | None = None
) -> list[list[tuple[int, str]]]:
    """Every page in order; fails instead of looping if the cursor stops advancing."""
    pages: list[list[tuple[int, str]]] = []
    for _ in range(100):
        page = store.list_extension_state_sessions(
            _EXT, key_prefix=key_prefix, after=pages[-1][-1] if pages else None, limit=limit
        )
        if not page:
            return pages
        assert not pages or page[0] > pages[-1][-1], "the cursor did not advance"
        pages.append(page)
    raise AssertionError("paging did not finish within 100 pages")


def _seed_dense_sessions(
    store: SqlAlchemyConversationStore, sessions: int, keys: int
) -> list[tuple[int, str]]:
    """Insert state rows directly: ``sessions`` sessions of ``keys`` keys each."""
    ids = sorted(uuid.uuid4().hex for _ in range(sessions))
    rows = [
        {
            "workspace_id": 0,
            "conversation_id": conv_id,
            "extension_id": _EXT,
            "key": f"k{index:02d}",
            "value": b"\x01v",
            "version": 1,
            "updated_at": 1,
            "updated_by": None,
        }
        for conv_id in ids
        for index in range(keys)
    ]
    with store._conv_engine.begin() as connection:
        connection.execute(insert(SqlExtensionSessionState.__table__), rows)
    return [(0, conv_id) for conv_id in ids]


@pytest.mark.parametrize("keys", [2, 13, 64])
def test_a_page_of_dense_sessions_takes_two_reads(
    conversation_store: SqlAlchemyConversationStore, keys: int
) -> None:
    holders = _seed_dense_sessions(conversation_store, 45, keys)
    statements: list[str] = []

    def capture(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if "extension_session_state" in statement:
            statements.append(statement)

    pages: list[list[tuple[int, str]]] = []
    reads: list[int] = []
    event.listen(conversation_store._conv_engine, "before_cursor_execute", capture)
    try:
        for _ in range(3):
            before = len(statements)
            pages.append(
                conversation_store.list_extension_state_sessions(
                    _EXT, after=pages[-1][-1] if pages else None, limit=20
                )
            )
            reads.append(len(statements) - before)
    finally:
        event.remove(conversation_store._conv_engine, "before_cursor_execute", capture)

    assert [pair for page in pages for pair in page] == holders
    # Full pages take at most two reads; the last also finds the end.
    assert reads[0] <= 2 and reads[1] <= 2 and reads[2] <= 3, reads


def test_sessions_with_state_page_across_workspaces(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    holders: list[tuple[int, str]] = []
    for workspace_id in (8, 7):
        with workspace_scope(workspace_id):
            for key in ("goal.a", "goal.b", "other"):
                conv = conversation_store.create_conversation()
                _put(conversation_store, conv.id, key, b"v")
                if key == "goal.a":
                    # Two matching keys still list the session once.
                    _put(conversation_store, conv.id, "goal.c", b"v")
                if key.startswith("goal"):
                    holders.append((workspace_id, conv.id))
            conversation_store._put_extension_state(
                conversation_store.create_conversation().id, "acme.other", "goal", b"v", max_keys=1
            )

    found = [
        pair
        for page in _walk_sessions(conversation_store, limit=1, key_prefix="goal")
        for pair in page
    ]

    assert found == sorted(holders)
    assert len(conversation_store.list_extension_state_sessions(_EXT)) == 6
    with pytest.raises(ValueError, match="limit"):
        conversation_store.list_extension_state_sessions(_EXT, limit=0)


@pytest.mark.parametrize("limit", [1, 2, 3, 7])
def test_sessions_with_many_keys_page_exactly(
    conversation_store: SqlAlchemyConversationStore, limit: int
) -> None:
    holders: list[tuple[int, str]] = []
    for workspace_id, key_counts in ((4, (64, 1, 3)), (5, (2, 64)), (6, (1,))):
        with workspace_scope(workspace_id):
            for count in key_counts:
                conv_id = conversation_store.create_conversation().id
                for index in range(count):
                    _put(conversation_store, conv_id, f"k{index:02d}", b"v")
                holders.append((workspace_id, conv_id))

    pages = _walk_sessions(conversation_store, limit=limit)

    assert [pair for page in pages for pair in page] == sorted(holders)
    assert all(len(page) == limit for page in pages[:-1])


def test_sessions_with_state_reads_index_ranges(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    """Each page is at most two range reads on the extension's rows: no OR, no DISTINCT."""
    with workspace_scope(3):
        conv = conversation_store.create_conversation()
        _put(conversation_store, conv.id, "goal", b"v")
    statements: list[str] = []

    def capture(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if "extension_session_state" in statement:
            statements.append(" ".join(statement.split()))

    event.listen(conversation_store._conv_engine, "before_cursor_execute", capture)
    try:
        page = conversation_store.list_extension_state_sessions(_EXT, after=(3, "0" * 32), limit=5)
    finally:
        event.remove(conversation_store._conv_engine, "before_cursor_execute", capture)

    assert page == [(3, conv.id)]
    assert 1 <= len(statements) <= 2
    for statement in statements:
        assert " OR " not in statement.upper()
        # CockroachDB reads the extension's whole span under DISTINCT ... LIMIT.
        assert "DISTINCT" not in statement.upper()
        assert "extension_session_state.extension_id = " in statement
        assert "LIMIT" in statement.upper()


def test_published_value_is_mirrored_as_a_label(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation(labels={"team": "ml"})

    _put(conversation_store, conv.id, "status", "blocked ✋".encode(), publish=True)
    assert _labels(conversation_store, conv.id) == {"team": "ml", _LABEL: "blocked ✋"}
    _put(conversation_store, conv.id, "status", b"done", publish=True)
    assert _labels(conversation_store, conv.id)[_LABEL] == "done"

    conversation_store._delete_extension_state(conv.id, _EXT, "status", publish=True)
    assert _labels(conversation_store, conv.id) == {"team": "ml"}


@pytest.mark.parametrize(("value", "message"), [(b"\xff", "UTF-8"), (b"x" * 257, "256")])
def test_published_value_must_fit_a_label(
    conversation_store: SqlAlchemyConversationStore, value: bytes, message: str
) -> None:
    conv = conversation_store.create_conversation()

    with pytest.raises(ValueError, match=message):
        _put(conversation_store, conv.id, "status", value, publish=True)
    assert conversation_store.get_extension_state(conv.id, _EXT, "status") is None


def test_state_and_mirror_commit_together(
    conversation_store: SqlAlchemyConversationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "status", b"old", publish=True)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("label write failed")

    monkeypatch.setattr(store_module, "_upsert_prepared_labels", fail)
    with pytest.raises(RuntimeError, match="label write failed"):
        _put(conversation_store, conv.id, "status", b"new", publish=True)

    stored = conversation_store.get_extension_state(conv.id, _EXT, "status")
    assert stored is not None and (stored.value, stored.version) == (b"old", 1)
    assert _labels(conversation_store, conv.id)[_LABEL] == "old"


def test_only_the_mirror_writes_ext_labels(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "status", b"done", publish=True)

    with pytest.raises(ValueError, match="read-only"):
        conversation_store.set_labels(conv.id, {_LABEL: "forged"})
    with pytest.raises(ValueError, match="read-only"):
        conversation_store.set_labels(conv.id, {"ext.other.status": "x"})
    with pytest.raises(ValueError, match="read-only"):
        conversation_store.delete_label(conv.id, _LABEL)
    with pytest.raises(ValueError, match="read-only"):
        conversation_store.create_conversation(labels={"ext.acme.watch.goal": "x"})
    with pytest.raises(ValueError, match="read-only"):
        conversation_store.update_conversation_with_changes(
            conv.id, label_updates={_LABEL: "forged"}
        )
    assert _labels(conversation_store, conv.id)[_LABEL] == "done"


def test_fork_copies_neither_state_nor_its_labels(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    source = conversation_store.create_conversation(labels={"team": "ml"})
    _put(conversation_store, source.id, "status", b"done", publish=True)

    fork = conversation_store.fork_conversation(source.id)

    assert _labels(conversation_store, fork.id) == {"team": "ml"}
    assert conversation_store.list_extension_state(fork.id, _EXT) == ([], None)
    with pytest.raises(ValueError, match="read-only"):
        conversation_store.fork_conversation(source.id, extra_labels={_LABEL: "x"})


def test_delete_conversation_removes_the_subtree_state_in_batches(
    conversation_store: SqlAlchemyConversationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "_STATE_DELETE_ROW_BATCH", 2)
    monkeypatch.setattr(store_module, "_STATE_DELETE_SESSION_CHUNK", 1)
    parent = conversation_store.create_conversation()
    child = conversation_store.create_conversation(
        kind="sub_agent", title="child", parent_conversation_id=parent.id
    )
    kept = conversation_store.create_conversation()
    for conv_id in (parent.id, child.id, kept.id):
        for index in range(5):
            _put(conversation_store, conv_id, f"k{index}", b"x")

    assert asyncio.run(conversation_store.delete_conversation(parent.id))

    with pytest.raises(ConversationNotFoundError):
        _put(conversation_store, child.id, "k0", b"x")
    for conv_id in (parent.id, child.id):
        assert conversation_store.list_extension_state(conv_id, _EXT) == ([], None)
    assert len(conversation_store.list_extension_state(kept.id, _EXT)[0]) == 5


def test_concurrent_inserts_respect_the_quota(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()

    results = _run_concurrently(
        [
            lambda index=index: _put(conversation_store, conv.id, f"k{index}", b"x", max_keys=3)
            for index in range(8)
        ]
    )

    assert sum(not isinstance(result, Exception) for result in results) == 3
    assert all(
        isinstance(result, ExtensionStateQuotaError)
        for result in results
        if isinstance(result, Exception)
    )
    assert len(conversation_store.list_extension_state(conv.id, _EXT)[0]) == 3


def test_concurrent_compare_and_set_has_one_winner(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "k", b"0")

    results = _run_concurrently(
        [
            lambda index=index: _put(
                conversation_store, conv.id, "k", str(index).encode(), expected_version=1
            )
            for index in range(6)
        ]
    )

    winners = [result for result in results if not isinstance(result, Exception)]
    assert len(winners) == 1
    assert all(
        isinstance(result, ExtensionStateConflictError)
        for result in results
        if isinstance(result, Exception)
    )
    stored = conversation_store.get_extension_state(conv.id, _EXT, "k")
    assert stored is not None and stored.version == 2


@pytest.mark.parametrize("publish", [False, True])
def test_delete_racing_writes_leaves_no_state(
    conversation_store: SqlAlchemyConversationStore, publish: bool
) -> None:
    for _ in range(3):
        conv_id = conversation_store.create_conversation().id
        writers: list[Callable[[], object]] = [
            lambda index=index, conv_id=conv_id: _put(
                conversation_store,
                conv_id,
                "status" if publish else f"k{index}",
                f"v{index}".encode(),
                publish=publish,
            )
            for index in range(4)
        ]
        results = _run_concurrently(
            [
                *writers,
                lambda conv_id=conv_id: asyncio.run(
                    conversation_store.delete_conversation(conv_id)
                ),
            ]
        )

        assert results[-1] is True
        assert all(
            isinstance(result, ConversationNotFoundError)
            for result in results[:-1]
            if isinstance(result, Exception)
        )
        assert conversation_store.list_extension_state(conv_id, _EXT) == ([], None)
        assert _raw_label_keys(conversation_store, conv_id) == set()


def test_reservation_covers_keys_that_collate_like_ext(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()

    for key in (
        "EXT.acme.watch.status",
        "Ext.x",
        "éxt.acme.watch.status",
        "e\u200bxt.acme.watch.status",
        "ｅｘｔ.x",
    ):
        with pytest.raises(ValueError, match="read-only"):
            conversation_store.set_labels(conv.id, {key: "forged"})
    conversation_store.set_labels(conv.id, {"extra": "ok", "text.ext": "ok"})


def test_mirror_replaces_a_label_that_collates_like_it(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _write_raw_label(conversation_store, conv.id, "EXT.acme.watch.status", "forged")

    _put(conversation_store, conv.id, "status", b"done", publish=True)

    assert _raw_label_keys(conversation_store, conv.id) == {_LABEL}
    assert _labels(conversation_store, conv.id) == {_LABEL: "done"}
    conversation_store._delete_extension_state(conv.id, _EXT, "status", publish=True)
    assert _raw_label_keys(conversation_store, conv.id) == set()


def test_only_matching_state_rows_verify_ext_labels(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "status", b"done", publish=True)
    _put(conversation_store, conv.id, "count", b"2")
    _write_raw_label(conversation_store, conv.id, "ext.acme.watch.count", "9")
    _write_raw_label(conversation_store, conv.id, "ext.acme.watch.goal", "planted")

    single = conversation_store.get_conversation(conv.id)
    listed = conversation_store.list_conversations(limit=10).data
    batch = conversation_store.get_conversations([conv.id])[conv.id]

    assert single is not None
    for loaded in (single, next(item for item in listed if item.id == conv.id), batch):
        assert loaded.verified_extension_labels == frozenset({_LABEL})
        assert loaded.labels["ext.acme.watch.goal"] == "planted"


def test_command_key_families_have_their_own_cap(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    for index in range(2):
        _put(
            conversation_store,
            conv.id,
            f"pr:{index}",
            b"x",
            family_prefix="pr:",
            max_family_keys=2,
        )

    with pytest.raises(ExtensionStateQuotaError, match="pr:"):
        _put(conversation_store, conv.id, "pr:9", b"x", family_prefix="pr:", max_family_keys=2)
    _put(conversation_store, conv.id, "pr:0", b"updated", family_prefix="pr:", max_family_keys=2)
    _put(conversation_store, conv.id, "service", b"x")


@pytest.mark.parametrize(
    ("extension_id", "value", "message"),
    [
        ("acme." + "a" * 110, b"x", "longer than 128"),
        (_EXT, b"a\x00b", "NUL"),
    ],
)
def test_published_values_fail_cleanly(
    conversation_store: SqlAlchemyConversationStore,
    extension_id: str,
    value: bytes,
    message: str,
) -> None:
    conv = conversation_store.create_conversation()

    with pytest.raises(ValueError, match=message):
        conversation_store._put_extension_state(
            conv.id, extension_id, "status-field", value, publish=True, max_keys=64
        )


def test_unknown_envelope_is_a_server_error(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "k", b"x")
    with conversation_store._conv_engine.begin() as connection:
        connection.execute(update(SqlExtensionSessionState.__table__).values(value=b"\x7fx"))

    with pytest.raises(ExtensionStateFormatError):
        conversation_store.get_extension_state(conv.id, _EXT, "k")


# U+0903 (a spacing mark) survives folding, but MySQL's default collations
# compare this key equal to the mirror label.
_COLLATING_VARIANT = "eःxt.acme.watch.status"


def test_a_key_the_database_equates_with_a_mirror_cannot_touch_it(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "status", b"done", publish=True)
    collates = conversation_store._conv_engine.dialect.name == "mysql"

    if collates:
        with pytest.raises(ValueError, match="read-only"):
            conversation_store.set_labels(conv.id, {_COLLATING_VARIANT: "forged"})
        with pytest.raises(ValueError, match="read-only"):
            conversation_store.delete_label(conv.id, _COLLATING_VARIANT)
    else:
        conversation_store.set_labels(conv.id, {_COLLATING_VARIANT: "other"})
        conversation_store.delete_label(conv.id, _COLLATING_VARIANT)

    loaded = conversation_store.get_conversation(conv.id)
    assert loaded is not None
    assert loaded.labels[_LABEL] == "done"
    assert loaded.verified_extension_labels == frozenset({_LABEL})


def test_reads_never_see_a_published_field_half_written(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "status", b"v0", publish=True)
    done = threading.Event()
    unverified: list[dict[str, str]] = []

    def write() -> None:
        try:
            for index in range(150):
                _put(conversation_store, conv.id, "status", f"v{index}".encode(), publish=True)
        finally:
            done.set()

    def read() -> None:
        while not done.is_set():
            loaded = conversation_store.get_conversation(conv.id)
            assert loaded is not None
            if _LABEL not in loaded.verified_extension_labels:
                unverified.append(dict(loaded.labels))

    threads = [threading.Thread(target=write), threading.Thread(target=read)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert unverified == []


def test_max_keys_has_a_hard_ceiling(conversation_store: SqlAlchemyConversationStore) -> None:
    conv = conversation_store.create_conversation()

    with pytest.raises(ValueError, match="max_keys"):
        _put(conversation_store, conv.id, "k", b"x", max_keys=65)


def test_update_results_report_verified_labels(
    conversation_store: SqlAlchemyConversationStore,
) -> None:
    conv = conversation_store.create_conversation()
    _put(conversation_store, conv.id, "status", b"done", publish=True)

    updated = conversation_store.update_conversation_with_changes(conv.id, title="renamed")
    bound = conversation_store.set_external_session_id(conv.id, "external-1")

    assert updated is not None
    assert updated.conversation.verified_extension_labels == frozenset({_LABEL})
    assert bound.verified_extension_labels == frozenset({_LABEL})
