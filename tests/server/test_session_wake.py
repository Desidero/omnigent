"""Session wake service: pending slots, pacing, budget and authorization at delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from omnigent.db.account_authority import AccountAuthority, current_account_user
from omnigent.entities.conversation import (
    ConversationItem,
    MessageData,
    MessageOrigin,
    SlashCommandData,
)
from omnigent.entities.pagination import PagedList, paginate_in_memory
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.server_messages import SessionNotReadyError
from omnigent.server.session_status_observers import SessionStatusObservation
from omnigent.server.session_wake import (
    MAX_DELIVERY_FAILURES,
    SessionWakeService,
    WakeOutcome,
    WakeRequest,
    WakeStop,
    latest_turn_input_source,
)

pytestmark = pytest.mark.asyncio

_SOURCE = "ext:acme.goal-loop"


@dataclass
class _World:
    """The service's collaborators, with knobs the tests turn."""

    now: float = 1000.0
    blocked: str | None = None
    edit: bool = True
    generation_ok: bool = True
    enabled: bool = True
    send_error: Exception | None = None
    # Native sessions acknowledge with a pending id until the terminal records the message.
    native: bool = False
    pending_inputs: set[str] = field(default_factory=set)
    send_gate: asyncio.Event | None = None
    # Runs while the post is in flight, after the terminal may already have recorded it.
    during_send: Any = None
    # Runs after the gate, before the post fails or returns.
    during_post: Any = None
    dropped: list[tuple[str, str]] = field(default_factory=list)
    # The source whose wake is the session's latest stored message, if any.
    latest_input_source: str | None = None
    # Holds the read of the latest input until set; records its cancellation.
    latest_input_gate: asyncio.Event | None = None
    latest_input_cancelled: bool = False
    # Whether the session is in a turn when a Stop arrives, and whether that is wired.
    turn_live: bool = True
    wire_turn_is_live: bool = True
    sent: list[dict[str, Any]] = field(default_factory=list)
    stops: list[tuple[str, str, WakeStop]] = field(default_factory=list)

    def service(self) -> SessionWakeService:
        async def send(
            session_id: str, user_id: str | None, content: list[Any], origin: dict[str, Any]
        ) -> dict[str, Any]:
            if self.send_gate is not None:
                await self.send_gate.wait()
            if self.during_post is not None:
                self.during_post()
            if self.send_error is not None:
                raise self.send_error
            self.sent.append(
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "bound_user": current_account_user(),
                    "text": content[0]["text"],
                    "origin": origin,
                }
            )
            if self.native:
                pending_id = f"pending_{len(self.sent)}"
                self.pending_inputs.add(pending_id)
                if self.during_send is not None:
                    self.during_send(pending_id)
                return {"queued": True, "pending_id": pending_id}
            return {"queued": True, "item_id": f"item_{len(self.sent)}"}

        async def owner_of(_session_id: str) -> AccountAuthority:
            return AccountAuthority("owner", "gen-owner", 0)

        async def admission(_session_id: str) -> str | None:
            return self.blocked

        async def has_edit(_user: str | None, _session_id: str) -> bool:
            return self.edit

        service = SessionWakeService(
            send=send,
            owner_of=owner_of,
            admission=admission,
            has_edit=has_edit,
            accepts_generation=lambda _user, _generation: self.generation_ok,
            is_source_enabled=lambda _source: self.enabled,
            is_pending_input=lambda _session_id, pending_id: pending_id in self.pending_inputs,
            drop_input=self._drop_input,
            latest_input_source=self._latest_source,
            turn_is_live=(lambda _session_id, _live_status: self.turn_live)
            if self.wire_turn_is_live
            else None,
            clock=lambda: self.now,
            min_gap_s=100.0,
            max_gap_s=350.0,
        )
        service.add_stop_listener(lambda *stop: self.stops.append(stop))
        self.service_ref = service
        return service

    async def _latest_source(self, _session_id: str) -> str | None:
        if self.latest_input_gate is not None:
            try:
                await self.latest_input_gate.wait()
            except asyncio.CancelledError:
                self.latest_input_cancelled = True
                raise
        return self.latest_input_source

    async def _drop_input(self, session_id: str, pending_id: str) -> None:
        self.dropped.append((session_id, pending_id))
        self.pending_inputs.discard(pending_id)


