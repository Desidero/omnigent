"""Built-in tool for the user's chat link rules.

``sys_link_rules`` lists, adds, updates and removes the rules that turn short
references in chat messages into links (``docs/chat-link-rules.md``). The
runner dispatches it to the Omnigent server's ``/v1/link-rules`` endpoints,
which validate every rule; every change asks the user first through the
``__ask_on_link_rule_change`` policy.
"""

from __future__ import annotations

from typing import Any

from omnigent.tools.base import Tool


class SysLinkRulesTool(Tool):
    """List or change chat link rules. Runner-dispatched to ``/v1/link-rules``."""

    @classmethod
    def name(cls) -> str:
        """:returns: ``"sys_link_rules"``."""
        return "sys_link_rules"

    @classmethod
    def description(cls) -> str:
        """:returns: Human-readable description of the tool."""
        return (
            "List, add, update or remove the user's chat link rules, which turn short "
            "references in chat messages into links. A 'url' rule has a pattern (a short "
            "form such as 'BST-{num}', with {num} digits, {key} an uppercase key, {id} "
            "letters/digits/_/-, or a raw '/regex/' without lookaround, named groups or "
            "backreferences) and an https URL template using the same placeholders "
            "('{1}' for a regex group), e.g. 'https://jira.example.com/browse/BST-{num}'. "
            "The built-in 'github' (#123) and 'session' (session:<id>) kinds take no "
            "pattern or url. Every change asks the user to approve it; only change rules "
            "when the user asks."
        )

    def get_schema(self) -> dict[str, Any]:
        """:returns: The OpenAI-format tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name(),
                "description": self.description(),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "add", "update", "remove"],
                            "description": "What to do.",
                        },
                        "name": {
                            "type": "string",
                            "description": (
                                "add: the new rule's name. update/remove: the rule to change."
                            ),
                        },
                        "new_name": {
                            "type": "string",
                            "description": "update: rename the rule.",
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["url", "github", "session"],
                            "description": "add: the rule's kind (default 'url').",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "add/update, url kind: the pattern.",
                        },
                        "url": {
                            "type": "string",
                            "description": "add/update, url kind: the link template.",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "add/update: whether chat messages use the rule.",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
        }
