"""Tests for the ``/v1/sessions/{id}/open-items`` routes and their live event."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from omnigent.runner.identity import (
    ORCHESTRATION_SOURCE_HEADER,
    RUNNER_TUNNEL_TOKEN_HEADER,
    token_bound_runner_id,
)
from omnigent.server import open_items as open_items_api
from omnigent.server.app import create_app
from omnigent.server.auth import LEVEL_EDIT, LEVEL_OWNER, LEVEL_READ, UnifiedAuthProvider
from omnigent.spec.types import ToolGroupsConfig
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore

pytestmark = pytest.mark.asyncio

_ITEMS_AGENT = "1" * 32
_NO_ITEMS_AGENT = "2" * 32
_BUNDLE_HASH = "c" * 64
_TOKEN = "runner-binding-token"
ALICE, BOB, CAROL, DAVE = (f"{name}@example.com" for name in ("alice", "bob", "carol", "dave"))


class _AgentCacheStub:
    """Specs whose ``open_items`` group is on only for the items agent; its sub-agent's is off."""

    def load(self, agent_id: str, bundle_location: str, **_: Any) -> SimpleNamespace:
        keeps = agent_id == _ITEMS_AGENT
        child = SimpleNamespace(
            name="child", tool_groups=ToolGroupsConfig(open_items=False), sub_agents=[]
        )
        return SimpleNamespace(
            spec=SimpleNamespace(
                tool_groups=ToolGroupsConfig(open_items=keeps), sub_agents=[child]
            )
        )


@pytest.fixture()
def stores(db_uri: str) -> SimpleNamespace:
    agents = SqlAlchemyAgentStore(db_uri)
    for agent_id in (_ITEMS_AGENT, _NO_ITEMS_AGENT):
        agents.create(agent_id, f"agent-{agent_id[0]}", f"{agent_id}/{_BUNDLE_HASH}")
    permissions = SqlAlchemyPermissionStore(db_uri)
    for user in (ALICE, BOB, CAROL, DAVE):
        permissions.ensure_user(user, is_admin=False)
    return SimpleNamespace(
        agents=agents,
        conversations=SqlAlchemyConversationStore(db_uri),
        permissions=permissions,
    )


def _app(stores: SimpleNamespace, tmp_path: Path) -> FastAPI:
    return create_app(
        agent_store=stores.agents,
        file_store=SqlAlchemyFileStore(stores.conversations.storage_location),
        conversation_store=stores.conversations,
        artifact_store=LocalArtifactStore(str(tmp_path / "artifacts")),
        agent_cache=_AgentCacheStub(),  # type: ignore[arg-type]
        auth_provider=UnifiedAuthProvider(source="header", local_single_user=False),
        permission_store=stores.permissions,
    )


@pytest_asyncio.fixture()
async def client(stores: SimpleNamespace, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app(stores, tmp_path))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture()
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    published: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        open_items_api.session_stream,
        "publish",
        lambda session_id, event: published.append((session_id, event)) or 1,
    )
    return published


def _session(
    stores: SimpleNamespace, agent_id: str = _ITEMS_AGENT, sub_agent_name: str | None = None
) -> str:
    session_id = stores.conversations.create_conversation(
        conversation_id=uuid.uuid4().hex,
        agent_id=agent_id,
        runner_id=token_bound_runner_id(_TOKEN),
        sub_agent_name=sub_agent_name,
    ).id
    stores.permissions.grant(ALICE, session_id, LEVEL_OWNER)
    return session_id


def _user(email: str) -> dict[str, str]:
    return {"X-Forwarded-Email": email}


def _runner(session_id: str, user: str = ALICE, token: str = _TOKEN) -> dict[str, str]:
    return {
        **_user(user),
        ORCHESTRATION_SOURCE_HEADER: session_id,
        RUNNER_TUNNEL_TOKEN_HEADER: token,
    }


def _raise_body(*items: dict[str, Any], key: str = "tool:call_1") -> dict[str, Any]:
    return {"items": list(items), "idempotency_key": key}


_QUESTION = {"kind": "question", "title": "Cache rows?", "detail": "Copy or link?"}


