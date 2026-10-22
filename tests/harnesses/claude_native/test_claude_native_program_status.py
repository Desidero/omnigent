"""Concurrency coverage for the Claude OSC status adapter."""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from omnigent.harnesses.claude_native.program_status import ClaudeProgramStatusPoller
from omnigent.harnesses.claude_native.status_file import SessionStatusPoller
from omnigent.terminals.program_status import ProgramStatusReader


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


def _write_report(path: Path, state: str, message: str | None = None) -> None:
    status = {"state": state, "app": "claude-code", "message": message}
    path.write_text(json.dumps({"relay_pid": os.getpid(), "status": status}))


def _delegate_poller(
    tmp_path: Path, prompt_at_ms: list[int | None]
) -> tuple[ClaudeProgramStatusPoller, Path, list[str]]:
    """Build an OSC poller over a working report, with a settable prompt time."""
    path = tmp_path / "program-status.json"
    _write_report(path, "working")
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


def test_changed_report_ends_the_delegate_holdover(tmp_path: Path) -> None:
    """A new report means Claude moved on, even if it later repeats the held one."""
    poller, path, published = _delegate_poller(tmp_path, [None])

    _write_report(path, "working", "Reading the delegate's result")
    poller.tick()
    _write_report(path, "working")
    poller.tick()
    assert published == ["running", "idle", "running", "running"]


def test_other_report_ends_the_delegate_holdover(tmp_path: Path) -> None:
    """A permission prompt in between means the held report no longer holds."""
    poller, path, published = _delegate_poller(tmp_path, [None])

    _write_report(path, "blocked")
    poller.tick()
    _write_report(path, "working")
    poller.tick()
    assert published == ["running", "idle", "running", "running"]


def test_report_changed_before_the_stop_tick_is_not_held(tmp_path: Path) -> None:
    """The holdover keeps the report seen before the Stop, not a newer one."""
    path = tmp_path / "program-status.json"
    _write_report(path, "working")
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
        prompt_submitted_at_getter=lambda: None,
    )
    poller.tick()
    poller.note_turn_ended(2000)
    _write_report(path, "working", "Starting a new turn")
    poller.tick()
    assert published == ["running", "running"]


def test_osc_returning_after_a_gap_does_not_resume_the_holdover(tmp_path: Path) -> None:
    """While OSC was gone the file fallback owned status; its return reads running."""
    poller, path, published = _delegate_poller(tmp_path, [None])

    path.unlink()
    poller.tick()
    _write_report(path, "working")
    poller.tick()
    assert published == ["running", "idle", "running"]
