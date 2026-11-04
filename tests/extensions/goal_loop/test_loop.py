"""The goal loop against a fake extension context: enrol, wake, commit, stop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from desidero_goal_loop.goals import Target
from desidero_goal_loop.loop import (
    MAX_GOALS,
    PAUSED_NOTE,
    Goal,
    GoalLoop,
    _Snapshot,
    goal_key,
    view_text,
)
from desidero_goal_loop.pr_green import PrGreen

from tests.extensions.goal_loop.fakes import (
    SESSION,
    CommandEvent,
    FakeContext,
    FakeWake,
    Linked,
    LinkedList,
    Observation,
    Reader,
    pr_info,
    url,
)

pytestmark = pytest.mark.asyncio


class Harness:
    def __init__(self, *prs: int) -> None:
        self.ctx = FakeContext()
        self.reader = Reader()
        self.ctx.linked[SESSION] = LinkedList(
            [Linked(url(n), "org/repo", n, title=f"PR {n}") for n in prs]
        )
        # CI still running: goals keep watching until a test says otherwise.
        for number in prs:
            self.reader.infos[url(number)] = pr_info(number, pending=True)
        self.loop = GoalLoop(self.ctx, self.reader.goal_type(), hint_delay_s=0)

    async def command(self, key: str, value: str, **event: Any) -> None:
        """Run a declared command: core writes the key, then tells the extension."""
        command = CommandEvent(SESSION, key, **event)
        await self.ctx.state.write(SESSION, key, value, updated_by=command.user_id)
        await self.loop.on_command(command)
        await self.settle()

    async def settle(self) -> None:
        for task in list(self.ctx.tasks):
            await task
        self.ctx.tasks.clear()

    async def check(self) -> None:
        await self.loop.check_session(SESSION)

    def field(self, key: str) -> str | None:
        return self.ctx.state.text(SESSION, key)

    def goal(self, number: int) -> dict[str, Any]:
        return json.loads(self.field(goal_key(url(number))) or "{}")

    def published(self) -> tuple[str | None, str | None, str | None]:
        return self.field("goal"), self.field("count"), self.field("summary")


async def test_all_prs_wakes_once_for_the_red_pr_then_meets_the_goal() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.reader.infos[url(9)] = pr_info(9, pending=True)

    await harness.command("all", "on")

    enabler = json.loads(harness.field("enablers") or "{}")["all"]
    assert (enabler["user"], enabler["generation"]) == ("alice@example.com", "g1")
    assert harness.goal(7)["user"] == "alice@example.com"
    [wake] = harness.ctx.wake.requests
    assert (wake["on_behalf_of"], wake["generation"], wake["label"]) == (
        "alice@example.com",
        "g1",
        "Goal loop",
    )
    assert wake["text"].startswith("Goal: PR green — #7 needs attention")
    assert url(9) not in wake["text"] and "Check failed: lint" in wake["text"]
    assert wake["dedupe_key"] and wake["evidence_key"]
    assert harness.published() == ("unmet", "2", "Watching 2 PRs")
    assert (harness.goal(7)["status"], harness.goal(9)["status"]) == ("unmet", "watching")

    # Still pending: checking again asks for nothing new.
    await harness.check()
    assert len(harness.ctx.wake.requests) == 1

    # Delivered: the events count as reported, and the same failure stays quiet.
    harness.ctx.wake.deliver(SESSION)
    await harness.check()
    assert len(harness.ctx.wake.requests) == 1
    assert harness.goal(7)["wakes"] == 1 and harness.goal(7)["pending"] is None

    # The agent fixed it, and the other PR's CI passed: both are green.
    harness.reader.infos[url(7)] = pr_info(7, head="b" * 40)
    harness.reader.infos[url(9)] = pr_info(9)
    await harness.check()
    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("met", "green")
    assert harness.goal(7)["note"] == (
        "#7 is green: all checks passed on bbbbbbb and no changes are requested"
    )
    assert harness.published() == ("met", "0", "PR goals met")
    view = json.loads(harness.field("goals") or "{}")
    assert [(item["label"], item["status"]) for item in view["items"]] == [
        ("#7", "met"),
        ("#9", "met"),
    ]


async def test_a_dropped_wake_is_asked_for_again() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.drop(SESSION)  # e.g. lost in a restart

    await harness.check()

    first, again = harness.ctx.wake.requests
    assert first["dedupe_key"] == again["dedupe_key"]
    assert harness.goal(7)["wakes"] == 0


async def test_a_person_stopping_the_session_pauses_until_resumed() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    assert (harness.goal(7)["status"], harness.goal(7)["note"]) == ("paused", PAUSED_NOTE)
    assert harness.published() == ("paused", "0", "PR goal paused")
    [item] = json.loads(harness.field("goals") or "{}")["items"]
    assert (item["status"], item["reason"], item["note"]) == (
        "paused",
        "stopped_by_user",
        PAUSED_NOTE,
    )

    # Something new on the PR doesn't resume it, and a paused goal isn't read.
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    harness.reader.reads.clear()
    await harness.check()
    assert len(harness.ctx.wake.requests) == 1
    assert harness.goal(7)["status"] == "paused"
    assert url(7) not in harness.reader.reads

    # Resume: it carries on for the person who resumed it, reporting what the
    # stopped wake didn't deliver and what is new.
    await harness.command("resume", "org/repo/7", user_id="carol@example.com", generation="g3")
    assert (harness.goal(7)["status"], harness.goal(7)["note"]) == ("unmet", "")
    assert harness.field("resume") is None
    woken = harness.ctx.wake.requests[-1]
    assert (woken["on_behalf_of"], woken["generation"]) == ("carol@example.com", "g3")
    assert "Check failed: lint" in woken["text"] and "Check failed: tests" in woken["text"]
    assert harness.published() == ("unmet", "1", "Watching 1 PR")


async def test_resume_keeps_the_wakes_used_and_off_then_on_restarts_fresh() -> None:
    harness = Harness(7)
    harness.loop = GoalLoop(harness.ctx, harness.reader.goal_type(), hint_delay_s=0, max_wakes=2)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    assert harness.goal(7)["wakes"] == 1

    await harness.command("resume", "org/repo/7")
    assert (harness.goal(7)["status"], harness.goal(7)["wakes"]) == ("unmet", 1)
    # The stopped wake's failure is offered again, as the goal's second wake.
    assert len(harness.ctx.wake.requests) == 2
    harness.ctx.wake.deliver(SESSION)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    await harness.check()
    assert harness.goal(7)["wakes"] == 2
    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("stopped", "budget")

    await harness.command("all", "off")
    await harness.command("all", "on")
    assert (harness.goal(7)["status"], harness.goal(7)["wakes"]) == ("unmet", 0)


@pytest.mark.parametrize("seen", [False, True], ids=["delivered-at-stop", "counted-before"])
async def test_resume_offers_the_stopped_wakes_events_again(seen: bool) -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    if seen:
        await harness.check()  # The loop counted the wake before the Stop.
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.command("resume", "org/repo/7")

    first, again = harness.ctx.wake.requests
    assert "Check failed: lint" in again["text"] and again["text"] == first["text"]
    # Not the delivered wake's dedupe key, or the service would call it a duplicate.
    assert again["dedupe_key"] != first["dedupe_key"]
    assert harness.goal(7)["wakes"] == 1
    # The goal that wasn't in the wake has nothing to offer again.
    await harness.command("resume", "org/repo/9")
    assert len(harness.ctx.wake.requests) == 2


async def test_only_the_stopped_wakes_goals_are_offered_again() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.check()  # #9's wake was handled.
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.check()
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")  # Stops #7's wake turn.

    await harness.command("resume", "org/repo/9")

    assert len(harness.ctx.wake.requests) == 2


async def test_a_goal_met_by_resume_offers_nothing_again() -> None:
    comment = {
        "author": "maintainer",
        "author_association": "MEMBER",
        "body": "please fix",
        "created_at": "2026-11-04T09:00:00Z",
        "url": f"{url(7)}#c-1",
    }
    harness = Harness(7)
    await harness.command("all", "on")
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",), comments=[comment])
    await harness.check()
    harness.ctx.wake.deliver(SESSION)
    assert "please fix" in harness.ctx.wake.requests[0]["text"]
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    # Fixed and green; the stopped wake's comment is still on the PR.
    harness.reader.infos[url(7)] = pr_info(7, head="b" * 40, comments=[comment])

    await harness.command("resume", "org/repo/7")

    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("met", "green")
    assert len(harness.ctx.wake.requests) == 1


async def test_a_stopped_reoffer_is_offered_again_under_a_new_key() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    await harness.command("resume", "org/repo/7")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")  # Stops the re-offer's turn too.

    await harness.command("resume", "org/repo/7")

    _, reoffer, again = harness.ctx.wake.requests
    assert "Check failed: lint" in again["text"]
    assert again["dedupe_key"] != reoffer["dedupe_key"]


async def test_a_dropped_waiting_reoffer_comes_back_after_resume() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    await harness.command("resume", "org/repo/7")
    harness.ctx.wake.drop(SESSION)  # A Stop drops the waiting re-offer.
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.command("resume", "org/repo/7")

    assert len(harness.ctx.wake.requests) == 3
    assert "Check failed: lint" in harness.ctx.wake.requests[-1]["text"]


async def test_the_reoffer_never_decides_that_a_goal_is_met() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, mergeable=False)
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    # Mergeability is being recomputed: unknown, after a conflict was reported.
    harness.reader.infos[url(7)] = pr_info(7, mergeable=None)

    await harness.command("resume", "org/repo/7")

    assert harness.goal(7)["status"] != "met"


@pytest.mark.parametrize("delivered", ["by-delivery", "already"])
async def test_another_goals_wake_while_paused_keeps_the_unhandled_events(
    delivered: str,
) -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("pr:org/repo/7", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    if delivered == "already":
        harness.ctx.wake.outcome = "duplicate"  # The service had delivered #9's events.
    await harness.command("pr:org/repo/9", "on")  # A new goal wakes while #7 is paused.
    harness.ctx.wake.outcome = "queued"
    harness.ctx.wake.deliver(SESSION)
    await harness.check()

    await harness.command("resume", "org/repo/7")

    assert len(harness.ctx.wake.requests) == 3
    assert "Check failed: lint" in harness.ctx.wake.requests[-1]["text"]


async def test_two_goals_resumed_one_after_the_other_share_one_reoffer() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.command("resume", "org/repo/7")
    await harness.command("resume", "org/repo/9")

    last = harness.ctx.wake.requests[-1]["text"]
    assert "Check failed: lint" in last and "Check failed: tests" in last


async def test_an_unreadable_recheck_keeps_the_reoffer_for_a_later_pass() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    reader = harness.reader
    calls: list[str] = []

    async def second_read_fails(session_id: str, pr_url: str) -> Any:
        calls.append(pr_url)
        return None if len(calls) == 2 else await Reader.__call__(reader, session_id, pr_url)

    harness.loop = GoalLoop(harness.ctx, PrGreen(second_read_fails), hint_delay_s=0)
    await harness.command("resume", "org/repo/7")
    assert len(harness.ctx.wake.requests) == 1 and harness.goal(7)["reoffer"]

    await harness.check()

    assert "Check failed: lint" in harness.ctx.wake.requests[-1]["text"]


def _fail_reads(harness: Harness, *failing: int) -> None:
    """Make the given reads (1-based, counted from now) fail, as an unreachable host."""
    reader = harness.reader
    calls: list[str] = []

    async def read(session_id: str, pr_url: str) -> Any:
        calls.append(pr_url)
        return None if len(calls) in failing else await Reader.__call__(reader, session_id, pr_url)

    harness.loop = GoalLoop(harness.ctx, PrGreen(read), hint_delay_s=0)


async def test_new_events_wait_for_a_failed_recheck_so_owed_ones_go_with_them() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    _fail_reads(harness, 2)  # Resume's re-check can't read the PR.

    await harness.command("resume", "org/repo/7")
    assert len(harness.ctx.wake.requests) == 1  # No wake without the owed events.
    await harness.check()

    last = harness.ctx.wake.requests[-1]["text"]
    assert "Check failed: lint" in last and "Check failed: tests" in last


async def test_a_recheck_failing_twice_offers_the_events_once_it_reads() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    _fail_reads(harness, 2, 4)
    await harness.command("resume", "org/repo/7")
    await harness.check()
    assert len(harness.ctx.wake.requests) == 1 and harness.goal(7)["reoffer"]

    await harness.check()
    assert "Check failed: lint" in harness.ctx.wake.requests[-1]["text"]
    harness.ctx.wake.deliver(SESSION)
    await harness.check()
    await harness.check()

    assert len(harness.ctx.wake.requests) == 2 and not harness.goal(7)["reoffer"]


async def test_events_reoffered_and_handled_are_not_owed_again() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    await harness.command("resume", "org/repo/7")
    await harness.command("resume", "org/repo/9")
    harness.ctx.wake.deliver(SESSION)  # The re-offer is delivered and handled.
    await harness.check()
    # Later #9 needs work; a person stops the turn of #9's wake.
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    await harness.check()
    harness.ctx.wake.deliver(SESSION)
    await harness.check()
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    asked = len(harness.ctx.wake.requests)

    await harness.command("resume", "org/repo/7")

    assert len(harness.ctx.wake.requests) == asked


async def test_an_agents_stop_owes_nothing_later() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.check()  # #7's wake was handled.
    await harness.loop.on_stop(SESSION, "stopped_by_agent")
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    await harness.check()
    harness.ctx.wake.deliver(SESSION)
    await harness.check()  # #9's wake was delivered, without #7.
    await harness.loop.on_stop(SESSION, "stopped_by_user")  # A Stop of #9's turn.
    asked = len(harness.ctx.wake.requests)

    await harness.command("resume", "org/repo/7")

    assert len(harness.ctx.wake.requests) == asked


async def test_a_goal_left_out_of_the_stopped_wake_owes_nothing() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    assert harness.goal(9)["unhandled"] is False

    await harness.command("resume", "org/repo/9")

    assert harness.goal(9)["reoffers"] == 0


async def test_a_pending_reoffer_survives_another_goals_wake() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    reader = harness.reader
    reads_of_7: list[str] = []
    rechecks_fail = True

    async def flaky_rechecks(session_id: str, pr_url: str) -> Any:
        if pr_url == url(7):
            reads_of_7.append(pr_url)
            if rechecks_fail and len(reads_of_7) % 2 == 0:
                return None
        return await Reader.__call__(reader, session_id, pr_url)

    harness.loop = GoalLoop(harness.ctx, PrGreen(flaky_rechecks), hint_delay_s=0)
    await harness.command("resume", "org/repo/7")
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    await harness.command("resume", "org/repo/9")
    assert "Check failed: lint" not in harness.ctx.wake.requests[-1]["text"]
    harness.ctx.wake.deliver(SESSION)  # #9's wake is delivered while #7 still waits.
    rechecks_fail = False

    await harness.check()

    assert "Check failed: lint" in harness.ctx.wake.requests[-1]["text"]


@pytest.mark.parametrize("left_out", [False, True], ids=["woken", "left-out"])
async def test_a_wake_the_service_already_delivered_counts_for_the_reoffer(
    left_out: bool,
) -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.check()  # #9's wake was handled.
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.ctx.wake.outcome = "duplicate"  # The service had delivered #7's events.
    await harness.check()
    harness.ctx.wake.outcome = "queued"
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.command("resume", "org/repo/9" if left_out else "org/repo/7")

    if left_out:
        assert len(harness.ctx.wake.requests) == 2
    else:
        assert len(harness.ctx.wake.requests) == 3
        assert "Check failed: lint" in harness.ctx.wake.requests[-1]["text"]


async def test_resume_skips_stopped_wake_events_resolved_meanwhile() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    harness.reader.infos[url(7)] = pr_info(7, pending=True)

    await harness.command("resume", "org/repo/7")

    assert len(harness.ctx.wake.requests) == 1
    assert harness.goal(7)["status"] == "watching"


async def test_a_stop_that_drops_a_waiting_wake_offers_nothing_again() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.check()  # Handled: the agent's turn for that wake ended.
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    await harness.check()  # A second wake waits; a person stops their own turn.
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.command("resume", "org/repo/7")

    *_, last = harness.ctx.wake.requests
    assert "Check failed: tests" in last["text"] and "Check failed: lint" not in last["text"]


async def test_resume_only_touches_the_named_paused_goal() -> None:
    harness = Harness(7, 9)
    await harness.command("all", "on")
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.command("resume", "org/repo/9")

    assert (harness.goal(7)["status"], harness.goal(9)["status"]) == ("paused", "watching")
    assert harness.published() == ("watching", "1", "Watching 1 PR · 1 paused")
    # Resuming a goal that isn't paused changes nothing.
    await harness.command("resume", "org/repo/9")
    assert harness.goal(9)["status"] == "watching"


@pytest.mark.parametrize("written_by", ["yolanda@example.com", None], ids=["user", "unnamed"])
async def test_a_resume_applied_later_keeps_the_goals_own_enabler(
    written_by: str | None,
) -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    await harness.command("all", "on", user_id="dana@example.com")
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    await harness.command("resume", "org/repo/7", user_id="xavier@example.com")
    harness.ctx.wake.drop(SESSION)
    # Someone else's Resume of #9 is written, but its command callback is lost;
    # the reconciling pass applies it without knowing who sent it.
    harness.ctx.state.now = 2**40  # Written after Xavier's Resume was recorded.
    await harness.ctx.state.write(SESSION, "resume", "org/repo/9", updated_by=written_by)

    await harness.loop.reconcile_all()

    assert (harness.goal(9)["status"], harness.goal(9)["user"]) == ("unmet", "dana@example.com")
    assert harness.goal(7)["user"] == "xavier@example.com"


async def test_a_single_user_resume_in_the_same_second_is_credited() -> None:
    harness = Harness(7)
    harness.loop = GoalLoop(
        harness.ctx, harness.reader.goal_type(), hint_delay_s=0, clock=lambda: 1000.0
    )
    harness.ctx.state.now = 1000  # The command's write and its record share a second.
    await harness.command("all", "on", user_id=None, generation="g1")
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.command("resume", "org/repo/7", user_id=None, generation="g2")

    assert (harness.goal(7)["status"], harness.goal(7)["generation"]) == ("watching", "g2")


async def test_crossed_resumes_resume_one_goal_for_its_own_enabler() -> None:
    harness = Harness(7, 9)
    await harness.command("all", "on", user_id="dana@example.com")
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    # Alice resumes #7 and Bob #9; both writes land before either callback runs.
    await harness.ctx.state.write(SESSION, "resume", "org/repo/7", updated_by="alice@example.com")
    await harness.ctx.state.write(SESSION, "resume", "org/repo/9", updated_by="bob@example.com")
    await harness.loop.on_command(CommandEvent(SESSION, "resume", user_id="alice@example.com"))
    await harness.loop.on_command(CommandEvent(SESSION, "resume", user_id="bob@example.com"))
    await harness.settle()

    assert (harness.goal(7)["status"], harness.goal(9)["status"]) == ("paused", "watching")
    assert harness.goal(9)["user"] == "dana@example.com"


async def test_resume_leaves_an_ended_goal_ended() -> None:
    harness = Harness(7)
    harness.loop = GoalLoop(harness.ctx, harness.reader.goal_type(), hint_delay_s=0, max_wakes=1)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    await harness.check()
    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("stopped", "budget")

    await harness.command("resume", "org/repo/7", user_id="mallory@example.com")

    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("stopped", "budget")
    assert harness.goal(7)["user"] == "alice@example.com"


async def test_stop_all_ends_a_paused_goal_on_a_session_without_a_host() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    # The host went away; this replica serves the session without one.
    harness.ctx.hosted.discard(SESSION)
    harness.ctx.hostless.add(SESSION)

    await harness.command("stop", "requested")

    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("stopped", "off")
    assert harness.published() == ("stopped", "0", "Goals stopped")


async def test_a_full_session_keeps_its_paused_goals() -> None:
    numbers = range(1, MAX_GOALS + 1)
    harness = Harness(*numbers)
    await harness.command("all", "on")
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    newcomer = MAX_GOALS + 1
    harness.ctx.linked[SESSION].entries.append(Linked(url(newcomer), "org/repo", newcomer))
    harness.reader.infos[url(newcomer)] = pr_info(newcomer, pending=True)

    await harness.check()

    assert {harness.goal(number)["status"] for number in numbers} == {"paused"}
    assert harness.goal(newcomer) == {}


async def test_a_toggle_set_just_before_a_stop_does_not_undo_the_pause() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("pr:org/repo/7", "on")
    harness.ctx.wake.drop(SESSION)
    # Set again (a new version) before any check saw it; then the Stop.
    await harness.ctx.state.write(SESSION, "pr:org/repo/7", "on")
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.check()

    assert harness.goal(7)["status"] == "paused" and len(harness.ctx.wake.requests) == 1
    # A toggle set after the Stop restarts it.
    await harness.command("pr:org/repo/7", "on")
    assert harness.goal(7)["status"] == "unmet" and len(harness.ctx.wake.requests) == 2


@pytest.mark.parametrize(
    ("state", "ended", "published"),
    [
        ("MERGED", ("met", "merged"), ("met", "0", "PR goal met")),
        ("CLOSED", ("stopped", "closed"), ("stopped", "0", "Goals stopped")),
    ],
    ids=["merged", "closed"],
)
async def test_a_paused_goal_on_a_finished_pr_ends_without_reading_it(
    state: str, ended: tuple[str, str], published: tuple[str, str, str]
) -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    harness.ctx.linked[SESSION].entries[0].state = state
    harness.reader.reads.clear()

    await harness.check()

    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ended
    assert harness.published() == published
    assert harness.reader.reads == []


async def test_a_stop_that_meets_a_concurrent_write_is_retried() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    state = harness.ctx.state
    write = state.write
    raced: list[str] = []

    async def racing_write(session_id: str, key: str, value: Any, **kwargs: Any) -> Any:
        if key == goal_key(url(7)) and not raced:
            raced.append(key)
            current = await state.read(session_id, key)
            await write(session_id, key, current.value)  # Another writer gets there first.
        return await write(session_id, key, value, **kwargs)

    state.write = racing_write  # type: ignore[method-assign]
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    assert raced and harness.goal(7)["status"] == "paused"


async def test_a_pause_survives_a_restart() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    harness.ctx.wake = FakeWake()  # The wake service's memory is lost.
    harness.loop = GoalLoop(harness.ctx, harness.reader.goal_type(), hint_delay_s=0)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))

    await harness.loop.reconcile_all()

    assert harness.goal(7)["status"] == "paused"
    assert harness.published() == ("paused", "0", "PR goal paused")
    assert harness.ctx.wake.requests == []


@pytest.mark.parametrize("seen", [False, True], ids=["before-a-check", "after-a-check"])
async def test_a_stop_of_a_delivered_wakes_turn_pauses_and_counts_the_wake(seen: bool) -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    if seen:
        await harness.check()  # The loop already counted the delivered wake.

    await harness.loop.on_stop(SESSION, "stopped_by_user")

    assert (harness.goal(7)["status"], harness.goal(7)["wakes"]) == ("paused", 1)
    assert (harness.goal(7)["pending"], len(harness.goal(7)["state"]["f"])) == (None, 1)
    assert harness.goal(9)["status"] == "paused"


async def test_turning_a_paused_goal_off_or_stopping_all_ends_it() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.command("pr:org/repo/7", "off")
    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("stopped", "off")
    assert harness.published() == ("paused", "0", "PR goal paused")

    await harness.command("stop", "requested")
    assert (harness.goal(9)["status"], harness.goal(9)["reason"]) == ("stopped", "off")
    assert harness.published() == ("stopped", "0", "Goals stopped")


@pytest.mark.parametrize("reason", ["not_authorized", "undeliverable", "session_gone"])
async def test_other_wake_stops_end_the_goals(reason: str) -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")

    await harness.loop.on_stop(SESSION, reason)

    assert {harness.goal(7)["reason"], harness.goal(9)["reason"]} == {reason}
    assert harness.published() == ("stopped", "0", "Goals stopped")
    await harness.check()
    assert len(harness.ctx.wake.requests) == 1


async def test_not_authorized_at_request_time_stops_the_goals() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.ctx.wake.outcome = "not_authorized"

    await harness.command("all", "on")

    assert harness.goal(7)["reason"] == "not_authorized"


async def test_stop_all_turns_everything_off() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    await harness.command("pr:org/repo/9", "on")

    await harness.command("stop", "requested", command_id="desidero.goal-loop.stop")

    assert (harness.field("all"), harness.field("pr:org/repo/9"), harness.field("stop")) == (
        None,
        None,
        None,
    )
    assert SESSION in harness.ctx.wake.cancelled
    assert {harness.goal(7)["reason"], harness.goal(9)["reason"]} == {"off"}
    assert harness.published()[0] == "stopped"

    # Turning "All" on again restarts the goals.
    await harness.command("all", "on")
    assert harness.goal(7)["status"] == "unmet" and harness.goal(9)["status"] == "watching"


async def test_stop_all_on_a_session_without_a_host_applies_at_once() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    harness.ctx.hosted.clear()
    harness.ctx.hostless.add(SESSION)

    await harness.command("stop", "requested", command_id="desidero.goal-loop.stop")

    assert harness.goal(7)["reason"] == "off"
    assert harness.published() == ("stopped", "0", "Goals stopped")
    assert harness.field("stop") is None


async def test_stop_all_from_another_replica_is_applied_by_the_owner() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    harness.ctx.hosted.clear()  # This replica doesn't hold the session's host.

    await harness.command("stop", "requested", command_id="desidero.goal-loop.stop")

    # Only the toggles are cleared here; the goals belong to the owner.
    assert harness.field("all") is None and harness.field("stop") == "requested"
    assert harness.goal(7)["status"] == "watching"

    harness.ctx.hosted.add(SESSION)  # The owner's next check.
    await harness.check()
    assert harness.goal(7)["reason"] == "off" and harness.field("stop") is None


async def test_one_pr_can_be_left_out_of_all_and_turned_back_on() -> None:
    harness = Harness(7, 9)
    await harness.command("all", "on")
    await harness.command("pr:org/repo/9", "off", command_id="desidero.goal-loop.pr")

    assert harness.goal(9)["reason"] == "off"
    assert harness.goal(7)["status"] == "watching"
    assert harness.published() == ("watching", "1", "Watching 1 PR")

    await harness.command("pr:org/repo/9", "on", command_id="desidero.goal-loop.pr")
    assert harness.goal(9)["status"] == "watching"


async def test_only_the_toggled_pr_is_watched_without_all() -> None:
    harness = Harness(7, 9)
    await harness.command("pr:org/repo/9", "on", command_id="desidero.goal-loop.pr")

    assert harness.goal(7) == {} and harness.goal(9)["status"] == "watching"
    view = json.loads(harness.field("goals") or "{}")
    assert [(item["id"], item["toggle"]) for item in view["items"]] == [
        ("org/repo/7", ""),
        ("org/repo/9", "on"),
    ]


async def test_the_per_goal_budget_stops_it() -> None:
    harness = Harness(7)
    harness.loop = GoalLoop(harness.ctx, harness.reader.goal_type(), max_wakes=1)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.check()

    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",), head="b" * 40)
    await harness.check()

    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("stopped", "budget")
    assert len(harness.ctx.wake.requests) == 1


async def test_a_goal_without_a_recorded_enabler_is_stopped() -> None:
    harness = Harness(7)
    # The command committed but its callback never ran.
    await harness.ctx.state.write(SESSION, "all", "on")

    await harness.check()

    assert harness.goal(7)["reason"] == "no_enabler"
    assert harness.ctx.wake.requests == []
    view = json.loads(harness.field("goals") or "{}")
    assert view["all"] is True and view["enabled"] is False


async def test_sessions_without_a_host_here_are_not_checked() -> None:
    harness = Harness(7)
    harness.ctx.hosted.clear()

    await harness.command("all", "on")

    assert harness.reader.reads == [] and harness.goal(7) == {}
    assert harness.published() == ("watching", "0", "Watching for PRs")


async def test_an_unreachable_pr_is_enrolled_once_it_can_be_read() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = None
    await harness.command("all", "on")
    assert harness.goal(7) == {}

    harness.reader.infos[url(7)] = pr_info(7, pending=True)
    await harness.check()
    assert harness.goal(7)["status"] == "watching"


async def test_already_merged_prs_end_quietly() -> None:
    harness = Harness(7, 9)
    harness.ctx.linked[SESSION].entries[1].state = "MERGED"
    await harness.command("all", "on")

    assert (harness.goal(9)["reason"], harness.goal(9)["quiet"]) == ("closed", True)
    assert url(9) not in harness.reader.reads
    assert harness.published() == ("watching", "1", "Watching 1 PR")


async def test_an_idle_edge_checks_a_known_session_soon() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    reads = len(harness.reader.reads)

    await harness.loop.on_status(Observation(SESSION, "running", "idle"))
    await harness.loop.on_status(Observation("other", "running", "idle"))
    await harness.loop.on_status(Observation(SESSION, "idle", "running"))
    await harness.settle()

    assert len(harness.reader.reads) == reads + 1


async def test_reconcile_walks_every_session_with_state() -> None:
    harness = Harness(7)
    await harness.ctx.state.write(SESSION, "all", "on")
    await harness.ctx.state.write(SESSION, "enablers", json.dumps({"all": {"user": None}}))

    await harness.loop.reconcile_all()

    assert harness.goal(7)["status"] == "watching"


async def test_start_registers_callbacks_and_the_reconciler() -> None:
    harness = Harness()
    harness.loop.start()
    try:
        assert harness.ctx.command_callbacks and harness.ctx.status_callbacks
        assert harness.ctx.wake.stop_callbacks
        assert [task.get_name() for task in harness.ctx.tasks] == ["goal-loop-reconcile"]
    finally:
        for task in harness.ctx.tasks:
            task.cancel()
        await asyncio.gather(*harness.ctx.tasks, return_exceptions=True)


# ── Delivery bookkeeping, errors and limits ───────────────────


async def test_a_wake_delivered_during_a_check_is_committed_before_asking_again() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    reader = harness.reader

    async def deliver_during_read(session_id: str, pr_url: str) -> dict[str, Any] | None:
        harness.ctx.wake.deliver(SESSION)  # The first wake lands mid-check.
        harness.loop._type._read = reader  # type: ignore[attr-defined]
        return await reader(session_id, pr_url)

    harness.loop._type._read = deliver_during_read  # type: ignore[attr-defined]
    await harness.check()

    # Its events are committed; nothing is asked for in this pass.
    assert len(harness.ctx.wake.requests) == 1
    assert (harness.goal(7)["wakes"], harness.goal(7)["pending"]) == (1, None)

    await harness.check()
    [_, second] = harness.ctx.wake.requests
    assert "Check failed: tests" in second["text"] and "Check failed: lint" not in second["text"]

    # That wake is dropped by a Stop: its event must not count as reported.
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    await harness.check()
    assert len(harness.goal(7)["state"]["f"]) == 1


async def test_one_unreadable_pr_does_not_stop_the_others() -> None:
    harness = Harness(7, 9)
    await harness.command("all", "on")
    reader = harness.reader

    async def times_out_for_9(session_id: str, pr_url: str) -> dict[str, Any] | None:
        if pr_url == url(9):
            raise TimeoutError("30 s")
        return await reader(session_id, pr_url)

    harness.loop._type._read = times_out_for_9  # type: ignore[attr-defined]
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.check()

    assert harness.goal(7)["status"] == "unmet" and harness.goal(9)["status"] == "watching"
    assert len(harness.ctx.wake.requests) == 1


async def test_a_huge_failure_list_still_fits_one_wake() -> None:
    harness = Harness(*range(1, 21))
    names = tuple(f"job-{n:03d}-{'x' * 200}" for n in range(300))
    for number in range(1, 21):
        harness.reader.infos[url(number)] = pr_info(number, failing=names)

    await harness.command("all", "on")

    [wake] = harness.ctx.wake.requests
    assert len(wake["text"]) <= 8_000
    assert (
        "…and 285 more" in wake["text"]
        and "more pull requests also need attention" in wake["text"]
    )


async def test_the_service_budget_pauses_instead_of_ending_goals() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.ctx.wake.outcome = "budget_spent"
    await harness.command("all", "on")
    assert harness.goal(7)["status"] == "unmet"

    harness.ctx.wake.outcome = "queued"
    await harness.check()
    assert len(harness.ctx.wake.requests) == 1  # Paused: the same events wait.
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    await harness.check()
    assert len(harness.ctx.wake.requests) == 2


@pytest.mark.parametrize("reason", ["stopped_by_agent", "budget_spent"])
async def test_wake_stops_that_pause(reason: str) -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.drop(SESSION)

    await harness.loop.on_stop(SESSION, reason)
    await harness.check()

    assert harness.goal(7)["status"] == "unmet" and len(harness.ctx.wake.requests) == 1
    # Only the same events are held back: new ones are reported.
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    await harness.check()
    assert len(harness.ctx.wake.requests) == 2


async def test_a_duplicate_means_the_events_were_delivered() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.ctx.wake.outcome = "duplicate"

    await harness.command("all", "on")

    assert (harness.goal(7)["wakes"], harness.goal(7)["pending"]) == (1, None)
    assert len(harness.goal(7)["state"]["f"]) == 1


async def test_wakes_ask_the_service_for_its_largest_budget() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    assert harness.ctx.wake.requests[0]["max_wakes"] == 50


async def test_stop_all_then_turning_all_on_restarts_every_goal() -> None:
    harness = Harness(7)
    harness.loop = GoalLoop(harness.ctx, harness.reader.goal_type(), max_wakes=1)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.deliver(SESSION)
    await harness.check()
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",), head="b" * 40)
    await harness.check()
    assert harness.goal(7)["reason"] == "budget"

    harness.ctx.state.now += 1
    await harness.command("stop", "requested", command_id="desidero.goal-loop.stop")
    harness.ctx.state.now += 1
    await harness.command("all", "on")

    assert harness.goal(7)["status"] == "unmet"


async def test_a_toggle_set_after_stop_all_survives_it() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    harness.ctx.hosted.clear()
    harness.ctx.state.now += 1
    # Stop runs elsewhere and its callback never ran; then all is turned on again.
    await harness.ctx.state.write(SESSION, "stop", "requested")
    harness.ctx.state.now += 1
    await harness.command("all", "on")
    harness.ctx.hosted.add(SESSION)

    await harness.check()

    assert harness.field("stop") is None and harness.field("all") == "on"
    assert harness.goal(7)["status"] == "watching"


async def test_a_goal_changed_by_another_writer_is_not_overwritten() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    key = goal_key(url(7))
    reader = harness.reader

    async def stop_elsewhere(session_id: str, pr_url: str) -> dict[str, Any] | None:
        stopped = {**harness.goal(7), "status": "stopped", "reason": "off"}
        await harness.ctx.state.write(SESSION, key, json.dumps(stopped))
        return await reader(session_id, pr_url)

    harness.loop._type._read = stop_elsewhere  # type: ignore[attr-defined]
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.check()

    assert harness.goal(7)["status"] == "stopped"


async def test_each_goal_keeps_the_enabler_of_its_toggle() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.reader.infos[url(9)] = pr_info(9, failing=("lint",))
    await harness.command("pr:org/repo/7", "on", user_id="alice@example.com")
    await harness.command("pr:org/repo/9", "on", user_id="bob@example.com", generation="g2")
    assert harness.goal(7)["user"] == "alice@example.com"
    assert harness.goal(9)["user"] == "bob@example.com"
    [alice] = harness.ctx.wake.requests
    assert alice["on_behalf_of"] == "alice@example.com" and "#9" not in alice["text"]

    # One wake at a time: Bob's follows once Alice's is delivered.
    harness.ctx.wake.deliver(SESSION)
    await harness.check()
    bob = harness.ctx.wake.requests[-1]
    assert (bob["on_behalf_of"], bob["generation"]) == ("bob@example.com", "g2")
    assert "#9" in bob["text"] and "#7" not in bob["text"]

    # Bob loses access: only his goal ends.
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "not_authorized")
    assert harness.goal(9)["reason"] == "not_authorized"
    assert harness.goal(7)["status"] == "unmet"


async def test_the_enabler_comes_from_the_command_not_a_later_value() -> None:
    harness = Harness(7)
    await harness.ctx.state.write(SESSION, "all", "on")
    await harness.ctx.state.write(SESSION, "all", "off")  # Someone else, meanwhile.
    await harness.loop.on_command(CommandEvent(SESSION, "all"))

    assert json.loads(harness.field("enablers") or "{}")["all"]["user"] == "alice@example.com"


async def test_ended_goals_make_room_for_new_prs() -> None:
    harness = Harness(*range(1, 27))
    for number in range(1, 26):
        harness.reader.infos[url(number)] = pr_info(number)  # Green: met at once.
    harness.ctx.linked[SESSION].entries.pop()  # #26 is linked later.
    await harness.command("all", "on")
    assert len([k for k in harness.ctx.state.rows[SESSION] if k.startswith("g:")]) == 25

    harness.ctx.linked[SESSION].entries.append(Linked(url(26), "org/repo", 26))
    await harness.check()

    goals = [k for k in harness.ctx.state.rows[SESSION] if k.startswith("g:")]
    assert len(goals) == 25 and harness.goal(26)["status"] == "watching"


async def test_the_view_fits_one_state_value() -> None:
    harness = Harness()
    long_repo = "o" * 39 + "/" + "r" * 100
    numbers = range(100_000_000, 100_000_025)
    pr_urls = {n: f"https://github.com/{long_repo}/pull/{n}" for n in numbers}
    harness.ctx.linked[SESSION] = LinkedList(
        [Linked(pr_urls[n], long_repo, n, title="🚀" * 200) for n in numbers]
    )
    for number in numbers:  # Already merged: each goal ends with a note.
        harness.reader.infos[pr_urls[number]] = pr_info(
            number, state="MERGED", url=pr_urls[number]
        )

    await harness.command("all", "on")

    assert len((harness.field("goals") or "").encode()) <= 16_000


async def test_reconcile_skips_sessions_whose_host_is_elsewhere() -> None:
    harness = Harness(7)
    await harness.ctx.state.write(SESSION, "all", "on")
    await harness.ctx.state.write(SESSION, "enablers", json.dumps({"all": {"user": None}}))
    harness.ctx.hosted.clear()
    harness.ctx.hostless.add(SESSION)  # Without a host, every replica "serves" it.

    await harness.loop.reconcile_all()

    assert harness.reader.reads == [] and harness.goal(7) == {}


async def test_idle_edges_without_a_persisted_status_are_ignored() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    reads = len(harness.reader.reads)

    await harness.loop.on_status(Observation(SESSION, "running", "idle", persist_requested=False))
    await harness.settle()

    assert len(harness.reader.reads) == reads


async def test_the_wake_text_cache_is_dropped_when_no_goal_runs() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    assert harness.loop._type._heads  # type: ignore[attr-defined]

    harness.reader.infos[url(7)] = pr_info(7)
    await harness.check()

    assert harness.goal(7)["status"] == "met"
    assert not harness.loop._type._heads  # type: ignore[attr-defined]


# ── Several enablers, races with the wake service, limits ─────


async def _two_enablers(harness: Harness) -> tuple[int, int]:
    """Alice turns on #9 and Bob #7; returns (checked first, checked second)."""
    await harness.command("pr:org/repo/9", "on", user_id="alice@example.com")
    await harness.command("pr:org/repo/7", "on", user_id="bob@example.com")
    first = min((7, 9), key=lambda number: goal_key(url(number)))
    return first, 16 - first


