"""
Integration tests for multi-turn contextual policies with label state.

Verifies the realistic scenario where a policy monitors conversation state
(labels) and escalates based on accumulated context across turns:

- A condition-gated DENY policy that fires only when ``tainted: "1"`` is set.
- Label writes via PATCH persist across evaluations.
- The condition gate correctly skips when the label is at its initial value
  (``"0"``) and fires when updated to the matching value (``"1"``).
- Labels survive across multiple evaluation rounds (simulating multi-turn
  conversations).

Uses the shared ``client`` fixture from ``tests/server/conftest.py``
(real stores + mock LLM) so the tests hit the real route-to-store
pipeline without subprocesses or real LLM calls.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import insert

from omnigent.db.db_models import SqlConversationLabel
from omnigent.db.utils import get_or_create_engine
from omnigent.extensions.published_fields import PublishedFieldView, configure_published_fields
from omnigent.policies.published_fields import require_published_field
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.server.helpers import create_test_agent

pytestmark = pytest.mark.asyncio


POLICY_REGISTRY = [
    {"handler": f"{__name__}.{name}", "kind": "callable"}
    for name in (
        "_deny_all_tool_calls",
        "_deny_when_status_blocked",
        "_deny_when_other_flag_set",
        "_write_extension_label",
    )
]


@pytest.fixture(autouse=True)
def _register_test_policy_handlers() -> Iterator[None]:
    from omnigent.policies.registry import load_registry

    # HTTP uploads accept custom policies only when the server registers them.
    load_registry([__name__])
    yield
    load_registry()


# ── Policy callables ───────────────────────────────────────


def _deny_all_tool_calls(event: dict[str, Any]) -> dict[str, Any]:
    """
    Policy that unconditionally denies every tool call.

    Intended for use behind a condition gate so the DENY only fires
    when the gate's label condition matches. Without the gate, every
    tool call would be blocked.

    :param event: V0 event dict.
    :returns: DENY with a descriptive reason.
    """
    if event.get("type") != "tool_call":
        return {"result": "ALLOW"}
    return {
        "result": "DENY",
        "reason": "Conversation is tainted from a prior turn.",
    }


def _deny_when_status_blocked(event: dict[str, Any]) -> dict[str, Any]:
    """
    Deny tool calls while the published review status is ``blocked``.

    :param event: V0 event dict.
    :returns: DENY when blocked, else ALLOW.
    """
    if require_published_field(event, _STATUS_EXTENSION, "status") == "blocked":
        return {"result": "DENY", "reason": "Review status is blocked."}
    return {"result": "ALLOW"}


def _deny_when_other_flag_set(event: dict[str, Any]) -> dict[str, Any]:
    """
    Read an undeclared label under the extension's prefix the plain way.

    :param event: V0 event dict.
    :returns: DENY when the label is set, else ALLOW.
    """
    if event["context"]["labels"].get("ext.acme.status.other"):
        return {"result": "DENY", "reason": "Other flag is set."}
    return {"result": "ALLOW"}


def _write_extension_label(event: dict[str, Any]) -> dict[str, Any]:
    """
    Try to forge a published field through a policy label write.

    :param event: V0 event dict.
    :returns: ALLOW with an ``ext.*`` label write.
    """
    return {"result": "ALLOW", "set_labels": {_STATUS_LABEL: "done", "reviewed": "1"}}


# ── Helpers ────────────────────────────────────────────────


_STATUS_EXTENSION = "acme.status"
_STATUS_LABEL = "ext.acme.status.status"


@pytest.fixture
def published_status() -> Iterator[None]:
    """Make ``ext.acme.status.status`` an available published field."""
    configure_published_fields(
        PublishedFieldView(
            fields={_STATUS_LABEL: (_STATUS_EXTENSION, "status")},
            prefixes=frozenset({f"ext.{_STATUS_EXTENSION}."}),
        )
    )
    yield
    configure_published_fields(PublishedFieldView())


def _write_raw_label(db_uri: str, session_id: str, key: str, value: str) -> None:
    """Write a label as an older server could have, bypassing the store's checks."""
    with get_or_create_engine(db_uri).begin() as connection:
        connection.execute(
            insert(SqlConversationLabel.__table__).values(
                workspace_id=0, conversation_id=session_id, key=key, value=value, updated_at=1
            )
        )


