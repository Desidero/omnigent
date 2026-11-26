"""Open items recorded from labels an agent writes only in chat, and the note that tells it."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from omnigent.entities import MessageData, NewConversationItem
from omnigent.entities.open_items import normalize_new_item
from omnigent.inner.native_attachments import FRAMEWORK_NOTICE_BLOCK_TYPE, framework_notices
from omnigent.server import open_items_auto
from omnigent.server.open_items_auto import ChatItemRecorder, chat_changes, chat_note_text
from omnigent.server.routes._sessions import helpers
from omnigent.spec.types import ToolGroupsConfig
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.open_items_store import ChatNote, OpenItemsStore

_ITEMS_AGENT = "1" * 32
_NO_ITEMS_AGENT = "2" * 32
_ITEMS = (
    "Two calls for you:\n\n- [Q1] **Backfill window?** Batch it nightly.\n"
    "- [R1] **No snapshot.** See [the runbook](https://example.com/runbook).\n\n"
    "```\n[Q9] **in a fence**\n```\nAs [Q4] said."
)


class _AgentCache:
    def load(self, agent_id: str, bundle_location: str, **_: Any) -> SimpleNamespace:
        groups = ToolGroupsConfig(open_items=agent_id == _ITEMS_AGENT)
        return SimpleNamespace(spec=SimpleNamespace(tool_groups=groups, sub_agents=[]))


@pytest.fixture()
def conversations(db_uri: str) -> SqlAlchemyConversationStore:
    return SqlAlchemyConversationStore(db_uri)


@pytest.fixture()
def recorder(db_uri: str, conversations: SqlAlchemyConversationStore) -> ChatItemRecorder:
    agents = SqlAlchemyAgentStore(db_uri)
    for agent_id in (_ITEMS_AGENT, _NO_ITEMS_AGENT):
        if agents.get(agent_id) is None:
            agents.create(agent_id, f"agent-{agent_id[0]}", f"{agent_id}/{'c' * 64}")
    return ChatItemRecorder(
        conversations, agent_store=agents, agent_cache=_AgentCache(), settle_seconds=0
    )


def _session(conversations: SqlAlchemyConversationStore, agent_id: str = _ITEMS_AGENT) -> str:
    # Side rows outlive the per-test cleanup of main tables, so ids are fresh each test.
    return conversations.create_conversation(
        conversation_id=uuid.uuid4().hex, agent_id=agent_id
    ).id


def _say(conversations: SqlAlchemyConversationStore, session: str, role: str, text: str) -> str:
    if role == "user":
        data = MessageData(role="user", content=[{"type": "input_text", "text": text}])
    else:
        data = MessageData(
            role="assistant", agent="worker", content=[{"type": "output_text", "text": text}]
        )
    [item] = conversations.append(
        session, [NewConversationItem(response_id="turn", type="message", data=data)]
    )
    return item.id


def _labels(store: OpenItemsStore, session: str) -> dict[str, str]:
    return {item.label: item.status for item in store.list_items(session)}


def test_chat_changes_take_item_labels_and_strikes_only() -> None:
    raises, closes = chat_changes(
        [("m1", _ITEMS), ("m2", "~~[Q1]~~ batched nightly, per your answer. ~~[A4]~~ gone.")]
    )
    assert [(key, item.number, item.content["title"]) for key, item in raises] == [
        ("chat:m1:Q1", 1, "Backfill window?"),
        ("chat:m1:R1", 1, "No snapshot."),
    ]
    risk = raises[1][1].content
    assert risk["raised_by"] == "auto"
    assert risk["links"] == [{"url": "https://example.com/runbook", "label": "the runbook"}]
    assert risk["detail"].startswith("[R1] **No snapshot.**")
    [(ref, close)] = closes
    assert (ref, close.number, close.resolution) == (
        "chat:m2",
        1,
        "~~[Q1]~~ batched nightly, per your answer.",
    )


def test_a_pinned_link_in_chat_becomes_a_link_item() -> None:
    raises, _ = chat_changes([("m1", "[L1] **Release checklist** https://example.com/list")])
    [(_, item)] = raises
    assert (item.kind, item.content["url"], item.content["title"]) == (
        "link",
        "https://example.com/list",
        "Release checklist",
    )


def test_the_note_names_what_changed_in_a_stable_shape() -> None:
    added = [{"label": "Q3", "title": "Region?"}, {"label": "R1", "title": "No snapshot"}]
    assert chat_note_text(ChatNote(added=added, closed=["Q1"], open_count=4)) == (
        '[Open items] Q3 "Region?" and R1 "No snapshot" were labelled in chat without being '
        "recorded, so they were added for you. Next time record items with "
        "sys_open_items_raise; set a topic or close them with sys_open_items_update if "
        "needed. Closed from chat: Q1. Open now: 4."
    )
    assert chat_note_text(ChatNote(added=[], closed=["Q1", "Q2"], open_count=0)) == (
        "[Open items] Closed from chat: Q1 and Q2. Next time close items with "
        "sys_open_items_update. Open now: 0."
    )


@pytest.mark.asyncio
async def test_a_turn_records_its_labels_once_and_tells_the_agent_once(
    recorder: ChatItemRecorder, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    _say(conversations, session, "user", "Plan the migration")
    _say(conversations, session, "assistant", _ITEMS)
    record = await recorder.record(session)
    assert record is not None
    assert [item.label for item in record.added] == ["Q1", "R1"]
    store = recorder.store()
    assert _labels(store, session) == {"Q1": "open", "R1": "open"}

    # The same messages read again, or a retried read, add nothing.
    assert (await recorder.record(session)).added == []  # type: ignore[union-attr]
    note = await recorder.take_note(session)
    assert note is not None and note.startswith('[Open items] Q1 "Backfill window?" and R1')
    assert note.endswith("Open now: 2.")
    assert await recorder.take_note(session) is None

    # A later strike closes the item; nothing else changes, so the note says only that.
    _say(conversations, session, "user", "Go nightly")
    _say(conversations, session, "assistant", "~~[Q1]~~ batched nightly. [R1] still open.")
    record = await recorder.record(session)
    assert [item.label for item in record.closed] == ["Q1"]  # type: ignore[union-attr]
    closed = next(item for item in store.list_items(session) if item.label == "Q1")
    assert closed.outcome["closed_by"] == "auto"
    assert closed.outcome["resolution"] == "~~[Q1]~~ batched nightly."
    assert await recorder.take_note(session) == (
        "[Open items] Closed from chat: Q1. Next time close items with "
        "sys_open_items_update. Open now: 1."
    )
    # A turn that labels nothing leaves no note.
    _say(conversations, session, "assistant", "Nothing new.")
    await recorder.record(session)
    assert await recorder.take_note(session) is None


@pytest.mark.asyncio
async def test_earlier_history_is_not_backfilled(
    recorder: ChatItemRecorder, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    _say(conversations, session, "assistant", "[Q1] **Old question.** From before.")
    _say(conversations, session, "user", "Next")
    _say(conversations, session, "assistant", "[Q2] **New question.** Now.")
    await recorder.record(session)
    assert _labels(recorder.store(), session) == {"Q2": "open"}


@pytest.mark.asyncio
async def test_a_tool_raise_keeps_its_number_and_takes_over_a_recorded_label(
    recorder: ChatItemRecorder, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations)
    store = recorder.store()

    def raise_(key: str, **fields: Any) -> Any:
        item = normalize_new_item({"kind": "question", "detail": "", **fields})
        return store.raise_items(
            session, [item], idempotency_key=key, root_conversation_id=session, user_id="u"
        )[0]

    assert raise_("tool:a", title="From the tool").item.label == "Q1"
    _say(conversations, session, "user", "More")
    _say(conversations, session, "assistant", "[Q1] **Other text.** Mine.\n[Q2] **Chat only.**")
    record = await recorder.record(session)
    assert [item.label for item in record.added] == ["Q2"]  # type: ignore[union-attr]
    tool_item = next(item for item in store.list_items(session) if item.label == "Q1")
    assert tool_item.content["title"] == "From the tool"

    # The agent raising the recorded label afterwards takes it over; counting moves on.
    taken = raise_("tool:b", title="Chat only, now with detail", label="Q2", topic="cache")
    assert taken.took_over and taken.item.content.get("raised_by") is None
    assert taken.item.content["topic"] == "cache"
    assert raise_("tool:c", title="Next").item.label == "Q3"
    assert len(store.list_items(session)) == 3


@pytest.mark.asyncio
async def test_reads_respect_the_session_cap_and_the_note_limit(
    recorder: ChatItemRecorder,
    conversations: SqlAlchemyConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omnigent.stores import open_items_store

    monkeypatch.setattr(open_items_store, "ITEMS_PER_SESSION", 2)
    session = _session(conversations)
    _say(conversations, session, "assistant", "[Q1] **A.**\n[Q2] **B.**\n[Q3] **C.**")
    record = await recorder.record(session)
    assert [item.label for item in record.added] == ["Q1", "Q2"]  # type: ignore[union-attr]
    monkeypatch.setattr(open_items_store, "ITEMS_PER_SESSION", 500)
    notes = [await recorder.take_note(session)]
    for number in range(4, 4 + open_items_auto.NOTE_LIMIT):
        _say(conversations, session, "assistant", f"[Q{number}] **More {number}.**")
        await recorder.record(session)
        notes.append(await recorder.take_note(session))
    # Told NOTE_LIMIT times, then recording goes on without a note.
    assert [note is not None for note in notes] == [True] * open_items_auto.NOTE_LIMIT + [False]
    assert len(recorder.store().list_items(session)) == 2 + open_items_auto.NOTE_LIMIT


@pytest.mark.asyncio
async def test_a_session_without_the_tool_group_is_left_alone(
    recorder: ChatItemRecorder, conversations: SqlAlchemyConversationStore
) -> None:
    session = _session(conversations, _NO_ITEMS_AGENT)
    _say(conversations, session, "assistant", _ITEMS)
    assert await recorder.record(session) is None
    assert recorder.store().list_items(session) == []
    assert await recorder.take_note(session) is None


@pytest.mark.asyncio
async def test_the_next_message_carries_the_note_as_a_framework_notice(
    recorder: ChatItemRecorder,
    conversations: SqlAlchemyConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(conversations)
    content = [{"type": "input_text", "text": "Next"}]
    monkeypatch.setattr(open_items_auto, "_installed", recorder)
    assert await open_items_auto.with_pending_note(session, content) == content
    _say(conversations, session, "assistant", "[T1] **Rotate keys.**")
    await recorder.record(session)
    sent = await open_items_auto.with_pending_note(session, content)
    assert sent[:1] == content  # type: ignore[index]
    assert sent[1]["type"] == FRAMEWORK_NOTICE_BLOCK_TYPE  # type: ignore[index]
    assert framework_notices(sent) == [
        '[Open items] T1 "Rotate keys." was labelled in chat without being recorded, so it '
        "was added for you. Next time record items with sys_open_items_raise; set a topic "
        "or close them with sys_open_items_update if needed. Open now: 1."
    ]
    assert await open_items_auto.with_pending_note(session, content) == content


def test_only_a_completed_turn_reads_the_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    read: list[str] = []
    monkeypatch.setattr(helpers.open_items_auto, "notify_turn_end", read.append)
    monkeypatch.setattr(helpers.session_pull_requests, "notify_turn_end", lambda _: None)
    monkeypatch.setattr(helpers.background_session_titles, "notify_turn_end", lambda _: None)
    monkeypatch.setattr(helpers.session_live_state, "persist_live_status", lambda *_: None)
    session = "c0ffee00c0ffee00c0ffee00c0ffee01"
    monkeypatch.delitem(helpers._session_status_cache, session, raising=False)
    helpers._publish_status(session, "running")
    assert read == []
    helpers._publish_status(session, "idle")
    assert read == [session]


@pytest.mark.asyncio
async def test_deleting_a_session_removes_its_chat_note(
    recorder: ChatItemRecorder, conversations: SqlAlchemyConversationStore
) -> None:
    from omnigent.stores.open_items_store import delete_open_items_batch

    session = _session(conversations)
    _say(conversations, session, "assistant", "[F1] **Index unused.**")
    await recorder.record(session)
    store = recorder.store()
    with store._writes("delete_for_test") as db:
        delete_open_items_batch(db, [session])
    assert store.chat_scanned_through(session) == (False, None)
    assert await recorder.take_note(session) is None


def test_agents_are_not_told_that_chat_labels_get_recorded() -> None:
    """Told up front, agents would skip the tool and items would lose topics and links."""
    from omnigent.runtime.prompt import ITEM_LABEL_INSTRUCTION, OPEN_ITEMS_INSTRUCTION

    for text in (ITEM_LABEL_INSTRUCTION, OPEN_ITEMS_INSTRUCTION):
        assert "automatic" not in text.lower()
        assert "for you" not in text
