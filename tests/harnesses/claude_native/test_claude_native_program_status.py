"""Concurrency coverage for the Claude OSC status adapter."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from omnigent.debug_logging import record_to_row
from omnigent.harnesses.claude_native.program_status import ClaudeProgramStatusPoller
from omnigent.harnesses.claude_native.status_file import SessionStatusPoller
from omnigent.terminals.program_status import ProgramStatusReader

# The production grace period, from ERROR_HOOK_GRACE_S.
_GRACE_S = 5.0
_ERROR_REPORT = {"state": "error", "app": "claude-code", "message": "API Error: 499"}


class _FakeClock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _write_report(path: Path, status: dict[str, object]) -> None:
    path.write_text(json.dumps({"relay_pid": os.getpid(), "status": status}))


def _poller(
    tmp_path: Path,
    path: Path,
    published: list[str],
    *,
    turn_is_active: Callable[[], bool] | None = None,
    turn_activity_epoch: Callable[[], int] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ClaudeProgramStatusPoller:
    def on_status(status: str, _reason: str | None) -> None:
        published.append(status)

    return ClaudeProgramStatusPoller(
        ProgramStatusReader(path),
        SessionStatusPoller(
            on_status=on_status,
            pane_pid_getter=lambda: None,
            session_id_getter=lambda: None,
            config_dir=tmp_path,
        ),
        on_status,
        turn_is_active=turn_is_active,
        turn_activity_epoch=turn_activity_epoch,
        clock=clock,
    )


def test_error_report_without_a_hook_edge_fails_the_turn_once(tmp_path: Path) -> None:
    """A turn the runner still counts in flight fails once when its hook never lands."""
    path = tmp_path / "program-status.json"
    _write_report(path, _ERROR_REPORT)
    clock = _FakeClock()
    published: list[str] = []
    poller = _poller(tmp_path, path, published, turn_is_active=lambda: True, clock=clock)
    poller.tick()
    clock.now = _GRACE_S - 1
    poller.resync()
    poller.tick()
    assert published == []
    clock.now = _GRACE_S * 6
    poller.tick()
    poller.tick()
    assert published == ["failed"]


def test_forwarded_hook_edge_cancels_the_grace_period(tmp_path: Path) -> None:
    """Once the hook's terminal edge clears the turn, the standing error report fails nothing."""
    path = tmp_path / "program-status.json"
    _write_report(path, _ERROR_REPORT)
    clock = _FakeClock()
    turn_active = [True]
    published: list[str] = []
    poller = _poller(tmp_path, path, published, turn_is_active=lambda: turn_active[0], clock=clock)
    poller.tick()
    turn_active[0] = False
    clock.now = _GRACE_S * 6
    poller.tick()
    assert published == []


@pytest.mark.parametrize("poll_between_turns", [True, False])
def test_new_turn_on_a_standing_error_report_gets_its_own_grace_period(
    tmp_path: Path, poll_between_turns: bool
) -> None:
    """A turn dispatched after the previous hook landed is not failed by the old timer."""
    path = tmp_path / "program-status.json"
    _write_report(path, _ERROR_REPORT)
    clock = _FakeClock()
    turn_active = [True]
    activity_epoch = [1]
    published: list[str] = []
    poller = _poller(
        tmp_path,
        path,
        published,
        turn_is_active=lambda: turn_active[0],
        turn_activity_epoch=lambda: activity_epoch[0],
        clock=clock,
    )
    poller.tick()
    clock.now = 2.0
    turn_active[0] = False
    if poll_between_turns:
        poller.tick()
    clock.now = 3.0
    turn_active[0] = True
    activity_epoch[0] += 1
    poller.tick()
    clock.now = 3.0 + _GRACE_S - 1  # The old timer would have expired at _GRACE_S.
    poller.tick()
    assert published == []
    clock.now = 3.0 + _GRACE_S + 1
    poller.tick()
    assert published == ["failed"]


