"""HTTP routes for extension session state, commands and published fields."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import insert

from omnigent.db.db_models import SqlConversationLabel
from omnigent.extensions import (
    EXTENSION_API_VERSION,
    ClearState,
    CommandAccess,
    CommandArgument,
    CommandContribution,
    ExtensionManifest,
    ExtensionPluginState,
    SetState,
    StateContribution,
    StateField,
    StateVisibility,
)
from omnigent.extensions.published_fields import PublishedFieldView, configure_published_fields
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import LEVEL_EDIT, LEVEL_READ, UnifiedAuthProvider
from omnigent.server.extension_state import ExtensionStateService
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from tests.server.helpers import create_test_agent

pytestmark = pytest.mark.asyncio

_EXT = "acme.status"
_OWNER = "owner@state.test"
_EDITOR = "editor@state.test"
_READER = "reader@state.test"


def _manifest() -> ExtensionManifest:
    return ExtensionManifest(
        id=_EXT,
        display_name="Acme Status",
        distribution="omnigent-acme-status",
        version="1.0.0",
        requires_omnigent=">=0",
        extension_api=EXTENSION_API_VERSION,
        state=StateContribution(
            fields=(
                StateField("status", StateVisibility.PUBLISHED, max_length=16),
                StateField("pr:*", StateVisibility.READERS, max_keys=3),
                StateField("pr:0", StateVisibility.EDITORS),
                StateField("draft", StateVisibility.EDITORS),
                StateField("secret", StateVisibility.SERVICE),
            )
        ),
        commands=(
            CommandContribution(
                id=f"{_EXT}.set",
                title="Set status",
                action=SetState(key="status", value="{status}"),
                arguments=(CommandArgument("status", choices=("blocked", "done")),),
            ),
            CommandContribution(
                id=f"{_EXT}.clear", title="Clear status", action=ClearState(key="status")
            ),
            CommandContribution(
                id=f"{_EXT}.watch",
                title="Watch PR",
                action=SetState(key="pr:{pr}", value="watching"),
                arguments=(CommandArgument("pr", pattern=r"[0-9]{1,6}"),),
                required_access=CommandAccess.READ,
            ),
            CommandContribution(
                id=f"{_EXT}.draft",
                title="Draft",
                action=SetState(key="draft", value="{text}"),
                arguments=(CommandArgument("text", pattern=r"[a-z ]+"),),
            ),
            CommandContribution(
                id=f"{_EXT}.secret",
                title="Secret",
                action=SetState(key="secret", value="s"),
                writes_service_state=True,
            ),
            CommandContribution(id=f"{_EXT}.reserved", title="Reserved"),
        ),
    )


def _write_raw_label(server: _Server, key: str, value: str) -> None:
    """Write a label as an older server could have, bypassing the store's checks."""
    with server.store._conv_engine.begin() as connection:
        connection.execute(
            insert(SqlConversationLabel.__table__).values(
                workspace_id=0,
                conversation_id=server.session_id,
                key=key,
                value=value,
                updated_at=1,
            )
        )


def _service(server: _Server) -> ExtensionStateService:
    return ExtensionStateService(
        ExtensionPluginState(manifests=(_manifest(),)),
        is_enabled=lambda extension_id: extension_id == _EXT,
        store=server.store,
    )


@dataclass
class _Server:
    app: FastAPI
    store: SqlAlchemyConversationStore
    session_id: str

    def client(self, email: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://test",
            headers={"X-Forwarded-Email": email},
        )

    async def command(self, email: str, name: str, **arguments: str) -> httpx.Response:
        async with self.client(email) as client:
            return await client.post(
                f"/v1/sessions/{self.session_id}/extensions/{_EXT}/commands/{_EXT}.{name}",
                json={"arguments": arguments},
            )

    async def get(self, email: str, path: str) -> httpx.Response:
        async with self.client(email) as client:
            return await client.get(f"/v1/sessions/{self.session_id}{path}")


