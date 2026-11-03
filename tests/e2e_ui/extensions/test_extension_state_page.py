"""An extension page runs commands and reads its session state through the browser SDK.

The test package's page is a real bundle in a sandboxed iframe: its calls go
through the SDK, the host RPC and the server's state routes with the viewer's
credentials. Its header action shows a published field as its label.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, FrameLocator, Page, expect

from tests._helpers.extensions import extension_server, install_extension_packages
from tests.e2e_ui.collaboration._multi_user_server import create_user_session

_PACKAGE = Path(__file__).resolve().parent / "packages" / "state-page"
_EXTENSION_ID = "omnigent-test.state-page"
_ENABLED = {_EXTENSION_ID: {"enabled": True}}


@pytest.fixture(scope="module")
def state_packages(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return install_extension_packages([_PACKAGE], tmp_path_factory.mktemp("ext") / "packages")


@pytest.fixture
def enabled_server(built_spa: None, state_packages: Path, tmp_path: Path) -> Iterator[str]:
    with extension_server(tmp_path / "enabled", state_packages, extensions=_ENABLED) as base_url:
        yield base_url


def _open_page(page: Page, base_url: str, session_id: str) -> FrameLocator:
    page.goto(f"{base_url}/extensions/{_EXTENSION_ID}/goals?conversationId={session_id}")
    frame = page.frame_locator("iframe[title='State page']")
    expect(frame.locator("#watch")).to_be_visible()
    return frame


def _result(frame: FrameLocator, button: str) -> object:
    frame.locator("#result").evaluate("node => { node.textContent = '' }")
    frame.locator(f"#{button}").click()
    expect(frame.locator("#result")).not_to_have_text("")
    text = frame.locator("#result").text_content() or ""
    return text if text.startswith("error:") else json.loads(text)


def test_page_runs_commands_and_reads_state_as_the_viewer(page: Page, enabled_server: str) -> None:
    session_id = create_user_session(enabled_server, headers={}, metadata={"title": "Goals"})
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{enabled_server}/c/{session_id}")
    action = page.get_by_test_id(f"extension-slot-chat-header-{_EXTENSION_ID}.header-action")
    # Nothing published yet: the action is an icon button.
    expect(action).to_have_accessible_name("Goals")
    action.click()
    frame = page.frame_locator("iframe[title='State page']")

    # The page's own session is the default for commands and reads.
    assert _result(frame, "watch") == {"value": "watching", "keys": ["pr:7"]}
    assert _result(frame, "summarize") == {"summary": "Watching 2 PRs"}
    session = httpx.get(f"{enabled_server}/v1/sessions/{session_id}", timeout=10).json()
    assert session["published_fields"] == {_EXTENSION_ID: {"summary": "Watching 2 PRs"}}

    page.goto(f"{enabled_server}/c/{session_id}")
    labelled = page.get_by_test_id(f"extension-slot-chat-header-{_EXTENSION_ID}.header-action")
    expect(labelled).to_have_text("Watching 2 PRs")
    expect(labelled).to_have_accessible_name("Goals: Watching 2 PRs")


def test_a_read_only_viewer_runs_only_read_commands(
    browser: Browser, built_spa: None, state_packages: Path, tmp_path: Path
) -> None:
    owner = {"X-Forwarded-Email": "owner@ui.test"}
    viewer = {"X-Forwarded-Email": "viewer@ui.test"}
    with extension_server(
        tmp_path / "multi-user",
        state_packages,
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

        context = browser.new_context(
            extra_http_headers=viewer, viewport={"width": 1280, "height": 900}
        )
        frame = _open_page(context.new_page(), base_url, session_id)

        # `watch` needs read access; `summarize` needs edit, which the server refuses.
        assert _result(frame, "watch") == {"value": "watching", "keys": ["pr:7"]}
        assert _result(frame, "summarize") == "error:PermissionDenied"
        context.close()