def _wake(text: str = "PR #7 failed CI", **kwargs: Any) -> WakeRequest:
    return WakeRequest(
        session_id="conv_1",
        source=_SOURCE,
        on_behalf_of="alice",
        text=text,
        generation="gen-alice",
        label="Goal loop",
        **kwargs,
    )


async def _request(service: SessionWakeService, wake: WakeRequest) -> WakeOutcome:
    outcome = await service.request(wake)
    await service.settle()
    return outcome


async def test_idle_session_is_woken_as_its_owner_with_attribution() -> None:
    world = _World()
    service = world.service()

    assert await _request(service, _wake()) is WakeOutcome.QUEUED

    [sent] = world.sent
    assert sent["user_id"] == "owner"
    assert sent["bound_user"] == "owner"
    assert sent["text"] == "[Automation: Goal loop · on behalf of alice]\n\nPR #7 failed CI"
    assert sent["origin"] == {
        "kind": "automation",
        "source": _SOURCE,
        "on_behalf_of": "alice",
        "label": "Goal loop",
    }
    assert service.status("conv_1", _SOURCE).wakes == 1  # type: ignore[union-attr]


async def test_busy_session_keeps_one_slot_that_replaces_or_merges() -> None:
    world = _World(blocked="busy")
    service = world.service()

    assert await _request(service, _wake("first")) is WakeOutcome.QUEUED
    assert await _request(service, _wake("second")) is WakeOutcome.QUEUED
    assert await _request(service, _wake("third", merge=True)) is WakeOutcome.MERGED
    assert world.sent == []

    world.blocked = None
    service.observe(SessionStatusObservation("conv_1", "running", "idle", True, workspace_id=0))
    await service.settle()

    [sent] = world.sent
    assert sent["text"].endswith("second\n\nthird")


async def test_status_edges_other_than_idle_do_not_deliver() -> None:
    world = _World(blocked="busy")
    service = world.service()
    await _request(service, _wake())
    world.blocked = None

    service.observe(SessionStatusObservation("conv_1", "idle", "running", True, workspace_id=0))
    await service.settle()

    assert world.sent == []
    assert service.cancel("conv_1", _SOURCE) is True
    assert service.cancel("conv_1", _SOURCE) is False


async def test_repeated_dedupe_key_is_a_duplicate() -> None:
    world = _World()
    service = world.service()

    assert await _request(service, _wake(dedupe_key="d1")) is WakeOutcome.QUEUED
    assert await _request(service, _wake(dedupe_key="d1")) is WakeOutcome.DUPLICATE
    world.blocked = "busy"
    assert await _request(service, _wake(dedupe_key="d2")) is WakeOutcome.QUEUED
    assert await _request(service, _wake(dedupe_key="d2")) is WakeOutcome.DUPLICATE
    assert len(world.sent) == 1


async def test_back_off_doubles_while_the_evidence_does_not_change() -> None:
    world = _World()
    service = world.service()
    gaps: list[float] = []
    for index in range(5):
        await _request(service, _wake(f"wake {index}", dedupe_key=str(index), evidence_key="e"))
        status = service.status("conv_1", _SOURCE)
        assert status is not None and status.wakes == index + 1 and not status.pending
        gaps.append(status.next_eligible_in_s)
        world.now += status.next_eligible_in_s

    assert gaps == [100.0, 200.0, 350.0, 350.0, 350.0]
    await _request(service, _wake("moved", dedupe_key="new", evidence_key="f"))
    assert service.status("conv_1", _SOURCE).next_eligible_in_s == 100.0  # type: ignore[union-attr]
    # A request inside the gap waits for it.
    await _request(service, _wake("early", dedupe_key="early"))
    assert len(world.sent) == 6
    assert service.status("conv_1", _SOURCE).pending is True  # type: ignore[union-attr]


async def test_budget_is_spent_after_max_wakes() -> None:
    world = _World()
    service = world.service()

    assert await _request(service, _wake("one", max_wakes=1)) is WakeOutcome.QUEUED
    world.now += 1000
    assert await _request(service, _wake("two", max_wakes=1)) is WakeOutcome.BUDGET_SPENT
    assert len(world.sent) == 1