async def test_a_persons_stop_pauses_every_enablers_goals() -> None:
    harness = Harness(7, 9)
    first, other = await _two_enablers(harness)
    harness.reader.infos[url(first)] = pr_info(first, failing=("lint",))
    await harness.check()
    harness.ctx.wake.deliver(SESSION)  # The first enabler's wake starts a turn.
    await harness.check()
    harness.reader.infos[url(other)] = pr_info(other, failing=("tests",))
    await harness.check()  # The other's wake waits behind that turn.
    assert len(harness.ctx.wake.requests) == 2
    harness.ctx.wake.drop(SESSION)

    await harness.loop.on_stop(SESSION, "stopped_by_user")

    assert (harness.goal(first)["status"], harness.goal(other)["status"]) == ("paused", "paused")
    assert harness.published() == ("paused", "0", "PR goals paused")
    harness.reader.infos[url(first)] = pr_info(first, failing=("lint", "tests"))
    harness.reader.infos[url(other)] = pr_info(other, failing=("tests", "docs"))
    await harness.check()
    assert len(harness.ctx.wake.requests) == 2


async def test_another_enablers_outstanding_wake_is_not_replaced() -> None:
    harness = Harness(7, 9)
    first, other = await _two_enablers(harness)
    harness.reader.infos[url(first)] = pr_info(first, failing=("lint",))
    await harness.check()
    harness.reader.infos[url(other)] = pr_info(other, failing=("tests",))
    harness.reader.infos[url(first)] = pr_info(first, pending=True, head="b" * 40)

    await harness.check()

    assert len(harness.ctx.wake.requests) == 1  # Waits for the first wake to resolve.


