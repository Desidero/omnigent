"""Hand an idle session a message from server-side automation.

A *wake* is a user message the server sends into a session for an automation
(``source``, e.g. ``"ext:acme.goal-loop"``) that a user (``on_behalf_of``)
turned on. :class:`SessionWakeService` keeps one pending wake per
``(session, source)`` and delivers it only when the session looks idle:

- **When.** On a persisted ``idle`` or ``failed`` status edge (a core status
  observer; the idle a Stop or archive publishes doesn't count) and on a slow
  retry timer, because edges are lossy. A wake is never sent while this
  replica sees the session running, waiting or starting, archived or closed,
  and only by the replica its host is connected to.
- **One at a time.** A native session's wake stays *in flight* until its
  terminal records it (or its queued input is dropped): meanwhile new requests
  only replace or merge the pending text, and the wake counts as delivered
  only once its message is persisted.
- **Stop wins.** A person's Stop or interrupt drops the session's pending and
  in-flight wakes; stop listeners hear ``stopped_by_user``. If the session is
  running or waiting, no wake is being posted or in flight, no other message
  is on its way to the runner, and its latest turn-starting input (a user
  message, hidden ones included, or a slash command) is a delivered wake,
  that wake's source is stopped too. An agent's interrupt only drops pending
  and in-flight wakes.
- **Who.** It is posted as the session owner, inside the owner's account
  scope, through the normal message path: input policies apply. The item
  records ``origin`` (source, enabler, label) and the text starts with a
  one-line ``[Automation: …]`` header so the model doesn't take it as typed.
- **Authorization at every delivery.** The enabler must still have EDIT on
  the session, their account generation must still be accepted and the source
  must still be enabled. Otherwise the wake is dropped and the source's stop
  listeners hear ``not_authorized``.
- **Never mid-turn.** The message carries ``delivery: "next_turn_only"``: the
  runner holds it while a turn runs instead of steering it in, so a turn that
  starts after this server's check still can't receive it mid-turn.
- **Pacing.** A wake whose ``dedupe_key`` equals the last delivered one is a
  ``duplicate``. Wakes are at least :data:`MIN_GAP_S` apart; the gap doubles,
  up to :data:`MAX_GAP_S`, while consecutive wakes carry the same
  ``evidence_key``. ``max_wakes`` (at most :data:`MAX_WAKES_LIMIT`) caps them,
  and :data:`MAX_DELIVERY_FAILURES` failures in a row stop the source with
  ``undeliverable``.

State is in memory, per replica: a restart loses at most the pending wake and
the counters, so callers keep their own state as the source of truth and
request again when they reconcile.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from omnigent.db.account_authority import (
    AccountAuthority,
    account_authority_scope,
    account_generation,
)
from omnigent.db.db_models import current_workspace_id, workspace_scope
from omnigent.entities.conversation import MESSAGE_ORIGIN_SOURCE_PATTERN
from omnigent.errors import OmnigentError
from omnigent.native.next_turn import DROP_NEXT_TURN_INPUT, NEXT_TURN_ONLY
from omnigent.server import session_status_observers
from omnigent.server.server_messages import AUTOMATION_HEADER_PREFIX, SessionNotReadyError

_logger = logging.getLogger(__name__)

MIN_GAP_S = 120.0
MAX_GAP_S = 1800.0
DEFAULT_MAX_WAKES = 10
MAX_WAKES_LIMIT = 50
MAX_DELIVERY_FAILURES = 5
RETRY_INTERVAL_S = 15.0
# Counters of a source with nothing pending are forgotten after this long.
IDLE_SLOT_TTL_S = 6 * 3600.0
MAX_TEXT_CHARS = 16_000
MAX_EARLY_RECORDS = 64
# A record of a wake whose post never returned is forgotten after this long.
EARLY_RECORD_TTL_S = 120.0
# Page size of a Stop's newest-first walk to the session's latest input.
LATEST_INPUT_PAGE_SIZE = 100
# A Stop of a turn with more items than this pauses no wake source.
LATEST_INPUT_SCAN_CAP = 5000
MAX_LABEL_CHARS = 64
MAX_USER_CHARS = 256
_SOURCE_RE = re.compile(MESSAGE_ORIGIN_SOURCE_PATTERN)
# The label and enabler appear in the one-line ``[Automation: …]`` header.
_HEADER_UNSAFE_RE = re.compile(r"[\]\x00-\x1f\x7f]")


class WakeOutcome(enum.StrEnum):
    """What :meth:`SessionWakeService.request` did with a request."""

    QUEUED = "queued"
    MERGED = "merged"
    DUPLICATE = "duplicate"
    BUDGET_SPENT = "budget_spent"
    NOT_AUTHORIZED = "not_authorized"


class WakeStop(enum.StrEnum):
    """Why a source's pending wake was dropped at delivery time."""

    NOT_AUTHORIZED = "not_authorized"
    UNDELIVERABLE = "undeliverable"
    BUDGET_SPENT = "budget_spent"
    SESSION_GONE = "session_gone"
    STOPPED_BY_USER = "stopped_by_user"
    STOPPED_BY_AGENT = "stopped_by_agent"