@pytest.mark.parametrize("revoked", ["edit", "generation", "extension"])
async def test_revocation_before_delivery_stops_the_source(revoked: str) -> None:
    world = _World(blocked="busy")
    service = world.service()
    assert await _request(service, _wake()) is WakeOutcome.QUEUED

    setattr(
        world,
        {"edit": "edit", "generation": "generation_ok", "extension": "enabled"}[revoked],
        False,
    )
    world.blocked = None
    service.observe(SessionStatusObservation("conv_1", "running", "idle", True, workspace_id=0))
    await service.settle()

    assert world.sent == []
    assert world.stops == [("conv_1", _SOURCE, WakeStop.NOT_AUTHORIZED)]
    assert await _request(service, _wake("again")) is WakeOutcome.NOT_AUTHORIZED


async def test_policy_denials_stop_the_source_as_undeliverable() -> None:
    world = _World(send_error=OmnigentError("Blocked by policy", code=ErrorCode.FORBIDDEN))
    service = world.service()
    await _request(service, _wake())
    for _ in range(MAX_DELIVERY_FAILURES - 1):
        world.now += 1000
        service.observe(SessionStatusObservation("conv_1", None, "idle", True, workspace_id=0))
        await service.settle()

    assert world.stops == [("conv_1", _SOURCE, WakeStop.UNDELIVERABLE)]
    assert service.status("conv_1", _SOURCE).pending is False  # type: ignore[union-attr]


async def test_starting_or_deleted_sessions() -> None:
    world = _World(send_error=SessionNotReadyError())
    service = world.service()
    await _request(service, _wake())
    assert service.status("conv_1", _SOURCE).failures == 0  # type: ignore[union-attr]

    world.blocked = "gone"
    service.observe(SessionStatusObservation("conv_1", None, "failed", True, workspace_id=0))
    await service.settle()
    assert world.stops == [("conv_1", _SOURCE, WakeStop.SESSION_GONE)]


async def test_requests_are_validated() -> None:
    service = _World().service()
    with pytest.raises(ValueError, match="source"):
        await service.request(WakeRequest("conv_1", "goal-loop", None, "hi"))
    with pytest.raises(ValueError, match="text"):
        await service.request(WakeRequest("conv_1", _SOURCE, None, "  "))


def _idle(persisted: bool = True) -> SessionStatusObservation:
    return SessionStatusObservation("conv_1", "running", "idle", persisted, workspace_id=0)


async def test_stop_and_archive_idles_do_not_wake() -> None:
    """Stop and archive publish idle without persisting it; that is no turn end."""
    world = _World(blocked="busy")
    service = world.service()
    await _request(service, _wake())
    world.blocked = None

    service.observe(_idle(persisted=False))
    await service.settle()

    assert world.sent == []


async def test_a_person_stopping_the_session_drops_pending_and_in_flight_wakes() -> None:
    world = _World(native=True)
    service = world.service()
    await _request(service, _wake("first", dedupe_key="a"))
    other = WakeRequest("conv_1", "core:other", None, "second", generation=None)
    world.blocked = "busy"
    await _request(service, other)

    assert service.stop_session("conv_1") == 2
    assert sorted(world.stops) == [
        ("conv_1", "core:other", WakeStop.STOPPED_BY_USER),
        ("conv_1", _SOURCE, WakeStop.STOPPED_BY_USER),
    ]
    status = service.status("conv_1", _SOURCE)
    assert status is not None and not status.pending and not status.in_flight
    world.blocked = None
    service.observe(_idle())
    await service.settle()
    assert len(world.sent) == 1


@pytest.mark.parametrize(
    ("reason", "latest_input_source", "stopped"),
    [
        (WakeStop.STOPPED_BY_USER, _SOURCE, True),
        # A person's message came after the wake: the stopped turn is theirs.
        (WakeStop.STOPPED_BY_USER, None, False),
        (WakeStop.STOPPED_BY_USER, "core:other", False),
        # An orchestrating agent's interrupt never pauses the automation.
        (WakeStop.STOPPED_BY_AGENT, _SOURCE, False),
    ],
    ids=["person-stops-wake-turn", "person-message-after", "other-source", "agent"],
)
async def test_stopping_a_delivered_wakes_turn_stops_its_source(
    reason: WakeStop, latest_input_source: str | None, stopped: bool
) -> None:
    world = _World()
    service = world.service()
    await _request(service, _wake())
    assert len(world.sent) == 1
    world.latest_input_source = latest_input_source

    assert service.stop_session("conv_1", reason) == 0
    await service.settle()

    expected = [("conv_1", _SOURCE, WakeStop.STOPPED_BY_USER)] if stopped else []
    assert [stop for stop in world.stops if stop[1] == _SOURCE] == expected
    status = service.status("conv_1", _SOURCE)
    assert status is not None
    assert status.stopped is (WakeStop.STOPPED_BY_USER if stopped else None)