async def _server(
    db_uri: str,
    tmp_path: Path,
    *,
    enabled: bool = True,
    installed: bool = True,
    server_config: dict[str, object] | None = None,
) -> _Server:
    permission_store = SqlAlchemyPermissionStore(db_uri)
    for user in (_OWNER, _EDITOR, _READER):
        permission_store.ensure_user(user)
    store = SqlAlchemyConversationStore(db_uri)
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    app = create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=store,
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        permission_store=permission_store,
        auth_provider=UnifiedAuthProvider(source="header", local_single_user=False),
        extension_state=ExtensionPluginState(manifests=(_manifest(),) if installed else ()),
        server_config={} if server_config is None else server_config,
        # A server config stands in for the predicate, as at server startup.
        extension_is_enabled=(
            (lambda extension_id: enabled and extension_id == _EXT)
            if server_config is None
            else None
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Forwarded-Email": _OWNER},
    ) as client:
        agent = await create_test_agent(client, user=_OWNER)
    session_id = agent["_session_id"]
    permission_store.grant(_EDITOR, session_id, LEVEL_EDIT)
    permission_store.grant(_READER, session_id, LEVEL_READ)
    return _Server(app=app, store=store, session_id=session_id)


@pytest.fixture(autouse=True)
def _reset_published_fields() -> Iterator[None]:
    yield
    configure_published_fields(PublishedFieldView())


@pytest.fixture
async def server(db_uri: str, tmp_path: Path) -> _Server:
    return await _server(db_uri, tmp_path)


async def test_command_publishes_a_field_to_session_responses(server: _Server) -> None:
    response = await server.command(_EDITOR, "set", status="blocked")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entry"]["value"] == "blocked"
    assert body["entry"]["updated_by"] == _EDITOR
    assert body["published_fields"] == {_EXT: {"status": "blocked"}}
    session = (await server.get(_READER, "")).json()
    assert session["published_fields"] == {_EXT: {"status": "blocked"}}
    assert session["labels"][f"ext.{_EXT}.status"] == "blocked"
    listed = await server.get(_READER, "/labels")
    assert listed.json()["labels"][f"ext.{_EXT}.status"] == "blocked"

    cleared = await server.command(_EDITOR, "clear")
    assert cleared.json()["deleted"] is True
    session = (await server.get(_READER, "")).json()
    assert session["published_fields"] == {}
    assert f"ext.{_EXT}.status" not in session["labels"]


async def test_reads_follow_visibility_and_share_level(server: _Server) -> None:
    for name, arguments in (("set", {"status": "done"}), ("watch", {"pr": "7"})):
        assert (await server.command(_OWNER, name, **arguments)).status_code == 200
    assert (await server.command(_OWNER, "draft", text="wip")).status_code == 200
    assert (await server.command(_OWNER, "secret")).status_code == 200

    async def keys(email: str) -> list[str]:
        response = await server.get(email, f"/extensions/{_EXT}/state")
        assert response.status_code == 200, response.text
        return [entry["key"] for entry in response.json()["data"]]

    assert await keys(_READER) == ["pr:7", "status"]
    assert await keys(_EDITOR) == ["draft", "pr:7", "status"]
    assert await keys(_OWNER) == ["draft", "pr:7", "status"]
    assert (await server.get(_READER, f"/extensions/{_EXT}/state/pr:7")).json()["value"] == (
        "watching"
    )
    assert (await server.get(_READER, f"/extensions/{_EXT}/state/draft")).status_code == 404
    # Service-only state is unreadable over HTTP, even for the owner.
    assert (await server.get(_OWNER, f"/extensions/{_EXT}/state/secret")).status_code == 404
    stranger = await server.get("stranger@state.test", f"/extensions/{_EXT}/state")
    assert stranger.status_code == 404


async def test_command_access_and_argument_validation(server: _Server) -> None:
    assert (await server.command(_READER, "set", status="done")).status_code == 403
    assert (await server.command(_READER, "watch", pr="42")).status_code == 200
    assert (await server.command(_EDITOR, "set", status="maybe")).status_code == 400
    assert (await server.command(_EDITOR, "set", status="done", extra="x")).status_code == 400
    assert (await server.command(_EDITOR, "set")).status_code == 400
    assert (await server.command(_READER, "watch", pr="4 2")).status_code == 400
    assert (await server.command(_READER, "watch", pr="1" * 65)).status_code == 400
    assert (await server.command(_EDITOR, "reserved")).status_code == 404
    assert (await server.command(_EDITOR, "missing")).status_code == 404


