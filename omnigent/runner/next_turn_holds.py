"""Hold ``next_turn_only`` messages until a native session can start a turn.

The server sends automation messages (session wakes) with
``delivery: "next_turn_only"``: they must start a turn of their own, never be
steered into one that is running. The server's idle check can be stale, so the
runner makes the decisive check where it starts turns:

- SDK harnesses already run one turn at a time; the runner only skips their
  live mid-turn injection.
- A native harness's delivery returns as soon as the input is typed, so the
  runner holds the message here while it sees a turn (its own, a queued
  message, a pending approval, or the terminal's ``running``/``waiting``
  status) or a person who used the terminal within :data:`QUIET_WINDOW_S`.
  A waiter releases it through the normal ordered drain, which checks again.
- The harness checks once more under its own injection lock and refuses with
  :data:`NEXT_TURN_BUSY_CODE`; the runner then holds the message again instead
  of failing the turn.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from omnigent.native.next_turn import NEXT_TURN_BUSY_CODE, NEXT_TURN_ONLY

_logger = logging.getLogger(__name__)

# How long a person's last keypress (or, for unverified harnesses, screen
# output) keeps a held message waiting.
QUIET_WINDOW_S = 5.0
POLL_INTERVAL_S = 1.0
# A held message older than this is dropped, like the server's queued-input
# record of it (``omnigent.runtime.pending_inputs``), so neither outlives the other.
MAX_HOLD_S = 600.0
# A delivered native turn with no running edge this long after it counts as
# settled (a command that started no turn, or a lost edge).
DELIVERED_TURN_GRACE_S = 20.0
_HELD_SINCE_KEY = "next_turn_held_since"
# Native harnesses whose own turn signal the hold relies on; the others also
# wait for the terminal's screen to stay unchanged for the quiet window.
VERIFIED_NATIVE_HARNESSES = frozenset({"claude-native", "codex-native", "pi-native"})
_IN_FLIGHT = frozenset({"running", "waiting"})
# Hold reason for a message the harness refused under its injection lock.
HARNESS_BUSY = "harness_busy"


def is_next_turn_only(body: Mapping[str, Any] | None) -> bool:
    """Whether a forwarded message must wait for a turn of its own."""
    return body is not None and body.get("delivery") == NEXT_TURN_ONLY


def is_slash_command_only(body: Mapping[str, Any] | None) -> bool:
    """Whether a message is just a slash command (``/model``, ``/cost``…), not a prompt.

    Such a command may start no turn, so its delivery doesn't hold wakes.
    """
    if body is None:
        return False
    content = body.get("content")
    if isinstance(content, str):
        text = content
    elif (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
        and content[0].get("type") == "input_text"
    ):
        text = content[0].get("text")
    else:
        return False
    return isinstance(text, str) and text.lstrip().startswith("/") and "\n" not in text.strip()


def is_next_turn_refusal(error: Mapping[str, Any] | None) -> bool:
    """Whether a harness refused a next-turn-only message because it is busy."""
    return error is not None and error.get("code") == NEXT_TURN_BUSY_CODE


def block_reason(
    *,
    harness: str | None,
    turn_active: bool,
    awaiting_turn_end: bool = False,
    composer_blocker: str | None = None,
    queued: bool,
    approval_pending: bool,
    pane_status: str | None,
    person_active: bool,
    screen_active: bool | None,
) -> str | None:
    """Why a native session can't start a next-turn-only message now, or ``None``.

    :param harness: The session's harness, e.g. ``"claude-native"``.
    :param turn_active: The runner is delivering a turn.
    :param composer_blocker: Why the terminal's composer isn't free (a draft,
        shell mode, unreadable), when the runner reads it (codex-native).
    :param awaiting_turn_end: The runner delivered a message to the terminal
        and has seen no idle or failed edge since; a terminal's own status can
        lag the prompt it just accepted.
    :param queued: Other messages wait in the runner's queue; they go first.
    :param approval_pending: A permission prompt owns the session.
    :param pane_status: The terminal's last reported status.
    :param person_active: Someone typed in the terminal within the quiet window.
    :param screen_active: The screen changed within the quiet window, or
        ``None`` when unknown.
    """
    if turn_active:
        return "turn"
    if awaiting_turn_end and harness in VERIFIED_NATIVE_HARNESSES:
        return "delivered"
    if queued:
        return "queued"
    if approval_pending:
        return "approval"
    if pane_status in _IN_FLIGHT:
        return "running"
    if person_active:
        return "person"
    if composer_blocker is not None:
        return f"composer {composer_blocker}"
    if harness not in VERIFIED_NATIVE_HARNESSES and screen_active is not False:
        # Pane output is the only turn evidence these harnesses give.
        return "screen"
    return None


class NextTurnHolds:
    """Per-session ledger of held next-turn-only messages and their waiters."""

    def __init__(
        self,
        *,
        blocked: Callable[[str], Awaitable[str | None]],
        release: Callable[[str, dict[str, Any]], Awaitable[None]],
        poll_interval_s: float = POLL_INTERVAL_S,
        refusal_cooldown_s: float = QUIET_WINDOW_S,
        max_hold_s: float = MAX_HOLD_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        :param blocked: Why a session can't take a held message now, or ``None``.
        :param release: Queue a held message for the normal ordered drain,
            which checks again and may hand it back with :meth:`hold`.
        :param refusal_cooldown_s: How long to wait before retrying a message
            the harness refused, e.g. while a draft sits in its input box.
        :param max_hold_s: Drop a held message after this long.
        """
        self._blocked = blocked
        self._release = release
        self._poll_interval_s = poll_interval_s
        self._refusal_cooldown_s = refusal_cooldown_s
        self._max_hold_s = max_hold_s
        self._clock = clock
        self._retry_after: dict[str, float] = {}
        self._held: dict[str, list[dict[str, Any]]] = {}
        self._waiters: dict[str, asyncio.Task[None]] = {}

    def held(self, session_id: str) -> list[dict[str, Any]]:
        """The session's held messages, oldest first."""
        return list(self._held.get(session_id, ()))

    def hold(
        self, session_id: str, body: dict[str, Any], *, reason: str, first: bool = False
    ) -> None:
        """Hold ``body`` and make sure a waiter runs.

        :param first: Put it ahead of the other held messages, as when a
            released message is handed back.
        """
        held = self._held.setdefault(session_id, [])
        body.setdefault(_HELD_SINCE_KEY, self._clock())
        if reason == HARNESS_BUSY:
            self._retry_after[session_id] = self._clock() + self._refusal_cooldown_s
        if first:
            held.insert(0, body)
        else:
            held.append(body)
        _logger.info(
            "Holding a next-turn-only message for %s (%s)",
            session_id,
            reason,
            extra={"session_id": session_id, "event_name": "next_turn_input_held"},
        )
        waiter = self._waiters.get(session_id)
        if waiter is None or waiter.done():
            self._waiters[session_id] = asyncio.get_running_loop().create_task(
                self._wait(session_id), name=f"next-turn-hold-{session_id}"
            )

    def drop_pending(self, session_id: str, pending_id: str) -> int:
        """Forget one held message by the server's ``pending_id``."""
        held = self._held.get(session_id)
        if not held:
            return 0
        kept = [
            body
            for body in held
            if not (is_next_turn_only(body) and body.get("pending_id") == pending_id)
        ]
        if kept:
            self._held[session_id] = kept
        else:
            self._held.pop(session_id, None)
        return len(held) - len(kept)

    def drop(self, session_id: str) -> int:
        """Forget a session's held messages (stop, interrupt, delete)."""
        dropped = len(self._held.pop(session_id, ()))
        self._retry_after.pop(session_id, None)
        waiter = self._waiters.pop(session_id, None)
        if waiter is not None:
            waiter.cancel()
        return dropped

    def close(self) -> list[asyncio.Task[None]]:
        """Drop every held message and cancel the waiters (runner shutdown).

        :returns: The cancelled waiters, for a caller that can await them.
        """
        waiters = list(self._waiters.values())
        self._waiters.clear()
        self._held.clear()
        self._retry_after.clear()
        for waiter in waiters:
            waiter.cancel()
        return waiters

    async def aclose(self) -> None:
        """Like :meth:`close`, then wait for the waiters to finish."""
        await asyncio.gather(*self.close(), return_exceptions=True)

    def _drop_expired(self, session_id: str) -> None:
        held = self._held.get(session_id)
        if not held:
            return
        now = self._clock()
        kept = [body for body in held if now - body.get(_HELD_SINCE_KEY, now) < self._max_hold_s]
        if len(kept) == len(held):
            return
        # The server's queued-input record expires with it, which the wake
        # service counts as a failed delivery.
        _logger.warning(
            "Dropping %d next-turn-only message(s) for %s held longer than %.0f s",
            len(held) - len(kept),
            session_id,
            self._max_hold_s,
            extra={"session_id": session_id, "event_name": "next_turn_input_expired"},
        )
        if kept:
            self._held[session_id] = kept
        else:
            self._held.pop(session_id, None)

    async def _wait(self, session_id: str) -> None:
        try:
            while self._held.get(session_id):
                await asyncio.sleep(self._poll_interval_s)
                self._drop_expired(session_id)
                if not self._held.get(session_id):
                    break
                if self._clock() < self._retry_after.get(session_id, 0.0):
                    continue
                try:
                    if await self._blocked(session_id) is not None:
                        continue
                except Exception:
                    _logger.warning(
                        "Failed to check %s before releasing a held message",
                        session_id,
                        exc_info=True,
                        extra={"session_id": session_id},
                    )
                    continue
                held = self._held.get(session_id)
                if not held:
                    break
                body = held.pop(0)
                if not held:
                    self._held.pop(session_id, None)
                await self._release(session_id, body)
        finally:
            if self._waiters.get(session_id) is asyncio.current_task():
                self._waiters.pop(session_id, None)
