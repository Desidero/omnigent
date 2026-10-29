"""``sys_link_rules``: the runner's handler against the real ``/v1/link-rules`` routes,
its registration, and the approval it asks for."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from omnigent.link_rules import DEFAULT_LINK_RULES
from omnigent.policies.builtins.safety import ask_on_link_rule_change
from omnigent.runner.tool_dispatch import (
    _ALL_LOCAL_TOOLS,
    _LINK_RULE_TOOLS,
    _NATIVE_RELAY_BUILTIN_TOOLS,
    _execute_link_rules_tool,
)
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.preference_store.sqlalchemy_store import SqlAlchemyPreferenceStore

TRACKER = {
    "action": "add",
    "name": "Tracker",
    "pattern": "BST-{num}",
    "url": "https://jira.example.com/browse/BST-{num}",
}


@pytest.fixture
def server_client(db_uri, tmp_path):
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    app = create_app(
        SqlAlchemyAgentStore(db_uri),
        SqlAlchemyFileStore(db_uri),
        SqlAlchemyConversationStore(db_uri),
        artifacts,
        AgentCache(artifact_store=artifacts, cache_dir=tmp_path / "cache"),
        preference_store=SqlAlchemyPreferenceStore(db_uri, authority_id="test-authority"),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _call(client: httpx.AsyncClient, **args: object) -> Any:
    return json.loads(await _execute_link_rules_tool(json.dumps(args), server_client=client))


async def test_list_add_update_remove(server_client):
    async with server_client as client:
        listed = await _call(client, action="list")
        assert listed["saved"] is False
        assert [rule["name"] for rule in listed["rules"]] == [r.name for r in DEFAULT_LINK_RULES]

        added = await _call(client, **TRACKER)
        assert added["saved"] is True
        assert added["rules"][-1] == {
            "name": "Tracker",
            "kind": "url",
            "pattern": "BST-{num}",
            "url": "https://jira.example.com/browse/BST-{num}",
            "enabled": True,
        }
        assert "already exists" in (await _call(client, **TRACKER))["error"]

        updated = await _call(
            client, action="update", name="tracker", enabled=False, new_name="Tix"
        )
        assert updated["rules"][-1]["name"] == "Tix"
        assert updated["rules"][-1]["enabled"] is False

        removed = await _call(client, action="remove", name="GitHub")
        assert "GitHub" not in [rule["name"] for rule in removed["rules"]]
        assert "no rule named" in (await _call(client, action="remove", name="GitHub"))["error"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"url": "javascript:alert(1)//{num}"}, "https://"),
        ({"pattern": "/(a+)+/"}, "repeated group"),
        ({"pattern": "/(?<=x)BST-(\\d+)/"}, "lookaround"),
        ({"kind": "github"}, "takes no pattern"),
    ],
)
async def test_invalid_changes_are_refused_before_saving(server_client, change, message):
    async with server_client as client:
        result = await _call(client, **{**TRACKER, **change})
        assert message in result["error"]
        assert (await _call(client, action="list"))["saved"] is False


async def test_bad_arguments(server_client):
    async with server_client as client:
        assert "action must be" in (await _call(client, action="wipe"))["error"]
        assert "needs the rule's name" in (await _call(client, action="remove"))["error"]
    assert (
        "server access"
        in json.loads(await _execute_link_rules_tool('{"action":"list"}', server_client=None))[
            "error"
        ]
    )


def test_registered_for_local_dispatch_and_the_native_relay():
    assert {"sys_link_rules"} == _LINK_RULE_TOOLS
    assert _LINK_RULE_TOOLS <= _ALL_LOCAL_TOOLS
    assert _LINK_RULE_TOOLS <= _NATIVE_RELAY_BUILTIN_TOOLS


def _event(args: Mapping[str, object], target: str = "sys_link_rules") -> Any:
    return {
        "type": "tool_call",
        "target": target,
        "data": {"name": target, "arguments": args},
    }


def test_every_change_asks_and_listing_does_not():
    assert ask_on_link_rule_change(_event({"action": "list"}))["result"] == "ALLOW"
    assert ask_on_link_rule_change(_event(TRACKER, target="other"))["result"] == "ALLOW"
    asked = ask_on_link_rule_change(_event(TRACKER))
    assert asked["result"] == "ASK"
    assert "add chat link rule 'Tracker'" in asked["reason"]
    assert "url=https://jira.example.com/browse/BST-{num}" in asked["reason"]
    for args in ({"action": "remove", "name": "GitHub"}, {"action": "update", "name": "x"}, {}):
        assert ask_on_link_rule_change(_event(args))["result"] == "ASK"