async def test_command_compare_and_set(server: _Server) -> None:
    path = f"/v1/sessions/{server.session_id}/extensions/{_EXT}/commands/{_EXT}.set"
    async with server.client(_EDITOR) as client:
        first = await client.post(
            path, json={"arguments": {"status": "done"}, "expected_version": 0}
        )
        stale = await client.post(
            path, json={"arguments": {"status": "blocked"}, "expected_version": 0}
        )

    assert first.status_code == 200
    assert stale.status_code == 409


async def test_label_writes_cannot_forge_published_fields(server: _Server) -> None:
    async with server.client(_OWNER) as client:
        response = await client.patch(
            f"/v1/sessions/{server.session_id}",
            json={"labels": {f"ext.{_EXT}.status": "done"}},
        )

    assert response.status_code == 400
    assert "read-only" in response.text


async def test_disabled_extension_publishes_nothing(db_uri: str, tmp_path: Path) -> None:
    server = await _server(db_uri, tmp_path, enabled=True)
    assert (await server.command(_OWNER, "set", status="done")).status_code == 200

    disabled = await _server(db_uri, tmp_path / "disabled", enabled=False)
    disabled.session_id = server.session_id

    assert (await disabled.command(_OWNER, "set", status="done")).status_code == 404
    assert (await disabled.get(_OWNER, f"/extensions/{_EXT}/state")).status_code == 404
    session = (await disabled.get(_OWNER, "")).json()
    assert session["published_fields"] == {}
    # An installed extension's prefix stays governed: nothing under it shows.
    assert f"ext.{_EXT}.status" not in session["labels"]
    # The data is kept for when the operator enables the extension again.
    assert server.store.get_extension_state(server.session_id, _EXT, "status") is not None

    uninstalled = await _server(db_uri, tmp_path / "uninstalled", installed=False)
    uninstalled.session_id = server.session_id
    session = (await uninstalled.get(_OWNER, "")).json()
    # Once uninstalled, the last value is an ordinary, read-only label.
    assert session["labels"][f"ext.{_EXT}.status"] == "done"


@pytest.mark.parametrize(
    ("server_config", "expected_status"),
    [
        ({"extensions": {_EXT: {"enabled": True}}}, 200),
        ({}, 404),
        ({"extensions": {_EXT: {"enabled": False}}}, 404),
    ],
)
async def test_operator_config_enables_state_without_a_predicate(
    db_uri: str,
    tmp_path: Path,
    server_config: dict[str, object],
    expected_status: int,
) -> None:
    server = await _server(db_uri, tmp_path, server_config=server_config)

    response = await server.command(_OWNER, "set", status="done")

    assert response.status_code == expected_status, response.text
    session = (await server.get(_READER, "")).json()
    expected = {_EXT: {"status": "done"}} if expected_status == 200 else {}
    assert session["published_fields"] == expected
    if expected_status != 200:
        # An installed extension's prefix stays governed, even when turned off.
        _write_raw_label(server, f"ext.{_EXT}.status", "done")
        session = (await server.get(_READER, "")).json()
        assert f"ext.{_EXT}.status" not in session["labels"]


async def test_an_explicit_predicate_overrides_the_operator_config(
    db_uri: str, tmp_path: Path
) -> None:
    permission_store = SqlAlchemyPermissionStore(db_uri)
    permission_store.ensure_user(_OWNER)
    store = SqlAlchemyConversationStore(db_uri)
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    app = create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=store,
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        permission_store=permission_store,
        auth_provider=UnifiedAuthProvider(source="header", local_single_user=False),
        extension_state=ExtensionPluginState(manifests=(_manifest(),)),
        server_config={"extensions": {_EXT: {"enabled": True}}},
        extension_is_enabled=lambda _extension_id: False,
    )
    server = _Server(app=app, store=store, session_id="")
    async with server.client(_OWNER) as client:
        server.session_id = (await create_test_agent(client, user=_OWNER))["_session_id"]

    assert (await server.command(_OWNER, "set", status="done")).status_code == 404


async def test_patch_refuses_keys_the_database_equates_with_a_mirror(server: _Server) -> None:
    assert (await server.command(_EDITOR, "set", status="done")).status_code == 200
    # U+0903 survives folding; MySQL's default collations equate the keys.
    variant = f"e\u0903xt.{_EXT}.status"

    async with server.client(_OWNER) as client:
        response = await client.patch(
            f"/v1/sessions/{server.session_id}", json={"labels": {variant: "forged"}}
        )

    if server.store._conv_engine.dialect.name == "mysql":
        assert response.status_code == 400
        assert "read-only" in response.text
    else:
        assert response.status_code == 200
    session = (await server.get(_READER, "")).json()
    assert session["published_fields"] == {_EXT: {"status": "done"}}


