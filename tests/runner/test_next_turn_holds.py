"""Next-turn-only messages (session wakes) never join a running turn.

SDK sessions keep them out of live mid-turn injection; native sessions hold
them while the terminal is busy, and take them back when the harness refuses
one under its injection lock.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI

from omnigent.native.next_turn import NEXT_TURN_BUSY_CODE
from omnigent.runner import app as runner_app
from omnigent.runner import create_runner_app
from omnigent.runner.next_turn_holds import HARNESS_BUSY, NextTurnHolds, block_reason
from omnigent.spec.types import AgentSpec, ExecutorSpec
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.runner.conftest import _FakeProcessManager, _runner_client, _ScriptedHarnessClient, _sse
from tests.runner.helpers import NullServerClient


def _wake(text: str = "[Automation: Goal loop] PR #7 failed CI") -> dict[str, Any]:
    return {
        "type": "message",
        "role": "user",
        "model": "t",
        "content": [{"type": "input_text", "text": text}],
        "delivery": "next_turn_only",
    }


class _RefusingOnceHarness(_ScriptedHarnessClient):
    """Refuses the first next-turn-only delivery as busy, then accepts."""

    def __init__(self, refusals: int) -> None:
        super().__init__([])
        self.refusals = refusals

    def stream(self, method: str, url: str, *, json: dict[str, Any], timeout: Any) -> Any:
        del method, url, timeout
        self.posted_bodies.append(json)
        refuse = self.refusals > 0
        self.refusals -= 1
        response_id = f"resp_{len(self.posted_bodies)}"

        class _Handle:
            status_code = 200

            async def aiter_text(self) -> AsyncIterator[str]:
                yield _sse({"type": "response.created", "response": {"id": response_id}})
                if refuse:
                    error = {
                        "code": NEXT_TURN_BUSY_CODE,
                        "message": "A turn is running",
                        "undelivered": True,
                    }
                    yield _sse(
                        {
                            "type": "response.failed",
                            "response": {"id": response_id, "error": error},
                        }
                    )
                else:
                    yield _sse({"type": "response.completed", "response": {"id": response_id}})

        class _Ctx:
            status_code = 200

            async def __aenter__(self) -> _Handle:
                return _Handle()

            async def __aexit__(self, *_: Any) -> None:
                return None

        return _Ctx()


def _native_app(
    harness: _ScriptedHarnessClient, monkeypatch: pytest.MonkeyPatch, name: str = "pi-native"
) -> FastAPI:
    spec = AgentSpec(
        spec_version=1, name="t", executor=ExecutorSpec(type="omnigent", config={"harness": name})
    )

    async def resolver(agent_id: str, session_id: str | None = None) -> AgentSpec:
        return spec

    async def skip_terminal_launch(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(runner_app, "_launch_native_terminal", skip_terminal_launch)
    app = create_runner_app(
        process_manager=_FakeProcessManager(harness),  # type: ignore[arg-type]
        spec_resolver=resolver,
        server_client=NullServerClient(),  # type: ignore[arg-type]
    )
    app.state.next_turn_holds._poll_interval_s = 0.01
    app.state.next_turn_holds._refusal_cooldown_s = 0.0
    return app


@pytest.mark.asyncio
async def test_native_wake_waits_for_the_terminal_turn_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ScriptedHarnessClient(
        [
            _sse({"type": "response.created", "response": {"id": "resp_1"}}),
            _sse({"type": "response.completed", "response": {"id": "resp_1"}}),
        ]
    )
    app = _native_app(harness, monkeypatch)
    sid = uuid.uuid4().hex
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        # Someone started a turn in the terminal after the server's idle check.
        app.state.native_pane_status[sid] = "running"

        held = await client.post(f"/v1/sessions/{sid}/events", json=_wake())
        assert held.status_code == 202
        assert held.json()["status"] == "held"
        await asyncio.sleep(0.05)  # custom-lint: disable=sleep-then-assert -- no send in window
        assert harness.posted_bodies == []

        typed = await client.post(
            f"/v1/sessions/{sid}/events",
            json={**_wake("typed by a person"), "delivery": None},
        )
        assert typed.status_code == 202
        await poll_until_async(lambda: len(harness.posted_bodies) == 1, timeout_s=budget(5))

        # The terminal reports the person's turn ending.
        await client.post(
            f"/v1/sessions/{sid}/events",
            json={"type": "external_session_status", "data": {"status": "idle"}},
        )
        await poll_until_async(lambda: len(harness.posted_bodies) == 2, timeout_s=budget(5))

    person, wake = harness.posted_bodies
    assert "delivery" not in person
    assert wake["delivery"] == "next_turn_only"
    assert app.state.next_turn_holds.held(sid) == []


@pytest.mark.asyncio
async def test_harness_refusal_holds_the_wake_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RefusingOnceHarness(refusals=1)
    app = _native_app(harness, monkeypatch, name="codex-native")
    sid = uuid.uuid4().hex
    published: list[dict[str, Any]] = []
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        accepted = await client.post(f"/v1/sessions/{sid}/events", json=_wake())
        assert accepted.status_code == 202
        await poll_until_async(lambda: len(harness.posted_bodies) == 2, timeout_s=budget(5))
        queue = app.state.session_event_queues.get(sid)
        while queue is not None and not queue.empty():
            published.append(queue.get_nowait())

    # The refusal changes no status: the terminal reports its own turn's edges.
    assert not [event for event in published if event and event.get("type") == "session.status"]
    assert not [event for event in published if event and event.get("type") == "response.failed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "harness_name"),
    [("interrupt", "claude-native"), ("delete", "claude-native"), ("interrupt", "pi-native")],
)
async def test_stop_controls_drop_held_wakes(
    monkeypatch: pytest.MonkeyPatch, action: str, harness_name: str
) -> None:
    harness = _ScriptedHarnessClient([])
    app = _native_app(harness, monkeypatch, name=harness_name)
    monkeypatch.setattr(
        "omnigent.harnesses.claude_native.bridge.has_pending_user_prompt", lambda _: False
    )
    monkeypatch.setattr(
        "omnigent.harnesses.claude_native.bridge.inject_interrupt", lambda *_a, **_k: None
    )

    async def bridge_id(**_: Any) -> str:
        return "bridge"

    monkeypatch.setattr(runner_app, "_claude_native_bridge_id_for_session", bridge_id)
    sid = uuid.uuid4().hex
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        app.state.native_pane_status[sid] = "running"
        await client.post(f"/v1/sessions/{sid}/events", json=_wake())
        assert app.state.next_turn_holds.held(sid)

        if action == "interrupt":
            await client.post(f"/v1/sessions/{sid}/events", json={"type": "interrupt"})
        else:
            await client.delete(f"/v1/sessions/{sid}")
        app.state.native_pane_status[sid] = "idle"
        await asyncio.sleep(0.05)

    assert app.state.next_turn_holds.held(sid) == []
    assert harness.posted_bodies == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, None),
        ({"turn_active": True}, "turn"),
        ({"queued": True}, "queued"),
        ({"approval_pending": True}, "approval"),
        ({"pane_status": "running"}, "running"),
        ({"pane_status": "waiting"}, "running"),
        ({"pane_status": "failed"}, None),
        ({"person_active": True}, "person"),
        ({"screen_active": True}, None),
        ({"harness": "kiro-native", "screen_active": None}, "screen"),
        ({"harness": "kiro-native", "screen_active": False}, None),
    ],
)
def test_block_reason(overrides: dict[str, Any], expected: str | None) -> None:
    state: dict[str, Any] = {
        "harness": "claude-native",
        "turn_active": False,
        "queued": False,
        "approval_pending": False,
        "pane_status": "idle",
        "person_active": False,
        "screen_active": False,
        **overrides,
    }
    assert block_reason(**state) == expected


@pytest.mark.asyncio
async def test_released_message_handed_back_stays_first() -> None:
    reasons = iter(["busy", None, None, None])
    released: list[str] = []
    holds: NextTurnHolds

    async def blocked(_session_id: str) -> str | None:
        return next(reasons, None)

    async def release(session_id: str, body: dict[str, Any]) -> None:
        released.append(body["text"])
        if len(released) == 1:
            holds.hold(session_id, body, reason="harness_busy", first=True)

    holds = NextTurnHolds(
        blocked=blocked, release=release, poll_interval_s=0, refusal_cooldown_s=0
    )
    holds.hold("s", {"text": "a"}, reason="running")
    holds.hold("s", {"text": "b"}, reason="running")
    await poll_until_async(lambda: len(released) == 3, timeout_s=budget(5))

    assert released == ["a", "a", "b"]
    assert holds.held("s") == []


@pytest.mark.asyncio
async def test_a_refused_message_waits_out_the_cooldown() -> None:
    now = [0.0]
    released: list[str] = []

    async def blocked(_session_id: str) -> str | None:
        return None

    async def release(_session_id: str, body: dict[str, Any]) -> None:
        released.append(body["text"])

    holds = NextTurnHolds(
        blocked=blocked,
        release=release,
        poll_interval_s=0,
        refusal_cooldown_s=5,
        clock=lambda: now[0],
    )
    holds.hold("s", {"text": "draft in the box"}, reason=HARNESS_BUSY, first=True)
    for _ in range(20):
        await asyncio.sleep(0)
    assert released == []

    now[0] = 5.0
    await poll_until_async(lambda: released == ["draft in the box"], timeout_s=budget(5))


@pytest.mark.asyncio
async def test_wake_buffered_mid_turn_is_rechecked_when_the_queue_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wake queued behind a delivery waits again if the terminal is busy at drain time."""
    harness = _ScriptedHarnessClient(
        [
            _sse({"type": "response.created", "response": {"id": "resp_1"}}),
            _sse({"type": "response.completed", "response": {"id": "resp_1"}}),
        ]
    )
    app = _native_app(harness, monkeypatch)
    sid = uuid.uuid4().hex
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        app.state.active_turns[sid] = None  # a delivery is in progress
        buffered = await client.post(f"/v1/sessions/{sid}/events", json=_wake())
        assert buffered.json()["status"] == "buffered"
        app.state.active_turns.pop(sid)
        app.state.native_pane_status[sid] = "running"

        await app.state.check_and_start_next_turn(sid)

        assert harness.posted_bodies == []
        assert len(app.state.next_turn_holds.held(sid)) == 1
        app.state.native_pane_status[sid] = "idle"
        await poll_until_async(lambda: len(harness.posted_bodies) == 1, timeout_s=budget(5))


