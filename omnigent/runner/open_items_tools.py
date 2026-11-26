"""Runner-side handlers for the ``sys_open_items_*`` tools.

The runner has no open items store, so these tools call the server's
``/v1/sessions/{id}/open-items`` routes for the calling session only. A raise
carries an idempotency key from the tool call, so its retries get the labels
the first attempt allocated. Results come back compact, for the model to scan.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from typing import Any

import httpx

from omnigent.entities.open_items import BATCH_KEY_MAX_CHARS
from omnigent.runner.identity import ORCHESTRATION_SOURCE_HEADER
from omnigent.runner.journal_tools import _idempotency_key, _is_unrouted, _server_message
from omnigent.tools.builtins.open_items import OPEN_ITEMS_LIST_MAX, OPEN_ITEMS_TOOL_NAMES

__all__ = ["OPEN_ITEMS_TOOL_NAMES", "execute_open_items_tool"]

_UNAVAILABLE = (
    "unavailable: this Omnigent server does not store open items; label items in chat instead"
)
_WRITE_ATTEMPTS = 3
_RETRYABLE_STATUSES = frozenset({502, 503, 504})
_DETAIL_PREVIEW_CHARS = 300


def _url(session_id: str) -> str:
    """The session's open items route; the ID must stay one URL segment."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
        raise ValueError("conversation_id must be a session ID")
    return f"/v1/sessions/{session_id}/open-items"


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _batch_key(call_id: str | None) -> str:
    key = _idempotency_key(call_id)
    if len(key) > BATCH_KEY_MAX_CHARS:
        key = f"tool:sha256:{hashlib.sha256(key.encode()).hexdigest()}"
    return key


async def _sleep(seconds: float) -> None:
    """Wait before a retry; tests replace this, never ``asyncio.sleep`` itself."""
    await asyncio.sleep(seconds)


