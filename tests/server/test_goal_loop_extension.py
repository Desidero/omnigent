"""The goal-loop extension, activated in a real server with a stubbed PR reader.

Turning on "All PRs" through the extension's command, then an idle edge, gives
one attributed wake that lists only the red PR; once that PR is green the
goal is met and the session row's published field changes.

What a connected host would provide is stubbed: the session is bound to a host
the registry reports as connected here, and the panel's per-PR reader behind
``ctx.pull_request_info`` answers from a dict.
"""

from __future__ import annotations

import asyncio
import copy
import functools
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from omnigent.extensions import ExtensionPluginState
from omnigent.extensions.published_fields import PublishedFieldView, configure_published_fields
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server import extension_activation, session_status_observers
from omnigent.server.app import create_app
from omnigent.server.routes._sessions.common import _session_status_cache
from omnigent.server.session_pull_requests import open_store
from omnigent.server.session_status_observers import SessionStatusObservation
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.session_pull_request_store import PullRequestReport
from tests.server.helpers import create_test_agent

pytestmark = pytest.mark.asyncio

_SOURCE = Path(__file__).parents[2] / "ext-demo" / "extensions" / "goal-loop" / "src"
_EXT = "desidero.goal-loop"
_PACKAGE = "desidero_goal_loop"
_HEAD = "a" * 40
_HOST = "a" * 32
# What the host registry holds for a connected host, as far as these paths read it.
_CONNECTED = SimpleNamespace(hello=SimpleNamespace(version="test"))


def _url(number: int) -> str:
    return f"https://github.com/org/repo/pull/{number}"


def _info(number: int, *, failing: tuple[str, ...] = (), head: str = _HEAD) -> dict[str, Any]:
    runs = [{"name": name, "bucket": "failing", "url": f"https://ci/{name}"} for name in failing]
    runs = runs or [{"name": "tests", "bucket": "passing", "url": "https://ci/tests"}]
    return {
        "object": "session.github.info",
        "pr": {
            "number": number,
            "url": _url(number),
            "state": "OPEN",
            "author": "agent-bot",
            "base_ref": "main",
            "head_sha": head,
            "checks": {
                "passing": 0 if failing else 1,
                "failing": len(failing),
                "pending": 0,
                "total": len(runs),
                "runs": runs,
            },
            "comments": [],
            "reviewers": [],
            "mergeable": True,
        },
    }


@pytest.fixture(autouse=True)
def _runtime(runtime_init: None) -> Any:
    yield
    configure_published_fields(PublishedFieldView())


@dataclass
class _Server:
    app: FastAPI
    store: SqlAlchemyConversationStore
    client: httpx.AsyncClient
    infos: dict[str, dict[str, Any]]
    forwarded: list[dict[str, Any]]
    # PR URLs the extension read, and the goal loops it started.
    reads: list[str]
    loops: list[Any]


def _install(monkeypatch: pytest.MonkeyPatch, loops: list[Any]) -> None:
    """Load the extension from its source tree and stub what a host would provide."""
    monkeypatch.syspath_prepend(str(_SOURCE))
    # Installed from a wheel, its modules would be the distribution's files.
    monkeypatch.setattr(
        extension_activation,
        "module_in_distribution",
        lambda loaded, _distribution: loaded.__name__.startswith(_PACKAGE),
    )

    # Check right after an idle edge instead of a few seconds later.
    import desidero_goal_loop.server as server_module

    start_loop = functools.partial(server_module.GoalLoop, hint_delay_s=0)

    def goal_loop(*args: Any, **kwargs: Any) -> Any:
        loops.append(start_loop(*args, **kwargs))
        return loops[-1]

    monkeypatch.setattr(server_module, "GoalLoop", goal_loop)


def _stub_runner(monkeypatch: pytest.MonkeyPatch, forwarded: list[dict[str, Any]]) -> Any:
    def accept(request: httpx.Request) -> httpx.Response:
        forwarded.append(json.loads(request.content))
        return httpx.Response(202, json={"queued": True})

    runner = httpx.AsyncClient(transport=httpx.MockTransport(accept), base_url="http://r")

    async def get_runner_client(*_: Any, **__: Any) -> httpx.AsyncClient:
        return runner

    monkeypatch.setattr("omnigent.server.routes.sessions._get_runner_client", get_runner_client)
    return runner