async def test_a_wake_delivered_while_the_next_is_asked_for_does_not_commit_it() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    wake = harness.ctx.wake
    request = wake.request

    async def deliver_first_meanwhile(session_id: str, text: str, **kwargs: Any) -> str:
        wake.deliver(session_id)  # The first wake lands during the authorization check.
        return await request(session_id, text, **kwargs)

    wake.request = deliver_first_meanwhile  # type: ignore[method-assign]
    await harness.check()
    wake.request = request  # type: ignore[method-assign]
    await harness.check()

    assert wake.statuses[SESSION].pending
    assert harness.goal(7)["pending"] is not None and len(harness.goal(7)["state"]["f"]) < 2


async def test_a_duplicate_of_a_pending_wake_is_still_outstanding() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    reader = harness.reader

    async def another_writer(session_id: str, pr_url: str) -> dict[str, Any] | None:
        # Someone writes the loop record mid-check, so this pass saves nothing.
        await harness.ctx.state.write(SESSION, "loop", harness.field("loop") or "{}")
        harness.loop._type._read = reader  # type: ignore[attr-defined]
        return await reader(session_id, pr_url)

    harness.loop._type._read = another_writer  # type: ignore[attr-defined]
    await harness.command("all", "on")  # Asks for the wake, then saves nothing.
    assert len(harness.ctx.wake.requests) == 1
    harness.ctx.wake.outcome = "duplicate"  # The service still holds that wake.

    await harness.check()

    assert harness.ctx.wake.statuses[SESSION].pending
    assert harness.goal(7)["wakes"] == 0 and harness.goal(7)["pending"] is not None