async def test_the_runner_raises_people_read_and_every_write_is_announced(
    client: httpx.AsyncClient, stores: SimpleNamespace, events: list[Any]
) -> None:
    session_id = _session(stores)
    url = f"/v1/sessions/{session_id}/open-items"
    raised = await client.post(
        url,
        json=_raise_body(_QUESTION, {"kind": "risk", "title": "Flaky", "topic": "CI"}),
        headers=_runner(session_id),
    )
    assert raised.status_code == 200, raised.text
    body = raised.json()
    assert [row["item"]["label"] for row in body["items"]] == ["Q1", "R1"]
    assert (body["open_count"], body["topics"]) == (2, ["ci"])
    assert events[-1] == (
        session_id,
        {
            "type": "session.open_items.changed",
            "conversation_id": session_id,
            "labels": ["Q1", "R1"],
            "open_count": 2,
        },
    )
    # A retry of the same call gets the same labels and writes nothing new.
    retried = await client.post(
        url,
        json=_raise_body(_QUESTION, {"kind": "risk", "title": "Flaky", "topic": "CI"}),
        headers=_runner(session_id),
    )
    assert [row["item"]["label"] for row in retried.json()["items"]] == ["Q1", "R1"]

    closed = await client.patch(
        url,
        json={
            "updates": [{"label": "Q1", "status": "closed", "resolution": "Copied"}],
            "ref": "tool:call_2",
        },
        headers=_runner(session_id),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["items"][0]["item"]["closed_by"] == "agent"
    assert events[-1][1]["labels"] == ["Q1"] and events[-1][1]["open_count"] == 1

    listed = await client.get(url, headers=_user(ALICE))
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert [item["label"] for item in page["data"]] == ["R1"]
    assert page["counts"]["status"] == {"open": 1, "answered": 0, "closed": 1}
    everything = await client.get(url, params={"status": "all", "limit": 1}, headers=_user(ALICE))
    assert (everything.json()["next_after"], everything.json()["has_more"]) == ("Q1", True)
    rest = await client.get(
        url,
        params=[("status", "open"), ("status", "closed"), ("after", "Q1")],
        headers=_user(ALICE),
    )
    assert [item["label"] for item in rest.json()["data"]] == ["R1"]


async def test_viewers_read_editors_close_and_answer_and_others_are_refused(
    client: httpx.AsyncClient, stores: SimpleNamespace, events: list[Any]
) -> None:
    session_id = _session(stores)
    stores.permissions.grant(BOB, session_id, LEVEL_READ)
    stores.permissions.grant(CAROL, session_id, LEVEL_EDIT)
    url = f"/v1/sessions/{session_id}/open-items"
    await client.post(url, json=_raise_body(_QUESTION, _QUESTION), headers=_runner(session_id))
    close = {"updates": [{"label": "Q1", "status": "closed", "resolution": "Not needed"}]}
    answer = {"answers": [{"label": "Q2", "text": "Link them"}]}

    assert (await client.get(url, headers=_user(BOB))).status_code == 200
    assert (await client.patch(url, json=close, headers=_user(BOB))).status_code == 403
    assert (
        await client.post(f"{url}/answers", json=answer, headers=_user(BOB))
    ).status_code == 403
    for refused in (
        await client.get(url, headers=_user(DAVE)),
        await client.patch(url, json=close, headers=_user(DAVE)),
    ):
        assert refused.status_code in (403, 404)

    by_carol = await client.patch(url, json=close, headers=_user(CAROL))
    assert by_carol.status_code == 200, by_carol.text
    assert by_carol.json()["items"][0]["item"]["closed_by"] == "user"
    answered = await client.post(f"{url}/answers", json=answer, headers=_user(CAROL))
    assert answered.status_code == 200, answered.text
    item = answered.json()["items"][0]["item"]
    assert (item["status"], item["answers"][0]["text"], item["answers"][0]["by"]) == (
        "answered",
        "Link them",
        CAROL,
    )
    assert [event[1]["labels"] for event in events[-2:]] == [["Q1"], ["Q2"]]


async def test_only_the_sessions_own_runner_raises(
    client: httpx.AsyncClient, stores: SimpleNamespace
) -> None:
    session_id, other = _session(stores), _session(stores)
    stores.permissions.grant(CAROL, session_id, LEVEL_EDIT)
    url = f"/v1/sessions/{session_id}/open-items"
    for headers in (
        _user(ALICE),
        _runner(other),
        _runner(session_id, token="another-runner"),
        _runner(session_id, token=" "),
        # An edit collaborator is not the session's runner.
        {**_user(CAROL), ORCHESTRATION_SOURCE_HEADER: session_id},
        _runner(session_id, user=BOB),
    ):
        refused = await client.post(url, json=_raise_body(_QUESTION), headers=headers)
        assert refused.status_code in (403, 404), (headers, refused.text)
    assert (await client.get(url, headers=_user(ALICE))).json()["data"] == []


async def test_an_agent_without_the_tool_group_cannot_write(
    client: httpx.AsyncClient, stores: SimpleNamespace
) -> None:
    for session_id in (
        _session(stores, _NO_ITEMS_AGENT),
        _session(stores, sub_agent_name="child"),
    ):
        url = f"/v1/sessions/{session_id}/open-items"
        refused = await client.post(url, json=_raise_body(_QUESTION), headers=_runner(session_id))
        assert refused.status_code == 403
        assert "open_items tool group" in refused.text
        closing = {"updates": [{"label": "Q1", "status": "closed", "resolution": "x"}]}
        assert (
            await client.patch(url, json=closing, headers=_runner(session_id))
        ).status_code == 403


async def test_invalid_input_and_per_item_errors(
    client: httpx.AsyncClient, stores: SimpleNamespace, events: list[Any]
) -> None:
    session_id = _session(stores)
    url = f"/v1/sessions/{session_id}/open-items"
    headers = _runner(session_id)
    for items in (
        [{"kind": "question"}],
        [{"kind": "idea", "title": "x"}],
        [{"kind": "link", "url": "ftp://example.com"}],
        [{**_QUESTION, "colour": "red"}],
    ):
        bad = await client.post(url, json=_raise_body(*items), headers=headers)
        assert bad.status_code == 400 and "invalid_input" in bad.text, bad.text
    assert events == []
    await client.post(url, json=_raise_body(_QUESTION), headers=headers)
    taken = await client.post(
        url, json=_raise_body({**_QUESTION, "label": "Q1"}, key="tool:2"), headers=headers
    )
    assert taken.json()["items"][0]["error"]["code"] == "label_taken"
    missing = await client.patch(
        url, json={"updates": [{"label": "T4", "topic": "x"}]}, headers=headers
    )
    assert missing.json()["items"] == [
        {"label": "T4", "error": {"code": "not_found", "message": "no item T4"}}
    ]
    assert (await client.get(url, params={"after": "X9"}, headers=_user(ALICE))).status_code == 400


async def test_a_server_without_storage_hides_the_feature(
    client: httpx.AsyncClient,
    stores: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omnigent.open_items_availability import OPEN_ITEMS_HEADER
    from tests.server.helpers import build_agent_bundle

    session_id = _session(stores)
    LocalArtifactStore(str(tmp_path / "artifacts")).put(
        f"{_ITEMS_AGENT}/{_BUNDLE_HASH}", build_agent_bundle("items-agent")
    )
    bundle_url = f"/v1/sessions/{session_id}/agent/contents"
    # The runner keeps the tools only when the bundle download says the server stores items.
    assert (await client.get(bundle_url, headers=_user(ALICE))).headers[OPEN_ITEMS_HEADER] == "1"
    assert (await client.get("/v1/info", headers=_user(ALICE))).json()["open_items"] is True
    monkeypatch.setattr(open_items_api, "open_items_store_for", _unavailable)
    assert (await client.get(bundle_url, headers=_user(ALICE))).headers[OPEN_ITEMS_HEADER] == "0"
    assert (await client.get("/v1/info", headers=_user(ALICE))).json()["open_items"] is False
    missing = await client.get(f"/v1/sessions/{session_id}/open-items", headers=_user(ALICE))
    assert missing.status_code == 404
    assert "not available" in missing.text


def _unavailable(storage_location: str) -> Any:
    raise RuntimeError(f"no open items store at {storage_location}")


async def test_the_agents_tools_raise_update_and_list_through_the_runner(
    client: httpx.AsyncClient, stores: SimpleNamespace
) -> None:
    """The runner's handlers drive the real routes and return compact results."""
    import json

    from omnigent.runner.open_items_tools import execute_open_items_tool

    session_id = _session(stores)
    client.headers.update(_runner(session_id))

    async def run(tool: str, args: dict[str, Any], call_id: str | None = None) -> Any:
        output = await execute_open_items_tool(
            tool,
            json.dumps(args),
            server_client=client,
            conversation_id=session_id,
            call_id=call_id,
        )
        return json.loads(output)

    raise_args = {
        "items": [
            {**_QUESTION, "topic": "cache"},
            {"kind": "link", "url": "https://github.com/acme/app/pull/7", "title": "The PR"},
        ]
    }
    raised = await run("sys_open_items_raise", raise_args, call_id="toolu_1")
    assert raised == {
        "items": [
            {"label": "Q1", "status": "open", "title": "Cache rows?", "topic": "cache"},
            {"label": "L1", "status": "open", "title": "The PR"},
        ],
        "open_count": 2,
        "topics": ["cache"],
    }
    # The harness retrying the same call gets the same labels.
    assert await run("sys_open_items_raise", raise_args, call_id="toolu_1") == raised
    pinned_again = await run(
        "sys_open_items_raise",
        {"items": [{"kind": "link", "url": "https://github.com/acme/app/pull/7/files"}]},
    )
    assert pinned_again["items"][0] == {
        "label": "L1",
        "status": "open",
        "title": "The PR",
        "duplicate": True,
    }

    updated = await run(
        "sys_open_items_update",
        {
            "updates": [
                {"label": "Q1", "status": "closed", "resolution": "Copied as is"},
                {"label": "R9", "status": "open"},
            ]
        },
        call_id="toolu_2",
    )
    assert updated == {
        "items": [
            {
                "label": "Q1",
                "status": "closed",
                "title": "Cache rows?",
                "topic": "cache",
                "resolution": "Copied as is",
            },
            {"label": "R9", "error": "not_found: no item R9"},
        ]
    }
    listed = await run("sys_open_items_list", {"status": "all", "query": "copy"})
    assert listed["items"] == [
        {
            "label": "Q1",
            "status": "closed",
            "title": "Cache rows?",
            "topic": "cache",
            "resolution": "Copied as is",
            "kind": "question",
            "detail": "Copy or link?",
            "closed_by": "agent",
        }
    ]
    assert (listed["truncated"], listed["counts"]) == (
        False,
        {"open": 1, "answered": 0, "closed": 1},
    )
    refused = await run("sys_open_items_raise", {"items": [{"kind": "question"}]})
    assert refused == {"error": "invalid_input: title is required"}