async def test_unbacked_labels_never_pass_for_published_fields(server: _Server) -> None:
    for key, value in ((f"ext.{_EXT}.status", "done"), (f"ext.{_EXT}.other", "x")):
        _write_raw_label(server, key, value)
    _write_raw_label(server, "ext.another.status", "kept")

    session = (await server.get(_READER, "")).json()

    assert session["published_fields"] == {}
    assert f"ext.{_EXT}.status" not in session["labels"]
    assert f"ext.{_EXT}.other" not in session["labels"]
    assert session["labels"]["ext.another.status"] == "kept"

    assert (await server.command(_EDITOR, "set", status="blocked")).status_code == 200
    session = (await server.get(_READER, "")).json()
    assert session["published_fields"] == {_EXT: {"status": "blocked"}}


async def test_list_pages_count_only_readable_keys(server: _Server) -> None:
    assert (await server.command(_OWNER, "draft", text="wip")).status_code == 200
    assert (await server.command(_OWNER, "secret")).status_code == 200
    assert (await server.command(_OWNER, "watch", pr="7")).status_code == 200
    assert (await server.command(_OWNER, "set", status="done")).status_code == 200

    async def pages(email: str, after: str | None = None) -> list[list[str]]:
        collected: list[list[str]] = []
        while True:
            query = "?limit=1" + (f"&after={after}" if after else "")
            body = (await server.get(email, f"/extensions/{_EXT}/state{query}")).json()
            collected.append([entry["key"] for entry in body["data"]])
            after = body["next_after"]
            if after is None:
                return collected

    assert await pages(_READER) == [["pr:7"], ["status"]]
    # A hidden key as cursor behaves like any other position.
    assert await pages(_READER, after="draft") == await pages(_READER, after="dz")
    assert await pages(_READER, after="secret") == [["status"]]


async def test_argument_values_cannot_move_a_key_to_another_field(server: _Server) -> None:
    # ``pr:0`` is declared editors-only; the readers' ``pr:*`` command must not reach it.
    response = await server.command(_READER, "watch", pr="0")

    assert response.status_code == 400
    assert server.store.get_extension_state(server.session_id, _EXT, "pr:0") is None


async def test_commands_cannot_use_up_the_extensions_own_keys(server: _Server) -> None:
    for pr in ("1", "2", "3"):
        assert (await server.command(_READER, "watch", pr=pr)).status_code == 200
    assert (await server.command(_READER, "watch", pr="4")).status_code == 409

    service = _service(server)
    for index in range(45):
        service.write_state(server.session_id, _EXT, f"own:{index}", b"x")
    # 48 keys now: commands stop here, the extension's server code does not.
    assert (await server.command(_EDITOR, "draft", text="x")).status_code == 409
    service.write_state(server.session_id, _EXT, "own:last", b"x")
    assert service.write_state(server.session_id, _EXT, "status", b"done").version == 1
    session = (await server.get(_READER, "")).json()
    assert session["published_fields"] == {_EXT: {"status": "done"}}


async def test_readers_do_not_see_who_wrote_state(server: _Server) -> None:
    assert (await server.command(_EDITOR, "watch", pr="7")).status_code == 200

    async def writer(email: str) -> object:
        response = await server.get(email, f"/extensions/{_EXT}/state/pr:7")
        return response.json()["updated_by"]

    assert await writer(_READER) is None
    assert await writer(_EDITOR) == _EDITOR


async def test_server_writes_honour_the_published_field_declaration(server: _Server) -> None:
    service = _service(server)

    with pytest.raises(ValueError, match="longer than 16"):
        service.write_state(server.session_id, _EXT, "status", b"x" * 200)
    with pytest.raises(ValueError, match="UTF-8"):
        service.write_state(server.session_id, _EXT, "status", b"\xff")

    assert server.store.get_extension_state(server.session_id, _EXT, "status") is None
    session = (await server.get(_READER, "")).json()
    assert session["published_fields"] == {}
