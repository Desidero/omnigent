"""A fake extension context for the goal loop's unit tests."""

from __future__ import annotations

import asyncio
import contextlib
import copy
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from desidero_goal_loop.pr_green import PrGreen

from omnigent.stores.conversation_store import ExtensionStateConflictError

SESSION = "s1"
HEAD = "a" * 40


@dataclass
class Entry:
    key: str
    value: bytes
    version: int
    updated_at: int = 0


@dataclass
class Linked:
    url: str
    repository: str
    number: int
    title: str | None = None
    state: str | None = "OPEN"


@dataclass
class LinkedList:
    entries: list[Linked]
    synced: bool = True


@dataclass
class WakeStatus:
    pending: bool = False
    in_flight: bool = False
    wakes: int = 0
    max_wakes: int = 50
    failures: int = 0
    next_eligible_in_s: float = 0.0
    stopped: Any = None


@dataclass
class SessionRef:
    workspace_id: int
    session_id: str


@dataclass
class CommandEvent:
    session_id: str
    key: str
    user_id: str | None = "alice@example.com"
    generation: str | None = "g1"
    deleted: bool = False
    workspace_id: int = 0
    command_id: str = "desidero.goal-loop.all"
    extension_id: str = "desidero.goal-loop"


@dataclass
class Observation:
    session_id: str
    previous_status: str | None
    status: str
    persist_requested: bool = True
    workspace_id: int = 0


class FakeState:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Entry]] = {}
        self.writes: list[tuple[str, str, str]] = []
        # A logical clock for ``updated_at``; tests advance it between commands.
        self.now = 0

    @staticmethod
    def _expect(key: str, old: Entry | None, expected_version: int | None) -> None:
        current = old.version if old is not None else None
        if expected_version is not None and (current or 0) != expected_version:
            raise ExtensionStateConflictError(key, expected_version, current)

    async def read(self, session_id: str, key: str) -> Entry | None:
        return self.rows.get(session_id, {}).get(key)

    async def entries(self, session_id: str) -> list[Entry]:
        return sorted(self.rows.get(session_id, {}).values(), key=lambda entry: entry.key)

    async def write(
        self,
        session_id: str,
        key: str,
        value: str | bytes,
        *,
        expected_version: int | None = None,
        **_: Any,
    ) -> Entry:
        data = value.encode() if isinstance(value, str) else value
        assert len(data) <= 16_382, f"{key} is {len(data)} bytes"
        rows = self.rows.setdefault(session_id, {})
        old = rows.get(key)
        self._expect(key, old, expected_version)
        rows[key] = Entry(key, data, (old.version if old else 0) + 1, self.now)
        self.writes.append((session_id, key, data.decode()))
        return rows[key]

    async def clear(
        self, session_id: str, key: str, *, expected_version: int | None = None
    ) -> bool:
        rows = self.rows.get(session_id, {})
        old = rows.get(key)
        if old is not None:
            self._expect(key, old, expected_version)
        return rows.pop(key, None) is not None

    async def sessions(self) -> Any:
        for session_id, rows in list(self.rows.items()):
            if rows:
                yield SessionRef(0, session_id)

    def text(self, session_id: str, key: str) -> str | None:
        entry = self.rows.get(session_id, {}).get(key)
        return entry.value.decode() if entry else None


class FakeWake:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.statuses: dict[str, WakeStatus] = {}
        self.outcome = "queued"
        self.cancelled: list[str] = []
        self.stop_callbacks: list[Any] = []

    async def request(self, session_id: str, text: str, **kwargs: Any) -> str:
        self.requests.append({"session_id": session_id, "text": text, **kwargs})
        if self.outcome in ("queued", "merged"):
            status = self.statuses.setdefault(session_id, WakeStatus())
            status.pending = True
        return self.outcome

    def deliver(self, session_id: str) -> None:
        status = self.statuses[session_id]
        status.pending = False
        status.wakes += 1

    def drop(self, session_id: str) -> None:
        self.statuses[session_id].pending = False

    def cancel(self, session_id: str) -> bool:
        self.cancelled.append(session_id)
        status = self.statuses.get(session_id)
        if status is not None:
            status.pending = False
        return True

    def status(self, session_id: str) -> WakeStatus | None:
        return self.statuses.get(session_id)

    def on_stop(self, callback: Any) -> None:
        self.stop_callbacks.append(callback)


@dataclass
class FakeContext:
    state: FakeState = field(default_factory=FakeState)
    wake: FakeWake = field(default_factory=FakeWake)
    linked: dict[str, LinkedList] = field(default_factory=dict)
    # Sessions whose host is connected here, and sessions without a host.
    hosted: set[str] = field(default_factory=lambda: {SESSION})
    hostless: set[str] = field(default_factory=set)
    command_callbacks: list[Any] = field(default_factory=list)
    status_callbacks: list[Any] = field(default_factory=list)
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)

    async def pull_requests(self, session_id: str) -> LinkedList | None:
        return self.linked.get(session_id)

    async def serves_session(self, session_id: str, *, require_host: bool = False) -> bool:
        if session_id in self.hosted:
            return True
        return not require_host and session_id in self.hostless

    def on_command(self, callback: Any) -> None:
        self.command_callbacks.append(callback)

    def subscribe_status(self, callback: Any) -> None:
        self.status_callbacks.append(callback)

    def create_task(self, coroutine: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        task = asyncio.get_running_loop().create_task(coroutine, name=name)
        self.tasks.append(task)
        return task

    @contextlib.contextmanager
    def workspace(self, _workspace_id: int) -> Iterator[None]:
        yield


def pr_info(
    number: int,
    *,
    failing: tuple[str, ...] = (),
    pending: bool = False,
    head: str = HEAD,
    **pr: Any,
) -> dict[str, Any]:
    """A ``session.github.info`` payload for an open PR in ``org/repo``."""
    runs = [{"name": name, "bucket": "failing", "url": f"https://ci/{name}"} for name in failing]
    bucket = "pending" if pending else "passing"
    runs = runs or [{"name": "tests", "bucket": bucket, "url": "https://ci/tests"}]
    body: dict[str, Any] = {
        "number": number,
        "url": url(number),
        "state": "OPEN",
        "author": "agent-bot",
        "base_ref": "main",
        "head_sha": head,
        "checks": {
            "passing": 0 if failing or pending else 1,
            "failing": len(failing),
            "pending": int(pending and not failing),
            "total": len(runs),
            "runs": runs,
        },
        "comments": [],
        "reviewers": [],
        "mergeable": True,
    }
    body.update(pr)
    return {"object": "session.github.info", "pr": body}


def url(number: int) -> str:
    return f"https://github.com/org/repo/pull/{number}"


class Reader:
    """Scripted PR reads by URL; ``None`` means the host can't be reached now."""

    def __init__(self) -> None:
        self.infos: dict[str, dict[str, Any] | None] = {}
        self.reads: list[str] = []

    async def __call__(self, _session_id: str, pr_url: str) -> dict[str, Any] | None:
        self.reads.append(pr_url)
        info = self.infos.get(pr_url)
        return copy.deepcopy(info) if info is not None else None

    def goal_type(self) -> PrGreen:
        return PrGreen(self)