async def test_stop_all_covers_toggles_set_in_the_same_second() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    # "Stop all" commits in the same second, and its callback never runs.
    await harness.ctx.state.write(SESSION, "stop", "requested")

    await harness.check()
    await harness.check()

    assert harness.field("all") is None
    assert (harness.goal(7)["status"], harness.goal(7)["reason"]) == ("stopped", "off")


async def test_a_replaced_wake_clears_the_pending_state_of_goals_it_no_longer_covers() -> None:
    harness = Harness(7, 9)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    assert harness.goal(7)["pending"] is not None

    # #7's failure is gone before the wake went out; #9 now fails.
    harness.reader.infos[url(7)] = pr_info(7, pending=True, head="b" * 40)
    harness.reader.infos[url(9)] = pr_info(9, failing=("tests",))
    await harness.check()

    assert harness.goal(7)["pending"] is None and harness.goal(9)["pending"] is not None


async def test_a_pr_unlinked_and_linked_again_is_watched_again() -> None:
    harness = Harness(7)
    await harness.command("all", "on")
    linked = harness.ctx.linked[SESSION].entries
    removed = linked.pop()
    await harness.check()
    assert harness.goal(7)["reason"] == "off"

    linked.append(removed)
    await harness.check()

    assert harness.goal(7)["status"] == "watching"


