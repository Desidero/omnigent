"""Extension status observers: enablement, context, bounds, isolation and shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from omnigent.db.db_models import current_workspace_id, workspace_scope
from omnigent.server import session_status_observers
from omnigent.server.extension_status_observers import (
    ExtensionNotEnabledError,
    ExtensionStatusObservers,
    SubscriberStats,
)
from omnigent.server.routes._sessions import helpers
from omnigent.server.session_status_observers import SessionStatusObservation
from tests._helpers.polling import poll_until_async

SESSION = "e7e75e55e7e75e55e7e75e55e7e75e55"
EXTENSION = "example.status-watch"


def _observation(status: str, previous: str | None = None) -> SessionStatusObservation:
    return SessionStatusObservation(
        session_id=SESSION, previous_status=previous, status=status, persist_requested=True
    )


async def _settle(hub: ExtensionStatusObservers, extension_id: str, handled: int) -> None:
    """Wait until ``handled`` observations finished, whatever their outcome."""

    def finished() -> bool:
        stats = hub.stats()[extension_id]
        return stats.delivered + stats.failed + stats.timed_out >= handled

    await poll_until_async(finished, timeout_s=5)


@pytest.fixture()
async def make_hub() -> AsyncIterator[Callable[..., ExtensionStatusObservers]]:
    """Start observers that are closed after the test, even when it fails."""
    started: list[ExtensionStatusObservers] = []

    def make(**options: Any) -> ExtensionStatusObservers:
        observers = ExtensionStatusObservers(**options)
        observers.start()
        started.append(observers)
        return observers

    yield make
    for observers in started:
        await observers.aclose(wait_s=0.5)


@pytest.fixture()
async def hub(make_hub: Callable[..., ExtensionStatusObservers]) -> ExtensionStatusObservers:
    enabled = {EXTENSION, "example.other"}
    return make_hub(is_enabled=enabled.__contains__, max_pending=2)


async def test_callbacks_run_in_the_publishers_workspace_on_and_off_the_loop(
    hub: ExtensionStatusObservers, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[int, str]] = []

    async def on_status(observation: SessionStatusObservation) -> None:
        seen.append((current_workspace_id(), observation.status))

    hub.subscribe(EXTENSION, on_status)
    monkeypatch.setattr(helpers.session_live_state, "persist_live_status", lambda *_: None)
    monkeypatch.delitem(helpers._session_status_cache, SESSION, raising=False)

    with workspace_scope(4):
        helpers._publish_status(SESSION, "running")
    await _settle(hub, EXTENSION, 1)

    def publish_idle_from_a_thread() -> None:
        with workspace_scope(5):
            helpers._publish_status(SESSION, "idle")

    await asyncio.to_thread(publish_idle_from_a_thread)
    await _settle(hub, EXTENSION, 2)

    assert seen == [(4, "running"), (5, "idle")]


async def test_subscribe_takes_async_callbacks_on_the_loop_only(
    hub: ExtensionStatusObservers,
) -> None:
    def on_status_sync(_: SessionStatusObservation) -> None:
        raise AssertionError("never called")

    async def on_status(_: SessionStatusObservation) -> None:
        raise AssertionError("never called")

    with pytest.raises(TypeError, match="must be async"):
        hub.subscribe(EXTENSION, on_status_sync)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="event loop"):
        await asyncio.to_thread(hub.subscribe, EXTENSION, on_status)
    assert hub.stats() == {}


async def test_only_installed_and_enabled_extensions_receive_observations(
    make_hub: Callable[..., ExtensionStatusObservers],
) -> None:
    enabled = {EXTENSION}
    hub = make_hub(is_enabled=enabled.__contains__)
    seen: list[str] = []

    async def on_status(observation: SessionStatusObservation) -> None:
        seen.append(observation.status)

    with pytest.raises(ExtensionNotEnabledError):
        hub.subscribe("example.not-enabled", on_status)
    hub.subscribe(EXTENSION, on_status)
    session_status_observers.observe(_observation("running"))
    await _settle(hub, EXTENSION, 1)

    enabled.clear()
    session_status_observers.observe(_observation("idle", "running"))
    await hub.aclose()
    assert seen == ["running"]
    assert hub.stats()[EXTENSION] == SubscriberStats(delivered=1)

    # Closed observers no longer see edges.
    session_status_observers.observe(_observation("running", "idle"))
    assert hub.stats()[EXTENSION] == SubscriberStats(delivered=1)


async def test_a_full_backlog_drops_and_counts_in_order(
    hub: ExtensionStatusObservers,
) -> None:
    release = asyncio.Event()
    seen: list[str] = []

    async def on_status(observation: SessionStatusObservation) -> None:
        seen.append(observation.status)
        await release.wait()

    hub.subscribe(EXTENSION, on_status)
    for status in ("running", "waiting", "idle", "running", "idle"):
        session_status_observers.observe(_observation(status))
    release.set()
    await _settle(hub, EXTENSION, 2)

    assert seen == ["running", "waiting"]
    assert hub.stats()[EXTENSION] == SubscriberStats(delivered=2, dropped=3)


async def test_a_callback_that_ignores_cancellation_keeps_its_slot_until_it_returns(
    make_hub: Callable[..., ExtensionStatusObservers],
) -> None:
    hub = make_hub(is_enabled=lambda _: True, max_pending=2, callback_timeout_s=0.02)
    release = asyncio.Event()
    running = 0
    peak = 0

    async def stubborn(_: SessionStatusObservation) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        try:
            while not release.is_set():
                # Deliberately ignores cancellation, like a misbehaving extension.
                with contextlib.suppress(asyncio.CancelledError):
                    await release.wait()
        finally:
            running -= 1

    hub.subscribe(EXTENSION, stubborn)
    for status in ("running", "waiting", "idle", "running", "idle"):
        session_status_observers.observe(_observation(status))
    await poll_until_async(lambda: hub.stats()[EXTENSION].timed_out == 1, timeout_s=5)
    # Still running after its timeout, so it counts against the backlog.
    session_status_observers.observe(_observation("waiting"))
    await hub.aclose(wait_s=0.05)
    stats = hub.stats()[EXTENSION]
    release.set()
    await poll_until_async(lambda: running == 0, timeout_s=5)

    assert peak == 1
    assert stats == SubscriberStats(timed_out=1, dropped=4, abandoned=2)


async def test_failures_and_timeouts_are_counted_without_affecting_others(
    make_hub: Callable[..., ExtensionStatusObservers],
) -> None:
    hub = make_hub(is_enabled=lambda _: True, max_pending=4, callback_timeout_s=0.05)
    calls = 0
    healthy: list[str] = []

    async def flaky(observation: SessionStatusObservation) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("extension bug")
        if calls == 2:
            await asyncio.sleep(60)

    async def healthy_callback(observation: SessionStatusObservation) -> None:
        healthy.append(observation.status)

    hub.subscribe("example.flaky", flaky)
    hub.subscribe("example.healthy", healthy_callback)
    for status in ("running", "idle", "running"):
        session_status_observers.observe(_observation(status))
    await _settle(hub, "example.flaky", 3)
    await _settle(hub, "example.healthy", 3)
    await hub.aclose()

    assert hub.stats() == {
        "example.flaky": SubscriberStats(delivered=1, failed=1, timed_out=1),
        "example.healthy": SubscriberStats(delivered=3),
    }
    assert healthy == ["running", "idle", "running"]


async def test_shutdown_drains_quick_backlogs(
    make_hub: Callable[..., ExtensionStatusObservers],
) -> None:
    hub = make_hub(is_enabled=lambda _: True)
    seen: list[str] = []

    async def on_status(observation: SessionStatusObservation) -> None:
        await asyncio.sleep(0.01)
        seen.append(observation.status)

    hub.subscribe(EXTENSION, on_status)
    for status in ("running", "idle"):
        session_status_observers.observe(_observation(status))
    await hub.aclose(wait_s=5)

    assert seen == ["running", "idle"]
    assert hub.stats()[EXTENSION] == SubscriberStats(delivered=2)


async def test_shutdown_stops_waiting_for_stuck_callbacks_and_counts_them(
    make_hub: Callable[..., ExtensionStatusObservers],
) -> None:
    hub = make_hub(is_enabled=lambda _: True, callback_timeout_s=60)
    started = asyncio.Event()

    async def stuck(_: SessionStatusObservation) -> None:
        started.set()
        await asyncio.sleep(60)

    hub.subscribe(EXTENSION, stuck)
    for status in ("running", "idle"):
        session_status_observers.observe(_observation(status))
    await asyncio.wait_for(started.wait(), timeout=5)

    began = time.monotonic()
    await hub.aclose(wait_s=0.1)

    assert time.monotonic() - began < 2
    assert hub.stats() == {EXTENSION: SubscriberStats(abandoned=2)}


async def test_a_failure_after_cancellation_is_retrieved_not_left_unhandled(
    make_hub: Callable[..., ExtensionStatusObservers],
    caplog: pytest.LogCaptureFixture,
) -> None:
    hub = make_hub(is_enabled=lambda _: True, callback_timeout_s=0.02)
    release = asyncio.Event()
    unhandled: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: unhandled.append(context))

    async def stubborn_then_failing(_: SessionStatusObservation) -> None:
        # Deliberately ignores cancellation, then fails, like a misbehaving extension.
        with contextlib.suppress(asyncio.CancelledError):
            await release.wait()
        await release.wait()
        raise RuntimeError("late extension bug")

    try:
        hub.subscribe(EXTENSION, stubborn_then_failing)
        session_status_observers.observe(_observation("idle"))
        await poll_until_async(lambda: hub.stats()[EXTENSION].timed_out == 1, timeout_s=5)
        with caplog.at_level("DEBUG", logger="omnigent.server.extension_status_observers"):
            release.set()
            await poll_until_async(lambda: "late extension bug" in caplog.text, timeout_s=5)
        gc.collect()
    finally:
        loop.set_exception_handler(previous_handler)

    assert unhandled == []
    assert hub.stats()[EXTENSION] == SubscriberStats(timed_out=1)
