"""Best-effort delivery of session status observations to extensions.

A core observer (see :mod:`omnigent.server.session_status_observers`) hands
each observation to every subscribed extension that the operator has
installed and enabled. Delivery never blocks the publisher:

- Callbacks are ``async def`` and run on the server's event loop, one at a
  time per subscriber.
- Each subscriber has a bounded backlog, counting the running callback. When
  it is full the observation is dropped and counted.
- Each delivery runs in a copy of the publisher's ``contextvars``, so the
  callback sees the session's workspace, not the default one.
- A callback is cancelled after a timeout. One that ignores cancellation
  still holds its backlog slot until it returns, so it only delays its own
  subscriber.
- Errors, timeouts and drops are counted per subscriber and never
  quarantine anything.

:meth:`ExtensionStatusObservers.aclose` bounds how long the application waits
for backlogs at shutdown; a callback that ignores cancellation can still be
running afterwards.
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import inspect
import logging
from collections import deque
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any

from omnigent.server import session_status_observers
from omnigent.server.session_status_observers import SessionStatusObservation

_logger = logging.getLogger(__name__)

StatusCallback = Callable[[SessionStatusObservation], Coroutine[Any, Any, None]]


class ExtensionNotEnabledError(RuntimeError):
    """The extension is not installed and enabled, so it can't subscribe."""


@dataclass
class SubscriberStats:
    """What happened to the observations offered to one subscriber.

    :param delivered: Callbacks that returned normally.
    :param failed: Callbacks that raised.
    :param timed_out: Callbacks cancelled after the callback timeout.
    :param dropped: Observations not queued because the backlog was full or
        the subscriber was closing.
    :param abandoned: Observations still queued or running when shutdown
        stopped waiting.
    """

    delivered: int = 0
    failed: int = 0
    timed_out: int = 0
    dropped: int = 0
    abandoned: int = 0


class _Subscriber:
    """Runs one extension's callback on the event loop, one observation at a time."""

    def __init__(
        self,
        extension_id: str,
        callback: StatusCallback,
        *,
        loop: asyncio.AbstractEventLoop,
        max_pending: int,
        timeout_s: float,
    ) -> None:
        self.extension_id = extension_id
        self.stats = SubscriberStats()
        self._callback = callback
        self._loop = loop
        self._max_pending = max_pending
        self._timeout_s = timeout_s
        self._closing = False
        self._backlog: deque[tuple[SessionStatusObservation, contextvars.Context]] = deque()
        self._wakeup = asyncio.Event()
        # The running callback, until it actually finishes (even after a timeout).
        self._current: asyncio.Task[None] | None = None
        self.worker = loop.create_task(self._work(), name=f"extension-status-{extension_id}")

    def _count(self, field: str, error: BaseException | None = None) -> None:
        total = getattr(self.stats, field) + 1
        setattr(self.stats, field, total)
        if field == "delivered":
            return
        # Warn on the first of each kind; the counters carry the rest.
        _logger.log(
            logging.WARNING if total == 1 else logging.DEBUG,
            "extension %s status observation %s (%d so far)",
            self.extension_id,
            field,
            total,
            exc_info=error,
        )

    def _pending(self) -> int:
        return len(self._backlog) + (0 if self._current is None else 1)

    def offer(self, observation: SessionStatusObservation, context: contextvars.Context) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._enqueue(observation, context)
            return
        try:
            self._loop.call_soon_threadsafe(self._enqueue, observation, context)
        except RuntimeError:  # the loop has closed
            self._count("dropped")

    def _enqueue(
        self, observation: SessionStatusObservation, context: contextvars.Context
    ) -> None:
        if self._closing or self._pending() >= self._max_pending:
            self._count("dropped")
            return
        self._backlog.append((observation, context))
        self._wakeup.set()

    async def _work(self) -> None:
        while True:
            if not self._backlog:
                if self._closing:
                    return
                self._wakeup.clear()
                await self._wakeup.wait()
                continue
            observation, context = self._backlog.popleft()
            await self._deliver(observation, context)

    async def _deliver(
        self, observation: SessionStatusObservation, context: contextvars.Context
    ) -> None:
        try:
            coroutine = context.run(self._callback, observation)
            task = self._loop.create_task(coroutine, context=context)
        except Exception as error:  # noqa: BLE001 — an extension bug is counted, never raised
            self._count("failed", error)
            return
        self._current = task
        done, _ = await asyncio.wait({task}, timeout=self._timeout_s)
        if not done:
            task.cancel()
            task.add_done_callback(self._retrieve_late_failure)
            self._count("timed_out")
            # A callback that ignores cancellation keeps its slot until it returns.
            await asyncio.wait({task})
            self._current = None
            return
        self._current = None
        if task.cancelled():
            self._count("failed")
        elif (error := task.exception()) is not None:
            self._count("failed", error)
        else:
            self._count("delivered")

    def _retrieve_late_failure(self, task: asyncio.Task[None]) -> None:
        """Log a failure that follows a timeout or abandonment, already counted."""
        if not task.cancelled() and (error := task.exception()) is not None:
            _logger.debug(
                "extension %s status callback failed after it was cancelled",
                self.extension_id,
                exc_info=error,
            )

    def begin_close(self) -> None:
        self._closing = True
        self._wakeup.set()

    async def abandon(self) -> None:
        abandoned = self._pending()
        self._backlog.clear()
        if self._current is not None:
            self._current.cancel()
            self._current.add_done_callback(self._retrieve_late_failure)
        self.worker.cancel()
        await asyncio.gather(self.worker, return_exceptions=True)
        self.stats.abandoned += abandoned

    def snapshot(self) -> SubscriberStats:
        return dataclasses.replace(self.stats)