def _publish_status(db_uri: str, session_id: str, status: str) -> None:
    SqlAlchemyConversationStore(db_uri)._put_extension_state(
        session_id, _STATUS_EXTENSION, "status", status.encode(), publish=True, max_keys=64
    )


async def _create_policy_session(
    client: httpx.AsyncClient, policy: dict[str, Any], **guardrails: Any
) -> str:
    agent = await create_test_agent(
        client, guardrails={"policies": {"gate": {"type": "function", **policy}}, **guardrails}
    )
    return await _create_session(client, agent["id"])


async def _evaluate(client: httpx.AsyncClient, session_id: str) -> dict[str, Any]:
    resp = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate", json=_tool_call_request("Bash")
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _create_session(
    client: httpx.AsyncClient,
    agent_id: str,
    *,
    labels: dict[str, str] | None = None,
) -> str:
    """
    Create a session bound to an agent and return its id.

    :param client: Test HTTP client.
    :param agent_id: Agent to bind.
    :param labels: Optional initial labels.
    :returns: New session id.
    """
    payload: dict[str, Any] = {"agent_id": agent_id}
    if labels is not None:
        payload["labels"] = labels
    resp = await client.post("/v1/sessions", json=payload)
    assert resp.status_code == 201, f"create failed: {resp.status_code} {resp.text}"
    return resp.json()["id"]


def _tool_call_request(tool_name: str = "Bash") -> dict[str, Any]:
    """
    Build a PHASE_TOOL_CALL EvaluationRequest.

    :param tool_name: Tool name, e.g. ``"Bash"``.
    :returns: EvaluationRequest JSON dict.
    """
    return {
        "event": {
            "type": "PHASE_TOOL_CALL",
            "target": "",
            "data": {"name": tool_name, "arguments": {}},
            "context": {},
        },
    }


# ── Tests ──────────────────────────────────────────────────


async def test_condition_gate_skips_when_label_at_initial_value(
    client: httpx.AsyncClient,
) -> None:
    """
    A condition-gated DENY policy is skipped when the label is at its
    initial value (``"0"``), which does not match the condition.

    This is turn 1 of the multi-turn scenario: the label ``tainted``
    starts at its declared ``initial: "0"`` value, so the condition
    ``tainted: "1"`` does not match and the policy is skipped entirely.
    The evaluate endpoint returns ALLOW.
    """
    agent = await create_test_agent(
        client,
        guardrails={
            "labels": {"tainted": {"values": ["0", "1"], "initial": "0"}},
            "policies": {
                "deny_when_tainted": {
                    "type": "function",
                    "condition": {"tainted": "1"},
                    "function": {
                        "path": f"{__name__}._deny_all_tool_calls",
                    },
                },
            },
        },
    )
    session_id = await _create_session(client, agent["id"])

    resp = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate",
        json=_tool_call_request("Bash"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "POLICY_ACTION_ALLOW", (
        f"Condition gate should skip when tainted=0; got {body}"
    )


async def test_condition_gate_fires_after_label_write(
    client: httpx.AsyncClient,
) -> None:
    """
    After labels are updated to match the condition, the gated DENY
    policy fires on the next evaluation.

    Simulates a multi-turn scenario:
    - Turn 1: ``tainted=0`` (default) → condition skips → ALLOW.
    - Label write: ``tainted=1`` via PATCH.
    - Turn 2: ``tainted=1`` → condition matches → DENY.

    This is the core IFC-through-labels pattern: a policy writes a
    label on one turn, and a downstream condition gate fires on the
    next.
    """
    agent = await create_test_agent(
        client,
        guardrails={
            "labels": {"tainted": {"values": ["0", "1"], "initial": "0"}},
            "policies": {
                "deny_when_tainted": {
                    "type": "function",
                    "condition": {"tainted": "1"},
                    "function": {
                        "path": f"{__name__}._deny_all_tool_calls",
                    },
                },
            },
        },
    )
    session_id = await _create_session(client, agent["id"])

    # Turn 1: tainted=0 → ALLOW
    resp1 = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate",
        json=_tool_call_request("Bash"),
    )
    assert resp1.status_code == 200
    assert resp1.json()["result"] == "POLICY_ACTION_ALLOW", "Turn 1 should ALLOW when tainted=0"

    # Simulate label write (as if a prior policy on a previous turn
    # wrote tainted=1 via set_labels).
    patch_resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"labels": {"tainted": "1"}},
    )
    assert patch_resp.status_code == 200

    # Turn 2: tainted=1 → condition matches → DENY
    resp2 = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate",
        json=_tool_call_request("Bash"),
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["result"] == "POLICY_ACTION_DENY", (
        f"Turn 2 should DENY when tainted=1; got {body2}"
    )
    assert "tainted" in body2.get("reason", "").lower(), (
        f"DENY reason should mention the taint; got {body2}"
    )


