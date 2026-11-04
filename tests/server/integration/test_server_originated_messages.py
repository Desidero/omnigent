"""Messages the server sends into a session, and the wake service that sends them.

Only the server may set ``origin`` and ``delivery`` on a message: a client
that tries is refused. A server message is stored with its origin and reaches
the runner with ``delivery: "next_turn_only"`` so it is never steered into a
running turn.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from omnigent.entities.conversation import MessageData, NewConversationItem, SlashCommandData
from omnigent.runner.identity import RUNNER_TUNNEL_TOKEN_HEADER
from omnigent.runtime import pending_inputs
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import LEVEL_EDIT
from omnigent.server.extension_status_observers import (
    ExtensionNotEnabledError,
    ExtensionStatusObservers,
)
from omnigent.server.routes._sessions.common import _session_status_cache
from omnigent.server.routes._sessions.orchestration import _dispatch_in_flight
from omnigent.server.schemas import SessionStartupInput
from omnigent.server.server_messages import SessionNotReadyError
from omnigent.server.session_status_observers import SessionStatusObservation
from omnigent.server.session_wake import (
    SessionWakeService,
    WakeOutcome,
    WakeRequest,
    WakeStop,
)
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from tests.server.helpers import build_agent_bundle, create_test_agent

_ORIGIN = {"kind": "automation", "source": "ext:acme.goal-loop", "on_behalf_of": "alice"}
_CONTENT = [{"type": "input_text", "text": "[Automation: Goal loop] PR #7 failed CI"}]


def _stub_runner(monkeypatch: pytest.MonkeyPatch, forwarded: list[dict[str, Any]]) -> Any:
    def accept(request: httpx.Request) -> httpx.Response:
        forwarded.append(json.loads(request.content))
        return httpx.Response(202, json={"queued": True})

    fake_runner = httpx.AsyncClient(transport=httpx.MockTransport(accept), base_url="http://r")

    async def get_runner_client(*_: Any, **__: Any) -> httpx.AsyncClient:
        return fake_runner

    monkeypatch.setattr("omnigent.server.routes.sessions._get_runner_client", get_runner_client)
    return fake_runner


async def _new_session(client: httpx.AsyncClient) -> str:
    agent = await create_test_agent(client)
    create = await client.post("/v1/sessions", json={"agent_id": agent["id"]})
    assert create.status_code == 201, create.text
    return create.json()["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [{"origin": _ORIGIN}, {"delivery": "next_turn_only"}],
    ids=["origin", "delivery"],
)
@pytest.mark.parametrize("path", ["event", "initial_items", "external_item"])
async def test_client_cannot_set_server_only_message_fields(
    client: httpx.AsyncClient, extra: dict[str, Any], path: str
) -> None:
    message = {"role": "user", "content": _CONTENT, **extra}
    if path == "initial_items":
        agent = await create_test_agent(client)
        response = await client.post(
            "/v1/sessions",
            json={
                "agent_id": agent["id"],
                "initial_items": [{"type": "message", "data": message}],
            },
        )
    else:
        session_id = await _new_session(client)
        event = (
            {"type": "message", "data": message}
            if path == "event"
            else {
                "type": "external_conversation_item",
                "data": {"item_type": "message", "item_data": message},
            }
        )
        response = await client.post(f"/v1/sessions/{session_id}/events", json=event)

    assert response.status_code == 422, response.text
    assert "set only by the server" in response.text


@pytest.mark.parametrize("extra", [{"origin": _ORIGIN}, {"delivery": "next_turn_only"}])
def test_startup_input_cannot_set_server_only_message_fields(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="set only by the server"):
        SessionStartupInput(type="message", data={"role": "user", "content": _CONTENT, **extra})


@pytest.mark.asyncio
async def test_server_message_is_stored_with_origin_and_forwarded_next_turn_only(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    forwarded: list[dict[str, Any]] = []
    fake_runner = _stub_runner(monkeypatch, forwarded)
    try:
        session_id = await _new_session(client)
        ack = await app.state.server_message_dispatch(
            app, session_id, None, _CONTENT, origin=_ORIGIN
        )
    finally:
        await fake_runner.aclose()

    assert ack["queued"] is True
    [turn] = [body for body in forwarded if body.get("type") == "message"]
    assert turn["delivery"] == "next_turn_only"
    items = (await client.get(f"/v1/sessions/{session_id}/items")).json()["data"]
    [message] = [item for item in items if item["type"] == "message"]
    assert message["id"] == turn["persisted_item_id"]
    assert message["origin"] == _ORIGIN


@pytest.mark.asyncio
async def test_server_message_waits_for_a_starting_session(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session still starting queues inputs as their sender; a wake retries later."""
    session_id = await _new_session(client)

    class _Starting:
        async def accepts(self, *_: Any) -> bool:
            return True

    monkeypatch.setattr(app.state, "startup_inputs", _Starting(), raising=False)

    with pytest.raises(SessionNotReadyError):
        await app.state.server_message_dispatch(app, session_id, None, _CONTENT, origin=_ORIGIN)