class ExtensionStatusObservers:
    """Delivers status observations to installed, enabled extensions."""

    def __init__(
        self,
        *,
        is_enabled: Callable[[str], bool],
        max_pending: int = 256,
        callback_timeout_s: float = 10.0,
    ) -> None:
        """
        :param is_enabled: Whether an extension id is installed and enabled by
            the operator. It runs inline on every status edge for every
            subscriber, so it must be a constant-time, in-memory check. It is
            checked at subscription and before each observation is queued; an
            error counts as not enabled.
        :param max_pending: The most observations one subscriber may have
            queued or running.
        :param callback_timeout_s: How long one callback may run before it is
            cancelled.
        """
        self._is_enabled = is_enabled
        self._max_pending = max_pending
        self._timeout_s = callback_timeout_s
        self._subscribers: dict[str, _Subscriber] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._unregister: Callable[[], None] | None = None
        self._closed = False

    def start(self) -> None:
        """Start observing; call on the server's event loop."""
        if self._unregister is not None or self._closed:
            return
        self._loop = asyncio.get_running_loop()
        self._unregister = session_status_observers.register_core_observer(self._observe)

    def subscribe(self, extension_id: str, callback: StatusCallback) -> None:
        """Deliver every later observation to ``callback``.

        Call on the event loop the observers started on.

        :param extension_id: The subscribing extension. One subscription each.
        :param callback: An ``async def`` taking the observation.
        :raises TypeError: ``callback`` is not an ``async def``.
        :raises ExtensionNotEnabledError: The extension is not installed and
            enabled.
        :raises RuntimeError: Not started, already closed, already subscribed,
            or called off that event loop.
        """
        if self._loop is None or self._closed:
            raise RuntimeError("status observers are not running")
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not self._loop:
            raise RuntimeError("subscribe on the event loop the status observers started on")
        if not inspect.iscoroutinefunction(callback):
            raise TypeError(
                f"extension {extension_id}: status callbacks must be async functions, "
                f"got {callback!r}"
            )
        if extension_id in self._subscribers:
            raise RuntimeError(f"extension {extension_id} is already subscribed")
        if not self._enabled(extension_id):
            raise ExtensionNotEnabledError(extension_id)
        self._subscribers[extension_id] = _Subscriber(
            extension_id,
            callback,
            loop=self._loop,
            max_pending=self._max_pending,
            timeout_s=self._timeout_s,
        )

    def stats(self) -> Mapping[str, SubscriberStats]:
        """Return a snapshot of each subscriber's counters."""
        return {
            extension_id: subscriber.snapshot()
            for extension_id, subscriber in self._subscribers.items()
        }

    def _enabled(self, extension_id: str) -> bool:
        try:
            return bool(self._is_enabled(extension_id))
        except Exception:
            _logger.warning("extension %s enablement check failed", extension_id, exc_info=True)
            return False

    def _observe(self, observation: SessionStatusObservation) -> None:
        for subscriber in tuple(self._subscribers.values()):
            if self._enabled(subscriber.extension_id):
                subscriber.offer(observation, contextvars.copy_context())

    async def aclose(self, *, wait_s: float = 2.0) -> None:
        """Stop observing and wait at most ``wait_s`` for queued deliveries.

        Whatever is still queued or running then is abandoned and counted.
        """
        if self._closed:
            return
        self._closed = True
        if self._unregister is not None:
            self._unregister()
        subscribers = tuple(self._subscribers.values())
        for subscriber in subscribers:
            subscriber.begin_close()
        if subscribers:
            await asyncio.wait({subscriber.worker for subscriber in subscribers}, timeout=wait_s)
        for subscriber in subscribers:
            await subscriber.abandon()
