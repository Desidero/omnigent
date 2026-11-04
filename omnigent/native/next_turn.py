"""The ``next_turn_only`` delivery rule, shared by the server, runner and harnesses.

A message the server sends for automation (a session wake) carries
``delivery: "next_turn_only"``: it must start a turn of its own and never be
steered into a running one. The runner binds the rule to the turn that
delivers such a message (:func:`next_turn_delivery`), and a native executor
that finds its terminal busy under its injection lock refuses the message with
:data:`NEXT_TURN_BUSY_CODE` instead of typing it; the runner then holds it for
the next turn.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

NEXT_TURN_ONLY = "next_turn_only"
NEXT_TURN_BUSY_CODE = "next_turn_busy"
# Runner control event: drop a queued next-turn-only input by ``pending_id``
# (a Stop overtook the post that queued it).
DROP_NEXT_TURN_INPUT = "drop_next_turn_input"

_next_turn_only: ContextVar[bool] = ContextVar("next_turn_only_delivery", default=False)


@contextlib.contextmanager
def next_turn_delivery(delivery: str | None) -> Iterator[None]:
    """Bind one turn's delivery rule for the executor that delivers it."""
    token = _next_turn_only.set(delivery == NEXT_TURN_ONLY)
    try:
        yield
    finally:
        _next_turn_only.reset(token)


def delivery_is_next_turn_only() -> bool:
    """Whether the message being delivered must not join a running turn."""
    return _next_turn_only.get()