@pytest.mark.parametrize("unwired", [False, True], ids=["turn-ended", "no-turn-check"])
async def test_a_stop_after_the_wake_turn_ended_stops_nothing(unwired: bool) -> None:
    world = _World(wire_turn_is_live=not unwired)
    service = world.service()
    await _request(service, _wake())
    world.latest_input_source = _SOURCE
    # The agent answered the wake and the session went idle (or nobody can tell).
    world.turn_live = unwired

    service.stop_session("conv_1")
    await service.settle()

    assert world.stops == []
    assert service.status("conv_1", _SOURCE).stopped is None  # type: ignore[union-attr]


async def test_closing_the_service_cancels_a_stop_check_still_reading() -> None:
    world = _World()
    service = world.service()
    await _request(service, _wake())
    world.latest_input_source = _SOURCE
    world.latest_input_gate = asyncio.Event()

    service.stop_session("conv_1")
    await asyncio.sleep(0)
    await service.aclose()

    assert world.latest_input_cancelled
    world.latest_input_gate.set()
    await asyncio.sleep(0)
    assert world.stops == []


async def test_a_stop_does_not_stop_a_delivered_wake_twice_or_behind_a_newer_one() -> None:
    world = _World(native=True)
    service = world.service()
    await _request(service, _wake("first", dedupe_key="a"))
    world.pending_inputs.discard("pending_1")
    service.note_persisted("conv_1", "pending_1")
    world.latest_input_source = _SOURCE
    world.blocked = "busy"
    await _request(service, _wake("second", dedupe_key="b"))

    # Pending text and the delivered wake's turn: one notification.
    assert service.stop_session("conv_1") == 1
    await service.settle()
    assert world.stops == [("conv_1", _SOURCE, WakeStop.STOPPED_BY_USER)]

    # Another source's wake is in flight, so the stored wake's turn is over.
    world.stops.clear()
    world.blocked = None
    world.now += 1000
    other = WakeRequest("conv_1", "core:other", None, "other", generation=None)
    await _request(service, other)
    assert service.status("conv_1", "core:other").in_flight  # type: ignore[union-attr]
    service.stop_session("conv_1")
    await service.settle()
    assert world.stops == [("conv_1", "core:other", WakeStop.STOPPED_BY_USER)]


async def test_native_wake_stays_in_flight_until_its_terminal_records_it() -> None:
    """While the runner holds a wake, new text waits on the server and nothing is re-sent."""
    world = _World(native=True)
    service = world.service()
    await _request(service, _wake("first", dedupe_key="a"))
    assert service.status("conv_1", _SOURCE).in_flight  # type: ignore[union-attr]
    assert service.status("conv_1", _SOURCE).wakes == 0  # type: ignore[union-attr]

    world.now += 1000
    assert await _request(service, _wake("first again", dedupe_key="a")) is WakeOutcome.DUPLICATE
    await _request(service, _wake("second", dedupe_key="b"))
    await _request(service, _wake("third", dedupe_key="c", merge=True))
    service.observe(_idle())
    await service.settle()
    assert [sent["text"].split("\n\n", 1)[1] for sent in world.sent] == ["first"]

    world.pending_inputs.discard("pending_1")
    service.note_persisted("conv_1", "pending_1")
    assert service.status("conv_1", _SOURCE).wakes == 1  # type: ignore[union-attr]
    world.now += 1000
    service.observe(_idle())
    await service.settle()
    assert world.sent[1]["text"].endswith("second\n\nthird")


async def test_in_flight_wake_dropped_unrecorded_counts_as_a_failure() -> None:
    world = _World(native=True)
    service = world.service()
    await _request(service, _wake())
    world.pending_inputs.clear()  # expired or settled undelivered on the runner

    service.observe(_idle())
    await service.settle()

    status = service.status("conv_1", _SOURCE)
    assert status is not None
    assert (status.in_flight, status.wakes, status.failures) == (False, 0, 1)


