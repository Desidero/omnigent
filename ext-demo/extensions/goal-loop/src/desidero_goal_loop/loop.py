"""The goal loop: check each session's goals, wake the agent at idle, stop when done.

Everything lives in the extension's session state (``docs/extending/extension_state.md``),
so the loop survives restarts and moves between replicas:

- ``all`` and ``pr:<owner>/<repo>/<n>`` (``on``/``off``) and ``stop``: what people
  asked for, written by the extension's commands.
- ``enablers``: who last set each toggle, recorded from the command (service).
- ``g:<digest of the target URL>``: one envelope per goal (service).
- ``loop``: the session's wake bookkeeping (service).
- ``goals``: a view of the goals for the extension's page (readers).
- ``goal``, ``count``, ``summary``: the published fields rows and the composer show.

The loop checks on a timer and, sooner, after a session goes idle. Only the
replica that serves the session's host checks it and writes its goals.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, TypeVar

from desidero_goal_loop.goals import Check, GoalType, Target
from omnigent.stores.conversation_store import ExtensionStateConflictError

_logger = logging.getLogger(__name__)
_T = TypeVar("_T")

KEY_ALL = "all"
TOGGLE_PREFIX = "pr:"
KEY_STOP = "stop"
KEY_REFRESH = "refresh"
KEY_ENABLERS = "enablers"
KEY_LOOP = "loop"
KEY_VIEW = "goals"
GOAL_PREFIX = "g:"
FIELD_GOAL = "goal"
FIELD_COUNT = "count"
FIELD_SUMMARY = "summary"

ON, OFF = "on", "off"
WATCHING, UNMET, MET, STOPPED = "watching", "unmet", "met", "stopped"
_ACTIVE = frozenset({WATCHING, UNMET})
_MET_REASONS = frozenset({"green", "merged"})
# Wake stops that only pause: the same events are not asked for again.
_PAUSES = frozenset({"stopped_by_user", "stopped_by_agent", "budget_spent"})
# Goals one session can hold, active or ended; with the toggles and published
# fields this stays under the 64 keys an extension may keep per session.
MAX_GOALS = 25
DEFAULT_MAX_WAKES = 10
# The wake service's own per-session budget; the per-goal budget above is the real one.
SERVICE_MAX_WAKES = 50
# Below the wake service's 16,000-character limit on a wake's text.
MAX_WAKE_TEXT_CHARS = 15_000
# Below the 16,382-byte limit on a state value.
MAX_VIEW_BYTES = 16_000
INTERVAL_ENV_VAR = "DESIDERO_GOAL_LOOP_INTERVAL_S"
DEFAULT_INTERVAL_S = 90.0
MIN_INTERVAL_S = 5.0
# After an idle edge, wait a little so the host's PR refresh and CI can catch up.
DEFAULT_HINT_DELAY_S = 5.0
WAKE_LABEL = "Goal loop"
_VIEW_TITLE_BYTES = 120


def configured_interval_s(environ: dict[str, str] | None = None) -> float:
    """Seconds between reconciling passes, from :data:`INTERVAL_ENV_VAR`."""
    raw = (environ if environ is not None else os.environ).get(INTERVAL_ENV_VAR, "")
    try:
        value = float(raw) if raw.strip() else DEFAULT_INTERVAL_S
    except ValueError:
        value = DEFAULT_INTERVAL_S
    return max(MIN_INTERVAL_S, value)


def goal_key(url: str) -> str:
    """The state key of the goal for one target URL."""
    return GOAL_PREFIX + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def is_toggle(key: str) -> bool:
    return key == KEY_ALL or key.startswith(TOGGLE_PREFIX)


def _digest(parts: list[str]) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _json(entry: Any) -> dict[str, Any]:
    if entry is None:
        return {}
    try:
        data = json.loads(entry.value)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(entry: Any) -> str:
    if entry is None:
        return ""
    try:
        return bytes(entry.value).decode("utf-8")
    except (TypeError, UnicodeDecodeError):
        return ""


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def trim_bytes(text: str, limit: int) -> str:
    """*text* cut to at most *limit* UTF-8 bytes, on a character boundary."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[: max(0, limit - 3)].decode("utf-8", "ignore") + "…"