async def test_labels_persist_across_multiple_evaluations(
    client: httpx.AsyncClient,
) -> None:
    """
    Labels written via PATCH persist across multiple policy evaluations,
    verifiable through both GET /labels and repeated DENY verdicts.

    Turn 1: ALLOW (clean). Label write. Turn 2: DENY. Turn 3: still
    DENY (the label was not cleared). GET /labels confirms the persisted
    value between turns.
    """
    agent = await create_test_agent(
        client,
        guardrails={
            "labels": {"tainted": {"values": ["0", "1"], "initial": "0"}},
            "policies": {
                "deny_when_tainted": {
                    "type": "function",
                    "condition": {"tainted": "1"},
                    "function": {
                        "path": f"{__name__}._deny_all_tool_calls",
                    },
                },
            },
        },
    )
    session_id = await _create_session(client, agent["id"])

    # Turn 1: ALLOW
    resp1 = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate",
        json=_tool_call_request("Read"),
    )
    assert resp1.status_code == 200
    assert resp1.json()["result"] == "POLICY_ACTION_ALLOW"

    # Write the taint label
    patch_resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"labels": {"tainted": "1"}},
    )
    assert patch_resp.status_code == 200

    # Verify label persistence via GET
    labels_resp = await client.get(f"/v1/sessions/{session_id}/labels")
    assert labels_resp.status_code == 200
    labels_data = labels_resp.json()
    assert labels_data["labels"]["tainted"] == "1", (
        f"Label not persisted after PATCH; got {labels_data['labels']}"
    )

    # Turn 2: DENY (tainted=1)
    resp2 = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate",
        json=_tool_call_request("Bash"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["result"] == "POLICY_ACTION_DENY", (
        "Turn 2 should DENY after taint label write"
    )

    # Turn 3: still DENY — label persists across evaluations
    resp3 = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate",
        json=_tool_call_request("Bash"),
    )
    assert resp3.status_code == 200
    assert resp3.json()["result"] == "POLICY_ACTION_DENY", (
        "Turn 3 should still DENY — label was not cleared"
    )

    # Final label check: still tainted
    labels_resp2 = await client.get(f"/v1/sessions/{session_id}/labels")
    assert labels_resp2.status_code == 200
    assert labels_resp2.json()["labels"]["tainted"] == "1"