@pytest.mark.asyncio
async def test_wake_after_a_delivered_prompt_waits_for_that_turn_to_settle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal's status can lag the prompt it just took; only a fresh idle edge counts."""
    harness = _ScriptedHarnessClient(
        [
            _sse({"type": "response.created", "response": {"id": "resp_1"}}),
            _sse({"type": "response.completed", "response": {"id": "resp_1"}}),
        ]
    )
    app = _native_app(harness, monkeypatch)
    sid = uuid.uuid4().hex
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        typed = {**_wake("typed by a person"), "delivery": None}
        await client.post(f"/v1/sessions/{sid}/events", json=typed)
        await poll_until_async(
            lambda: len(harness.posted_bodies) == 1 and not app.state.active_turns,
            timeout_s=budget(5),
        )
        # The terminal still reads idle: its busy edge has not arrived yet.
        assert app.state.native_pane_status.get(sid) in (None, "idle")

        held = await client.post(f"/v1/sessions/{sid}/events", json=_wake())
        assert held.json()["status"] == "held"

        await client.post(
            f"/v1/sessions/{sid}/events",
            json={"type": "external_session_status", "data": {"status": "idle"}},
        )
        await poll_until_async(lambda: len(harness.posted_bodies) == 2, timeout_s=budget(5))