@asynccontextmanager
async def _serve(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[_Server]:
    infos: dict[str, dict[str, Any]] = {}
    forwarded: list[dict[str, Any]] = []
    reads: list[str] = []
    loops: list[Any] = []
    _install(monkeypatch, loops)
    from desidero_goal_loop.plugin import get_manifest

    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    store = SqlAlchemyConversationStore(db_uri)
    app = create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=store,
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        extension_state=ExtensionPluginState(
            manifests=(get_manifest(),), asset_packages={_EXT: _PACKAGE}
        ),
        server_config={"extensions": {_EXT: {"enabled": True}}},
    )
    runner = _stub_runner(monkeypatch, forwarded)

    async def pull_request_info(_session_id: str, pr_url: str) -> dict[str, Any] | None:
        reads.append(pr_url)
        info = infos.get(pr_url)
        return copy.deepcopy(info) if info is not None else None

    try:
        async with app.router.lifespan_context(app):
            app.state.pull_request_info = pull_request_info
            monkeypatch.setattr(
                app.state.host_registry,
                "get",
                lambda host_id, workspace_id=None: _CONNECTED if host_id == _HOST else None,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield _Server(app, store, client, infos, forwarded, reads, loops)
    finally:
        await runner.aclose()


async def _until(check: Callable[[], Awaitable[object]], timeout_s: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not await check():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.05)


async def test_all_prs_wakes_once_for_the_red_pr_and_meets_the_goal(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _serve(db_uri, tmp_path, monkeypatch) as server:
        assert server.app.state.extension_activations.records()[_EXT].state == "active"
        agent = await create_test_agent(server.client)
        # A session on a host connected to this replica, so this replica owns it.
        session_id = server.store.create_conversation(
            agent_id=agent["id"], host_id=_HOST, workspace="/w"
        ).id
        # The session links two PRs, as its host reported them; #7 is red.
        open_store(server.store).apply_report(
            session_id,
            [
                PullRequestReport(_url(n), "github", "github.com", "org/repo", n, "created", 1, 1)
                for n in (7, 9)
            ],
            complete=True,
        )
        server.infos[_url(7)] = _info(7, failing=("lint",))
        server.infos[_url(9)] = _info(9)

        async def fields() -> dict[str, str]:
            response = await server.client.get(f"/v1/sessions/{session_id}")
            return response.json().get("published_fields", {}).get(_EXT, {})

        def messages() -> list[dict[str, Any]]:
            return [body for body in server.forwarded if body.get("type") == "message"]

        _session_status_cache[session_id] = "running"
        try:
            # A person turns on "All PRs in this session" while a turn runs.
            response = await server.client.post(
                f"/v1/sessions/{session_id}/extensions/{_EXT}/commands/{_EXT}.all",
                json={"arguments": {"mode": "on"}},
            )
            assert response.status_code == 200, response.text
            await _until(lambda: _equals(fields(), "goal", "unmet"))
            assert (await fields())["summary"] == "Watching 1 PR"
            await server.app.state.session_wake.settle()
            assert messages() == []  # Never mid-turn.

            # The turn ends: the wake goes out once.
            _session_status_cache[session_id] = "idle"
            session_status_observers.observe(
                SessionStatusObservation(session_id, "running", "idle", True)
            )
            await _until(_async(lambda: messages()))
            await server.app.state.session_wake.settle()
            [message] = messages()
            assert message["delivery"] == "next_turn_only"

            items = (await server.client.get(f"/v1/sessions/{session_id}/items")).json()["data"]
            [stored] = [item for item in items if item["type"] == "message"]
            assert stored["origin"]["source"] == f"ext:{_EXT}"
            assert stored["origin"]["label"] == "Goal loop"
            text = stored["content"][0]["text"]
            assert text.startswith("[Automation: Goal loop")
            assert "#7 needs attention" in text and "Check failed: lint" in text
            assert _url(9) not in text

            # The agent pushes a fix; at its next idle edge #7 is green.
            server.infos[_url(7)] = _info(7, head="b" * 40)
            _session_status_cache[session_id] = "running"
            session_status_observers.observe(
                SessionStatusObservation(session_id, "idle", "running", True)
            )
            _session_status_cache[session_id] = "idle"
            session_status_observers.observe(
                SessionStatusObservation(session_id, "running", "idle", True)
            )
            await _until(lambda: _equals(fields(), "goal", "met"))
            assert (await fields())["summary"] == "PR goals met"
            assert len(messages()) == 1

            labels = server.store.get_conversation(session_id).labels
            assert labels[f"ext.{_EXT}.goal"] == "met"
            view = await server.client.get(
                f"/v1/sessions/{session_id}/extensions/{_EXT}/state/goals"
            )
            goals = json.loads(view.json()["value"])
            assert [(item["label"], item["status"]) for item in goals["items"]] == [
                ("#7", "met"),
                ("#9", "met"),
            ]
        finally:
            _session_status_cache.pop(session_id, None)


@pytest.mark.parametrize("delivered", [False, True], ids=["wake-waiting", "wake-turn"])
async def test_a_persons_stop_pauses_the_goal_on_its_page(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivered: bool
) -> None:
    async with _serve(db_uri, tmp_path, monkeypatch) as server:
        agent = await create_test_agent(server.client)
        session_id = server.store.create_conversation(
            agent_id=agent["id"], host_id=_HOST, workspace="/w"
        ).id
        open_store(server.store).apply_report(
            session_id,
            [PullRequestReport(_url(7), "github", "github.com", "org/repo", 7, "created", 1, 1)],
            complete=True,
        )
        server.infos[_url(7)] = _info(7, failing=("lint",))

        async def fields() -> dict[str, str]:
            response = await server.client.get(f"/v1/sessions/{session_id}")
            return response.json().get("published_fields", {}).get(_EXT, {})

        def messages() -> list[dict[str, Any]]:
            return [body for body in server.forwarded if body.get("type") == "message"]

        def idle_edge() -> None:
            _session_status_cache[session_id] = "idle"
            session_status_observers.observe(
                SessionStatusObservation(session_id, "running", "idle", True)
            )

        _session_status_cache[session_id] = "running"
        try:
            response = await server.client.post(
                f"/v1/sessions/{session_id}/extensions/{_EXT}/commands/{_EXT}.all",
                json={"arguments": {"mode": "on"}},
            )
            assert response.status_code == 200, response.text
            await _until(lambda: _equals(fields(), "goal", "unmet"))
            if delivered:
                # The wake's turn starts; the person stops it.
                idle_edge()
                await _until(_async(lambda: messages()))
                _session_status_cache[session_id] = "running"

            stop = await server.client.post(
                f"/v1/sessions/{session_id}/events", json={"type": "interrupt"}
            )
            assert stop.status_code < 300, stop.text
            await _until(lambda: _equals(fields(), "goal", "paused"))
            assert (await fields())["summary"] == "PR goal paused"
            view = await server.client.get(
                f"/v1/sessions/{session_id}/extensions/{_EXT}/state/goals"
            )
            [item] = json.loads(view.json()["value"])["items"]
            assert (item["status"], item["note"], item["wakes"]) == (
                "paused",
                "Paused by Stop — Resume to continue",
                1 if delivered else 0,
            )

            # Idle again: the stopped wake doesn't go out, and a check doesn't read the PR.
            idle_edge()
            await server.app.state.session_wake.settle()
            assert len(messages()) == (1 if delivered else 0)
            [loop] = server.loops
            server.reads.clear()
            await loop.reconcile_all()
            assert server.reads == [] and (await fields())["goal"] == "paused"

            # Resume from the page: the goal carries on, and the failure the stopped
            # (or dropped) wake was about goes out again.
            response = await server.client.post(
                f"/v1/sessions/{session_id}/extensions/{_EXT}/commands/{_EXT}.resume",
                json={"arguments": {"pr": "org/repo/7"}},
            )
            assert response.status_code == 200, response.text
            await _until(lambda: _equals(fields(), "goal", "unmet"))
            if delivered:
                # Offered again, not taken for a duplicate: it waits out the wake gap.
                status = server.app.state.session_wake.status(session_id, f"ext:{_EXT}")
                assert status is not None and status.pending and len(messages()) == 1
            else:
                await _until(_async(lambda: len(messages()) == 1))
                assert "Check failed: lint" in json.dumps(messages()[-1])
        finally:
            _session_status_cache.pop(session_id, None)


async def _equals(fields: Awaitable[dict[str, str]], key: str, value: str) -> bool:
    return (await fields).get(key) == value


def _async(check: Callable[[], object]) -> Callable[[], Awaitable[object]]:
    async def wrapped() -> object:
        return check()

    return wrapped