class _Conflict(Exception):
    """Another writer changed a goal since this pass read it; the next pass re-reads."""


@dataclass
class Goal:
    """One goal's envelope.

    :param type: The goal type's id.
    :param target: What the goal is about.
    :param status: ``watching``, ``unmet``, ``met`` or ``stopped``.
    :param reason: Why it ended (``green``, ``off``, ``budget``, ...).
    :param note: One line about the end, for the page.
    :param state: The goal type's state (what was already reported).
    :param pending: The state to commit once the requested wake is delivered.
    :param wakes: Wakes delivered for this goal.
    :param max_wakes: Its budget.
    :param by: The toggle that started it, as ``<epoch>:<key>:<version>``; a
        different stamp restarts an ended goal.
    :param enabled: Whether the person who set that toggle was recorded.
    :param user: That person, on whose behalf the goal's wakes go out.
    :param generation: Their account generation when they set it.
    :param quiet: Ended before it was ever watched (already merged or closed).
    """

    type: str
    target: Target
    status: str = WATCHING
    reason: str = ""
    note: str = ""
    state: Any = None
    pending: Any = None
    wakes: int = 0
    max_wakes: int = DEFAULT_MAX_WAKES
    by: str = ""
    enabled: bool = False
    user: str | None = None
    generation: str | None = None
    quiet: bool = False
    started_at: int = 0

    @property
    def active(self) -> bool:
        return self.status in _ACTIVE

    @property
    def enabler(self) -> tuple[str | None, str | None]:
        return self.user, self.generation

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["v"] = 1
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Goal | None:
        target = data.get("target")
        if not isinstance(target, dict) or not isinstance(target.get("url"), str):
            return None
        try:
            return cls(
                type=str(data.get("type") or ""),
                target=Target(
                    **{k: target[k] for k in Target.__dataclass_fields__ if k in target}
                ),
                status=str(data.get("status") or STOPPED),
                reason=str(data.get("reason") or ""),
                note=str(data.get("note") or ""),
                state=data.get("state"),
                pending=data.get("pending"),
                wakes=int(data.get("wakes") or 0),
                max_wakes=int(data.get("max_wakes") or DEFAULT_MAX_WAKES),
                by=str(data.get("by") or ""),
                enabled=bool(data.get("enabled")),
                user=data.get("user") if isinstance(data.get("user"), str) else None,
                generation=(
                    data.get("generation") if isinstance(data.get("generation"), str) else None
                ),
                quiet=bool(data.get("quiet")),
                started_at=int(data.get("started_at") or 0),
            )
        except (TypeError, ValueError):
            return None


@dataclass
class LoopRecord:
    """A session's wake bookkeeping.

    :param requested: Dedupe key of the wake requested and not yet delivered.
    :param mark: The wake service's delivered count when it was requested.
    :param requested_for: The enabler (user, generation) that wake goes out for.
    :param paused: Per enabler (see :func:`enabler_key`), the dedupe key of a
        wake that was stopped; it is not requested again.
    :param epoch: Counts "Stop all goals"; part of every goal's toggle stamp.
    :param last_woken: The enabler of the last wake asked for; other enablers
        go first next time.
    """

    requested: str = ""
    mark: int = 0
    requested_for: list[str | None] | None = None
    paused: dict[str, str] = field(default_factory=dict)
    epoch: int = 0
    last_woken: list[str | None] | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LoopRecord:
        def number(key: str) -> int:
            value = data.get(key)
            return value if isinstance(value, int) else 0

        requested_for = data.get("requested_for")
        paused = data.get("paused")
        last_woken = data.get("last_woken")
        return cls(
            requested=str(data.get("requested") or ""),
            mark=number("mark"),
            requested_for=requested_for if isinstance(requested_for, list) else None,
            paused={
                str(key): str(value)
                for key, value in (paused.items() if isinstance(paused, dict) else ())
            },
            epoch=number("epoch"),
            last_woken=last_woken if isinstance(last_woken, list) else None,
        )