async def _send(
    server_client: httpx.AsyncClient,
    method: str,
    url: str,
    conversation_id: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response | str:
    """Send one request as the session's agent, retrying gateway failures."""
    for attempt in range(_WRITE_ATTEMPTS):
        last = attempt + 1 == _WRITE_ATTEMPTS
        try:
            response = await server_client.request(
                method,
                url,
                json=body,
                params=params,
                headers={ORCHESTRATION_SOURCE_HEADER: conversation_id},
                timeout=30.0,
            )
        except httpx.TransportError as exc:
            if last:
                return f"could not reach the server: {exc}"
        else:
            if response.status_code not in _RETRYABLE_STATUSES or last:
                return response
        await _sleep(0.5 * (attempt + 1) + random.uniform(0.0, 0.25))
    raise AssertionError("unreachable")


def _failure(response: httpx.Response | str) -> str | None:
    """The tool's error for a failed request, or ``None`` when it succeeded."""
    if isinstance(response, str):
        return _error(response)
    if _is_unrouted(response):
        return _error(_UNAVAILABLE)
    if response.status_code < 400:
        return None
    message = _server_message(response)
    if response.status_code == 404 and message.startswith("Open items are not available"):
        return _error(_UNAVAILABLE)
    return _error(message)


def _error_text(error: dict[str, Any]) -> str:
    return f"{error.get('code')}: {error.get('message')}"


def _state(item: dict[str, Any]) -> dict[str, Any]:
    state = {"label": item["label"], "status": item["status"], "title": item["title"]}
    if item.get("topic"):
        state["topic"] = item["topic"]
    if item["status"] == "closed":
        state["resolution"] = item.get("resolution")
    return state


def _row(item: dict[str, Any]) -> dict[str, Any]:
    row = {**_state(item), "kind": item["kind"]}
    detail = item.get("detail") or ""
    if detail:
        row["detail"] = detail[:_DETAIL_PREVIEW_CHARS]
        if len(detail) > _DETAIL_PREVIEW_CHARS:
            row["detail_truncated"] = True
    for name in ("url", "raised_by"):
        if item.get(name):
            row[name] = item[name]
    if item.get("links"):
        row["links"] = [link["url"] for link in item["links"]]
    if item.get("answers"):
        row["latest_answer"] = item["answers"][-1]["text"]
    if item.get("closed_by"):
        row["closed_by"] = item["closed_by"]
    return row


async def _raise(
    args: dict[str, Any],
    server_client: httpx.AsyncClient,
    conversation_id: str,
    call_id: str | None,
) -> str:
    items = args.get("items")
    if not isinstance(items, list) or not items:
        return _error("invalid_input: items must be a non-empty list")
    body = {"items": items, "idempotency_key": _batch_key(call_id)}
    response = await _send(
        server_client, "POST", _url(conversation_id), conversation_id, body=body
    )
    if (failure := _failure(response)) is not None:
        return failure
    assert isinstance(response, httpx.Response)
    payload = response.json()
    results = []
    for result in payload["items"]:
        if "error" in result:
            results.append({"error": _error_text(result["error"])})
            continue
        state = _state(result["item"])
        if result.get("duplicate"):
            state["duplicate"] = True
        results.append(state)
    return json.dumps(
        {"items": results, "open_count": payload["open_count"], "topics": payload["topics"]},
        ensure_ascii=False,
    )


async def _update(
    args: dict[str, Any],
    server_client: httpx.AsyncClient,
    conversation_id: str,
    call_id: str | None,
) -> str:
    updates = args.get("updates")
    if not isinstance(updates, list) or not updates:
        return _error("invalid_input: updates must be a non-empty list")
    body = {"updates": updates, "ref": f"tool:{call_id}"[:128] if call_id else None}
    response = await _send(
        server_client, "PATCH", _url(conversation_id), conversation_id, body=body
    )
    if (failure := _failure(response)) is not None:
        return failure
    assert isinstance(response, httpx.Response)
    results = [
        {"label": result["label"], "error": _error_text(result["error"])}
        if "error" in result
        else _state(result["item"])
        for result in response.json()["items"]
    ]
    return json.dumps({"items": results}, ensure_ascii=False)


async def _list(
    args: dict[str, Any], server_client: httpx.AsyncClient, conversation_id: str
) -> str:
    params: dict[str, Any] = {}
    for name, param in (("status", "status"), ("kind", "kind"), ("topic", "topic")):
        if args.get(name) is not None:
            params[param] = args[name]
    if args.get("query"):
        params["q"] = args["query"]
    if args.get("after"):
        params["after"] = args["after"]
    limit = args.get("limit", 50)
    if not isinstance(limit, int) or not 1 <= limit <= OPEN_ITEMS_LIST_MAX:
        return _error(f"invalid_input: limit must be 1 to {OPEN_ITEMS_LIST_MAX}")
    params["limit"] = limit
    response = await _send(
        server_client, "GET", _url(conversation_id), conversation_id, params=params
    )
    if (failure := _failure(response)) is not None:
        return failure
    assert isinstance(response, httpx.Response)
    page = response.json()
    return json.dumps(
        {
            "items": [_row(item) for item in page["data"]],
            "truncated": page["has_more"],
            "next_after": page["next_after"],
            "counts": page["counts"]["status"],
            "topics": page["topics"],
        },
        ensure_ascii=False,
    )


async def execute_open_items_tool(
    tool_name: str,
    arguments: str,
    *,
    server_client: httpx.AsyncClient | None,
    conversation_id: str | None,
    call_id: str | None = None,
) -> str:
    """Run one ``sys_open_items_*`` call for the calling session.

    :param tool_name: One of :data:`OPEN_ITEMS_TOOL_NAMES`.
    :param arguments: The call's JSON arguments.
    :param server_client: HTTP client pointed at the Omnigent server.
    :param conversation_id: The calling session; the tools reach its items only.
    :param call_id: The harness's tool call ID, which names a raise for its
        retries; ``None`` when the call came without one, e.g. over MCP.
    :returns: The tool output, a JSON object; ``{"error": …}`` on failure.
    """
    if server_client is None or not conversation_id:
        return _error(f"{tool_name} requires server access")
    try:
        args = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError:
        return _error(f"{tool_name}: malformed JSON arguments")
    if not isinstance(args, dict):
        return _error(f"{tool_name}: arguments must be an object")
    try:
        if tool_name == "sys_open_items_raise":
            return await _raise(args, server_client, conversation_id, call_id)
        if tool_name == "sys_open_items_update":
            return await _update(args, server_client, conversation_id, call_id)
        return await _list(args, server_client, conversation_id)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return _error(f"{tool_name} failed: {exc}")
