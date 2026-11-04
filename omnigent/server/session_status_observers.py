"""In-process observers of session status edges.

``_publish_status`` builds one :class:`SessionStatusObservation` for every
edge that changes a session's cached status and, once the edge is published,
hands it to :func:`observe`, which calls each registered core observer inline, in
registration order, in the publisher's context. An observer that raises is
logged and does not affect the others or the publisher.

Observations are display-state edges seen by this replica, not lifecycle
events: an ``idle`` edge does not prove the model finished its turn, and a
``waiting`` edge is not a durable, answerable decision.

Core observers must be quick and must not block; one that needs async work,
or wants to start a turn, schedules it itself (see
``session_pull_requests.PullRequestRefresher``).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

from omnigent.db.db_models import current_workspace_id

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionStatusObservation:
    """One status edge as this replica published it.

    :param session_id: Session/conversation identifier.
    :param previous_status: The status cached before this edge, or ``None``
        when this replica had none (for example, after a restart).
    :param status: The new status, e.g. ``"idle"``.
    :param persist_requested: Whether the publisher asked to mirror the
        status onto the conversation row. Stops, archives and orphan
        settlement publish ``idle`` without it. The write itself is
        best-effort, so this does not mean it committed.
    :param response_id: The response the edge names, when it names one.
    :param blocked_on: What a ``waiting`` edge waits for, when known.
    :param workspace_id: The publisher's workspace.
    :param observed_at: When the edge was published, as a Unix timestamp.
    """

    type: ClassVar[str] = "session.status"
    schema_version: ClassVar[int] = 1

    session_id: str
    previous_status: str | None
    status: str
    persist_requested: bool
    response_id: str | None = None
    blocked_on: str | None = None
    workspace_id: int = field(default_factory=current_workspace_id)
    observed_at: float = field(default_factory=time.time)


CoreStatusObserver = Callable[[SessionStatusObservation], None]

_observers: tuple[CoreStatusObserver, ...] = ()
_lock = threading.Lock()


def register_core_observer(observer: CoreStatusObserver) -> Callable[[], None]:
    """Call ``observer`` inline on every status edge.

    Registering the same observer twice keeps one registration.

    :param observer: Called with each observation, in registration order.
    :returns: A function that unregisters ``observer``.
    """
    global _observers
    with _lock:
        if observer not in _observers:
            _observers = (*_observers, observer)

    def unregister() -> None:
        global _observers
        with _lock:
            _observers = tuple(item for item in _observers if item != observer)

    return unregister


def observe(observation: SessionStatusObservation) -> None:
    """Hand ``observation`` to every core observer; failures are logged.

    :param observation: The edge ``_publish_status`` just took.
    """
    for observer in _observers:
        try:
            observer(observation)
        except Exception:
            _logger.exception(
                "session status observer %r failed for %s",
                observer,
                observation.session_id,
            )