@dataclass
class _Snapshot:
    """One session's state, as read at the start of a check."""

    entries: dict[str, Any]
    goals: dict[str, Goal] = field(default_factory=dict)
    record: LoopRecord = field(default_factory=LoopRecord)
    enablers: dict[str, dict[str, Any]] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)
    # Keys to clear once an applied "Stop all" is saved, with their versions.
    stopped_keys: list[tuple[str, int]] = field(default_factory=list)

    def toggle(self, key: str) -> tuple[str, int]:
        entry = self.entries.get(key)
        return (_text(entry), entry.version) if entry is not None else ("", 0)

    @property
    def all_on(self) -> bool:
        return self.toggle(KEY_ALL)[0] == ON

    def pr_toggles(self) -> dict[str, tuple[str, int]]:
        return {
            key[len(TOGGLE_PREFIX) :]: self.toggle(key)
            for key in self.entries
            if key.startswith(TOGGLE_PREFIX)
        }

    def toggles_on(self) -> list[str]:
        return [key for key in self.entries if is_toggle(key) and self.toggle(key)[0] == ON]


class _Session:
    """The :class:`~desidero_goal_loop.goals.GoalSession` a goal type sees."""

    def __init__(self, ctx: Any, session_id: str) -> None:
        self._ctx = ctx
        self.session_id = session_id
        self.linked_known = True

    async def linked_pull_requests(self) -> list[Any]:
        linked = await self._ctx.pull_requests(self.session_id)
        if linked is None:
            self.linked_known = False
            return []
        return list(linked.entries)


def enabler_key(enabler: tuple[str | None, str | None] | list[str | None]) -> str:
    """One enabler (user, generation) as a JSON key."""
    return json.dumps(list(enabler))


def _outcome(value: Any) -> str:
    return str(getattr(value, "value", value))


