"""Messages the server sends into a session carry their origin and delivery rule.

Only the server may set ``origin`` and ``delivery`` on a message: a client
that tries is refused. A server message is stored with its origin and reaches
the runner with ``delivery: "next_turn_only"`` so it is never steered into a
running turn.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from omnigent.server.schemas import SessionStartupInput
from omnigent.server.server_messages import SessionNotReadyError
from tests.server.helpers import create_test_agent

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