async def test_untainted_session_never_triggers_condition_gate(
    client: httpx.AsyncClient,
) -> None:
    """
    A session that never has its taint label set always passes the
    condition-gated policy — the gate never matches and every
    evaluation returns ALLOW.

    Regression guard: if the condition gate defaults to match-all
    instead of match-none, this test catches it.
    """
    agent = await create_test_agent(
        client,
        guardrails={
            "labels": {"tainted": {"values": ["0", "1"], "initial": "0"}},
            "policies": {
                "deny_when_tainted": {
                    "type": "function",
                    "condition": {"tainted": "1"},
                    "function": {
                        "path": f"{__name__}._deny_all_tool_calls",
                    },
                },
            },
        },
    )
    session_id = await _create_session(client, agent["id"])

    # Multiple evaluations — all ALLOW because tainted stays at "0"
    for tool in ("Bash", "Read", "Bash"):
        resp = await client.post(
            f"/v1/sessions/{session_id}/policies/evaluate",
            json=_tool_call_request(tool),
        )
        assert resp.status_code == 200
        assert resp.json()["result"] == "POLICY_ACTION_ALLOW", (
            f"Untainted session should always ALLOW; failed on tool={tool}"
        )


async def test_condition_reads_an_available_published_field(
    client: httpx.AsyncClient, db_uri: str, published_status: None
) -> None:
    """A condition on a published field gates like any label once it is available."""
    session_id = await _create_policy_session(
        client,
        {
            "condition": {_STATUS_LABEL: "blocked"},
            "function": {"path": f"{__name__}._deny_all_tool_calls"},
        },
    )
    assert (await _evaluate(client, session_id))["result"] == "POLICY_ACTION_ALLOW"

    _publish_status(db_uri, session_id, "blocked")

    assert (await _evaluate(client, session_id))["result"] == "POLICY_ACTION_DENY"


async def test_condition_on_an_unreadable_extension_label_fails_closed(
    client: httpx.AsyncClient, db_uri: str, published_status: None
) -> None:
    """Under an enabled extension's prefix, an undeclared or unbacked label denies."""
    undeclared = await _create_policy_session(
        client,
        {
            "condition": {"ext.acme.status.other": "1"},
            "function": {"path": f"{__name__}._deny_all_tool_calls"},
        },
    )
    planted = await _create_policy_session(
        client,
        {
            "condition": {_STATUS_LABEL: "done"},
            "function": {"path": f"{__name__}._deny_all_tool_calls"},
        },
    )
    # A label no state row backs, e.g. one written before ``ext.`` was reserved.
    _write_raw_label(db_uri, planted, _STATUS_LABEL, "blocked")

    for session_id, label in ((undeclared, "ext.acme.status.other"), (planted, _STATUS_LABEL)):
        body = await _evaluate(client, session_id)
        assert body["result"] == "POLICY_ACTION_DENY"
        assert label in body["reason"] and "unavailable" in body["reason"]


async def test_a_disabled_extensions_fields_fail_closed(
    client: httpx.AsyncClient, db_uri: str
) -> None:
    """An installed but disabled extension keeps its prefix governed: conditions deny."""
    configure_published_fields(
        PublishedFieldView(prefixes=frozenset({f"ext.{_STATUS_EXTENSION}."}))
    )
    try:
        session_id = await _create_policy_session(
            client,
            {
                "condition": {_STATUS_LABEL: "done"},
                "function": {"path": f"{__name__}._deny_all_tool_calls"},
            },
        )
        _publish_status(db_uri, session_id, "blocked")

        body = await _evaluate(client, session_id)
    finally:
        configure_published_fields(PublishedFieldView())

    assert body["result"] == "POLICY_ACTION_DENY"
    assert "unavailable" in body["reason"]


async def test_an_operator_disabled_extensions_fields_fail_closed(
    client: httpx.AsyncClient, db_uri: str, tmp_path: Path
) -> None:
    """``enabled: false`` turns an extension off but keeps its prefix governed."""
    from tests.server.routes.test_extension_state_routes import _server

    session_id = await _create_policy_session(
        client,
        {
            "condition": {_STATUS_LABEL: "blocked"},
            "function": {"path": f"{__name__}._deny_all_tool_calls"},
        },
    )
    _publish_status(db_uri, session_id, "done")
    # Building a server whose config turns the installed extension off installs
    # the process-wide published-field view that policies read.
    await _server(
        db_uri,
        tmp_path / "off",
        server_config={"extensions": {_STATUS_EXTENSION: {"enabled": False}}},
    )
    try:
        body = await _evaluate(client, session_id)
    finally:
        configure_published_fields(PublishedFieldView())

    assert body["result"] == "POLICY_ACTION_DENY"
    assert "unavailable" in body["reason"]


