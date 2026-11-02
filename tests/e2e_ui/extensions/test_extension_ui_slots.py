"""Packaged extension UI slots through a real server and browser.

The hello-page reference extension is built and installed as a wheel. Slot
items appear only after the operator enables it, lead to its isolated page
with the session's context, and core settings survive a failed catalog.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests._helpers.extensions import extension_server, install_extension_packages
from tests.e2e_ui.collaboration._multi_user_server import create_user_session

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HELLO_PAGE = _REPO_ROOT / "examples" / "extensions" / "hello-page"
_EXTENSION_ID = "omnigent.hello-page"


@pytest.fixture(scope="module")
def hello_page_packages(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return install_extension_packages([_HELLO_PAGE], tmp_path_factory.mktemp("ext") / "packages")


@pytest.fixture
def enabled_server(built_spa: None, hello_page_packages: Path, tmp_path: Path) -> Iterator[str]:
    with extension_server(
        tmp_path / "enabled",
        hello_page_packages,
        extensions={_EXTENSION_ID: {"enabled": True}},
    ) as base_url:
        yield base_url


def test_installed_extension_keeps_pages_but_not_slots_until_enabled(
    page: Page, built_spa: None, hello_page_packages: Path, tmp_path: Path
) -> None:
    with extension_server(tmp_path / "installed", hello_page_packages) as base_url:
        session_id = create_user_session(base_url, headers={}, metadata={"title": "Slots"})
        page.goto(f"{base_url}/c/{session_id}")
        expect(page.get_by_test_id(f"extension-nav-{_EXTENSION_ID}.primary-nav")).to_be_visible()
        expect(page.get_by_test_id(re.compile(r"^extension-slot-"))).to_have_count(0)

        page.goto(f"{base_url}/settings/general")
        expect(page.get_by_test_id("settings-nav-import")).to_be_visible()
        expect(page.get_by_test_id(re.compile(r"^extension-slot-"))).to_have_count(0)


def test_enabled_slot_actions_open_the_page_with_session_context(
    page: Page, enabled_server: str
) -> None:
    session_id = create_user_session(enabled_server, headers={}, metadata={"title": "Slots"})
    page.goto(f"{enabled_server}/c/{session_id}")

    header_action = page.get_by_test_id(
        f"extension-slot-chat-header-{_EXTENSION_ID}.header-action"
    )
    expect(header_action).to_be_visible()
    expect(
        page.get_by_test_id(f"extension-slot-chat-composer-{_EXTENSION_ID}.composer-action")
    ).to_be_visible()
    header_action.click()

    expect(page).to_have_url(
        re.compile(rf"/extensions/{re.escape(_EXTENSION_ID)}/hello\?conversationId={session_id}$")
    )
    frame = page.frame_locator("iframe[title='Hello Extension']")
    expect(frame.get_by_role("heading", name="Hello from an isolated page")).to_be_visible()
    # The id crossed the iframe boundary through the SDK's invocation context.
    expect(frame.locator("#session-id")).to_have_text(session_id)


def test_settings_section_joins_general_and_core_survives_a_failed_catalog(
    page: Page, enabled_server: str
) -> None:
    page.goto(f"{enabled_server}/settings/general")
    general = page.get_by_role("heading", name="General", level=2).locator("xpath=..")
    section = general.get_by_test_id(f"extension-slot-settings-{_EXTENSION_ID}.settings-section")
    expect(section).to_be_visible()
    section.click()
    expect(page).to_have_url(
        re.compile(rf"/settings/extensions/{re.escape(_EXTENSION_ID)}/hello$")
    )
    expect(section).to_have_attribute("aria-current", "page")

    page.route("**/v1/extensions", lambda route: route.fulfill(status=500, body="unavailable"))
    page.goto(f"{enabled_server}/settings/general")

    expect(page.get_by_test_id("settings-nav-general")).to_be_visible()
    expect(page.get_by_test_id("settings-nav-import")).to_be_visible()
    expect(page.get_by_test_id(re.compile(r"^extension-slot-"))).to_have_count(0)