class GoalLoop:
    """Runs one goal type for every session where someone turned it on.

    :param ctx: The extension's activation context.
    :param goal_type: The goal type.
    :param interval_s: Seconds between reconciling passes.
    :param hint_delay_s: Delay before checking a session that just went idle.
    :param clock: Epoch seconds, for tests.
    """

    def __init__(
        self,
        ctx: Any,
        goal_type: GoalType,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        hint_delay_s: float = DEFAULT_HINT_DELAY_S,
        max_wakes: int = DEFAULT_MAX_WAKES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ctx = ctx
        self._type = goal_type
        self._interval_s = interval_s
        self._hint_delay_s = hint_delay_s
        self._max_wakes = max_wakes
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}
        self._scheduled: set[tuple[int, str]] = set()
        # Sessions with goal-loop state, so idle hints skip every other session.
        self._known: set[str] = set()

    def start(self) -> None:
        """Register the callbacks and the reconciling task (from ``activate``)."""
        self._ctx.on_command(self.on_command)
        self._ctx.wake.on_stop(self.on_stop)
        self._ctx.subscribe_status(self.on_status)
        self._ctx.create_task(self.run(), name="goal-loop-reconcile")

    async def run(self) -> None:
        while True:
            try:
                await self.reconcile_all()
            except Exception:
                _logger.exception("goal loop: reconciling failed")
            await asyncio.sleep(self._interval_s)

    async def reconcile_all(self) -> None:
        """Check every session where the extension holds state."""
        async for ref in self._ctx.state.sessions():
            self._known.add(ref.session_id)
            with self._ctx.workspace(ref.workspace_id):
                try:
                    await self.check_session(ref.session_id)
                except Exception:
                    _logger.exception("goal loop: checking session %s failed", ref.session_id)

    # ── Hints: commands, idle edges, wake stops ───────────────

    async def on_status(self, observation: Any) -> None:
        """An idle edge after a turn is a hint to check that session soon."""
        if (
            observation.status == "idle"
            and observation.previous_status in ("running", "waiting")
            and observation.persist_requested
            and observation.session_id in self._known
        ):
            self.schedule(observation.workspace_id, observation.session_id, self._hint_delay_s)

    def schedule(self, workspace_id: int, session_id: str, delay_s: float) -> None:
        """Check one session after ``delay_s`` unless a check is already scheduled."""
        if (workspace_id, session_id) in self._scheduled:
            return
        self._scheduled.add((workspace_id, session_id))

        async def later() -> None:
            try:
                await asyncio.sleep(delay_s)
            finally:
                self._scheduled.discard((workspace_id, session_id))
            with self._ctx.workspace(workspace_id):
                await self.check_session(session_id)

        self._ctx.create_task(later(), name=f"goal-loop-check-{session_id}")

    async def on_command(self, event: Any) -> None:
        """Record who set a toggle, handle "Stop all", refresh the view, and check soon."""
        session_id = event.session_id
        self._known.add(session_id)
        owner = await self._ctx.serves_session(session_id, require_host=True)
        async with self._lock(session_id):
            if is_toggle(event.key) and not event.deleted:
                await self._record_enabler(event)
            if event.key == KEY_STOP and not event.deleted:
                # The newest action wins over every toggle set before it.
                for entry in await self._ctx.state.entries(session_id):
                    if is_toggle(entry.key):
                        await self._clear(session_id, entry.key, entry.version)
            snapshot = await self._snapshot(session_id)
            # Only the owner writes goals; a session without a host has none.
            if KEY_STOP in snapshot.entries and (
                owner or await self._ctx.serves_session(session_id)
            ):
                self._apply_stop(session_id, snapshot)
                if await self._save_or_skip(session_id, snapshot):
                    await self._clear_stop(session_id, snapshot)
            await self._publish(session_id, snapshot, await self._targets(session_id))
        if owner:
            self.schedule(event.workspace_id, session_id, 0)

    async def _record_enabler(self, event: Any) -> None:
        """Remember who set this toggle, from the command itself."""
        record = {"user": event.user_id, "generation": event.generation, "at": int(self._clock())}
        for _ in range(3):
            entry = await self._ctx.state.read(event.session_id, KEY_ENABLERS)
            enablers = _json(entry)
            enablers[event.key] = record
            try:
                await self._ctx.state.write(
                    event.session_id,
                    KEY_ENABLERS,
                    _dump(enablers),
                    expected_version=entry.version if entry is not None else 0,
                )
                return
            except ExtensionStateConflictError:
                continue
        _logger.warning("goal loop: couldn't record who set %s", event.key)

    async def on_stop(self, session_id: str, reason: Any) -> None:
        """A dropped wake: a Stop or the service's budget pauses; anything else stops goals."""
        reason = _outcome(reason)
        async with self._lock(session_id):
            snapshot = await self._snapshot(session_id)
            record = snapshot.record
            if reason in _PAUSES and record.requested and record.requested_for:
                record.paused[enabler_key(record.requested_for)] = record.requested
            elif reason not in _PAUSES:
                enabler = tuple(record.requested_for) if record.requested_for else None
                for goal in snapshot.goals.values():
                    # Only the goals of the enabler who lost access, when that is known.
                    if goal.active and (
                        reason != "not_authorized" or enabler is None or goal.enabler == enabler
                    ):
                        self._end(goal, reason)
            record.requested, record.requested_for = "", None
            for goal in snapshot.goals.values():
                goal.pending = None
            if await self._save_or_skip(session_id, snapshot):
                await self._publish(session_id, snapshot, await self._targets(session_id))

    # ── One session ───────────────────────────────────────────

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    async def check_session(self, session_id: str) -> None:
        """Reconcile one session's goals with its toggles and check the active ones."""
        async with self._lock(session_id):
            await self._check(session_id)

    async def _snapshot(self, session_id: str) -> _Snapshot:
        entries = {entry.key: entry for entry in await self._ctx.state.entries(session_id)}
        snapshot = _Snapshot(entries, record=LoopRecord.from_json(_json(entries.get(KEY_LOOP))))
        for key, entry in entries.items():
            if key.startswith(GOAL_PREFIX) and (goal := Goal.from_json(_json(entry))) is not None:
                snapshot.goals[key] = goal
        snapshot.enablers = {
            key: value
            for key, value in _json(entries.get(KEY_ENABLERS)).items()
            if isinstance(value, dict)
        }
        return snapshot

    async def _guarded(self, what: str, call: Awaitable[_T]) -> _T | None:
        """Run one goal-type call; a failure skips that target for this pass only."""
        try:
            return await call
        except Exception as exc:
            _logger.warning("goal loop: %s failed: %s", what, exc, exc_info=True)
            return None

    async def _targets(self, session_id: str) -> list[Target] | None:
        session = _Session(self._ctx, session_id)
        targets = await self._guarded(f"listing {session_id}", self._type.targets(session))
        return targets if targets is not None and session.linked_known else None

    async def _check(self, session_id: str) -> None:
        snapshot = await self._snapshot(session_id)
        if not snapshot.entries:
            self._known.discard(session_id)
            self._type.forget(session_id)
            return
        owner = await self._ctx.serves_session(session_id, require_host=True)
        if KEY_STOP in snapshot.entries and (owner or await self._ctx.serves_session(session_id)):
            self._apply_stop(session_id, snapshot)
        if not owner:
            # A session without a host has no owner, so a stop is applied anywhere.
            if snapshot.stopped_keys and await self._save_or_skip(session_id, snapshot):
                await self._clear_stop(session_id, snapshot)
                await self._publish(session_id, snapshot, await self._targets(session_id))
            return
        session = _Session(self._ctx, session_id)
        targets = await self._targets(session_id)
        await self._enrol(session, snapshot, targets)
        self._settle_requested(session_id, snapshot)
        await self._check_goals(session, snapshot)
        if not any(goal.active for goal in snapshot.goals.values()):
            # Nothing left to wake for, e.g. after "Stop all".
            self._ctx.wake.cancel(session_id)
            snapshot.record.requested, snapshot.record.requested_for = "", None
            self._type.forget(session_id)
        if not await self._save_or_skip(session_id, snapshot):
            return
        await self._clear_stop(session_id, snapshot)
        await self._publish(session_id, snapshot, targets)

    def _apply_stop(self, session_id: str, snapshot: _Snapshot) -> None:
        """Handle "Stop all goals": end every goal; turning one on again restarts it.

        Toggles set before the stop are dropped with it, and so are ones set in
        the same second (``updated_at`` has one-second steps); later ones stand.
        """
        stop = snapshot.entries.pop(KEY_STOP)
        snapshot.stopped_keys.append((KEY_STOP, stop.version))
        for key, entry in list(snapshot.entries.items()):
            if is_toggle(key) and entry.updated_at <= stop.updated_at:
                snapshot.stopped_keys.append((key, entry.version))
                del snapshot.entries[key]
        for goal in snapshot.goals.values():
            if goal.active:
                self._end(goal, "off")
            goal.pending = None
        snapshot.record.epoch += 1
        snapshot.record.requested, snapshot.record.requested_for = "", None
        self._ctx.wake.cancel(session_id)
        _logger.info("goal loop: stopped every goal of session %s", session_id)

    async def _clear_stop(self, session_id: str, snapshot: _Snapshot) -> None:
        """Clear an applied stop and the toggles set before it."""
        for key, version in snapshot.stopped_keys:
            await self._clear(session_id, key, version)
        snapshot.stopped_keys.clear()

    async def _clear(self, session_id: str, key: str, version: int) -> None:
        # A conflict means it was set again since: the newer value stands.
        with contextlib.suppress(ExtensionStateConflictError):
            await self._ctx.state.clear(session_id, key, expected_version=version)

    def _wanted(
        self, snapshot: _Snapshot, targets: list[Target]
    ) -> dict[str, tuple[Target, str, str]]:
        """The targets that should have a running goal, with the toggle asking for it."""
        epoch = snapshot.record.epoch
        all_value, all_version = snapshot.toggle(KEY_ALL)
        toggles = snapshot.pr_toggles()
        wanted: dict[str, tuple[Target, str, str]] = {}
        for target in targets:
            value, version = toggles.get(target.id, ("", 0))
            key = f"{TOGGLE_PREFIX}{target.id}"
            if value == ON:
                wanted[target.id] = (target, key, f"{epoch}:{key}:{version}")
            elif all_value == ON and value != OFF:
                wanted[target.id] = (target, KEY_ALL, f"{epoch}:{KEY_ALL}:{all_version}")
        return wanted

    def _free_slot(self, snapshot: _Snapshot) -> bool:
        """Make room for a new goal by forgetting the oldest ended one."""
        if len(snapshot.goals) < MAX_GOALS:
            return True
        ended = [(goal.started_at, key) for key, goal in snapshot.goals.items() if not goal.active]
        if not ended:
            return False
        _, key = min(ended)
        del snapshot.goals[key]
        snapshot.removed.add(key)
        return True

    async def _enrol(
        self, session: Any, snapshot: _Snapshot, targets: list[Target] | None
    ) -> None:
        if targets is None:
            return  # The linked list is unknown; change nothing.
        wanted = self._wanted(snapshot, targets)
        wanted_urls = {target.url for target, _, _ in wanted.values()}
        for goal in snapshot.goals.values():
            if goal.active and goal.target.url not in wanted_urls:
                self._end(goal, "off")
        now = int(self._clock())
        for target, toggle, stamp in wanted.values():
            key = goal_key(target.url)
            goal = snapshot.goals.get(key)
            # An ended goal restarts when a different toggle stamp asks for it; one
            # turned off restarts whenever it is wanted again.
            if goal is not None and (goal.active or (goal.by == stamp and goal.reason != "off")):
                goal.target = target
                continue
            if goal is None and not self._free_slot(snapshot):
                continue
            fresh = Goal(
                self._type.id, target, by=stamp, max_wakes=self._max_wakes, started_at=now
            )
            enabler = snapshot.enablers.get(toggle)
            if target.closed:
                fresh.quiet = True
                self._end(fresh, "closed")
            elif enabler is None:
                self._end(fresh, "no_enabler")
            else:
                fresh.enabled = True
                fresh.user, fresh.generation = enabler.get("user"), enabler.get("generation")
                baseline = await self._guarded(
                    f"reading {target.url}", self._type.baseline(session, target)
                )
                if baseline is None:
                    continue  # Not readable from here now; try again later.
                fresh.state = baseline.state
                if baseline.outcome is not None:
                    fresh.quiet = True
                    self._end(fresh, baseline.outcome)
                else:
                    _logger.info(
                        "goal loop: session %s now has a %s goal for %s",
                        session.session_id,
                        self._type.id,
                        target.url,
                    )
            snapshot.goals[key] = fresh

    def _settle_requested(self, session_id: str, snapshot: _Snapshot) -> bool:
        """Commit the reported events once the requested wake was delivered.

        :returns: Whether a delivered wake was committed just now.
        """
        record = snapshot.record
        if not record.requested:
            return False
        status = self._ctx.wake.status(session_id)
        if status is not None and status.wakes > record.mark:
            for goal in snapshot.goals.values():
                if goal.pending is not None:
                    goal.state, goal.pending = goal.pending, None
                    goal.wakes += 1
            record.requested, record.requested_for = "", None
            return True
        if status is None or not (status.pending or status.in_flight):
            # Dropped, or lost in a restart: the events stay unreported.
            for goal in snapshot.goals.values():
                goal.pending = None
            record.requested, record.requested_for = "", None
        return False

    async def _check_goals(self, session: Any, snapshot: _Snapshot) -> None:
        items: list[tuple[Goal, Check]] = []
        for goal in snapshot.goals.values():
            if not goal.active:
                continue
            if not goal.enabled:
                self._end(goal, "no_enabler")
                continue
            check = await self._guarded(
                f"reading {goal.target.url}", self._type.check(session, goal.target, goal.state)
            )
            if check is None:
                continue
            if check.outcome is not None:
                goal.state = check.state
                self._end(goal, check.outcome)
                continue
            goal.status = UNMET if check.red or check.events else WATCHING
            if not check.events:
                if goal.pending is None:
                    goal.state = check.state
                continue
            if goal.wakes >= goal.max_wakes:
                self._end(goal, "budget")
                continue
            items.append((goal, check))
        if items:
            await self._request_wake(session, snapshot, items)

    def _choose_group(
        self, snapshot: _Snapshot, items: list[tuple[Goal, Check]]
    ) -> tuple[tuple[str | None, str | None], list[tuple[Goal, Check]], str] | None:
        """The enabler whose goals' wake to ask for now, or ``None`` to wait.

        One wake at a time per session, so one enabler's goals at a time. While
        a wake is outstanding only its enabler's can replace it; otherwise
        enablers take turns (the last one woken goes last), skipping paused ones.
        """
        record = snapshot.record
        groups: dict[tuple[str | None, str | None], list[tuple[Goal, Check]]] = {}
        for goal, check in items:
            groups.setdefault(goal.enabler, []).append((goal, check))

        def digest(group: list[tuple[Goal, Check]]) -> str:
            return _digest(sorted(key for _, check in group for key in check.event_keys))

        if record.requested:
            user, generation = (record.requested_for or [None, None])[:2]
            group = groups.get((user, generation))
            if group is None or digest(group) == record.requested:
                return None  # Wait for the outstanding wake.
            return (user, generation), group, digest(group)
        last = tuple(record.last_woken or ())
        for enabler in sorted(groups, key=lambda candidate: candidate == last):
            dedupe = digest(groups[enabler])
            if record.paused.get(enabler_key(enabler)) != dedupe:
                return enabler, groups[enabler], dedupe
        return None

    async def _request_wake(
        self, session: Any, snapshot: _Snapshot, items: list[tuple[Goal, Check]]
    ) -> None:
        session_id = session.session_id
        record = snapshot.record
        chosen_group = self._choose_group(snapshot, items)
        if chosen_group is None:
            return
        enabler, items, dedupe = chosen_group
        if self._settle_requested(session_id, snapshot):
            return  # Delivered during this pass: check again from what it reported.
        status = self._ctx.wake.status(session_id)
        if status is not None and status.in_flight:
            return  # One at a time; ask again once it lands.
        evidence = _digest(sorted(check.evidence for _, check in items))
        text = self._type.wake_text(session, [(goal.target, check) for goal, check in items])
        if len(text) > MAX_WAKE_TEXT_CHARS:  # A backstop for goal types without their own cap.
            text = text[: MAX_WAKE_TEXT_CHARS - 2] + "\n…"
        outcome = _outcome(
            await self._ctx.wake.request(
                session_id,
                text,
                on_behalf_of=enabler[0],
                generation=enabler[1],
                dedupe_key=dedupe,
                evidence_key=evidence,
                max_wakes=SERVICE_MAX_WAKES,
                label=WAKE_LABEL,
            )
        )
        # Read again: an earlier wake may have been delivered while this one was asked for.
        after = self._ctx.wake.status(session_id)
        outstanding = after is not None and (after.pending or after.in_flight)
        if outcome in ("queued", "merged") or (outcome == "duplicate" and outstanding):
            # Counted from now, so only this wake's delivery commits its events.
            record.mark = after.wakes if after is not None else 0
            record.requested, record.requested_for = dedupe, list(enabler)
            record.last_woken = list(enabler)
            record.paused.pop(enabler_key(enabler), None)
            chosen = {id(goal) for goal, _ in items}
            for goal in snapshot.goals.values():
                if id(goal) not in chosen:
                    goal.pending = None  # Its earlier wake was replaced by this one.
            for goal, check in items:
                goal.pending = check.state
        elif outcome == "duplicate":
            # Nothing outstanding: the service already delivered exactly these events.
            for goal, check in items:
                goal.state, goal.pending = check.state, None
                goal.wakes += 1
        elif outcome == "budget_spent":
            # The service's own budget resets; pause, don't end.
            record.paused[enabler_key(enabler)] = dedupe
        elif outcome == "not_authorized":
            for goal, _ in items:
                self._end(goal, "not_authorized")

    def _end(self, goal: Goal, reason: str) -> None:
        goal.status = MET if reason in _MET_REASONS else STOPPED
        goal.reason = reason
        goal.pending = None
        goal.note = self._type.stop_text(goal.target, reason, wakes=goal.wakes, state=goal.state)
        if not goal.quiet:
            _logger.info("goal loop: %s goal for %s ended: %s", goal.type, goal.target.url, reason)

    # ── Writes ────────────────────────────────────────────────

    async def _write_checked(
        self, session_id: str, snapshot: _Snapshot, key: str, value: str
    ) -> None:
        """Write *key* only if nobody changed it since the snapshot."""
        entry = snapshot.entries.get(key)
        if entry is not None and _text(entry) == value:
            return
        try:
            snapshot.entries[key] = await self._ctx.state.write(
                session_id, key, value, expected_version=entry.version if entry else 0
            )
        except ExtensionStateConflictError as exc:
            raise _Conflict(key) from exc

    async def _save_or_skip(self, session_id: str, snapshot: _Snapshot) -> bool:
        """Write the loop record and the goals; ``False`` if another writer got there first."""
        try:
            # The record first: if a goal write then conflicts, the requested wake
            # is still known, so its events are re-sent rather than lost.
            record = asdict(snapshot.record)
            if any(record.values()) or KEY_LOOP in snapshot.entries:
                await self._write_checked(session_id, snapshot, KEY_LOOP, _dump(record))
            for key in snapshot.removed:
                entry = snapshot.entries.pop(key, None)
                if entry is not None:
                    await self._ctx.state.clear(session_id, key, expected_version=entry.version)
            for key, goal in snapshot.goals.items():
                await self._write_checked(session_id, snapshot, key, _dump(goal.to_json()))
        except (_Conflict, ExtensionStateConflictError) as exc:
            _logger.info(
                "goal loop: %s changed during a check of %s; retrying later", exc, session_id
            )
            return False
        return True

    async def _write_if_changed(
        self, session_id: str, snapshot: _Snapshot, key: str, value: str
    ) -> None:
        entry = snapshot.entries.get(key)
        if entry is not None and _text(entry) == value:
            return
        snapshot.entries[key] = await self._ctx.state.write(session_id, key, value)

    async def _publish(
        self, session_id: str, snapshot: _Snapshot, targets: list[Target] | None
    ) -> None:
        """Write the page's view and the published fields, when they changed."""
        goal, count, summary = published_fields(snapshot)
        for key, value in ((FIELD_GOAL, goal), (FIELD_COUNT, count), (FIELD_SUMMARY, summary)):
            if value:
                await self._write_if_changed(session_id, snapshot, key, value)
            elif snapshot.entries.pop(key, None) is not None:
                await self._ctx.state.clear(session_id, key)
        await self._write_if_changed(session_id, snapshot, KEY_VIEW, view_text(snapshot, targets))


