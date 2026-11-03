"""The goal loop against a fake extension context: enrol, wake, commit, stop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from desidero_goal_loop.goals import Target
from desidero_goal_loop.loop import Goal, GoalLoop, _Snapshot, goal_key, view_text

from tests.extensions.goal_loop.fakes import (
    SESSION,
    CommandEvent,
    FakeContext,
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
        await self.ctx.state.write(SESSION, key, value)
        await self.loop.on_command(CommandEvent(SESSION, key, **event))
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
    assert harness.goal(7)["note"].startswith("#7 is green")
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


async def test_a_person_stopping_the_session_pauses_until_something_new() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")

    await harness.check()
    assert len(harness.ctx.wake.requests) == 1
    assert harness.goal(7)["status"] == "unmet"

    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    await harness.check()
    assert len(harness.ctx.wake.requests) == 2


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


async def test_a_paused_enabler_does_not_hold_back_another() -> None:
    harness = Harness(7, 9)
    first, other = await _two_enablers(harness)
    harness.reader.infos[url(first)] = pr_info(first, failing=("lint",))
    await harness.check()
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")  # Pauses the first enabler's wake.

    harness.reader.infos[url(other)] = pr_info(other, failing=("tests",))
    await harness.check()

    paused, woken = harness.ctx.wake.requests
    assert f"#{other} needs attention" in woken["text"]
    assert woken["on_behalf_of"] != paused["on_behalf_of"]
    # The first enabler stays paused until its PR changes.
    harness.ctx.wake.deliver(SESSION)
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


async def test_a_new_wake_for_a_paused_enabler_clears_the_pause() -> None:
    harness = Harness(7)
    harness.reader.infos[url(7)] = pr_info(7, failing=("lint",))
    await harness.command("all", "on")
    harness.ctx.wake.drop(SESSION)
    await harness.loop.on_stop(SESSION, "stopped_by_user")
    assert json.loads(harness.field("loop") or "{}")["paused"]

    harness.reader.infos[url(7)] = pr_info(7, failing=("lint", "tests"))
    await harness.check()

    assert len(harness.ctx.wake.requests) == 2
    assert json.loads(harness.field("loop") or "{}")["paused"] == {}