class _FromContext(enum.Enum):
    TOKEN = 0


FROM_CONTEXT = _FromContext.TOKEN


@dataclass(frozen=True)
class WakeRequest:
    """One request to wake a session.

    :param session_id: The session to wake.
    :param source: ``core:<name>`` or ``ext:<extension id>``.
    :param on_behalf_of: The user who turned the automation on; ``None`` in
        single-user mode.
    :param text: The message for the agent, without the automation header.
    :param dedupe_key: Identifies what the text reports, e.g. a digest of
        events. Equal to the last delivered key means ``duplicate``.
    :param evidence_key: Identifies the state the automation waits on. While
        consecutive wakes carry the same key, the gap between them doubles.
    :param max_wakes: Most wakes this source may deliver to this session.
    :param merge: Append to a pending wake's text instead of replacing it.
    :param label: Short display name for the automation chip and header.
    :param generation: ``on_behalf_of``'s account generation; by default the
        one bound in the caller's context.
    """

    session_id: str
    source: str
    on_behalf_of: str | None
    text: str
    dedupe_key: str | None = None
    evidence_key: str | None = None
    max_wakes: int = DEFAULT_MAX_WAKES
    merge: bool = False
    label: str | None = None
    generation: str | _FromContext | None = FROM_CONTEXT


@dataclass(frozen=True)
class WakeStatus:
    """A source's wake state for one session, as this replica holds it."""

    pending: bool
    in_flight: bool
    wakes: int
    max_wakes: int
    failures: int
    next_eligible_in_s: float
    stopped: WakeStop | None


@dataclass
class _Pending:
    text: str
    dedupe_key: str | None
    evidence_key: str | None
    on_behalf_of: str | None
    generation: str | None
    label: str | None


@dataclass
class _InFlight:
    """A wake the server sent that its native terminal has not recorded yet."""

    pending: _Pending
    pending_id: str


@dataclass
class _Slot:
    max_wakes: int = DEFAULT_MAX_WAKES
    pending: _Pending | None = None
    # Being posted right now; a merge during the post starts a new pending wake.
    sending: _Pending | None = None
    in_flight: _InFlight | None = None
    wakes: int = 0
    failures: int = 0
    last_key: str | None = None
    last_evidence: str | None = None
    gap_s: float = 0.0
    next_eligible_at: float = 0.0
    touched_at: float = field(default_factory=time.monotonic)
    stopped: WakeStop | None = None


_Key = tuple[int, str, str]
StopListener = Callable[[str, str, WakeStop], None]
# send(session_id, user_id, content, origin) -> acknowledgement
SendMessage = Callable[[str, str | None, list[dict[str, Any]], dict[str, Any]], Awaitable[Any]]


