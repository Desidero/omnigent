"""Hide the open items tools from runners whose server cannot store them."""

from __future__ import annotations

from dataclasses import replace

from omnigent.spec.types import AgentSpec

# Sent on the runner's bundle download. A missing header means "no open items":
# servers that predate it have no /v1/sessions/{id}/open-items routes.
OPEN_ITEMS_HEADER = "X-Omnigent-Open-Items"


def without_open_items_tools(spec: AgentSpec) -> AgentSpec:
    """Return *spec* and its sub-agents with the open items tool group off."""
    return replace(
        spec,
        tool_groups=replace(spec.tool_groups, open_items=False),
        sub_agents=[without_open_items_tools(child) for child in spec.sub_agents],
    )