async def test_merge_while_posting_starts_a_new_wake() -> None:
    """Text already being posted is never sent again with the merged addition."""
    world = _World(send_gate=asyncio.Event())
    service = world.service()
    await service.request(_wake("first"))
    await asyncio.sleep(0)
    assert await service.request(_wake("second", merge=True)) is WakeOutcome.QUEUED
    world.send_gate.set()  # type: ignore[union-attr]
    await service.settle()
    world.now += 1000
    service.observe(_idle())
    await service.settle()

    assert [sent["text"].split("\n\n", 1)[1] for sent in world.sent] == ["first", "second"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"label": "Goal] loop"},
        {"label": "Goal\nloop"},
        {"label": "x" * 65},
        {"on_behalf_of": "alice]"},
        {"on_behalf_of": "alice\u0007"},
        {"on_behalf_of": " "},
    ],
)
async def test_header_fields_are_validated(overrides: dict[str, Any]) -> None:
    service = _World().service()
    wake = WakeRequest(
        **{
            "session_id": "conv_1",
            "source": _SOURCE,
            "on_behalf_of": "alice",
            "text": "hi",
            "label": "Goal loop",
            **overrides,
        }
    )
    with pytest.raises(ValueError, match="without"):
        await service.request(wake)


async def test_a_wake_recorded_before_its_post_returns_counts_as_delivered() -> None:
    world = _World(native=True)
    service = world.service()

    def recorded(pending_id: str) -> None:
        world.pending_inputs.discard(pending_id)
        service.note_persisted("conv_1", pending_id)

    world.during_send = recorded
    await _request(service, _wake())

    status = service.status("conv_1", _SOURCE)
    assert status is not None
    assert (status.in_flight, status.wakes, status.failures) == (False, 1, 0)


@pytest.mark.parametrize("native", [True, False], ids=["native", "sdk"])
async def test_a_stop_during_the_post_takes_the_queued_wake_back(native: bool) -> None:
    world = _World(native=native)
    service = world.service()
    world.during_send = lambda _pending_id: service.stop_session("conv_1")
    if not native:
        world.send_gate = asyncio.Event()
    await service.request(_wake())
    if not native:
        await asyncio.sleep(0)
        service.stop_session("conv_1")
        world.send_gate.set()  # type: ignore[union-attr]
    await service.settle()

    status = service.status("conv_1", _SOURCE)
    assert status is not None and not status.in_flight and not status.pending
    assert world.stops == [("conv_1", _SOURCE, WakeStop.STOPPED_BY_USER)]
    # An SDK message is persisted by the time the post returns: too late to take back.
    assert world.dropped == ([("conv_1", "pending_1")] if native else [])


async def test_a_stop_during_a_failing_post_does_not_bring_the_wake_back() -> None:
    world = _World(send_gate=asyncio.Event(), send_error=RuntimeError("tunnel dropped"))
    service = world.service()
    world.during_post = lambda: service.stop_session("conv_1")
    await service.request(_wake())
    world.send_gate.set()  # type: ignore[union-attr]
    await service.settle()

    status = service.status("conv_1", _SOURCE)
    assert status is not None and not status.pending and status.failures == 0
    world.send_error = None
    world.now += 1000
    service.observe(_idle())
    await service.settle()
    assert world.sent == []


async def test_early_records_of_concurrent_wakes_are_kept_apart() -> None:
    """Two sources posting at once: each wake keeps its own early record."""
    world = _World(native=True, send_gate=asyncio.Event())
    service = world.service()
    other = WakeRequest("conv_1", "core:other", None, "other", generation=None)
    await service.request(_wake())
    await service.request(other)
    await asyncio.sleep(0)

    def recorded(pending_id: str) -> None:
        world.pending_inputs.discard(pending_id)
        if pending_id == "pending_1":
            # Both posts are in flight: the terminal records both wakes now.
            service.note_persisted("conv_1", "pending_1")
            service.note_persisted("conv_1", "pending_2")

    world.during_send = recorded
    world.send_gate.set()  # type: ignore[union-attr]
    await service.settle()

    for source in (_SOURCE, "core:other"):
        status = service.status("conv_1", source)
        assert status is not None and (status.in_flight, status.wakes) == (False, 1)


# ── The latest turn-starting input, read from the stored transcript ──

_WAKE_TURN = "turn_wake"


