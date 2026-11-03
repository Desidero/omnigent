"""The goal-loop extension, installed as a wheel, through a real server and browser.

Its Goals page turns on "All PRs in this session" through a declared command;
the composer action then shows the published summary as its label and the
session row shows the goal badge. "Stop all goals" in the row menu clears both.
The session has no linked PRs and no host, so nothing is read or woken here.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from tests._helpers.extensions import extension_server, install_extension_packages
from tests._helpers.polling import poll_until
from tests.e2e_ui.collaboration._multi_user_server import create_user_session

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE = _REPO_ROOT / "ext-demo" / "extensions" / "goal-loop"
_EXTENSION_ID = "desidero.goal-loop"
_COMPOSER = f"extension-slot-chat-composer-{_EXTENSION_ID}.composer"
_ENABLED = {_EXTENSION_ID: {"enabled": True}}


@pytest.fixture(scope="module")
def goal_packages(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return install_extension_packages([_PACKAGE], tmp_path_factory.mktemp("ext") / "packages")


@pytest.fixture
def goal_server(built_spa: None, goal_packages: Path, tmp_path: Path) -> Iterator[str]:
    with extension_server(tmp_path / "enabled", goal_packages, extensions=_ENABLED) as base_url:
        yield base_url


def _row(page: Page, session_id: str) -> Locator:
    return page.locator(f'li[data-sidebar-session-id="{session_id}"]')


def _published(base_url: str, session_id: str) -> dict[str, str]:
    session = httpx.get(f"{base_url}/v1/sessions/{session_id}", timeout=10).json()
    return session.get("published_fields", {}).get(_EXTENSION_ID, {})


def test_composer_action_page_badge_and_stop_all(page: Page, goal_server: str) -> None:
    session_id = create_user_session(goal_server, headers={}, metadata={"title": "Fix login"})
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{goal_server}/c/{session_id}")

    action = page.get_by_test_id(_COMPOSER)
    expect(action).to_have_accessible_name("Goals")
    expect(_row(page, session_id).get_by_test_id("session-row-decorations")).to_have_count(0)
    action.click()

    frame = page.frame_locator("iframe[title='Goals']")
    expect(frame.get_by_text("This session has no linked pull requests yet.")).to_be_visible()
    frame.get_by_label("All PRs in this session").check()
    poll_until(
        lambda: _published(goal_server, session_id).get("summary") == "Watching for PRs",
        timeout_s=10,
    )
    assert _published(goal_server, session_id)["goal"] == "watching"

    page.goto(f"{goal_server}/c/{session_id}")
    labelled = page.get_by_test_id(_COMPOSER)
    expect(labelled).to_have_text("Watching for PRs")
    expect(labelled).to_have_accessible_name("Goals: Watching for PRs")
    row = _row(page, session_id)
    expect(row.get_by_role("img", name="Goal: Watching")).to_be_visible()

    row.hover()
    row.get_by_test_id("conversation-actions").click()
    page.get_by_test_id(f"session-row-menu-{_EXTENSION_ID}.stop-menu").click()
    page.get_by_test_id("extension-command-confirm").click()

    expect(row.get_by_test_id("session-row-decorations")).to_have_count(0)
    poll_until(lambda: _published(goal_server, session_id) == {}, timeout_s=10)
    page.goto(f"{goal_server}/c/{session_id}")
    expect(page.get_by_test_id(_COMPOSER)).to_have_accessible_name("Goals")


def test_a_read_only_viewer_sees_goals_without_controls(
    browser: Browser, built_spa: None, goal_packages: Path, tmp_path: Path
) -> None:
    owner = {"X-Forwarded-Email": "owner@ui.test"}
    viewer = {"X-Forwarded-Email": "viewer@ui.test"}
    with extension_server(
        tmp_path / "multi-user",
        goal_packages,
        extensions=_ENABLED,
        env={"OMNIGENT_LOCAL_SINGLE_USER": None},
    ) as base_url:
        session_id = create_user_session(base_url, headers=owner, metadata={"title": "Shared"})
        httpx.put(
            f"{base_url}/v1/sessions/{session_id}/permissions",
            json={"user_id": viewer["X-Forwarded-Email"], "level": 1},
            headers=owner,
            timeout=10,
        ).raise_for_status()
        command = f"{base_url}/v1/sessions/{session_id}/extensions/{_EXTENSION_ID}/commands"
        httpx.post(
            f"{command}/{_EXTENSION_ID}.all",
            json={"arguments": {"mode": "on"}},
            headers=owner,
            timeout=10,
        ).raise_for_status()

        context = browser.new_context(
            extra_http_headers=viewer, viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()
        page.goto(f"{base_url}/extensions/{_EXTENSION_ID}/goals?conversationId={session_id}")
        frame = page.frame_locator("iframe[title='Goals']")

        expect(
            frame.get_by_text("People who can edit this session can change its goals.")
        ).to_be_visible()
        expect(frame.get_by_label("All PRs in this session")).to_be_checked()
        expect(frame.get_by_label("All PRs in this session")).to_be_disabled()
        expect(frame.get_by_role("button", name="Stop all goals")).to_have_count(0)
        expect(frame.get_by_text("You need edit access", exact=False)).to_have_count(0)
        context.close()
