"""Built-in tools that keep the session's open items: questions, risks, findings, follow-ups.

Registered unless the agent spec sets ``tool_groups.open_items: false``, and
kept by the runner only when the server stores open items. The runner sends
them to the server's ``/v1/sessions/{id}/open-items`` routes, which allocate
labels such as ``Q7``.

``sys_open_items_raise``
    Raise items and get their labels.

``sys_open_items_update``
    Close, reopen, retitle, retopic or relink items.

``sys_open_items_list``
    List the session's items, open and answered by default.
"""

from __future__ import annotations

from typing import Any

from omnigent.entities.open_items import (
    KINDS,
    LINKS_PER_ITEM,
    RAISE_BATCH_MAX,
    UPDATE_BATCH_MAX,
)
from omnigent.tools.base import Tool

# The most rows one list call returns.
OPEN_ITEMS_LIST_MAX = 100

_LINKS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "maxItems": LINKS_PER_ITEM,
    "description": "http(s) links that support the item.",
    "items": {
        "type": "object",
        "properties": {"url": {"type": "string"}, "label": {"type": "string"}},
        "required": ["url"],
        "additionalProperties": False,
    },
}


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


class SysOpenItemsRaiseTool(Tool):
    """Raise items. Dispatched to ``POST /v1/sessions/{id}/open-items``."""

    @classmethod
    def name(cls) -> str:
        """:returns: ``"sys_open_items_raise"``."""
        return "sys_open_items_raise"

    @classmethod
    def description(cls) -> str:
        """:returns: Human-readable description of the tool."""
        return (
            "Record items that need the user's decision or attention later in this session's "
            "open items list, which the user sees beside the chat: a question, risk, finding "
            "or follow-up, or a link worth keeping. Returns each item's label (e.g. Q7); write "
            "that label in chat when you present the item. Pass label to adopt a label you "
            "already wrote in chat without the tool. Reuse a topic for items about the same "
            "piece of work."
        )

    def get_schema(self) -> dict[str, Any]:
        """:returns: The OpenAI-format tool schema."""
        item = {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(KINDS)},
                "title": {"type": "string", "description": "A few words, under 160 characters."},
                "detail": {"type": "string", "description": "The full item, Markdown."},
                "topic": {
                    "type": "string",
                    "description": "Short slug for the piece of work, e.g. 'cache-rollout'.",
                },
                "links": _LINKS_SCHEMA,
                "url": {"type": "string", "description": "A link item's URL (kind link only)."},
                "raised_by": {
                    "type": "string",
                    "description": "The sub-agent this item speaks for, if not you.",
                },
                "label": {"type": "string", "description": "A label already used in chat."},
            },
            "required": ["kind"],
            "additionalProperties": False,
        }
        return _schema(
            self.name(),
            self.description(),
            {
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": RAISE_BATCH_MAX,
                    "items": item,
                }
            },
            ["items"],
        )


class SysOpenItemsUpdateTool(Tool):
    """Change items. Dispatched to ``PATCH /v1/sessions/{id}/open-items``."""

    @classmethod
    def name(cls) -> str:
        """:returns: ``"sys_open_items_update"``."""
        return "sys_open_items_update"

    @classmethod
    def description(cls) -> str:
        """:returns: Human-readable description of the tool."""
        return (
            "Change this session's open items by label. Close an item with status closed and a "
            "one-line resolution as soon as it is resolved, decided, rejected, done or no "
            "longer relevant; reopen it with status open. Also edits title, detail, topic and "
            "links. Each label gets its new state or its own error."
        )

    def get_schema(self) -> dict[str, Any]:
        """:returns: The OpenAI-format tool schema."""
        change = {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "e.g. Q7"},
                "status": {"type": "string", "enum": ["open", "closed"]},
                "resolution": {
                    "type": "string",
                    "description": "How it ended, one line; required to close.",
                },
                "title": {"type": "string"},
                "detail": {"type": "string"},
                "topic": {"type": "string", "description": "Empty to clear."},
                "add_links": _LINKS_SCHEMA,
                "remove_links": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["label"],
            "additionalProperties": False,
        }
        return _schema(
            self.name(),
            self.description(),
            {
                "updates": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": UPDATE_BATCH_MAX,
                    "items": change,
                }
            },
            ["updates"],
        )


class SysOpenItemsListTool(Tool):
    """List items. Dispatched to ``GET /v1/sessions/{id}/open-items``."""

    @classmethod
    def name(cls) -> str:
        """:returns: ``"sys_open_items_list"``."""
        return "sys_open_items_list"

    @classmethod
    def description(cls) -> str:
        """:returns: Human-readable description of the tool."""
        return (
            "List this session's open items in label order: open and answered ones unless "
            "status says otherwise, with a detail preview, the user's latest answer and how "
            "closed items ended. Use it instead of relying on memory before referring to, "
            "closing or raising items."
        )

    def get_schema(self) -> dict[str, Any]:
        """:returns: The OpenAI-format tool schema."""
        return _schema(
            self.name(),
            self.description(),
            {
                "status": {
                    "type": "string",
                    "enum": ["open", "answered", "closed", "all"],
                    "description": "Default: open and answered.",
                },
                "kind": {"type": "string", "enum": list(KINDS)},
                "topic": {"type": "string"},
                "query": {"type": "string", "description": "Text to look for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": OPEN_ITEMS_LIST_MAX},
                "after": {"type": "string", "description": "Continue after this label."},
            },
            [],
        )


OPEN_ITEMS_TOOLS: tuple[type[Tool], ...] = (
    SysOpenItemsRaiseTool,
    SysOpenItemsUpdateTool,
    SysOpenItemsListTool,
)
OPEN_ITEMS_TOOL_NAMES: frozenset[str] = frozenset(tool.name() for tool in OPEN_ITEMS_TOOLS)
