"""Core status observers: which edges they see, in what order, and their isolation."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from omnigent.db.db_models import workspace_scope
from omnigent.server import session_status_observers as observers
from omnigent.server.routes._sessions import helpers
from omnigent.server.session_status_observers import SessionStatusObservation

SESSION = "5e5510b5e5510b5e5510b5e5510b5e55"


@pytest.fixture()
def observed(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[SessionStatusObservation]]:
    seen: list[SessionStatusObservation] = []
    monkeypatch.setattr(helpers.session_live_state, "persist_live_status", lambda *_: None)
    monkeypatch.delitem(helpers._session_status_cache, SESSION, raising=False)
    monkeypatch.delitem(helpers._session_active_response_cache, SESSION, raising=False)
    unregister = observers.register_core_observer(seen.append)
    yield seen
    unregister()


def test_observers_see_each_status_change_with_its_publisher(
    observed: list[SessionStatusObservation],
) -> None:
    with workspace_scope(3):
        helpers._publish_status(SESSION, "running", response_id="resp_1")
        helpers._publish_status(SESSION, "running", response_id="resp_1")
        helpers._publish_status(SESSION, "waiting", blocked_on="approval")
        helpers._publish_status(SESSION, "idle", persist_live_status=False)

    assert [
        (
            item.previous_status,
            item.status,
            item.persist_requested,
            item.response_id,
            item.blocked_on,
            item.workspace_id,
        )
        for item in observed
    ] == [
        (None, "running", True, "resp_1", None, 3),
        ("running", "waiting", True, None, "approval", 3),
        ("waiting", "idle", False, None, None, 3),
    ]
    assert observed[0].type == "session.status"
    assert observed[0].schema_version == 1


def test_an_idle_that_sticky_failed_suppresses_is_not_observed(
    observed: list[SessionStatusObservation],
) -> None:
    helpers._publish_status(SESSION, "running")
    helpers._publish_status(SESSION, "failed")
    helpers._publish_status(SESSION, "idle")
    helpers._publish_status(SESSION, "idle", turn_completed=True)

    assert [(item.previous_status, item.status) for item in observed] == [
        (None, "running"),
        ("running", "failed"),
        ("failed", "idle"),
    ]


def test_a_failing_observer_does_not_stop_later_observers_or_the_publisher(
    observed: list[SessionStatusObservation],
    caplog: pytest.LogCaptureFixture,
) -> None:
    order: list[str] = []

    def failing(_: SessionStatusObservation) -> None:
        order.append("failing")
        raise RuntimeError("observer bug")

    unregister_failing = observers.register_core_observer(failing)
    unregister_last = observers.register_core_observer(lambda _: order.append("last"))
    try:
        helpers._publish_status(SESSION, "running")
    finally:
        unregister_failing()
        unregister_last()

    assert order == ["failing", "last"]
    assert len(observed) == 1
    assert helpers._session_status_cache[SESSION] == "running"
    assert "session status observer" in caplog.text


def test_registering_twice_keeps_one_registration_until_unregistered(
    observed: list[SessionStatusObservation],
) -> None:
    unregister = observers.register_core_observer(observed.append)
    helpers._publish_status(SESSION, "running")
    assert len(observed) == 1

    unregister()
    helpers._publish_status(SESSION, "idle")
    assert len(observed) == 1


def test_an_observer_that_publishes_inline_leaves_its_own_edge_last(
    observed: list[SessionStatusObservation], monkeypatch: pytest.MonkeyPatch
) -> None:
    streamed: list[str] = []
    # Patch the module itself: ``helpers.session_stream`` is a facade proxy, and
    # restoring an attribute on it would pin the real ``publish`` for later tests.
    monkeypatch.setattr(
        "omnigent.runtime.session_stream.publish",
        lambda session_id, payload: streamed.append(payload["status"]),
    )

    def start_next_turn(observation: SessionStatusObservation) -> None:
        if observation.status == "idle":
            helpers._publish_status(SESSION, "running", response_id="resp_next")

    unregister = observers.register_core_observer(start_next_turn)
    try:
        helpers._publish_status(SESSION, "running", response_id="resp_1")
        helpers._publish_status(SESSION, "idle")
    finally:
        unregister()

    assert streamed == ["running", "idle", "running"]
    assert helpers._session_status_cache[SESSION] == "running"
    assert helpers._session_active_response_cache[SESSION] == "resp_next"
    assert [item.status for item in observed] == ["running", "idle", "running"]


def test_an_invalid_status_never_reaches_observers(
    observed: list[SessionStatusObservation],
) -> None:
    with pytest.raises(ValueError):
        helpers._publish_status(SESSION, "not-a-status")
    assert observed == []
