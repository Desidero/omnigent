"""Tests for the ``sys_open_items_*`` tools: registration, relay and runner dispatch."""

from __future__ import annotations

import json

import httpx
import pytest

from omnigent.runner.open_items_tools import execute_open_items_tool
from omnigent.runner.tool_dispatch import (
    _ALL_LOCAL_TOOLS,
    _NATIVE_RELAY_BUILTIN_TOOLS,
    _OPEN_ITEMS_TOOLS,
    build_native_relay_tool_schemas,
    should_dispatch_locally,
)
from omnigent.spec.parser import parse_tool_groups
from omnigent.spec.types import AgentSpec, ToolGroupsConfig

_TOOLS = {"sys_open_items_raise", "sys_open_items_update", "sys_open_items_list"}


def _relay_names(spec: AgentSpec | None) -> set[str]:
    return {schema["name"] for schema in build_native_relay_tool_schemas(spec)}


def test_the_group_is_on_by_default_and_reaches_native_relays() -> None:
    assert _OPEN_ITEMS_TOOLS == _TOOLS
    assert _TOOLS <= _ALL_LOCAL_TOOLS and _TOOLS <= _NATIVE_RELAY_BUILTIN_TOOLS
    assert all(should_dispatch_locally(name) for name in _TOOLS)
    assert parse_tool_groups(None, spawn=False).open_items is True
    assert parse_tool_groups({"open_items": False}, spawn=False).open_items is False
    assert _relay_names(AgentSpec(spec_version=1, skills_filter="none")) >= _TOOLS
    opted_out = AgentSpec(
        spec_version=1, skills_filter="none", tool_groups=ToolGroupsConfig(open_items=False)
    )
    assert not _TOOLS & _relay_names(opted_out)
    # Without a spec the relay can't evaluate the gate, so it leaves them out.
    assert not _TOOLS & _relay_names(None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body"),
    [(404, {"detail": "Not Found"}), (405, {"detail": "Method Not Allowed"})],
)
async def test_a_server_without_open_items_says_to_label_in_chat(
    status: int, body: dict[str, str]
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json=body)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://server.test"
    ) as client:
        output = await execute_open_items_tool(
            "sys_open_items_raise",
            json.dumps({"items": [{"kind": "question", "title": "x"}]}),
            server_client=client,
            conversation_id="a" * 32,
            call_id="toolu_9",
        )
    assert json.loads(output)["error"].startswith("unavailable:")
    assert "label items in chat instead" in json.loads(output)["error"]
    (request,) = requests
    assert request.url.path == f"/v1/sessions/{'a' * 32}/open-items"
    assert json.loads(request.content)["idempotency_key"] == "tool:toolu_9"


@pytest.mark.asyncio
async def test_calls_without_a_session_or_with_bad_arguments_fail_fast() -> None:
    async with httpx.AsyncClient(base_url="http://server.test") as client:
        no_session = await execute_open_items_tool(
            "sys_open_items_list", "{}", server_client=client, conversation_id=None
        )
        bad = await execute_open_items_tool(
            "sys_open_items_update", "[1]", server_client=client, conversation_id="a" * 32
        )
        empty = await execute_open_items_tool(
            "sys_open_items_update", "{}", server_client=client, conversation_id="a" * 32
        )
    assert json.loads(no_session) == {"error": "sys_open_items_list requires server access"}
    assert json.loads(bad) == {"error": "sys_open_items_update: arguments must be an object"}
    assert json.loads(empty)["error"].startswith("invalid_input")