def published_fields(snapshot: _Snapshot) -> tuple[str, str, str]:
    """``goal``, ``count`` and ``summary`` for a session; empty strings clear them."""
    goals = [goal for goal in snapshot.goals.values() if not goal.quiet]
    active = [goal for goal in goals if goal.active]
    asked = bool(snapshot.toggles_on())
    if not goals:
        return (WATCHING, "0", "Watching for PRs") if asked else ("", "", "")
    if active:
        status = UNMET if any(goal.status == UNMET for goal in active) else WATCHING
        plural = "" if len(active) == 1 else "s"
        return status, str(len(active)), f"Watching {len(active)} PR{plural}"
    if all(goal.status == MET for goal in goals):
        return MET, "0", "PR goal met" if len(goals) == 1 else "PR goals met"
    return STOPPED, "0", "Goals stopped"


def view(snapshot: _Snapshot, targets: list[Target] | None) -> dict[str, Any]:
    """What the extension's page shows: each PR with its toggle and goal."""
    toggles = snapshot.pr_toggles()
    by_url = {goal.target.url: goal for goal in snapshot.goals.values()}
    listed = list(targets) if targets is not None else []
    listed_urls = {target.url for target in listed}
    listed += [goal.target for url, goal in by_url.items() if url not in listed_urls]
    items = []
    for target in listed[:MAX_GOALS]:
        goal = by_url.get(target.url)
        items.append(
            {
                "id": target.id,
                "url": target.url,
                "label": target.label,
                "title": trim_bytes(target.title, _VIEW_TITLE_BYTES),
                "toggle": toggles.get(target.id, ("", 0))[0],
                "status": goal.status if goal is not None else "",
                "reason": goal.reason if goal is not None else "",
                "note": goal.note if goal is not None else "",
                "wakes": goal.wakes if goal is not None else 0,
                "max_wakes": goal.max_wakes if goal is not None else 0,
            }
        )
    return {
        "v": 1,
        "all": snapshot.all_on,
        "enabled": all(key in snapshot.enablers for key in snapshot.toggles_on()),
        "items": items,
    }


def view_text(snapshot: _Snapshot, targets: list[Target] | None) -> str:
    """The view as stored, shortened to fit one state value."""
    data = view(snapshot, targets)
    text = _dump(data)
    for field_name in ("title", "note"):
        if len(text.encode("utf-8")) <= MAX_VIEW_BYTES:
            return text
        for item in data["items"]:
            item[field_name] = ""
        text = _dump(data)
    while len(text.encode("utf-8")) > MAX_VIEW_BYTES and data["items"]:
        data["items"].pop()
        text = _dump(data)
    return text