async def _bundled_session(client: httpx.AsyncClient, owner: str) -> str:
    response = await client.post(
        "/v1/sessions",
        data={"metadata": "{}"},
        files={"bundle": ("agent.tar.gz", build_agent_bundle(name="a"), "application/gzip")},
        headers={"X-Forwarded-Email": owner},
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


@pytest.mark.asyncio
async def test_wake_posts_as_the_owner_while_the_enabler_keeps_edit(
    auth_app: FastAPI, auth_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enabler's EDIT is rechecked; the message is attributed to the session owner."""
    forwarded: list[dict[str, Any]] = []
    fake_runner = _stub_runner(monkeypatch, forwarded)
    service: SessionWakeService = auth_app.state.session_wake
    try:
        session_id = await _bundled_session(auth_client, "owner@example.com")
        grant = await auth_client.put(
            f"/v1/sessions/{session_id}/permissions",
            json={"user_id": "bob@example.com", "level": LEVEL_EDIT},
            headers={"X-Forwarded-Email": "owner@example.com"},
        )
        assert grant.status_code == 200, grant.text
        wake = WakeRequest(
            session_id, "core:test", "bob@example.com", "CI failed", generation=None
        )

        assert await service.request(wake) is WakeOutcome.QUEUED
        await service.settle()

        revoke = await auth_client.delete(
            f"/v1/sessions/{session_id}/permissions/bob@example.com",
            headers={"X-Forwarded-Email": "owner@example.com"},
        )
        assert revoke.status_code in (200, 204), revoke.text
        later = WakeRequest(session_id, "core:test", "bob@example.com", "again", generation=None)
        assert await service.request(later) is WakeOutcome.NOT_AUTHORIZED
    finally:
        await fake_runner.aclose()

    [turn] = [body for body in forwarded if body.get("type") == "message"]
    assert turn["delivery"] == "next_turn_only"
    items = (
        await auth_client.get(
            f"/v1/sessions/{session_id}/items", headers={"X-Forwarded-Email": "owner@example.com"}
        )
    ).json()["data"]
    [message] = [item for item in items if item["type"] == "message"]
    assert message["created_by"] == "owner@example.com"
    assert message["origin"]["on_behalf_of"] == "bob@example.com"
    assert message["content"][0]["text"].startswith(
        "[Automation: core:test · on behalf of bob@example.com]"
    )


@pytest.mark.asyncio
async def test_wake_waits_while_the_server_sees_a_turn(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    forwarded: list[dict[str, Any]] = []
    fake_runner = _stub_runner(monkeypatch, forwarded)
    service: SessionWakeService = app.state.session_wake
    try:
        session_id = await _new_session(client)
        _session_status_cache[session_id] = "running"
        await service.request(WakeRequest(session_id, "core:test", None, "hi", generation=None))
        await service.settle()
        assert [body for body in forwarded if body.get("type") == "message"] == []

        _session_status_cache[session_id] = "idle"
        service.observe(SessionStatusObservation(session_id, "running", "idle", True))
        await service.settle()
    finally:
        _session_status_cache.pop(session_id, None)
        await fake_runner.aclose()

    assert [body["delivery"] for body in forwarded if body.get("type") == "message"] == [
        "next_turn_only"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("extensions", "enabled"),
    [({"acme.x": {"enabled": True}}, True), ({}, False), ({"acme.x": {"enabled": False}}, False)],
    ids=["enabled", "not-listed", "disabled"],
)
async def test_extension_sources_and_observers_follow_the_operator_config(
    runtime_init: None,
    db_uri: str,
    tmp_path: Path,
    extensions: dict[str, Any],
    enabled: bool,
) -> None:
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    conversation_store = SqlAlchemyConversationStore(db_uri)
    app = create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=conversation_store,
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        server_config={"extensions": extensions},
    )
    session_id = conversation_store.create_conversation().id
    service: SessionWakeService = app.state.session_wake
    observers: ExtensionStatusObservers = app.state.extension_status_observers
    # A busy session keeps the queued wake from being posted.
    _session_status_cache[session_id] = "running"
    observers.start()
    try:
        outcome = await service.request(
            WakeRequest(session_id, "ext:acme.x", None, "hi", generation=None)
        )
        await service.settle()
        if enabled:
            observers.subscribe("acme.x", _ignore_observation)
        else:
            with pytest.raises(ExtensionNotEnabledError):
                observers.subscribe("acme.x", _ignore_observation)
    finally:
        _session_status_cache.pop(session_id, None)
        await observers.aclose()

    assert outcome is (WakeOutcome.QUEUED if enabled else WakeOutcome.NOT_AUTHORIZED)


async def _ignore_observation(_observation: SessionStatusObservation) -> None:
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["interrupt", "stop_session"])
@pytest.mark.parametrize("by_agent", [False, True], ids=["person", "agent"])
async def test_a_person_stopping_the_session_drops_its_pending_wake(
    app: FastAPI,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    by_agent: bool,
) -> None:
    forwarded: list[dict[str, Any]] = []
    fake_runner = _stub_runner(monkeypatch, forwarded)
    service: SessionWakeService = app.state.session_wake
    stops: list[tuple[str, str, WakeStop]] = []
    service.add_stop_listener(lambda *stop: stops.append(stop))
    try:
        session_id = await _new_session(client)
        _session_status_cache[session_id] = "running"
        await service.request(WakeRequest(session_id, "core:test", None, "hi", generation=None))
        await service.settle()

        # An orchestrator's sys_cancel_task calls with its runner's token.
        headers = {RUNNER_TUNNEL_TOKEN_HEADER: "runner-token"} if by_agent else {}
        await client.post(
            f"/v1/sessions/{session_id}/events", json={"type": event_type}, headers=headers
        )
        _session_status_cache[session_id] = "idle"
        service.observe(SessionStatusObservation(session_id, "running", "idle", True))
        await service.settle()
    finally:
        _session_status_cache.pop(session_id, None)
        await fake_runner.aclose()

    reason = WakeStop.STOPPED_BY_AGENT if by_agent else WakeStop.STOPPED_BY_USER
    assert stops == [(session_id, "core:test", reason)]
    assert [body for body in forwarded if body.get("type") == "message"] == []


def _user_item(text: str, turn: str, *, hidden: bool = False) -> NewConversationItem:
    content = [{"type": "input_text", "text": text}]
    return NewConversationItem(
        type="message",
        response_id=turn,
        data=MessageData(role="user", content=content, is_meta=hidden),
    )


def _reply_item(text: str, turn: str) -> NewConversationItem:
    content = [{"type": "output_text", "text": text}]
    return NewConversationItem(
        type="message",
        response_id=turn,
        data=MessageData(role="assistant", content=content, agent="t"),
    )


def _items_after_wake(after_wake: str, wake_turn: str) -> list[NewConversationItem]:
    """What the transcript holds after a delivered wake, per scenario."""
    if after_wake == "wake-context":
        return [_user_item("<hook context>", wake_turn, hidden=True), _reply_item("ok", wake_turn)]
    if after_wake == "long-turn":
        return [_reply_item(f"step {step}", wake_turn) for step in range(250)]
    if after_wake == "person-skill":
        skill = SlashCommandData(agent="t", name="review", arguments="")
        return [
            NewConversationItem(type="slash_command", response_id="turn_skill", data=skill),
            _user_item("<skill body>", "turn_skill", hidden=True),
        ]
    if after_wake == "hidden-turn":
        return [
            _reply_item("ok", wake_turn),
            _user_item("<timer fired>", "turn_timer", hidden=True),
        ]
    return []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("by_agent", "after_wake", "turn_live", "stopped"),
    [
        (False, "nothing", True, True),
        (False, "wake-context", True, True),
        (False, "long-turn", True, True),
        (False, "person-message", True, False),
        (False, "person-skill", True, False),
        (False, "hidden-turn", True, False),
        (False, "nothing", False, False),
        (True, "nothing", True, False),
    ],
    ids=[
        "person-stops-wake-turn",
        "wake-with-its-context",
        "long-wake-turn",
        "person-message-after-wake",
        "person-skill-after-wake",
        "hidden-turn-after-wake",
        "idle-after-wake-turn",
        "agent",
    ],
)
async def test_stopping_the_turn_a_delivered_wake_started_stops_its_source(
    app: FastAPI,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_uri: str,
    by_agent: bool,
    after_wake: str,
    turn_live: bool,
    stopped: bool,
) -> None:
    forwarded: list[dict[str, Any]] = []
    fake_runner = _stub_runner(monkeypatch, forwarded)
    service: SessionWakeService = app.state.session_wake
    stops: list[tuple[str, str, WakeStop]] = []
    service.add_stop_listener(lambda *stop: stops.append(stop))
    store = SqlAlchemyConversationStore(db_uri)
    try:
        session_id = await _new_session(client)
        await service.request(WakeRequest(session_id, "core:test", None, "hi", generation=None))
        await service.settle()
        assert [body["delivery"] for body in forwarded if body.get("type") == "message"] == [
            "next_turn_only"
        ]
        wake_item = store.list_items(session_id, limit=1, order="desc", type="message").data[0]
        assert wake_item.data.origin is not None  # type: ignore[union-attr]
        if after_wake == "person-message":
            posted = await client.post(
                f"/v1/sessions/{session_id}/events",
                json={
                    "type": "message",
                    "data": {"role": "user", "content": [{"type": "input_text", "text": "x"}]},
                },
            )
            assert posted.status_code < 300, posted.text
        later = _items_after_wake(after_wake, wake_item.response_id)
        if later:
            store.append(session_id, later)
        if turn_live:
            _session_status_cache[session_id] = "running"

        headers = {RUNNER_TUNNEL_TOKEN_HEADER: "runner-token"} if by_agent else {}
        await client.post(
            f"/v1/sessions/{session_id}/events", json={"type": "interrupt"}, headers=headers
        )
        await service.settle()
    finally:
        _session_status_cache.pop(session_id, None)
        await fake_runner.aclose()

    assert stops == ([(session_id, "core:test", WakeStop.STOPPED_BY_USER)] if stopped else [])


