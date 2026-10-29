"""``/v1/link-rules``: the caller's chat link rules over shared preferences."""

import httpx
import pytest

from omnigent.link_rules import DEFAULT_LINK_RULES
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import UnifiedAuthProvider
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.preference_store.sqlalchemy_store import SqlAlchemyPreferenceStore

ALICE = {"X-Forwarded-Email": "alice@example.test"}
BOB = {"X-Forwarded-Email": "bob@example.test"}
JIRA = {
    "name": "Jira",
    "kind": "url",
    "pattern": "BST-{num}",
    "url": "https://jira.example.com/browse/BST-{num}",
    "enabled": True,
}


def _app(db_uri, tmp_path, *, with_store: bool):
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    store = SqlAlchemyPreferenceStore(db_uri, authority_id="test-authority")
    return create_app(
        SqlAlchemyAgentStore(db_uri),
        SqlAlchemyFileStore(db_uri),
        SqlAlchemyConversationStore(db_uri),
        artifacts,
        AgentCache(artifact_store=artifacts, cache_dir=tmp_path / "cache"),
        auth_provider=UnifiedAuthProvider(source="header"),
        preference_store=store if with_store else None,
    )


@pytest.fixture
def client_factory(db_uri, tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIGENT_LOCAL_SINGLE_USER", "0")

    def build(*, with_store: bool = True) -> httpx.AsyncClient:
        app = _app(db_uri, tmp_path, with_store=with_store)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return build


async def test_defaults_until_saved_then_per_user(client_factory):
    async with client_factory() as client:
        assert (await client.get("/v1/link-rules")).status_code == 401
        initial = (await client.get("/v1/link-rules", headers=ALICE)).json()
        assert initial["supported"] is True
        assert initial["saved"] is False
        assert initial["version"] == 0
        assert [rule["name"] for rule in initial["rules"]] == [
            rule.name for rule in DEFAULT_LINK_RULES
        ]
        assert initial["defaults"] == initial["rules"]

        saved = await client.put(
            "/v1/link-rules",
            headers=ALICE,
            json={"rules": [{"name": "GitHub", "kind": "github"}, JIRA], "expected_version": 0},
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["saved"] is True and body["version"] == 1
        assert body["rules"][1] == JIRA
        assert body["rules"][0] == {
            "name": "GitHub",
            "kind": "github",
            "pattern": "",
            "url": None,
            "enabled": True,
        }

        # Bob still sees the defaults: rules are per user.
        assert (await client.get("/v1/link-rules", headers=BOB)).json()["saved"] is False

        reset = await client.put(
            "/v1/link-rules", headers=ALICE, json={"rules": None, "expected_version": 1}
        )
        assert reset.status_code == 200
        assert reset.json()["saved"] is False
        assert len(reset.json()["rules"]) == len(DEFAULT_LINK_RULES)


async def test_stale_version_is_refused_without_storing_a_conflict(client_factory):
    async with client_factory() as client:
        first = {"rules": [JIRA], "expected_version": 0}
        assert (await client.put("/v1/link-rules", headers=ALICE, json=first)).status_code == 200
        stale = await client.put(
            "/v1/link-rules", headers=ALICE, json={"rules": [], "expected_version": 0}
        )
        assert stale.status_code == 409
        shared = (await client.get("/v1/preferences/shared", headers=ALICE)).json()
        assert shared["conflicts"] == []
        assert (await client.get("/v1/link-rules", headers=ALICE)).json()["rules"] == [JIRA]


@pytest.mark.parametrize(
    "rule",
    [
        {**JIRA, "url": "javascript:alert(1)//{num}"},
        {**JIRA, "url": "https://{num}.example.com/"},
        {**JIRA, "pattern": "/(a+)+$/"},
        {**JIRA, "pattern": "/(?<=x)BST-(\\d+)/"},
        {"name": "GitHub", "kind": "github", "pattern": "#{num}"},
    ],
)
async def test_invalid_rules_are_rejected_with_the_reason(client_factory, rule):
    async with client_factory() as client:
        response = await client.put(
            "/v1/link-rules", headers=ALICE, json={"rules": [rule], "expected_version": 0}
        )
        assert response.status_code == 422
        assert "Invalid link rule" in response.text
        assert (await client.get("/v1/link-rules", headers=ALICE)).json()["saved"] is False


async def test_the_shared_preference_route_validates_rules_too(client_factory):
    async with client_factory() as client:
        identity = (await client.get("/v1/preferences/shared", headers=ALICE)).json()["identity"]
        response = await client.post(
            "/v1/preferences/shared/operations",
            headers=ALICE,
            json={
                "protocol_version": 1,
                "identity": identity,
                "operation_id": "00000000-0000-4000-8000-000000000001",
                "installation_id": "web-test",
                "key": {"kind": "link_rules", "name": "default"},
                "expected_version": 0,
                "value": '[{"name":"x","kind":"url","pattern":"X-{num}","url":"data:,{num}"}]',
            },
        )
        assert response.status_code == 422


async def test_without_shared_preferences_the_defaults_are_read_only(client_factory):
    async with client_factory(with_store=False) as client:
        body = (await client.get("/v1/link-rules", headers=ALICE)).json()
        assert body["supported"] is False
        assert len(body["rules"]) == len(DEFAULT_LINK_RULES)
        refused = await client.put(
            "/v1/link-rules", headers=ALICE, json={"rules": [JIRA], "expected_version": 0}
        )
        assert refused.status_code == 409