@pytest.mark.asyncio
async def test_held_messages_expire_and_close_stops_waiters() -> None:
    now = [0.0]
    released: list[str] = []

    async def blocked(_session_id: str) -> str | None:
        return "running"

    async def release(_session_id: str, body: dict[str, Any]) -> None:
        released.append(body["text"])

    holds = NextTurnHolds(
        blocked=blocked, release=release, poll_interval_s=0, max_hold_s=600, clock=lambda: now[0]
    )
    holds.hold("s", {"text": "old"}, reason="running")
    now[0] = 300.0
    holds.hold("s", {"text": "newer"}, reason="running")
    now[0] = 650.0
    await poll_until_async(lambda: len(holds.held("s")) == 1, timeout_s=budget(5))
    assert [body["text"] for body in holds.held("s")] == ["newer"]
    assert released == []

    holds.hold("t", {"text": "other"}, reason="running")
    waiters = holds.close()
    assert waiters
    await asyncio.gather(*waiters, return_exceptions=True)
    assert holds.held("s") == [] and holds.held("t") == []


def _scripted_harness() -> _ScriptedHarnessClient:
    return _ScriptedHarnessClient(
        [
            _sse({"type": "response.created", "response": {"id": "resp_1"}}),
            _sse({"type": "response.completed", "response": {"id": "resp_1"}}),
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness_name", ["claude-native", "codex-native", "pi-native"])
@pytest.mark.parametrize(
    ("first", "running_edge", "grace_s", "held"),
    [
        ("typed by a person", True, 0.0, True),
        ("typed by a person", False, 0.0, False),
        ("typed by a person", False, 60.0, True),
        ("/cost", False, 60.0, False),
    ],
    ids=["turn-running", "no-running-edge-after-grace", "within-grace", "slash-command"],
)
async def test_a_delivery_holds_wakes_only_while_its_turn_can_still_be_running(
    monkeypatch: pytest.MonkeyPatch,
    harness_name: str,
    first: str,
    running_edge: bool,
    grace_s: float,
    held: bool,
) -> None:
    """A command that starts no turn, or a lost edge, can't keep a session busy forever.

    Only the terminal's own running edge counts: the runner's own ``running``
    publish when it delivers a codex turn says nothing about the terminal.
    """
    monkeypatch.setattr(runner_app, "DELIVERED_TURN_GRACE_S", grace_s)
    monkeypatch.setattr(
        "omnigent.harnesses.claude_native.bridge.has_pending_user_prompt", lambda _: False
    )

    async def bridge_id(**_: Any) -> str:
        return "bridge"

    monkeypatch.setattr(runner_app, "_claude_native_bridge_id_for_session", bridge_id)
    harness = _scripted_harness()
    app = _native_app(harness, monkeypatch, name=harness_name)
    sid = uuid.uuid4().hex
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        await client.post(f"/v1/sessions/{sid}/events", json={**_wake(first), "delivery": None})
        await poll_until_async(
            lambda: len(harness.posted_bodies) == 1 and not app.state.active_turns,
            timeout_s=budget(5),
        )
        if running_edge:
            await client.post(
                f"/v1/sessions/{sid}/events",
                json={"type": "external_session_status", "data": {"status": "running"}},
            )
        app.state.native_pane_status[sid] = "idle"  # a stale read, not an idle edge

        response = await client.post(f"/v1/sessions/{sid}/events", json=_wake())

    assert (response.json().get("status") == "held") is held


def test_runner_shutdown_drops_held_wakes(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _native_app(_scripted_harness(), monkeypatch)
    closed: list[bool] = []
    monkeypatch.setattr(app.state.next_turn_holds, "close", lambda: closed.append(True) or [])

    app.state.drain_session_streams()

    assert closed == [True]


@pytest.mark.asyncio
async def test_the_server_can_take_back_a_held_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Stop that overtook the post: the runner forgets that one queued wake."""
    harness = _scripted_harness()
    app = _native_app(harness, monkeypatch)
    sid = uuid.uuid4().hex
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        app.state.native_pane_status[sid] = "running"
        await client.post(f"/v1/sessions/{sid}/events", json={**_wake("a"), "pending_id": "p_a"})
        await client.post(f"/v1/sessions/{sid}/events", json={**_wake("b"), "pending_id": "p_b"})

        response = await client.post(
            f"/v1/sessions/{sid}/events",
            json={"type": "drop_next_turn_input", "pending_id": "p_a"},
        )

        assert response.json() == {"dropped": 1}
        assert [body["pending_id"] for body in app.state.next_turn_holds.held(sid)] == ["p_b"]


@pytest.mark.asyncio
async def test_taking_back_a_wake_leaves_other_queued_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _native_app(_scripted_harness(), monkeypatch)
    sid = uuid.uuid4().hex
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        typed = {**_wake("typed"), "delivery": None, "pending_id": "p_a"}
        app.state.session_message_buffers[sid] = [typed, {**_wake("wake"), "pending_id": "p_a"}]

        response = await client.post(
            f"/v1/sessions/{sid}/events",
            json={"type": "drop_next_turn_input", "pending_id": "p_a"},
        )

    assert response.json() == {"dropped": 1}
    assert app.state.session_message_buffers[sid] == [typed]


@pytest.mark.asyncio
async def test_claude_status_file_running_edge_keeps_a_delivered_turn_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The status poller's running edge (not only a forwarded one) marks the turn running."""
    monkeypatch.setattr(runner_app, "DELIVERED_TURN_GRACE_S", 0.0)
    monkeypatch.setattr(
        "omnigent.harnesses.claude_native.bridge.has_pending_user_prompt", lambda _: False
    )

    async def bridge_id(**_: Any) -> str:
        return "bridge"

    monkeypatch.setattr(runner_app, "_claude_native_bridge_id_for_session", bridge_id)
    harness = _scripted_harness()
    app = _native_app(harness, monkeypatch, name="claude-native")
    sid = uuid.uuid4().hex
    registry = app.state.session_resource_registry
    async with _runner_client(app) as client:
        await client.post("/v1/sessions", json={"session_id": sid, "agent_id": uuid.uuid4().hex})
        await client.post(f"/v1/sessions/{sid}/events", json={**_wake("typed"), "delivery": None})
        await poll_until_async(
            lambda: len(harness.posted_bodies) == 1 and not app.state.active_turns,
            timeout_s=budget(5),
        )
        # Claude's status file flips to busy: the runner's status poller publishes it.
        registry._session_status_publisher(sid, "running", None)
        app.state.native_pane_status[sid] = "idle"  # a stale read, not an idle edge

        response = await client.post(f"/v1/sessions/{sid}/events", json=_wake())

    assert response.json().get("status") == "held"
