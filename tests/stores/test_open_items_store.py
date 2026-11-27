"""Tests for :class:`OpenItemsStore`, the ``open_items`` side store, against a real database."""

from __future__ import annotations

import asyncio
import dataclasses
import random
import shutil
import string
import threading
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest

from omnigent.entities.open_items import (
    OpenItem,
    OpenItemError,
    OpenItemFilter,
    normalize_change,
    normalize_new_item,
    page_items,
)
from omnigent.stores import open_items_store
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.open_items_store import (
    OpenItemsSessionNotFoundError,
    OpenItemsStore,
    RaisedItem,
)


@pytest.fixture()
def conversations(db_uri: str) -> SqlAlchemyConversationStore:
    return SqlAlchemyConversationStore(db_uri)


@pytest.fixture()
def store(db_uri: str) -> OpenItemsStore:
    return OpenItemsStore(db_uri)


def _session(conversations: SqlAlchemyConversationStore, parent: str | None = None) -> str:
    # Side rows outlive the per-test cleanup of main tables, so ids are fresh each test.
    return conversations.create_conversation(
        conversation_id=uuid.uuid4().hex, parent_conversation_id=parent
    ).id


def _raise(
    store: OpenItemsStore, session: str, *items: dict[str, object], key: str = "tool:call"
) -> list[RaisedItem]:
    return store.raise_items(
        session,
        [normalize_new_item(item) for item in items],
        idempotency_key=key,
        root_conversation_id=session,
        user_id="alice@example.com",
    )


def _labels(results: Sequence[RaisedItem]) -> list[str | None]:
    return [result.item.label if result.item else result.error.code for result in results]  # type: ignore[union-attr]


def _question(title: str = "Cache rows?", **fields: object) -> dict[str, object]:
    return {"kind": "question", "title": title, "detail": "Full detail", **fields}


