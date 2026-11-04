"""What a goal type gives the goal loop: targets, a baseline and a check.

The loop owns everything that is the same for every goal: when to check,
waking the agent at idle with what changed, dedupe and back-off, stopping on
met, off or budget, and the state that survives restarts. A goal type only
says what its targets are and whether one is met.

A second goal type would look like this (not implemented)::

    class TestsPass:
        id = "tests-pass"

        async def targets(self, session): ...  # e.g. one target: the session's branch
        async def baseline(self, session, target): ...
        async def check(self, session, target, state): ...  # run or read the suite
        def wake_text(self, session, items): ...
        def stop_text(self, target, reason, *, wakes, state): ...
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Target:
    """Something a goal is about, such as one pull request.

    :param id: Stable id, also the ``{pr}`` argument of the per-target toggle.
    :param url: Where it lives; the goal's state key is derived from it.
    :param title: Shown on the page.
    :param label: Short name, e.g. ``#7``.
    :param closed: Already finished before a goal started (not read again).
    """

    id: str
    url: str
    title: str = ""
    label: str = ""
    closed: bool = False


@dataclass
class Check:
    """One check of a goal against its state.

    :param state: The goal type's state once ``events`` are delivered (JSON).
    :param events: New one-line events for the wake message.
    :param event_keys: Stable ids for ``events``, digested into the wake's dedupe key.
    :param outcome: Why the goal ended (``green``, ``merged``, ...), or ``None``.
    :param red: Whether the target still needs work now.
    :param evidence: Digest of what the agent works on; unchanged means nothing moved.
    """

    state: Any
    events: list[str] = field(default_factory=list)
    event_keys: list[str] = field(default_factory=list)
    outcome: str | None = None
    red: bool = False
    evidence: str = ""


class LinkedPullRequest(Protocol):
    """The fields of a stored linked pull request the goal types read."""

    url: str
    repository: str
    number: int
    title: str | None
    state: str | None


class GoalSession(Protocol):
    """The session a goal is checked in."""

    session_id: str

    async def linked_pull_requests(self) -> Sequence[LinkedPullRequest]: ...


class GoalType(Protocol):
    """A kind of goal; see the module docstring."""

    id: str

    async def targets(self, session: GoalSession) -> list[Target]: ...

    async def baseline(self, session: GoalSession, target: Target) -> Check | None: ...

    async def check(self, session: GoalSession, target: Target, state: Any) -> Check | None: ...

    def wake_text(self, session: GoalSession, items: list[tuple[Target, Check]]) -> str: ...

    def stop_text(self, target: Target, reason: str, *, wakes: int, state: Any = None) -> str: ...

    def forget(self, session_id: str) -> None: ...
