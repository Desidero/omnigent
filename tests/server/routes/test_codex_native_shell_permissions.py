"""Codex shell input uses the same owner boundary as direct environment shell."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from omnigent.entities import Conversation
from omnigent.runtime import pending_inputs, set_runner_client, set_runner_router
from omnigent.server.auth import (
    LEVEL_EDIT,
    LEVEL_MANAGE,
    LEVEL_OWNER,
    LEVEL_READ,
    UnifiedAuthProvider,
)
from tests.server.routes.test_session_resources import (
    _ConversationStore,
    _FakeRunnerClient,
    _FakeRunnerRouter,
    _sessions_app,
    runner_globals_reset,  # noqa: F401 — reuse runner-state isolation
)
from tests.server.routes.test_shell_permission_gate import _StubPermissionStore

_SESSION_ID = "64a784c3aa907d1774f44313546947c6"
_EVENT_PATH = f"/v1/sessions/{_SESSION_ID}/events"


@pytest.fixture
async def codex_client(
    runner_globals_reset: None,  # noqa: F811 — imported fixture
) -> AsyncIterator[tuple[httpx.AsyncClient, _FakeRunnerClient, Conversation]]:
    del runner_globals_reset
    store = _ConversationStore()
    conv = store.get_conversation(_SESSION_ID)
    assert conv is not None
    conv.harness_override = "codex-native"
    conv.labels["omnigent.wrapper"] = "codex-native-ui"
    permissions = _StubPermissionStore()
    for user, level in (
        ("viewer", LEVEL_READ),
        ("editor", LEVEL_EDIT),
        ("manager", LEVEL_MANAGE),
        ("owner", LEVEL_OWNER),
    ):
        permissions.add_grant(f"{user}@example.com", _SESSION_ID, level)
    permissions.add_admin("admin@example.com")
    runner = _FakeRunnerClient(payload={})
    set_runner_router(_FakeRunnerRouter(runner))  # type: ignore[arg-type]
    set_runner_client(runner)  # type: ignore[arg-type]
    app = _sessions_app(
        store,
        auth_provider=UnifiedAuthProvider(source="header", local_single_user=False),
        permission_store=permissions,
    )
    pending_inputs.reset_for_tests()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://server"
        ) as client:
            yield client, runner, conv
    finally:
        pending_inputs.reset_for_tests()


def _message(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "message", "data": {"role": "user", "content": content}}


@pytest.mark.parametrize("running", [False, True], ids=["initial", "live"])
@pytest.mark.parametrize(
    ("caller", "expected_status"),
    [("viewer", 403), ("editor", 403), ("manager", 403), ("owner", 202), ("admin", 202)],
)
async def test_codex_shell_requires_owner_before_dispatch(
    codex_client: tuple[httpx.AsyncClient, _FakeRunnerClient, Conversation],
    running: bool,
    caller: str,
    expected_status: int,
) -> None:
    client, runner, conv = codex_client
    conv.live_status = "running" if running else "idle"
    content = [{"type": "input_text", "text": " !printf authorized"}]
    response = await client.post(
        _EVENT_PATH,
        json=_message(content),
        headers={"X-Forwarded-Email": f"{caller}@example.com"},
    )
    assert response.status_code == expected_status, response.text
    if expected_status == 403:
        assert runner.calls == []
        assert pending_inputs.snapshot_for(_SESSION_ID) == []
    else:
        messages = [payload for path, payload in runner.post_json_calls if path == _EVENT_PATH]
        assert len(messages) == 1
        assert messages[0]["content"] == content
        assert messages[0]["harness"] == "codex-native"


@pytest.mark.parametrize(
    "content",
    [
        [{"type": "input_text", "text": "Explain this code"}],
        [{"type": "input_text", "text": "!!literal bang"}],
        [{"type": "input_text", "text": "!printf FIRST"}, {"type": "input_text", "text": "more"}],
        [
            {"type": "input_text", "text": "!inspect this file"},
            {"type": "input_file", "filename": "note.txt", "file_data": "aGk="},
        ],
    ],
    ids=["ordinary", "escaped-bang", "multiple-blocks", "attachment"],
)
async def test_codex_editor_model_input_keeps_edit_access(
    codex_client: tuple[httpx.AsyncClient, _FakeRunnerClient, Conversation],
    content: list[dict[str, Any]],
) -> None:
    client, runner, _conv = codex_client
    response = await client.post(
        _EVENT_PATH,
        json=_message(content),
        headers={"X-Forwarded-Email": "editor@example.com"},
    )
    assert response.status_code == 202, response.text
    messages = [payload for path, payload in runner.post_json_calls if path == _EVENT_PATH]
    assert len(messages) == 1
    assert messages[0]["content"] == content


@pytest.mark.parametrize("shape", ["history", "batch", "forged-author", "assistant-role"])
async def test_codex_shell_authorization_cannot_be_bypassed_by_event_shape(
    codex_client: tuple[httpx.AsyncClient, _FakeRunnerClient, Conversation], shape: str
) -> None:
    client, runner, _conv = codex_client
    content = [{"type": "input_text", "text": "!printf unauthorized"}]
    if shape == "history":
        content = [{"type": "message", "role": "user", "content": content}]
    event = _message(content)
    if shape == "forged-author":
        event["created_by"] = "owner@example.com"
    if shape == "assistant-role":
        event["data"]["role"] = "assistant"
    response = await client.post(
        _EVENT_PATH,
        json=[event] if shape == "batch" else event,
        headers={"X-Forwarded-Email": "editor@example.com"},
    )
    assert response.status_code == 403, response.text
    assert runner.calls == []
    assert pending_inputs.snapshot_for(_SESSION_ID) == []