class SessionWakeService:
    """Deliver pending wakes to idle sessions; see the module docstring."""

    def __init__(
        self,
        *,
        send: SendMessage,
        owner_of: Callable[[str], Awaitable[AccountAuthority | None]],
        admission: Callable[[str], Awaitable[str | None]],
        has_edit: Callable[[str | None, str], Awaitable[bool]],
        accepts_generation: Callable[[str, str | None], bool],
        is_source_enabled: Callable[[str], bool],
        is_pending_input: Callable[[str, str], bool] = lambda _session_id, _pending_id: False,
        drop_input: Callable[[str, str], Awaitable[None]] | None = None,
        latest_input_source: Callable[[str], Awaitable[str | None]] | None = None,
        turn_is_live: Callable[[str, str | None], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        min_gap_s: float = MIN_GAP_S,
        max_gap_s: float = MAX_GAP_S,
        retry_interval_s: float = RETRY_INTERVAL_S,
    ) -> None:
        """
        :param send: Posts the message as the given user (see
            ``app.state.server_message_dispatch``).
        :param owner_of: The session owner's account authority, or ``None``.
        :param admission: ``None`` when the session can take a wake now,
            else why not: ``"busy"``, ``"elsewhere"`` (another replica serves
            it) or ``"gone"`` (deleted).
        :param has_edit: Whether a user still has EDIT on a session.
        :param accepts_generation: Whether a user's account generation is
            still valid.
        :param is_source_enabled: Whether a source may still wake sessions.
        :param is_pending_input: Whether a native session's queued input (by
            pending id) still waits for its terminal to record it.
        :param drop_input: Asks the runner to drop a queued input (by pending
            id) a Stop overtook while it was being posted.
        :param latest_input_source: The source whose delivered wake is the
            session's latest turn-starting input, or ``None`` when that input
            is anything else (see :func:`latest_turn_input_source`).
        :param turn_is_live: ``(session_id, live_status)``: whether the
            session is running or waiting (its cached status, else the
            persisted ``live_status`` passed in) with no message other than a
            wake on its way to the runner. Without it, or when it says no, a
            Stop checks no delivered wake's turn.
        """
        self._send = send
        self._owner_of = owner_of
        self._admission = admission
        self._has_edit = has_edit
        self._accepts_generation = accepts_generation
        self._is_source_enabled = is_source_enabled
        self._is_pending_input = is_pending_input
        self._drop_input = drop_input
        self._latest_input_source = latest_input_source
        self._turn_is_live = turn_is_live
        # Background reads of whose turn a Stop ended; settle() waits for them.
        self._stop_checks: set[asyncio.Task[None]] = set()
        # Bumped by every Stop, so a post a Stop overtook can be undone.
        self._stop_epochs: dict[tuple[int, str], int] = {}
        # Wakes the terminal recorded before their post returned, keyed by
        # (workspace, session, pending id), with when they were recorded.
        self._persisted_early: dict[tuple[int, str, str], float] = {}
        self._clock = clock
        self._min_gap_s = min_gap_s
        self._max_gap_s = max_gap_s
        self._retry_interval_s = retry_interval_s
        self._slots: dict[_Key, _Slot] = {}
        self._dispatching: dict[_Key, asyncio.Task[None]] = {}
        self._stop_listeners: list[StopListener] = []
        self._retry_task: asyncio.Task[None] | None = None
        self._unregister: Callable[[], None] | None = None
        self._closed = False

    # ── Caller API ────────────────────────────────────────────

    async def request(self, wake: WakeRequest) -> WakeOutcome:
        """Queue a wake for delivery at the session's next idle moment.

        :raises ValueError: On a malformed source or empty/oversized text.
        """
        if not _SOURCE_RE.fullmatch(wake.source):
            raise ValueError(f"invalid wake source {wake.source!r}")
        if not wake.text.strip() or len(wake.text) > MAX_TEXT_CHARS:
            raise ValueError(f"wake text must be 1-{MAX_TEXT_CHARS} characters")
        for name, value, limit in (
            ("label", wake.label, MAX_LABEL_CHARS),
            ("on_behalf_of", wake.on_behalf_of, MAX_USER_CHARS),
        ):
            if value is not None and (
                not value.strip() or len(value) > limit or _HEADER_UNSAFE_RE.search(value)
            ):
                raise ValueError(
                    f"wake {name} must be 1-{limit} characters without ']' or control characters"
                )
        generation = (
            (account_generation(wake.on_behalf_of) if wake.on_behalf_of is not None else None)
            if wake.generation is FROM_CONTEXT
            else wake.generation
        )
        assert not isinstance(generation, _FromContext)
        if not await self._authorized(wake.session_id, wake.source, wake.on_behalf_of, generation):
            return WakeOutcome.NOT_AUTHORIZED
        key = (current_workspace_id(), wake.session_id, wake.source)
        slot = self._slots.setdefault(key, _Slot())
        slot.touched_at = self._clock()
        slot.max_wakes = max(1, min(wake.max_wakes, MAX_WAKES_LIMIT))
        slot.stopped = None
        if slot.wakes >= slot.max_wakes:
            slot.pending = None
            return WakeOutcome.BUDGET_SPENT
        if wake.dedupe_key is not None and wake.dedupe_key in (
            slot.last_key,
            slot.pending.dedupe_key if slot.pending is not None else None,
            slot.sending.dedupe_key if slot.sending is not None else None,
            slot.in_flight.pending.dedupe_key if slot.in_flight is not None else None,
        ):
            return WakeOutcome.DUPLICATE
        outcome = WakeOutcome.QUEUED
        text = wake.text
        if wake.merge and slot.pending is not None:
            text = f"{slot.pending.text}\n\n{wake.text}"[-MAX_TEXT_CHARS:]
            outcome = WakeOutcome.MERGED
        slot.pending = _Pending(
            text=text,
            dedupe_key=wake.dedupe_key,
            evidence_key=wake.evidence_key,
            on_behalf_of=wake.on_behalf_of,
            generation=generation,
            label=wake.label,
        )
        self._schedule(key)
        return outcome

    def cancel(self, session_id: str, source: str) -> bool:
        """Drop a source's pending wake; returns whether one was pending."""
        slot = self._slots.get((current_workspace_id(), session_id, source))
        if slot is None or slot.pending is None:
            return False
        slot.pending = None
        return True

    def stop_session(
        self,
        session_id: str,
        reason: WakeStop = WakeStop.STOPPED_BY_USER,
        *,
        live_status: str | None = None,
    ) -> int:
        """Drop every source's pending and in-flight wake for a session.

        Called when a person stops or interrupts the session, so automation
        doesn't restart work they just ended. If a person stops a session that
        is running or waiting, no wake is being posted or in flight, no other
        message is on its way to the runner, and the session's latest
        turn-starting input is a delivered wake, that wake's source is stopped
        too (read in the background), since the turn it ends is the wake's.

        :param live_status: The session's persisted live status, for a
            replica that has none cached.
        :returns: How many sources had a pending or in-flight wake dropped.
        """
        workspace_id = current_workspace_id()
        session_key = (workspace_id, session_id)
        self._stop_epochs[session_key] = self._stop_epochs.get(session_key, 0) + 1
        stopped: set[str] = set()
        sent_unrecorded = False
        for key, slot in list(self._slots.items()):
            if key[0] != workspace_id or key[1] != session_id:
                continue
            if slot.pending is None and slot.sending is None and slot.in_flight is None:
                continue
            # A wake sent but not yet recorded is newer than any stored message.
            sent_unrecorded |= slot.sending is not None or slot.in_flight is not None
            slot.in_flight = None
            self._stop(key, slot, reason)
            stopped.add(key[2])
        if (
            reason is WakeStop.STOPPED_BY_USER
            and not sent_unrecorded
            and self._latest_input_source is not None
            and self._turn_is_live is not None
            and not self._closed
            and self._turn_is_live(session_id, live_status)
        ):
            with contextlib.suppress(RuntimeError):
                task = asyncio.get_running_loop().create_task(
                    self._stop_delivered_wake(workspace_id, session_id, stopped)
                )
                self._stop_checks.add(task)
                task.add_done_callback(self._stop_checks.discard)
        return len(stopped)

    def note_persisted(self, session_id: str, pending_id: str) -> None:
        """A native session's terminal recorded a wake: count it delivered.

        Keyed on the queued input's id. The record can land before the post
        that queued it returns; it is kept until then.
        """
        workspace_id = current_workspace_id()
        for key, slot in self._slots.items():
            in_flight = slot.in_flight
            if (
                key[0] == workspace_id
                and key[1] == session_id
                and in_flight is not None
                and in_flight.pending_id == pending_id
            ):
                slot.in_flight = None
                self._record_delivered(key, slot, in_flight.pending)
                return
        if any(
            key[0] == workspace_id and key[1] == session_id and slot.sending is not None
            for key, slot in self._slots.items()
        ):
            self._prune_early_records()
            if len(self._persisted_early) < MAX_EARLY_RECORDS:
                self._persisted_early[(workspace_id, session_id, pending_id)] = self._clock()

    def status(self, session_id: str, source: str) -> WakeStatus | None:
        """A source's wake state for a session, or ``None`` when there is none."""
        slot = self._slots.get((current_workspace_id(), session_id, source))
        if slot is None:
            return None
        return WakeStatus(
            pending=slot.pending is not None or slot.sending is not None,
            in_flight=slot.in_flight is not None,
            wakes=slot.wakes,
            max_wakes=slot.max_wakes,
            failures=slot.failures,
            next_eligible_in_s=max(0.0, slot.next_eligible_at - self._clock()),
            stopped=slot.stopped,
        )

    async def settle(self) -> None:
        """Wait until no delivery or Stop check is in flight."""
        while self._dispatching or self._stop_checks:
            await asyncio.gather(
                *self._dispatching.values(), *self._stop_checks, return_exceptions=True
            )

    def add_stop_listener(self, listener: StopListener) -> None:
        """Call ``listener(session_id, source, reason)`` when a source is stopped.

        That is when its pending or in-flight wake is dropped, or a person
        stops the turn its delivered wake started. The same stop can be
        reported more than once, so listeners must be idempotent.
        """
        self._stop_listeners.append(listener)

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Observe status edges and start the retry timer."""
        global _installed
        _installed = self
        self._unregister = session_status_observers.register_core_observer(self.observe)
        self._retry_task = asyncio.get_running_loop().create_task(self._retry_loop())

    async def aclose(self) -> None:
        """Stop observing and cancel in-flight work; pending wakes are dropped."""
        global _installed
        self._closed = True
        if _installed is self:
            _installed = None
        if self._unregister is not None:
            self._unregister()
        tasks = [*self._dispatching.values(), *self._stop_checks]
        if self._retry_task is not None:
            tasks.append(self._retry_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def observe(self, observation: session_status_observers.SessionStatusObservation) -> None:
        """Core status observer: a persisted ``idle`` or ``failed`` edge triggers delivery.

        Stop, archive and orphan settlement publish ``idle`` without persisting
        it; those never wake a session.
        """
        if observation.status not in ("idle", "failed") or not observation.persist_requested:
            return
        for key, slot in list(self._slots.items()):
            if (
                key[0] == observation.workspace_id
                and key[1] == observation.session_id
                and (slot.pending is not None or slot.in_flight is not None)
            ):
                self._schedule(key)

    # ── Delivery ──────────────────────────────────────────────

    def _schedule(self, key: _Key) -> None:
        if self._closed or key in self._dispatching:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._dispatch(key), name=f"session-wake-{key[1]}")
        self._dispatching[key] = task
        task.add_done_callback(lambda _done, key=key: self._dispatching.pop(key, None))

    async def _retry_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._retry_interval_s)
            now = self._clock()
            for key, slot in list(self._slots.items()):
                if slot.pending is not None or slot.in_flight is not None:
                    if now >= slot.next_eligible_at:
                        self._schedule(key)
                elif now - slot.touched_at > IDLE_SLOT_TTL_S:
                    self._slots.pop(key, None)

    async def _dispatch(self, key: _Key) -> None:
        workspace_id, session_id, source = key
        with workspace_scope(workspace_id):
            try:
                await self._dispatch_in_workspace(session_id, source, key)
            except Exception:
                _logger.exception("session wake: dispatch failed for %s", session_id)

    async def _dispatch_in_workspace(self, session_id: str, source: str, key: _Key) -> None:
        slot = self._slots.get(key)
        if slot is None:
            return
        if slot.in_flight is not None:
            if self._is_pending_input(session_id, slot.in_flight.pending_id):
                return
            # Dropped before its terminal recorded it (a Stop, an expired hold).
            slot.in_flight = None
            self._record_failure(key, slot)
            return
        if slot.pending is None or self._clock() < slot.next_eligible_at:
            return
        blocked = await self._admission(session_id)
        if blocked == "gone":
            self._stop(key, slot, WakeStop.SESSION_GONE)
            return
        if blocked is not None:
            return
        pending = slot.pending
        if slot.wakes >= slot.max_wakes:
            self._stop(key, slot, WakeStop.BUDGET_SPENT)
            return
        if not await self._authorized(
            session_id, source, pending.on_behalf_of, pending.generation
        ):
            self._stop(key, slot, WakeStop.NOT_AUTHORIZED)
            return
        owner = await self._owner_of(session_id)
        origin = {"kind": "automation", "source": source, "on_behalf_of": pending.on_behalf_of}
        if pending.label is not None:
            origin["label"] = pending.label
        content = [{"type": "input_text", "text": wake_text(pending, source)}]
        if slot.pending is not pending:
            return
        slot.pending = None
        slot.sending = pending
        stop_epoch = self._stop_epochs.get((key[0], session_id), 0)
        try:
            scope = (
                account_authority_scope(owner.user_id, owner.generation)
                if owner is not None
                else contextlib.nullcontext()
            )
            with scope:
                ack = await self._send(
                    session_id, owner.user_id if owner is not None else None, content, origin
                )
        except SessionNotReadyError:
            self._unsend(slot, pending, stopped=self._stopped_since(key, stop_epoch))
            return
        except Exception:
            _logger.warning(
                "session wake: delivering %s to %s failed", source, session_id, exc_info=True
            )
            if self._unsend(slot, pending, stopped=self._stopped_since(key, stop_epoch)):
                self._record_failure(key, slot)
            return
        pending_id = ack.get("pending_id") if isinstance(ack, Mapping) else None
        native = isinstance(pending_id, str) and not (
            isinstance(ack, Mapping) and ack.get("item_id")
        )
        early = (
            self._persisted_early.pop((key[0], session_id, pending_id), None)
            if isinstance(pending_id, str)
            else None
        )
        if self._stopped_since(key, stop_epoch):
            # A Stop overtook the post: take the queued input back if it is
            # still queued. One the runner already started can't be undone.
            if slot.sending is pending:
                slot.sending = None
            if native and self._drop_input is not None:
                assert isinstance(pending_id, str)
                await self._drop_input(session_id, pending_id)
            return
        slot.sending = None
        if native and early is None:
            assert isinstance(pending_id, str)
            # A native terminal records it later; until then it is in flight.
            slot.in_flight = _InFlight(pending, pending_id)
            slot.touched_at = self._clock()
            return
        self._record_delivered(key, slot, pending)

    def _unsend(self, slot: _Slot, pending: _Pending, *, stopped: bool) -> bool:
        """Put a wake whose post failed back, unless newer text replaced it or a Stop came.

        :returns: Whether the failure still counts (no Stop overtook the post).
        """
        self._prune_early_records()
        if slot.sending is pending:
            slot.sending = None
            if slot.pending is None and not stopped:
                slot.pending = pending
        return not stopped

    def _stopped_since(self, key: _Key, stop_epoch: int) -> bool:
        return self._stop_epochs.get((key[0], key[1]), 0) != stop_epoch

    def _prune_early_records(self) -> None:
        cutoff = self._clock() - EARLY_RECORD_TTL_S
        for record, at in list(self._persisted_early.items()):
            if at < cutoff:
                del self._persisted_early[record]

    def _record_failure(self, key: _Key, slot: _Slot) -> None:
        slot.failures += 1
        slot.next_eligible_at = self._clock() + self._min_gap_s / 4
        if slot.failures >= MAX_DELIVERY_FAILURES:
            self._stop(key, slot, WakeStop.UNDELIVERABLE)

    def _record_delivered(self, key: _Key, slot: _Slot, pending: _Pending) -> None:
        slot.failures = 0
        slot.wakes += 1
        slot.last_key = pending.dedupe_key
        repeated = pending.evidence_key is not None and pending.evidence_key == slot.last_evidence
        slot.gap_s = min(slot.gap_s * 2, self._max_gap_s) if repeated else self._min_gap_s
        slot.last_evidence = pending.evidence_key
        slot.next_eligible_at = self._clock() + slot.gap_s
        slot.touched_at = self._clock()
        _logger.info("session wake: woke %s for %s (%d)", key[1], key[2], slot.wakes)

    async def _authorized(
        self, session_id: str, source: str, user_id: str | None, generation: str | None
    ) -> bool:
        if not self._is_source_enabled(source):
            return False
        if user_id is not None and not self._accepts_generation(user_id, generation):
            return False
        return await self._has_edit(user_id, session_id)

    async def _stop_delivered_wake(
        self, workspace_id: int, session_id: str, already_stopped: set[str]
    ) -> None:
        """Stop the source whose delivered wake started the turn a person stopped."""
        assert self._latest_input_source is not None
        with workspace_scope(workspace_id):
            try:
                source = await self._latest_input_source(session_id)
            except Exception:
                _logger.warning(
                    "session wake: reading %s's latest input failed", session_id, exc_info=True
                )
                return
        if source is None or source in already_stopped:
            return
        key = (workspace_id, session_id, source)
        slot = self._slots.get(key)
        if slot is None:
            # Delivered by another replica or before a restart: still that source's turn.
            self._notify_stopped(session_id, source, WakeStop.STOPPED_BY_USER)
        else:
            self._stop(key, slot, WakeStop.STOPPED_BY_USER)

    def _stop(self, key: _Key, slot: _Slot, reason: WakeStop) -> None:
        slot.pending = None
        slot.stopped = reason
        self._notify_stopped(key[1], key[2], reason)

    def _notify_stopped(self, session_id: str, source: str, reason: WakeStop) -> None:
        _logger.info("session wake: stopped %s for %s: %s", source, session_id, reason.value)
        for listener in list(self._stop_listeners):
            try:
                listener(session_id, source, reason)
            except Exception:
                _logger.exception("session wake: stop listener failed")


# The app's service, for native transcript mirrors persisted outside it.
_installed: SessionWakeService | None = None


def note_persisted(session_id: str, pending_id: str) -> None:
    """Tell the running wake service a native wake's message was recorded."""
    if _installed is not None:
        _installed.note_persisted(session_id, pending_id)


def wake_text(pending: _Pending, source: str) -> str:
    """The delivered text: a one-line automation header, then the caller's text."""
    name = pending.label or source
    header = f"{AUTOMATION_HEADER_PREFIX}{name}"
    if pending.on_behalf_of is not None:
        header += f" · on behalf of {pending.on_behalf_of}"
    return f"{header}]\n\n{pending.text}"


def latest_turn_input_source(conversation_store: Any, session_id: str) -> str | None:
    """The source whose wake is the session's latest turn-starting input, else ``None``.

    Walks items newest first, skipping assistant output and tool items, to the
    latest user message (hidden ``is_meta`` ones included) or slash command. A
    hidden message counts as later input unless it shares the wake's turn
    (``response_id``), as context delivered with the wake does. Gives up with
    ``None`` after :data:`LATEST_INPUT_SCAN_CAP` items.
    """
    hidden_turns: set[str] = set()
    after: str | None = None
    scanned = 0
    while scanned < LATEST_INPUT_SCAN_CAP:
        page = conversation_store.list_items(
            session_id,
            limit=min(LATEST_INPUT_PAGE_SIZE, LATEST_INPUT_SCAN_CAP - scanned),
            after=after,
            order="desc",
        )
        scanned += len(page.data)
        for item in page.data:
            if item.type == "slash_command":
                return None
            data = item.data
            if item.type != "message" or getattr(data, "role", None) != "user":
                continue
            if getattr(data, "is_meta", False):
                hidden_turns.add(item.response_id)
                continue
            origin = getattr(data, "origin", None)
            if origin is None or hidden_turns - {item.response_id}:
                return None
            return origin.source
        if not page.has_more or page.last_id is None:
            return None
        after = page.last_id
    _logger.warning(
        "session wake: %s's latest input is over %d items back; pausing nothing",
        session_id,
        LATEST_INPUT_SCAN_CAP,
    )
    return None


def build_session_wake(
    app: Any,
    *,
    conversation_store: Any,
    permission_store: Any | None,
    auth_provider: Any | None,
    host_registry: Any | None,
    extension_is_enabled: Callable[[str], bool] | None,
) -> SessionWakeService:
    """Wire the app's wake service to the session routes and stores.

    :param extension_is_enabled: Whether an extension id is enabled by the
        operator. ``None`` lets no ``ext:`` source wake sessions.
    """
    from omnigent.runtime import pending_inputs
    from omnigent.server.auth import LEVEL_EDIT
    from omnigent.server.routes._auth_helpers import _require_access_and_level_sync
    from omnigent.server.routes._sessions.common import _session_status_cache
    from omnigent.server.routes._sessions.helpers import _forward_session_change_to_runner
    from omnigent.server.routes._sessions.orchestration import (
        _dispatch_in_flight,
        _session_is_starting,
    )
    from omnigent.util.session_lifecycle import is_session_closed

    async def send(
        session_id: str,
        user_id: str | None,
        content: list[dict[str, Any]],
        origin: Mapping[str, Any],
    ) -> Any:
        dispatch = app.state.server_message_dispatch
        return await dispatch(
            app, session_id, user_id, content, origin=origin, delivery=NEXT_TURN_ONLY
        )

    async def owner_of(session_id: str) -> AccountAuthority | None:
        return await asyncio.to_thread(
            conversation_store.get_session_owner_authority, session_id, owner_only=True
        )

    async def admission(session_id: str) -> str | None:
        conv = await asyncio.to_thread(conversation_store.get_conversation, session_id)
        if conv is None or conv.archived or is_session_closed(conv.labels, conv.title):
            return "gone"
        if host_registry is not None and conv.host_id and host_registry.get(conv.host_id) is None:
            return "elsewhere"
        status = _session_status_cache.get(session_id) or conv.live_status
        if status in ("running", "waiting") or _session_is_starting(session_id):
            return "busy"
        return None

    async def has_edit(user_id: str | None, session_id: str) -> bool:
        try:
            await asyncio.to_thread(
                _require_access_and_level_sync,
                user_id,
                session_id,
                LEVEL_EDIT,
                permission_store,
                conversation_store,
            )
        except OmnigentError:
            return False
        return True

    def accepts_generation(user_id: str, generation: str | None) -> bool:
        check = getattr(auth_provider, "accepts_account_generation", None)
        return True if check is None else bool(check(user_id, generation))

    def is_source_enabled(source: str) -> bool:
        kind, _, name = source.partition(":")
        if kind == "core":
            return True
        return extension_is_enabled is not None and bool(extension_is_enabled(name))

    def is_pending_input(session_id: str, pending_id: str) -> bool:
        return pending_inputs.is_pending(session_id, pending_id)

    async def latest_input_source(session_id: str) -> str | None:
        return await asyncio.to_thread(latest_turn_input_source, conversation_store, session_id)

    def turn_is_live(session_id: str, live_status: str | None) -> bool:
        # A message still on its way to the runner came after any stored wake.
        if _dispatch_in_flight.get(session_id, 0) > 0 or any(
            "origin" not in entry for entry in pending_inputs.snapshot_for(session_id)
        ):
            return False
        return _session_status_cache.get(session_id, live_status) in ("running", "waiting")

    async def drop_input(session_id: str, pending_id: str) -> None:
        pending_inputs.resolve(session_id, pending_id)
        try:
            await _forward_session_change_to_runner(
                session_id,
                getattr(app.state, "runner_router", None),
                {"type": DROP_NEXT_TURN_INPUT, "pending_id": pending_id},
            )
        except Exception:
            _logger.warning(
                "session wake: asking the runner to drop %s failed", pending_id, exc_info=True
            )

    service = SessionWakeService(
        send=send,
        is_pending_input=is_pending_input,
        drop_input=drop_input,
        latest_input_source=latest_input_source,
        turn_is_live=turn_is_live,
        owner_of=owner_of,
        admission=admission,
        has_edit=has_edit,
        accepts_generation=accepts_generation,
        is_source_enabled=is_source_enabled,
    )
    app.state.session_wake = service
    return service
