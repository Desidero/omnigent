"""A wake sent on a stale idle check reaches the agent once, as the next turn.

The real server routes forward to a real runner app (in process, over ASGI)
whose scripted SDK harness is held mid-turn. The server is made to believe the
session is idle while the runner still runs turn 1, which is the race the
``next_turn_only`` rule closes: the runner must buffer the wake, never inject it
into turn 1, and run it once as turn 2.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from omnigent.runner import create_runner_app
from omnigent.server.routes._sessions.common import _session_status_cache
from omnigent.server.session_status_observers import SessionStatusObservation
from omnigent.server.session_wake import SessionWakeService, WakeRequest
from omnigent.spec.types import AgentSpec
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.runner.conftest import _FakeProcessManager, _ScriptedHarnessClient, _sse
from tests.runner.helpers import NullServerClient
from tests.server.helpers import create_test_agent


class _GatedHarness(_ScriptedHarnessClient):
    """Holds the first turn open until ``gate`` is set; records live injections."""

    def __init__(self, gate: asyncio.Event) -> None:
        super().__init__([])
        self.gate = gate

    def stream(self, method: str, url: str, *, json: dict[str, Any], timeout: Any) -> Any:
        del method, url, timeout
        # Snapshot: the runner keeps appending to the history this body shares.
        self.posted_bodies.append(copy.deepcopy(json))
        turn = len(self.posted_bodies)
        gate = self.gate

        class _Handle:
            status_code = 200

            async def aiter_text(self) -> AsyncIterator[str]:
                yield _sse({"type": "response.created", "response": {"id": f"resp_{turn}"}})
                if turn == 1:
                    await gate.wait()
                yield _sse({"type": "response.completed", "response": {"id": f"resp_{turn}"}})

        class _Ctx:
            status_code = 200

            async def __aenter__(self) -> _Handle:
                return _Handle()

            async def __aexit__(self, *_: Any) -> None:
                return None

        return _Ctx()

    async def post(self, url: str, *, json: dict[str, Any], timeout: Any = None) -> Any:
        del url, timeout
        self.patched_events.append(json)

        class _Response:
            status_code = 200
            headers: dict[str, str] = {}
            content = b""

        return _Response()


def _text_of(body: dict[str, Any]) -> str:
    return repr(body)


@pytest.mark.asyncio
async def test_wake_on_a_stale_idle_check_runs_once_as_the_next_turn(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = asyncio.Event()
    harness = _GatedHarness(gate)

    async def resolver(agent_id: str, session_id: str | None = None) -> AgentSpec:
        return AgentSpec(spec_version=1, name="t")

    runner_app = create_runner_app(
        process_manager=_FakeProcessManager(harness),  # type: ignore[arg-type]
        spec_resolver=resolver,
        server_client=NullServerClient(),  # type: ignore[arg-type]
    )
    runner = httpx.AsyncClient(transport=httpx.ASGITransport(app=runner_app), base_url="http://r")

    async def get_runner_client(*_: Any, **__: Any) -> httpx.AsyncClient:
        return runner

    monkeypatch.setattr("omnigent.server.routes.sessions._get_runner_client", get_runner_client)
    service: SessionWakeService = app.state.session_wake
    try:
        agent = await create_test_agent(client)
        created = await client.post("/v1/sessions", json={"agent_id": agent["id"]})
        session_id = created.json()["id"]
        typed = await client.post(
            f"/v1/sessions/{session_id}/events",
            json={
                "type": "message",
                "data": {"role": "user", "content": [{"type": "input_text", "text": "first"}]},
            },
        )
        assert typed.status_code == 202, typed.text
        await poll_until_async(lambda: len(harness.posted_bodies) == 1, timeout_s=budget(5))

        # The server's view goes stale: it sees idle while turn 1 still runs.
        _session_status_cache[session_id] = "idle"
        await service.request(
            WakeRequest(session_id, "core:test", None, "PR #7 failed CI", generation=None)
        )
        service.observe(SessionStatusObservation(session_id, "running", "idle", True))
        await service.settle()
        assert service.status(session_id, "core:test").wakes == 1  # type: ignore[union-attr]
        assert runner_app.state.session_message_buffers.get(session_id)

        gate.set()
        await poll_until_async(lambda: len(harness.posted_bodies) == 2, timeout_s=budget(5))
        await poll_until_async(lambda: not runner_app.state.active_turns, timeout_s=budget(5))
    finally:
        _session_status_cache.pop(session_id, None)
        gate.set()
        await runner.aclose()

    assert harness.patched_events == [], "a wake must never be injected into a running turn"
    first, wake = harness.posted_bodies
    assert "PR #7 failed CI" not in _text_of(first)
    assert "PR #7 failed CI" in _text_of(wake)
    assert wake["delivery"] == "next_turn_only"