async def test_wake_text_has_a_backstop_below_the_service_limit() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    harness.loop._type.wake_text = lambda _session, _items: "x" * 20_000  # type: ignore[method-assign]

    await harness.command("all", "on")

    assert len(harness.ctx.wake.requests[0]["text"]) <= 15_000


async def test_the_view_drops_titles_then_notes_to_fit() -> None:
    long_repo = "o" * 39 + "/" + "r" * 100
    goals: dict[str, Goal] = {}
    targets = []
    for number in range(100_000_000, 100_000_025):
        target = Target(
            id=f"{long_repo}/{number}",
            url=f"https://github.com/{long_repo}/pull/{number}",
            title="🚀" * 120,
            label=f"#{number}",
        )
        targets.append(target)
        goals[goal_key(target.url)] = Goal("pr-green", target, status="stopped", note="n" * 80)

    with_notes = json.loads(view_text(_Snapshot({}, goals=goals), targets))
    assert {item["title"] for item in with_notes["items"]} == {""}
    assert with_notes["items"][0]["note"] == "n" * 80

    for goal in goals.values():
        goal.note = "n" * 800
    trimmed = view_text(_Snapshot({}, goals=goals), targets)
    assert len(trimmed.encode()) <= 16_000
    assert {item["note"] for item in json.loads(trimmed)["items"]} == {""}
    assert len(json.loads(trimmed)["items"]) == 25


async def test_enablers_take_turns_when_one_stays_busy() -> None:
    harness = Harness(7, 9)
    first, other = await _two_enablers(harness)
    harness.reader.infos[url(other)] = pr_info(other, failing=("tests",))
    for push in range(6):
        # The first enabler's PR fails again on every push, before every check.
        harness.reader.infos[url(first)] = pr_info(first, failing=("lint",), head=f"{push:x}" * 40)
        await harness.check()
        if harness.ctx.wake.statuses[SESSION].pending:
            harness.ctx.wake.deliver(SESSION)

    woken = [request["on_behalf_of"] for request in harness.ctx.wake.requests]
    patient = "alice@example.com" if other == 9 else "bob@example.com"
    # The other enabler's one failure is reported next, not after the busy PR settles.
    assert woken[1] == patient and woken.count(patient) == 1 and len(woken) == 6


async def test_a_new_wake_for_a_held_back_enabler_clears_the_hold() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_agent")
    assert json.loads(harness.field("loop") or "{}")["paused"]

    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    await harness.check()

    assert len(harness.ctx.wake.requests) == 2
    assert json.loads(harness.field("loop") or "{}")["paused"] == {}
