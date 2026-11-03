"""Server-side extension activation: who is activated, quarantine, and the ctx surfaces."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import json as json_module
import logging
import sys
import time
import types
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import insert

from omnigent.db.db_models import SqlExtensionSessionState
from omnigent.extensions import (
    EXTENSION_API_VERSION,
    CommandContribution,
    ExtensionEntrypoints,
    ExtensionManifest,
    ExtensionPluginState,
    SetState,
    StateContribution,
    StateField,
    StateVisibility,
)
from omnigent.extensions.published_fields import (
    PublishedFieldView,
    configure_published_fields,
    published_field_view,
)
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server import extension_activation, session_status_observers
from omnigent.server.app import create_app
from omnigent.server.extension_activation import (
    ActivationState,
    ExtensionContext,
    SessionRef,
)
from omnigent.server.extension_state import CommandEvent, ExtensionStateUnavailableError
from omnigent.server.routes._sessions.common import _session_status_cache
from omnigent.server.session_status_observers import SessionStatusObservation
from omnigent.server.session_wake import SessionWakeService, WakeOutcome, WakeStop
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from tests._helpers.polling import poll_until_async

pytestmark = pytest.mark.asyncio

_EXT = "acme.loop"
_PACKAGE = "acme_loop_fixture"


@pytest.fixture(autouse=True)
def _runtime(runtime_init: None) -> Iterator[None]:
    """The lifespan needs the initialized runtime; create_app sets the published view."""
    yield
    configure_published_fields(PublishedFieldView())


def _manifest(entrypoint: str = f"{_PACKAGE}.server:activate") -> ExtensionManifest:
    return ExtensionManifest(
        id=_EXT,
        display_name="Acme Loop",
        distribution="omnigent-acme-loop",
        version="1.2.0",
        requires_omnigent=">=0",
        extension_api=EXTENSION_API_VERSION,
        entrypoints=ExtensionEntrypoints(server=entrypoint),
        state=StateContribution(
            fields=(
                StateField("goal", StateVisibility.PUBLISHED, max_length=16),
                StateField("enabler", StateVisibility.SERVICE),
            )
        ),
        commands=(
            CommandContribution(
                id=f"{_EXT}.watch", title="Watch", action=SetState(key="goal", value="watching")
            ),
        ),
    )


def _install(
    monkeypatch: pytest.MonkeyPatch, activate: Callable[..., Any], package: str = _PACKAGE
) -> None:
    """Make ``<package>.server:activate`` importable, as an installed package would."""
    module = types.ModuleType(f"{package}.server")
    module.activate = activate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, package, types.ModuleType(package))
    monkeypatch.setitem(sys.modules, f"{package}.server", module)
    # In-memory modules have no installed files; the real check is tested on its own.
    monkeypatch.setattr(
        extension_activation,
        "module_in_distribution",
        lambda loaded, _distribution: loaded.__name__.split(".")[0].endswith("_fixture"),
        raising=False,
    )


def _other(extension_id: str, package: str) -> tuple[ExtensionManifest, str]:
    """Another extension like the fixture one, served from ``package``."""
    manifest = dataclasses.replace(
        _manifest(f"{package}.server:activate"),
        id=extension_id,
        distribution=f"omnigent-{extension_id.replace('.', '-')}",
        commands=(),
    )
    return manifest, package


@dataclass
class _Server:
    app: FastAPI
    store: SqlAlchemyConversationStore
    client: httpx.AsyncClient

    def record(self) -> Any:
        return self.app.state.extension_activations.records().get(_EXT)

    async def diagnostics(self) -> list[dict[str, Any]]:
        response = await self.client.get("/v1/extensions/diagnostics")
        assert response.status_code == 200, response.text
        return response.json()["activations"]


@asynccontextmanager
async def _serve(
    db_uri: str,
    tmp_path: Path,
    *,
    enabled: bool | None = True,
    manifest: ExtensionManifest | None = None,
    others: tuple[tuple[ExtensionManifest, str], ...] = (),
) -> AsyncIterator[_Server]:
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    store = SqlAlchemyConversationStore(db_uri)
    extensions = {} if enabled is None else {_EXT: {"enabled": enabled}}
    extensions.update({other.id: {"enabled": True} for other, _ in others})
    app = create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=store,
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        extension_state=ExtensionPluginState(
            manifests=(manifest or _manifest(), *(other for other, _ in others)),
            asset_packages={_EXT: _PACKAGE, **{other.id: package for other, package in others}},
        ),
        server_config={"extensions": extensions},
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield _Server(app, store, client)


@dataclass
class _Recorder:
    """An extension's activate() that records what reaches it."""

    contexts: list[ExtensionContext] = field(default_factory=list)
    observations: list[SessionStatusObservation] = field(default_factory=list)
    commands: list[CommandEvent] = field(default_factory=list)
    stops: list[tuple[str, WakeStop]] = field(default_factory=list)
    deactivated: int = 0
    background: asyncio.Task[None] | None = None

    async def activate(self, ctx: ExtensionContext) -> Callable[[], Any]:
        self.contexts.append(ctx)

        async def on_status(observation: SessionStatusObservation) -> None:
            self.observations.append(observation)

        async def on_command(event: CommandEvent) -> None:
            self.commands.append(event)
            # Record the enabler before the command answers.
            await ctx.state.write(event.session_id, "enabler", f"{event.user_id}")

        async def on_stop(session_id: str, reason: WakeStop) -> None:
            self.stops.append((session_id, reason))

        ctx.subscribe_status(on_status)
        ctx.on_command(on_command)
        ctx.wake.on_stop(on_stop)
        self.background = ctx.create_task(asyncio.Event().wait(), name="reconcile")

        async def deactivate() -> None:
            self.deactivated += 1

        return deactivate


