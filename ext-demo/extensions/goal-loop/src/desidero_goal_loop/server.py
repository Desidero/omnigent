"""Server entrypoint: run the goal loop with its ``pr-green`` goal type."""

from __future__ import annotations

from typing import Any

from desidero_goal_loop.loop import GoalLoop, configured_interval_s
from desidero_goal_loop.pr_green import PrGreen


async def activate(ctx: Any) -> None:
    """Start the loop; it stops with the extension's tasks at shutdown.

    PRs are read with ``ctx.pull_request_info``: the Pull Requests panel's
    payload, through a host connected to this replica.
    """
    GoalLoop(ctx, PrGreen(ctx.pull_request_info), interval_s=configured_interval_s()).start()