def test_error_report_leaves_the_failed_edge_to_the_stop_failure_hook(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An error report publishes nothing, so the hook's detailed failure is the turn's only one."""
    caplog.set_level(logging.INFO)
    path = tmp_path / "program-status.json"
    path.write_text(
        json.dumps(
            {
                "relay_pid": os.getpid(),
                "status": {
                    "state": "error",
                    "app": "claude-code",
                    "message": "private-synthetic-error-text",
                },
            }
        )
    )
    published: list[str] = []

    def on_status(status: str, _reason: str | None) -> None:
        published.append(status)

    poller = ClaudeProgramStatusPoller(
        ProgramStatusReader(path),
        SessionStatusPoller(
            on_status=on_status,
            pane_pid_getter=lambda: None,
            session_id_getter=lambda: None,
            config_dir=tmp_path,
        ),
        on_status,
        omnigent_session_id="synthetic-session",
        terminal_instance_id="synthetic-terminal",
        terminal_launch_id="synthetic-launch",
    )
    poller.tick()
    poller.resync()
    poller.tick()
    assert published == []
    observations = [
        record
        for record in caplog.records
        if getattr(record, "event_name", None) == "claude_program_error_observed"
    ]
    assert len(observations) == 1
    assert observations[0].levelno == logging.INFO
    row = record_to_row(observations[0], source="runner")
    assert row["session_id"] == "synthetic-session"
    assert row["attributes"]["terminal_instance_id"] == "synthetic-terminal"
    assert row["attributes"]["terminal_launch_id"] == "synthetic-launch"
    assert row["attributes"]["status_publication"] == "deferred_to_stop_failure"
    assert "private-synthetic-error-text" not in json.dumps(row)

    path.write_text(json.dumps({"relay_pid": os.getpid(), "status": {"state": "working"}}))
    poller.tick()
    assert published == ["running"]
    path.write_text(json.dumps({"relay_pid": os.getpid(), "status": {"state": "error"}}))
    poller.tick()
    poller.tick()
    poller.retire()
    poller.tick()
    assert published == ["running"]
    assert (
        sum(
            getattr(record, "event_name", None) == "claude_program_error_observed"
            for record in caplog.records
        )
        == 2
    )


def test_resync_during_tick_survives_the_in_flight_read(tmp_path: Path, monkeypatch) -> None:
    """A forwarded idle edge cannot lose its resync to an in-flight OSC read."""
    path = tmp_path / "program-status.json"
    path.write_text(json.dumps({"relay_pid": os.getpid(), "status": {"state": "idle"}}))
    published: list[str] = []

    def on_status(status: str, _reason: str | None) -> None:
        published.append(status)

    poller = ClaudeProgramStatusPoller(
        ProgramStatusReader(path),
        SessionStatusPoller(
            on_status=on_status,
            pane_pid_getter=lambda: None,
            session_id_getter=lambda: None,
            config_dir=tmp_path,
        ),
        on_status,
    )
    poller.tick()
    assert published == ["idle"]

    path.write_text(json.dumps({"relay_pid": os.getpid(), "status": {"state": "working"}}))
    entered = threading.Event()
    release = threading.Event()
    original_read = Path.read_text

    def pause_read(file: Path, *args, **kwargs):
        result = original_read(file, *args, **kwargs)
        if file == path and threading.current_thread() is not threading.main_thread():
            entered.set()
            assert release.wait(5), "poller did not resume"
        return result

    monkeypatch.setattr(Path, "read_text", pause_read)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(poller.tick)
        try:
            assert entered.wait(5), "poller did not reach the snapshot read"
            poller.resync()
        finally:
            release.set()
        pending.result(timeout=5)

    assert published == ["idle", "running"]
    poller.tick()
    assert published == ["idle", "running", "running"]
    poller.tick()
    assert published == ["idle", "running", "running"]


def _write_state_report(path: Path, state: str, message: str | None = None) -> None:
    status = {"state": state, "app": "claude-code", "message": message}
    path.write_text(json.dumps({"relay_pid": os.getpid(), "status": status}))


def _delegate_poller(
    tmp_path: Path, prompt_at_ms: list[int | None]
) -> tuple[ClaudeProgramStatusPoller, Path, list[str]]:
    """Build an OSC poller over a working report, with a settable prompt time."""
    path = tmp_path / "program-status.json"
    _write_state_report(path, "working")
    published: list[str] = []

    def on_status(status: str, _reason: str | None) -> None:
        published.append(status)

    poller = ClaudeProgramStatusPoller(
        ProgramStatusReader(path),
        SessionStatusPoller(
            on_status=on_status,
            pane_pid_getter=lambda: None,
            session_id_getter=lambda: None,
            config_dir=tmp_path,
        ),
        on_status,
        prompt_submitted_at_getter=lambda: prompt_at_ms[0],
    )
    poller.tick()
    poller.note_turn_ended(2000)
    poller.tick()
    return poller, path, published


def test_working_report_after_delegate_stop_reads_idle_until_prompt(tmp_path: Path) -> None:
    """A delegate keeps Claude's report working; the ended turn still reads idle."""
    prompt_at_ms: list[int | None] = [1000]
    poller, _path, published = _delegate_poller(tmp_path, prompt_at_ms)

    assert published == ["running", "idle"]
    assert poller.reports_busy is True
    poller.tick()
    assert published == ["running", "idle"]

    # Claude starts the delegate's completion turn without changing the report.
    prompt_at_ms[0] = 3000
    poller.tick()
    assert published == ["running", "idle", "running"]


def test_runner_turn_ends_the_delegate_holdover(tmp_path: Path) -> None:
    """A turn the runner delivers after the Stop reads running."""
    poller, _path, published = _delegate_poller(tmp_path, [None])

    poller.note_turn_started(3000)
    poller.tick()
    assert published == ["running", "idle", "running"]


def test_message_change_keeps_the_delegate_holdover_until_a_prompt(tmp_path: Path) -> None:
    """Only a new turn or a state change ends the holdover, not a new message."""
    prompt_at_ms: list[int | None] = [1000]
    poller, path, published = _delegate_poller(tmp_path, prompt_at_ms)

    _write_state_report(path, "working", "Waiting on the delegate")
    poller.tick()
    assert published == ["running", "idle", "idle"]

    prompt_at_ms[0] = 3000
    _write_state_report(path, "working", "Reading the delegate's result")
    poller.tick()
    assert published == ["running", "idle", "idle", "running"]


def test_other_report_ends_the_delegate_holdover(tmp_path: Path) -> None:
    """A permission prompt in between means the held report no longer holds."""
    poller, path, published = _delegate_poller(tmp_path, [None])

    _write_state_report(path, "blocked")
    poller.tick()
    _write_state_report(path, "working")
    poller.tick()
    assert published == ["running", "idle", "running", "running"]


def test_message_cleared_after_the_stop_is_noted_stays_held(tmp_path: Path) -> None:
    """Claude may clear the turn's message after the Stop reaches the poller."""
    path = tmp_path / "program-status.json"
    _write_state_report(path, "working")
    published: list[str] = []

    def on_status(status: str, _reason: str | None) -> None:
        published.append(status)

    poller = ClaudeProgramStatusPoller(
        ProgramStatusReader(path),
        SessionStatusPoller(
            on_status=on_status,
            pane_pid_getter=lambda: None,
            session_id_getter=lambda: None,
            config_dir=tmp_path,
        ),
        on_status,
        prompt_submitted_at_getter=lambda: 1000,
    )
    poller.note_turn_started(1000)
    poller.tick()
    _write_state_report(path, "working", "Running a long command")
    poller.tick()
    poller.note_turn_ended(2000)
    _write_state_report(path, "working")
    poller.tick()
    poller.tick()
    assert published == ["running", "running", "idle"]
    assert poller.reports_busy is True


def test_osc_returning_after_a_gap_does_not_resume_the_holdover(tmp_path: Path) -> None:
    """While OSC was gone the file fallback owned status; its return reads running."""
    poller, path, published = _delegate_poller(tmp_path, [None])

    path.unlink()
    poller.tick()
    _write_state_report(path, "working")
    poller.tick()
    assert published == ["running", "idle", "running"]