async def test_other_ext_labels_stay_ordinary_labels(
    client: httpx.AsyncClient, db_uri: str
) -> None:
    """With no extension enabled for a prefix, its labels gate like any label."""
    session_id = await _create_policy_session(
        client,
        {
            "condition": {"ext.legacy.flag": "1"},
            "function": {"path": f"{__name__}._deny_all_tool_calls"},
        },
    )
    assert (await _evaluate(client, session_id))["result"] == "POLICY_ACTION_ALLOW"

    _write_raw_label(db_uri, session_id, "ext.legacy.flag", "1")

    assert (await _evaluate(client, session_id))["result"] == "POLICY_ACTION_DENY"


async def test_function_policy_cannot_read_unreadable_labels_as_absent(
    client: httpx.AsyncClient, published_status: None
) -> None:
    """Looking up an undeclared label under an enabled prefix denies, not allows."""
    session_id = await _create_policy_session(
        client, {"function": {"path": f"{__name__}._deny_when_other_flag_set"}}
    )

    body = await _evaluate(client, session_id)

    assert body["result"] == "POLICY_ACTION_DENY"
    assert "unavailable" in body["reason"]


async def test_function_policy_requires_a_published_field(
    client: httpx.AsyncClient, db_uri: str, published_status: None
) -> None:
    """``require_published_field`` reads the value, and fails closed once it is unavailable."""
    session_id = await _create_policy_session(
        client, {"function": {"path": f"{__name__}._deny_when_status_blocked"}}
    )
    assert (await _evaluate(client, session_id))["result"] == "POLICY_ACTION_ALLOW"
    _publish_status(db_uri, session_id, "blocked")
    assert (await _evaluate(client, session_id))["result"] == "POLICY_ACTION_DENY"

    configure_published_fields(PublishedFieldView())
    _publish_status(db_uri, session_id, "done")
    body = await _evaluate(client, session_id)

    assert body["result"] == "POLICY_ACTION_DENY"
    assert "unavailable" in body["reason"]


async def test_policy_label_writes_cannot_forge_published_fields(
    client: httpx.AsyncClient, published_status: None
) -> None:
    """A policy's ``ext.*`` label write is dropped; its other writes land."""
    session_id = await _create_policy_session(
        client, {"function": {"path": f"{__name__}._write_extension_label"}}
    )

    assert (await _evaluate(client, session_id))["result"] == "POLICY_ACTION_ALLOW"

    labels = (await client.get(f"/v1/sessions/{session_id}/labels")).json()["labels"]
    assert labels.get("reviewed") == "1"
    assert _STATUS_LABEL not in labels


async def test_agent_spec_cannot_declare_an_enabled_extensions_labels(
    client: httpx.AsyncClient, published_status: None
) -> None:
    """Declaring a label under an enabled extension's prefix is rejected at spec load."""
    with pytest.raises(AssertionError, match="mirror its published state"):
        await create_test_agent(client, guardrails={"labels": {_STATUS_LABEL: "blocked"}})


async def test_agent_spec_may_declare_other_ext_labels_but_not_seed_them(
    client: httpx.AsyncClient,
) -> None:
    """Other ``ext.`` declarations load; their initial value is not written."""
    session_id = await _create_policy_session(
        client,
        {"function": {"path": f"{__name__}._deny_all_tool_calls"}},
        labels={"ext.legacy.flag": "1", "team": "ml"},
    )

    # The engine seeds declared labels when it is built.
    assert (await _evaluate(client, session_id))["result"] == "POLICY_ACTION_DENY"

    labels = (await client.get(f"/v1/sessions/{session_id}/labels")).json()["labels"]
    assert labels.get("team") == "ml"
    assert "ext.legacy.flag" not in labels