def test_raises_number_each_kind_and_keep_the_label_in_the_key(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session, other = _session(conversations), _session(conversations)
    first = _raise(
        store,
        session,
        _question(),
        {"kind": "risk", "title": "Flaky e2e"},
        _question("Rename?", topic="Cache Rollout"),
    )
    assert _labels(first) == ["Q1", "R1", "Q2"]
    assert first[2].item.content["topic"] == "cache-rollout"  # type: ignore[union-attr]
    assert _labels(_raise(store, session, {"kind": "finding", "title": "x"}, key="k2")) == ["F1"]
    # Another session counts on its own.
    assert _labels(_raise(store, other, _question())) == ["Q1"]
    assert [item.label for item in store.list_items(session)] == ["Q1", "Q2", "R1", "F1"]
    assert store.open_count(session) == 4


def test_two_raises_at_once_never_share_a_label(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    barrier = threading.Barrier(6)
    labels: list[str | None] = []
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait()
            labels.extend(
                _labels(_raise(store, session, _question(), _question(), key=f"tool:{index}"))
            )
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors
    assert sorted(labels, key=lambda label: int(label[1:])) == [f"Q{n}" for n in range(1, 13)]  # type: ignore[index]


def test_a_retried_raise_returns_its_first_labels(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    first = _raise(store, session, _question(), {"kind": "risk", "title": "r"}, key="tool:a")
    again = _raise(store, session, _question(), {"kind": "risk", "title": "r"}, key="tool:a")
    assert _labels(again) == _labels(first) == ["Q1", "R1"]
    assert not any(result.duplicate for result in again)
    assert len(store.list_items(session)) == 2


def test_pinning_a_link_twice_returns_one_item(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    pinned = _raise(store, session, {"kind": "link", "url": "https://github.com/a/b/pull/7"})
    again = _raise(
        store,
        session,
        {"kind": "link", "url": "https://www.github.com/a/b/pull/7/files", "title": "PR"},
        key="tool:b",
    )
    assert _labels(pinned) == _labels(again) == ["L1"]
    assert again[0].duplicate
    # A link pinned without a title is named by a short form of its URL.
    assert pinned[0].item.content["title"] == "github.com/a/b/…"  # type: ignore[union-attr]


def test_an_imported_label_is_taken_once_and_counting_moves_past_it(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    assert _labels(_raise(store, session, _question(label="Q7"))) == ["Q7"]
    assert _labels(_raise(store, session, _question(), key="tool:2")) == ["Q8"]
    taken = _raise(store, session, _question(label="q7"), _question(label="Q3"), key="tool:3")
    assert _labels(taken) == ["label_taken", "Q3"]
    assert _labels(_raise(store, session, _question(), key="tool:4")) == ["Q9"]
    with pytest.raises(OpenItemError, match="not a question label"):
        normalize_new_item(_question(label="R2"))


def test_a_full_session_and_a_used_up_kind_refuse_further_items(
    store: OpenItemsStore,
    conversations: SqlAlchemyConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(open_items_store, "ITEMS_PER_SESSION", 3)
    session = _session(conversations)
    results = _raise(store, session, _question(), _question(), _question(), _question())
    assert _labels(results) == ["Q1", "Q2", "Q3", "session_full"]
    monkeypatch.setattr(open_items_store, "ITEMS_PER_SESSION", 500)
    monkeypatch.setattr(open_items_store, "NUMBER_MAX", 4)
    assert _labels(_raise(store, session, _question(), _question(), key="k")) == [
        "Q4",
        "session_full",
    ]
    assert _labels(_raise(store, session, {"kind": "risk", "title": "r"}, key="r")) == ["R1"]


def test_raising_in_a_missing_session_writes_nothing(store: OpenItemsStore) -> None:
    missing = uuid.uuid4().hex
    with pytest.raises(OpenItemsSessionNotFoundError):
        _raise(store, missing, _question())
    assert store.list_items(missing) == []


def test_close_needs_a_resolution_and_reopen_clears_it(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    _raise(store, session, _question(), _question("Second"))
    with pytest.raises(OpenItemError, match="resolution"):
        normalize_change({"label": "Q1", "status": "closed"})
    (closed, missing) = store.change_items(
        session,
        [
            normalize_change({"label": "Q1", "status": "closed", "resolution": "Kept as is"}),
            normalize_change({"label": "Q9", "topic": "x"}),
        ],
        actor="agent",
        ref="tool:c1",
    )
    assert closed.item is not None and closed.item.status == "closed"
    assert closed.item.closed_at is not None
    assert closed.item.outcome == {
        "resolution": "Kept as is",
        "closed_by": "agent",
        "closed_ref": "tool:c1",
    }
    assert missing.error is not None and missing.error.code == "not_found"
    assert store.open_count(session) == 1
    (reopened,) = store.change_items(
        session, [normalize_change({"label": "Q1", "status": "open"})], actor="user"
    )
    assert reopened.item is not None
    assert (reopened.item.status, reopened.item.closed_at, reopened.item.outcome) == (
        "open",
        None,
        {},
    )


def test_edits_change_content_topic_and_links(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    _raise(store, session, _question(topic="cache", links=["https://example.com/a"]))
    (changed,) = store.change_items(
        session,
        [
            normalize_change(
                {
                    "label": "Q1",
                    "title": "Cache everything?",
                    "topic": "",
                    "add_links": [{"url": "https://example.com/b", "label": "B"}],
                    "remove_links": ["https://EXAMPLE.com/a/"],
                }
            )
        ],
        actor="agent",
    )
    assert changed.item is not None
    assert changed.item.content == {
        "title": "Cache everything?",
        "detail": "Full detail",
        "links": [{"url": "https://example.com/b", "label": "B"}],
    }
    # Each field is within its limit, but together they don't compress below the cap.
    noise = random.Random(0)
    detail = "".join(chr(noise.randrange(0x4E00, 0x9FFF)) for _ in range(6000))
    links = [
        "https://example.com/" + "".join(noise.choices(string.ascii_letters, k=1900))
        for _ in range(7)
    ]
    (too_big,) = store.change_items(
        session,
        [normalize_change({"label": "Q1", "detail": detail, "add_links": links})],
        actor="agent",
    )
    assert too_big.error is not None and too_big.error.code == "too_large"
    assert store.list_items(session)[0].content["title"] == "Cache everything?"


def _reply(
    store: OpenItemsStore, session: str, actor: str, *, ref: str | None = None, **change: object
) -> OpenItem:
    (result,) = store.change_items(
        session, [normalize_change({"label": "Q1", **change})], actor=actor, ref=ref
    )
    assert result.item is not None, result.error
    return result.item


def test_replies_build_one_chain_and_never_close_the_item(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    _raise(store, session, _question())
    (commented,) = store.record_replies(
        session, [("Q1", "Which region?")], user_id="bob", ref="comment:s1"
    )
    assert commented.item is not None and commented.item.status == "answered"
    # A retried comment adds nothing; the agent's reply hands the item back to the user.
    store.record_replies(session, [("Q1", "Which region?")], user_id="bob", ref="comment:s1")
    replied = _reply(store, session, "agent", ref="tool:c1", reply="eu-west-1, as before.")
    assert replied.status == "open"
    assert _reply(store, session, "agent", ref="tool:c1", reply="again").status == "open"
    closed = _reply(
        store,
        session,
        "agent",
        ref="tool:c2",
        reply="Done.",
        status="closed",
        resolution="Kept eu-west-1",
    )
    assert closed.status == "closed"
    assert [
        {key: value for key, value in reply.items() if key != "at"}
        for reply in closed.outcome["replies"]
    ] == [
        {"author": "user", "text": "Which region?", "by": "bob", "ref": "comment:s1"},
        {"author": "agent", "text": "eu-west-1, as before.", "ref": "tool:c1"},
        {"author": "agent", "text": "Done.", "ref": "tool:c2"},
    ]
    assert closed.outcome["resolution"] == "Kept eu-west-1"
    # A reply on a closed item keeps it closed, and reopening keeps the chain.
    assert _reply(store, session, "user", reply="Thanks").status == "closed"
    reopened = _reply(store, session, "user", status="open")
    assert len(reopened.outcome["replies"]) == 4
    with pytest.raises(OpenItemError, match="reply is required"):
        normalize_change({"label": "Q1", "reply": "  "})


def test_replies_keep_the_latest_ten_that_fit(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    _raise(store, session, _question())
    for index in range(12):
        (replied,) = store.record_replies(session, [("Q1", f"reply {index}")], user_id="bob")
    assert replied.item is not None
    assert [reply["text"] for reply in replied.item.outcome["replies"]] == [
        f"reply {index}" for index in range(2, 12)
    ]
    # Replies that would not fit the stored cap drop the oldest first.
    noise = random.Random(1)
    for _ in range(10):
        text = "".join(chr(noise.randrange(0x4E00, 0x9FFF)) for _ in range(2000))
        (replied,) = store.record_replies(session, [("Q1", text)], user_id="bob")
    assert replied.item is not None and 1 <= len(replied.item.outcome["replies"]) < 10
    (missing,) = store.record_replies(session, [("R4", "?")], user_id=None)
    assert missing.error is not None and missing.error.code == "not_found"


def test_deleting_a_session_removes_its_items_in_batches(
    store: OpenItemsStore,
    conversations: SqlAlchemyConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(open_items_store, "DELETE_BATCH", 2)
    parent = _session(conversations)
    child = _session(conversations, parent=parent)
    kept = _session(conversations)
    for session in (parent, child, kept):
        _raise(store, session, _question(), _question(), {"kind": "risk", "title": "r"})
    asyncio.run(conversations.delete_conversation(parent))
    assert store.list_items(parent) == store.list_items(child) == []
    assert len(store.list_items(kept)) == 3


def test_lists_filter_page_and_count_in_label_order(
    store: OpenItemsStore, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    _raise(
        store,
        session,
        _question("Cache rows?", topic="cache"),
        {"kind": "risk", "title": "Flaky e2e", "raised_by": "tester"},
        _question("Rename table?", links=["https://example.com/t"]),
        {"kind": "follow_up", "title": "Bump image", "topic": "release"},
    )
    store.change_items(
        session,
        [normalize_change({"label": "Q2", "status": "closed", "resolution": "Renamed it"})],
        actor="agent",
    )
    items = store.list_items(session)

    def labels(**wanted: object) -> list[str]:
        return [item.label for item in page_items(items, OpenItemFilter(**wanted)).items]  # type: ignore[arg-type]

    assert labels() == ["Q1", "R1", "T1"]
    assert labels(statuses=()) == ["Q1", "Q2", "R1", "T1"]
    assert labels(statuses=("closed",)) == ["Q2"]
    assert labels(kinds=("question",), statuses=()) == ["Q1", "Q2"]
    assert labels(topic="release") == ["T1"]
    assert labels(raised_by="tester") == ["R1"]
    assert labels(statuses=(), has_links=True) == ["Q2"]
    assert labels(statuses=(), query="RENAMED") == ["Q2"]
    page = page_items(items, OpenItemFilter(statuses=(), limit=2))
    assert ([item.label for item in page.items], page.has_more) == (["Q1", "Q2"], True)
    assert labels(statuses=(), after="Q2", limit=2) == ["R1", "T1"]
    assert page.status_counts == {"open": 3, "answered": 0, "closed": 1}
    assert page.kind_counts == {"question": 2, "risk": 1, "finding": 0, "follow_up": 1, "link": 0}
    assert page.topics == ["cache", "release"]


def test_the_retired_chat_notes_table_is_dropped_and_a_downgrade_restores_it(
    tmp_path: Path,
) -> None:
    """A database that ran open_items0002 loses its chat notes table and keeps its items."""
    from alembic import command
    from sqlalchemy import inspect, text

    from omnigent.db import side_schemas
    from omnigent.db.utils import get_or_create_engine

    revisions = Path(open_items_store.__file__).parent / "open_items_migrations"
    up_to_notes = tmp_path / "revisions"
    up_to_notes.mkdir()
    for name in ("open_items0001_create_tables.py", "open_items0002_chat_notes.py"):
        shutil.copy(revisions / name, up_to_notes)
    store = open_items_store.OPEN_ITEMS_SIDE_STORE
    engine = get_or_create_engine(f"sqlite:///{tmp_path / 'copy.db'}")

    def tables() -> set[str]:
        return set(inspect(engine).get_table_names())

    def revision() -> str | None:
        with engine.connect() as connection:
            return side_schemas._current_revision(connection, store)

    side_schemas.ensure_side_store(dataclasses.replace(store, migrations=up_to_notes), engine)
    assert revision() == "open_items0002" and "open_items_chat_notes" in tables()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO open_items_heads (workspace_id, conversation_id, kind, next_number) "
                "VALUES (0, :conversation, 1, 4)"
            ),
            {"conversation": uuid.uuid4().bytes},
        )

    side_schemas._migrated.pop(engine, None)
    side_schemas.ensure_side_store(store, engine)
    assert revision() == "open_items0003"
    assert "open_items_chat_notes" not in tables()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT next_number FROM open_items_heads")).all() == [(4,)]

    config = side_schemas._alembic_config(store)
    with engine.connect() as connection:
        config.attributes.update(connection=connection, side_store=store)
        command.downgrade(config, "open_items0002")
        connection.commit()
    assert revision() == "open_items0002" and "open_items_chat_notes" in tables()
    side_schemas._migrated.pop(engine, None)
    side_schemas.ensure_side_store(store, engine)
    assert revision() == "open_items0003" and "open_items_chat_notes" not in tables()