@pytest.mark.parametrize("enabled", [False, None], ids=["disabled", "not-listed"])
async def test_only_an_enabled_extension_is_activated(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool | None
) -> None:
    recorder = _Recorder()
    _install(monkeypatch, recorder.activate)

    async with _serve(db_uri, tmp_path, enabled=enabled) as server:
        assert server.record() is None
        assert await server.diagnostics() == []
        # Not activated, but its installed prefix stays governed.
        label = f"ext.{_EXT}.goal"
        assert published_field_view().governs(label)
        assert published_field_view().visible_labels({label: "met"}, frozenset({label})) == {}
        with pytest.raises(ExtensionStateUnavailableError):
            server.app.state.extension_activations._state_service.manifest(_EXT)

    assert recorder.contexts == []


async def test_activation_runs_at_startup_and_deactivates_at_shutdown(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    _install(monkeypatch, recorder.activate)

    async with _serve(db_uri, tmp_path) as server:
        [ctx] = recorder.contexts
        assert (ctx.extension_id, ctx.version, ctx.wake.source) == (_EXT, "1.2.0", f"ext:{_EXT}")
        assert await server.diagnostics() == [
            {"extension_id": _EXT, "status": "active", "error": None}
        ]
        assert recorder.deactivated == 0

    assert recorder.deactivated == 1
    assert server.record().state is ActivationState.STOPPED
    assert recorder.background is not None and recorder.background.cancelled()
    with pytest.raises(RuntimeError, match="not active"):
        await ctx.state.read("conv_x", "goal")


async def _raises(_ctx: ExtensionContext) -> None:
    raise RuntimeError("no token configured")


def _not_async(_ctx: ExtensionContext) -> None:
    return None


@pytest.mark.parametrize(
    ("activate", "entrypoint", "error"),
    [
        (_raises, f"{_PACKAGE}.server:activate", "RuntimeError: no token configured"),
        (_not_async, f"{_PACKAGE}.server:activate", "must be an async def"),
        (_raises, "json:loads", "outside the extension's package"),
    ],
    ids=["raises", "not-async", "other-package"],
)
async def test_a_failed_activation_is_quarantined_and_the_server_keeps_serving(
    db_uri: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    activate: Callable[..., Any],
    entrypoint: str,
    error: str,
) -> None:
    _install(monkeypatch, activate)

    async with _serve(db_uri, tmp_path, manifest=_manifest(entrypoint)) as server:
        [record] = await server.diagnostics()
        catalog = await server.client.get("/v1/extensions")

    assert record["status"] == "quarantined"
    assert error in record["error"]
    # Quarantine stops only the server code; the operator's enablement still stands.
    assert catalog.status_code == 200
    assert [item["id"] for item in catalog.json()["data"]] == [_EXT]


async def test_a_failed_activation_drops_what_it_set_up(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts: list[ExtensionContext] = []
    session: dict[str, str] = {}

    async def activate(ctx: ExtensionContext) -> None:
        contexts.append(ctx)
        _session_status_cache[session["id"]] = "running"
        outcome = await ctx.wake.request(
            session["id"], "check CI", on_behalf_of=None, generation=None
        )
        assert outcome is WakeOutcome.QUEUED
        raise RuntimeError("half set up")

    _install(monkeypatch, activate)
    store = SqlAlchemyConversationStore(db_uri)
    session["id"] = store.create_conversation().id
    try:
        async with _serve(db_uri, tmp_path) as server:
            wake: SessionWakeService = server.app.state.session_wake
            assert server.record().state is ActivationState.QUARANTINED
            assert wake.status(session["id"], f"ext:{_EXT}").pending is False
    finally:
        _session_status_cache.pop(session["id"], None)
    with pytest.raises(RuntimeError, match="not active"):
        contexts[0].create_task(asyncio.sleep(0))


async def test_ctx_surfaces_reach_the_real_services(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    _install(monkeypatch, recorder.activate)

    async with _serve(db_uri, tmp_path) as server:
        [ctx] = recorder.contexts
        session_id = server.store.create_conversation().id

        # Own state, with the published key mirrored as a label.
        await ctx.state.write(session_id, "goal", "unmet")
        assert (await ctx.state.read(session_id, "goal")).value == b"unmet"
        labels = server.store.get_conversation(session_id).labels
        assert labels[f"ext.{_EXT}.goal"] == "unmet"
        assert [ref async for ref in ctx.state.sessions(key_prefix="go")] == [
            SessionRef(0, session_id)
        ]
        assert [ref async for ref in ctx.state.sessions(key_prefix="nothing")] == []

        # A declared command reaches on_command before it answers.
        response = await server.client.post(
            f"/v1/sessions/{session_id}/extensions/{_EXT}/commands/{_EXT}.watch",
            json={"arguments": {}},
        )
        assert response.status_code == 200, response.text
        [event] = recorder.commands
        assert (event.extension_id, event.session_id, event.key) == (_EXT, session_id, "goal")
        assert (await ctx.state.read(session_id, "enabler")).value == b"None"

        # Read-only pull requests, and single-owner routing.
        prs = await ctx.pull_requests(session_id)
        assert prs is not None and prs.entries == []
        assert await ctx.serves_session(session_id) is True
        assert await ctx.serves_session("0" * 32) is False

        # Status observations, delivered through the extension tier.
        session_status_observers.observe(
            SessionStatusObservation(session_id, "running", "idle", True)
        )
        await poll_until_async(lambda: recorder.observations, timeout_s=5)
        assert recorder.observations[0].session_id == session_id

        # Wakes go out as ext:<id>, and their stops reach on_stop.
        _session_status_cache[session_id] = "running"
        try:
            outcome = await ctx.wake.request(
                session_id, "PR #7 failed", on_behalf_of=None, generation=None
            )
            assert outcome is WakeOutcome.QUEUED
            assert ctx.wake.status(session_id).pending is True
            server.app.state.session_wake.stop_session(session_id)
            await poll_until_async(lambda: recorder.stops, timeout_s=5)
        finally:
            _session_status_cache.pop(session_id, None)
        assert recorder.stops == [(session_id, WakeStop.STOPPED_BY_USER)]


@dataclass
class _Stubborn:
    """Code that ignores cancellation until the test releases it."""

    released: bool = False

    async def hold(self, seconds: float = 30.0) -> None:
        deadline = time.monotonic() + seconds
        while not self.released and time.monotonic() < deadline:
            with suppress(asyncio.CancelledError):
                await asyncio.sleep(0.05)


@pytest_asyncio.fixture
async def stubborn() -> AsyncIterator[_Stubborn]:
    """Released before the event loop closes, so its leftover tasks can end."""
    holder = _Stubborn()
    yield holder
    holder.released = True
    await asyncio.sleep(0.1)


@pytest.fixture
def short_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extension_activation, "ACTIVATE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(extension_activation, "DEACTIVATE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(extension_activation, "COMMAND_CALLBACK_TIMEOUT_S", 0.2)


async def test_activation_time_limit_holds_against_code_that_ignores_cancellation(
    db_uri: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stubborn: _Stubborn,
    short_limits: None,
) -> None:
    async def activate(_ctx: ExtensionContext) -> None:
        await stubborn.hold()

    _install(monkeypatch, activate)
    started = time.monotonic()
    async with asyncio.timeout(5), _serve(db_uri, tmp_path) as server:
        elapsed = time.monotonic() - started
        record = server.record()
        catalog = await server.client.get("/v1/extensions")

    assert elapsed < 2
    assert record.state is ActivationState.QUARANTINED
    assert "timed out" in record.error
    assert catalog.status_code == 200


async def _cancels_itself(_ctx: ExtensionContext) -> None:
    raise asyncio.CancelledError


async def _exits(_ctx: ExtensionContext) -> None:
    raise SystemExit(3)


class _ExitsOnImport(types.ModuleType):
    def __getattr__(self, name: str) -> Any:
        raise SystemExit(3)


@pytest.mark.parametrize("failure", ["cancels-itself", "exits", "exits-on-import"])
async def test_cancellation_and_exit_from_extension_code_quarantine_it(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    _install(monkeypatch, _cancels_itself if failure == "cancels-itself" else _exits)
    if failure == "exits-on-import":
        monkeypatch.setitem(
            sys.modules, f"{_PACKAGE}.server", _ExitsOnImport(f"{_PACKAGE}.server")
        )

    async with asyncio.timeout(5), _serve(db_uri, tmp_path) as server:
        record = server.record()
        catalog = await server.client.get("/v1/extensions")

    assert record.state is ActivationState.QUARANTINED
    assert catalog.status_code == 200


@pytest.mark.parametrize("failure", ["ignores-cancellation", "cancels-itself"])
async def test_deactivation_is_bounded_and_shutdown_still_closes_services(
    db_uri: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stubborn: _Stubborn,
    short_limits: None,
    failure: str,
) -> None:
    async def activate(_ctx: ExtensionContext) -> Callable[[], Any]:
        async def deactivate() -> None:
            if failure == "cancels-itself":
                raise asyncio.CancelledError
            await stubborn.hold()

        return deactivate

    _install(monkeypatch, activate)
    closed: list[str] = []
    async with asyncio.timeout(5):
        async with _serve(db_uri, tmp_path) as server:
            wake: SessionWakeService = server.app.state.session_wake
            close_wake = wake.aclose

            async def spy() -> None:
                closed.append("wake")
                await close_wake()

            wake.aclose = spy  # type: ignore[method-assign]
            stopping = time.monotonic()
        elapsed = time.monotonic() - stopping

    assert elapsed < 2
    assert closed == ["wake"]
    assert server.record().state is ActivationState.STOPPED


async def test_command_callbacks_share_one_bound_and_never_fail_the_command(
    db_uri: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stubborn: _Stubborn,
    short_limits: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def activate(ctx: ExtensionContext) -> None:
        async def raises(_event: CommandEvent) -> None:
            raise RuntimeError("no enabler recorded")

        async def holds(_event: CommandEvent) -> None:
            await stubborn.hold()

        ctx.on_command(raises)
        ctx.on_command(holds)
        ctx.on_command(holds)

    _install(monkeypatch, activate)
    async with asyncio.timeout(5), _serve(db_uri, tmp_path) as server:
        session_id = server.store.create_conversation().id
        started = time.monotonic()
        with caplog.at_level(logging.ERROR):
            response = await server.client.post(
                f"/v1/sessions/{session_id}/extensions/{_EXT}/commands/{_EXT}.watch",
                json={"arguments": {}},
            )
        elapsed = time.monotonic() - started
        stored = server.store.get_extension_state(session_id, _EXT, "goal")

    assert response.status_code == 200, response.text
    assert stored is not None and stored.value == b"watching"
    assert elapsed < 1
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "no enabler recorded" in caplog.text
    assert "did not finish" in messages


async def test_the_module_must_be_one_of_the_distributions_files() -> None:
    import httpx._client as installed

    assert extension_activation.module_in_distribution(installed, "httpx") is True
    assert extension_activation.module_in_distribution(installed, "pytest") is False
    assert extension_activation.module_in_distribution(json_module, "httpx") is False


async def test_imports_finish_before_any_activation_time_starts(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, short_limits: None
) -> None:
    async def quick(_ctx: ExtensionContext) -> None:
        await asyncio.sleep(0.1)

    _install(monkeypatch, quick)
    _install(monkeypatch, quick, "zeta_slow_fixture")
    import_module = importlib.import_module

    def slow_import(name: str, package: str | None = None) -> types.ModuleType:
        if name == "zeta_slow_fixture.server":
            time.sleep(0.4)  # longer than any activation's time limit
        return import_module(name, package)

    monkeypatch.setattr(extension_activation.importlib, "import_module", slow_import)
    others = (_other("zeta.slow", "zeta_slow_fixture"),)
    async with asyncio.timeout(5), _serve(db_uri, tmp_path, others=others) as server:
        records = server.app.state.extension_activations.records()

    assert {key: record.state for key, record in records.items()} == {
        _EXT: ActivationState.ACTIVE,
        "zeta.slow": ActivationState.ACTIVE,
    }


async def test_extensions_activate_concurrently(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spans: dict[str, tuple[float, float]] = {}

    async def activate(ctx: ExtensionContext) -> None:
        started = time.monotonic()
        await asyncio.sleep(0.2)
        spans[ctx.extension_id] = (started, time.monotonic())

    others = tuple(_other(f"zeta.n{index}", f"zeta_n{index}_fixture") for index in range(3))
    _install(monkeypatch, activate)
    for _, package in others:
        _install(monkeypatch, activate, package)
    async with asyncio.timeout(5), _serve(db_uri, tmp_path, others=others):
        pass

    assert len(spans) == 4
    assert max(start for start, _ in spans.values()) < min(end for _, end in spans.values())


async def test_a_module_the_distribution_did_not_install_is_quarantined(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    _install(monkeypatch, recorder.activate)
    monkeypatch.setattr(
        extension_activation, "module_in_distribution", lambda _module, _distribution: False
    )

    async with _serve(db_uri, tmp_path) as server:
        record = server.record()

    assert recorder.contexts == []
    assert record.state is ActivationState.QUARANTINED
    assert "not a file of the installed distribution" in record.error


async def test_command_callbacks_run_concurrently(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extension_activation, "COMMAND_CALLBACK_TIMEOUT_S", 0.5)
    finished: list[int] = []

    async def activate(ctx: ExtensionContext) -> None:
        for index in range(4):

            async def takes_a_while(_event: CommandEvent, index: int = index) -> None:
                await asyncio.sleep(0.2)
                finished.append(index)

            ctx.on_command(takes_a_while)

    _install(monkeypatch, activate)
    async with asyncio.timeout(5), _serve(db_uri, tmp_path) as server:
        session_id = server.store.create_conversation().id
        response = await server.client.post(
            f"/v1/sessions/{session_id}/extensions/{_EXT}/commands/{_EXT}.watch",
            json={"arguments": {}},
        )

    assert response.status_code == 200, response.text
    # Run one after another, only two would finish within the shared 0.5 s.
    assert sorted(finished) == [0, 1, 2, 3]


async def test_sessions_iterates_past_the_first_page(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    _install(monkeypatch, recorder.activate)
    async with asyncio.timeout(20), _serve(db_uri, tmp_path) as server:
        [ctx] = recorder.contexts
        ids = sorted(uuid.uuid4().hex for _ in range(205))
        with server.store._conv_engine.begin() as connection:
            connection.execute(
                insert(SqlExtensionSessionState.__table__),
                [
                    {
                        "workspace_id": 0,
                        "conversation_id": conv_id,
                        "extension_id": _EXT,
                        "key": "goal",
                        "value": b"\x01v",
                        "version": 1,
                        "updated_at": 1,
                        "updated_by": None,
                    }
                    for conv_id in ids
                ],
            )

        listed = [ref.session_id async for ref in ctx.state.sessions()]

    assert listed == ids


async def test_serves_session_can_require_a_host(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    _install(monkeypatch, recorder.activate)
    async with _serve(db_uri, tmp_path) as server:
        [ctx] = recorder.contexts
        hostless = server.store.create_conversation().id
        host_here, host_elsewhere = "a" * 32, "b" * 32
        here = server.store.create_conversation(host_id=host_here, workspace="/w").id
        elsewhere = server.store.create_conversation(host_id=host_elsewhere, workspace="/w").id
        registry = server.app.state.host_registry
        monkeypatch.setattr(
            registry,
            "get",
            lambda host_id, workspace_id=None: object() if host_id == host_here else None,
        )

        served = {
            session_id: (
                await ctx.serves_session(session_id),
                await ctx.serves_session(session_id, require_host=True),
            )
            for session_id in (hostless, here, elsewhere)
        }

    assert served == {
        hostless: (True, False),
        here: (True, True),
        elsewhere: (False, False),
    }


async def test_pull_request_info_reads_through_the_panel_reader(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    _install(monkeypatch, recorder.activate)
    monkeypatch.setattr(extension_activation, "PULL_REQUEST_INFO_TIMEOUT_S", 0.2)
    pr_url = "https://github.com/acme/repo/pull/7"
    async with asyncio.timeout(5), _serve(db_uri, tmp_path) as server:
        [ctx] = recorder.contexts
        session_id = server.store.create_conversation().id
        # The panel's reader answers only where the session's host is connected.
        assert callable(server.app.state.pull_request_info)
        assert await ctx.pull_request_info(session_id, pr_url) is None

        calls: list[tuple[str, str]] = []

        async def reader(sid: str, url: str) -> dict[str, Any]:
            calls.append((sid, url))
            if url.endswith("/8"):
                await asyncio.sleep(1)
            return {"available": True, "pr": {"url": url, "headRefOid": "abc"}}

        server.app.state.pull_request_info = reader
        info = await ctx.pull_request_info(session_id, pr_url)
        with pytest.raises(TimeoutError):
            await ctx.pull_request_info(session_id, pr_url[:-1] + "8")

    assert info == {"available": True, "pr": {"url": pr_url, "headRefOid": "abc"}}
    assert calls[0] == (session_id, pr_url)