def _user(text: str, *, hidden: bool = False) -> MessageData:
    return MessageData(role="user", content=[{"type": "input_text", "text": text}], is_meta=hidden)


def _item(index: int, data: Any, turn: str) -> ConversationItem:
    item_type = "slash_command" if isinstance(data, SlashCommandData) else "message"
    return ConversationItem(
        id=f"item_{index:04d}",
        type=item_type,
        status="completed",
        response_id=turn,
        created_at=index,
        data=data,
    )


class _Transcript:
    """A conversation store's newest-first item pages over a fixed transcript."""

    def __init__(self, entries: list[tuple[Any, str]]) -> None:
        self.items = [_item(index, data, turn) for index, (data, turn) in enumerate(entries)]

    def list_items(
        self,
        conversation_id: str,
        limit: int = 100,
        after: str | None = None,
        before: str | None = None,
        order: str = "asc",
        type: str | None = None,
    ) -> PagedList[ConversationItem]:
        del conversation_id
        items = [item for item in self.items if type is None or item.type == type]
        return paginate_in_memory(
            items, lambda item: item.id, limit=limit, after=after, before=before, order=order
        )


def _wake_message() -> tuple[MessageData, str]:
    wake = MessageData(
        role="user",
        content=[{"type": "input_text", "text": "[Automation: Goal loop]\n\nPR #7 failed CI"}],
        origin=MessageOrigin(source=_SOURCE, on_behalf_of="alice", label="Goal loop"),
    )
    return wake, _WAKE_TURN


def _reply(text: str = "Looking into it") -> tuple[MessageData, str]:
    return MessageData(
        role="assistant", content=[{"type": "output_text", "text": text}], agent="claude"
    ), _WAKE_TURN


@pytest.mark.parametrize(
    ("after_wake", "source"),
    [
        ([_reply()], _SOURCE),
        # Context delivered with the wake, in the wake's own turn.
        ([(_user("<hook context>", hidden=True), _WAKE_TURN), _reply()], _SOURCE),
        # A turn of more than one page of assistant segments.
        ([_reply(f"step {step}") for step in range(250)], _SOURCE),
        ([(_user("also check the docs"), "turn_person"), _reply()], None),
        # A person's /skill: the command item and the skill text it expands to.
        (
            [
                (SlashCommandData(agent="claude-native-ui", name="review", arguments=""), "t2"),
                (_user("<skill body>", hidden=True), "t2"),
            ],
            None,
        ),
        ([(SlashCommandData(agent="claude-native-ui", name="review", arguments=""), "t2")], None),
        # A timer or notification turn, hidden from the transcript.
        ([_reply(), (_user("<scheduled task fired>", hidden=True), "turn_timer")], None),
        # The wake's own context doesn't excuse a later hidden turn.
        (
            [
                (_user("<hook context>", hidden=True), _WAKE_TURN),
                _reply(),
                (_user("<scheduled task fired>", hidden=True), "turn_timer"),
            ],
            None,
        ),
    ],
    ids=[
        "wake-turn",
        "wake-with-its-context",
        "long-wake-turn",
        "person-message-after",
        "person-skill-after",
        "person-command-after",
        "hidden-turn-after",
        "wake-context-then-hidden-turn",
    ],
)
async def test_latest_turn_input_is_found_past_output_but_not_past_later_input(
    after_wake: list[tuple[Any, str]], source: str | None
) -> None:
    transcript = _Transcript(
        [(_user("fix CI please"), "turn_0"), _reply(), _wake_message(), *after_wake]
    )

    assert latest_turn_input_source(transcript, "conv_1") == source


async def test_latest_turn_input_of_a_session_without_input_is_none() -> None:
    assert latest_turn_input_source(_Transcript([_reply()]), "conv_1") is None


# The documented cap is 5,000 stored items.
@pytest.mark.parametrize(("replies", "source"), [(4999, _SOURCE), (5000, None)])
async def test_latest_turn_input_walk_gives_up_past_its_cap(
    replies: int, source: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    transcript = _Transcript(
        [_wake_message(), *[_reply(f"step {step}") for step in range(replies)]]
    )

    assert latest_turn_input_source(transcript, "conv_1") == source
    warned = [record for record in caplog.records if "conv_1" in record.getMessage()]
    assert len(warned) == (0 if source else 1)
