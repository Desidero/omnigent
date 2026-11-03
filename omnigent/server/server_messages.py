"""Messages the server sends into a session on its own initiative.

A server-originated message (for example a session wake, see
:mod:`omnigent.server.session_wake`) travels the same path as a person's
message, through the session events route, so authorization, input policies,
persistence and runner delivery all apply. Two message fields are reserved for
it: every client input model rejects them at validation (see
``SessionEventInput.reject_server_only_fields``), and only
:class:`~omnigent.server.schemas.ServerMessageInput` carries them:

- ``origin``: :class:`~omnigent.entities.conversation.MessageOrigin`, stored on
  the item so clients can show who started the message.
- ``delivery``: ``"next_turn_only"`` asks the runner never to steer the message
  into a running turn; it waits for the next turn instead.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from starlette.datastructures import Headers

from omnigent.errors import ErrorCode, OmnigentError

NEXT_TURN_ONLY: Literal["next_turn_only"] = "next_turn_only"
# Runner control event: drop a queued next-turn-only input by ``pending_id``
# (a Stop overtook the post that queued it).
DROP_NEXT_TURN_INPUT = "drop_next_turn_input"


# A wake's text starts with this one-line framework header.
AUTOMATION_HEADER_PREFIX = "[Automation: "


@dataclass(frozen=True)
class ServerEventContext:
    """The identity a server-originated message is posted as.

    :param app: The FastAPI application.
    :param user_id: The user the message is attributed to, or ``None`` in
        single-user mode.
    :param headers: Request headers; empty, since no client sent it.
    """

    app: Any
    user_id: str | None
    headers: Headers = field(default_factory=Headers)


class SessionNotReadyError(OmnigentError):
    """The session can't take a server-originated message yet (it is still starting)."""

    def __init__(self, message: str = "session is still starting") -> None:
        super().__init__(message, code=ErrorCode.CONFLICT)


# ``send(app, session_id, user_id, content, *, origin, delivery)``.
ServerMessageDispatch = Callable[..., Awaitable[Mapping[str, Any]]]