async def _deliver_wake(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, list[tuple[str, str, WakeStop]], httpx.AsyncClient]:
    """A session whose latest input is a delivered ``core:test`` wake, and its stops."""
    fake_runner = _stub_runner(monkeypatch, [])
    service: SessionWakeService = app.state.session_wake
    stops: list[tuple[str, str, WakeStop]] = []
    service.add_stop_listener(lambda *stop: stops.append(stop))
    session_id = await _new_session(client)
    await service.request(WakeRequest(session_id, "core:test", None, "hi", generation=None))
    await service.settle()
    _session_status_cache.pop(session_id, None)
    return session_id, stops, fake_runner


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "starting", "stopped"),
    [
        ("idle", "person-message", False),
        ("idle", "dispatch", False),
        ("running", "person-message", False),
        ("running", "dispatch", False),
        # A queued wake is no person's input: the running turn is still the stored wake's,
        # and an idle session still has no turn to stop.
        ("running", "wake", True),
        ("idle", "wake", False),
    ],
    ids=[
        "idle-message-parked",
        "idle-dispatching",
        "running-message-parked",
        "running-dispatching",
        "wake-parked",
        "idle-wake-parked",
    ],
)
async def test_a_message_on_its_way_to_the_runner_is_newer_than_the_wake(
    app: FastAPI,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    starting: str,
    stopped: bool,
) -> None:
    session_id, stops, fake_runner = await _deliver_wake(app, client, monkeypatch)
    _session_status_cache[session_id] = status
    content = [{"type": "input_text", "text": "next please"}]
    pending_id = None
    try:
        if starting == "dispatch":
            _dispatch_in_flight[session_id] = 1
        else:
            origin = {"kind": "automation", "source": "core:test"} if starting == "wake" else None
            pending_id = pending_inputs.record(session_id, content, created_by=None, origin=origin)
        await client.post(f"/v1/sessions/{session_id}/events", json={"type": "interrupt"})
        await app.state.session_wake.settle()
    finally:
        _session_status_cache.pop(session_id, None)
        _dispatch_in_flight.pop(session_id, None)
        if pending_id is not None:
            pending_inputs.resolve(session_id, pending_id)
        await fake_runner.aclose()

    assert stops == ([(session_id, "core:test", WakeStop.STOPPED_BY_USER)] if stopped else [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "cached", "persisted", "stopped"),
    [
        ("interrupt", None, "running", True),
        ("interrupt", None, "waiting", True),
        ("interrupt", None, "idle", False),
        ("stop_session", None, "running", True),
        ("stop_session", "running", None, True),
        ("interrupt", "waiting", None, True),
    ],
    ids=[
        "persisted-running",
        "persisted-waiting",
        "persisted-idle",
        "stop-session-persisted-running",
        "stop-session-cached-running",
        "cached-waiting",
    ],
)
async def test_a_stop_reads_whether_the_wake_turn_runs_from_cache_or_row(
    app: FastAPI,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_uri: str,
    event_type: str,
    cached: str | None,
    persisted: str | None,
    stopped: bool,
) -> None:
    session_id, stops, fake_runner = await _deliver_wake(app, client, monkeypatch)
    if persisted is not None:
        # A replica without a cached status reads the row the route loaded.
        SqlAlchemyConversationStore(db_uri).set_session_live_status(session_id, persisted)
    if cached is not None:
        _session_status_cache[session_id] = cached
    try:
        await client.post(f"/v1/sessions/{session_id}/events", json={"type": event_type})
        await app.state.session_wake.settle()
    finally:
        _session_status_cache.pop(session_id, None)
        await fake_runner.aclose()

    assert stops == ([(session_id, "core:test", WakeStop.STOPPED_BY_USER)] if stopped else [])


@pytest.mark.asyncio
async def test_archived_sessions_are_not_woken(app: FastAPI, client: httpx.AsyncClient) -> None:
    service: SessionWakeService = app.state.session_wake
    stops: list[tuple[str, str, WakeStop]] = []
    service.add_stop_listener(lambda *stop: stops.append(stop))
    session_id = await _new_session(client)
    archived = await client.patch(f"/v1/sessions/{session_id}", json={"archived": True})
    assert archived.status_code == 200, archived.text

    await service.request(WakeRequest(session_id, "core:test", None, "hi", generation=None))
    await service.settle()

    assert stops == [(session_id, "core:test", WakeStop.SESSION_GONE)]
