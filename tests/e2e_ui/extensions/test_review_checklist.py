"""The review checklist example, installed as a wheel, through a real server and browser.

Reuses the packaged-install fixture from the UI-slot tests: the header action
opens the checklist page for the invoking session, ticks persist in this
browser, the composer action reaches the same ticks, an archived session still
loads by id, and the settings section edits templates inside the settings
layout, listed after core's General entries.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import FrameLocator, Page, expect

from tests._helpers.extensions import extension_server, install_extension_packages
from tests.e2e_ui.collaboration._multi_user_server import create_user_session

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKLIST = _REPO_ROOT / "examples" / "extensions" / "review-checklist"
_EXTENSION_ID = "omnigent.review-checklist"


@pytest.fixture(scope="module")
def checklist_packages(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return install_extension_packages([_CHECKLIST], tmp_path_factory.mktemp("ext") / "packages")


@pytest.fixture
def enabled_server(built_spa: None, checklist_packages: Path, tmp_path: Path) -> Iterator[str]:
    with extension_server(
        tmp_path / "enabled",
        checklist_packages,
        extensions={_EXTENSION_ID: {"enabled": True}},
    ) as base_url:
        yield base_url


def _session_in_project(base_url: str, title: str, project: str) -> str:
    session_id = create_user_session(base_url, headers={}, metadata={"title": title})
    project_id = httpx.post(f"{base_url}/v1/projects", json={"name": project}, timeout=10.0)
    project_id.raise_for_status()
    httpx.patch(
        f"{base_url}/v1/sessions/{session_id}",
        json={"title": title, "project_id": project_id.json()["id"]},
        timeout=10.0,
    ).raise_for_status()
    return session_id


def _checklist(page: Page) -> FrameLocator:
    return page.frame_locator("iframe[title='Review checklist']")


def test_header_action_opens_the_checklist_for_the_invoking_session(
    page: Page, enabled_server: str
) -> None:
    session_id = _session_in_project(enabled_server, "Add CSV export", "Storefront")
    page.goto(f"{enabled_server}/c/{session_id}")

    page.get_by_test_id(f"extension-slot-chat-header-{_EXTENSION_ID}.header-action").click()
    expect(page).to_have_url(
        re.compile(rf"/extensions/{re.escape(_EXTENSION_ID)}/review\?conversationId={session_id}$")
    )
    frame = _checklist(page)
    # The id crossed the iframe boundary; the details came through sessions.read.
    expect(frame.locator("#session-id")).to_have_text(session_id)
    expect(frame.locator("#session-title")).to_have_text("Add CSV export")
    expect(frame.get_by_test_id("status-chip")).to_contain_text("Idle")
    expect(frame.get_by_text("Storefront", exact=True)).to_be_visible()
    expect(frame.locator("#template-select")).to_have_value("builtin.agent-change-review")
    expect(frame.locator("#template-source")).to_have_text("From: Your default")
    expect(frame.locator("#storage-notice")).to_contain_text("Saved in this browser only")
    expect(frame.locator("#progress")).to_have_text("0 of 11 checked")

    frame.get_by_role("checkbox", name="Every changed file is one you expected to change.").check()
    frame.get_by_role("checkbox", name="New or changed behaviour has a test.").check()
    expect(frame.locator("#progress")).to_have_text("2 of 11 checked")
    expect(frame.locator("#save-status")).to_have_text("Saved in this browser.")

    page.reload()
    expect(_checklist(page).locator("#progress")).to_have_text("2 of 11 checked")

    # The composer action carries the same session to the same ticks.
    page.goto(f"{enabled_server}/c/{session_id}")
    page.get_by_test_id(f"extension-slot-chat-composer-{_EXTENSION_ID}.composer-action").click()
    frame = _checklist(page)
    expect(frame.locator("#session-id")).to_have_text(session_id)
    expect(frame.locator("#progress")).to_have_text("2 of 11 checked")
    expect(
        frame.get_by_role("checkbox", name="New or changed behaviour has a test.")
    ).to_be_checked()


def test_review_page_reads_an_archived_session_by_id(page: Page, enabled_server: str) -> None:
    session_id = create_user_session(enabled_server, headers={}, metadata={"title": "Old export"})
    httpx.patch(
        f"{enabled_server}/v1/sessions/{session_id}", json={"archived": True}, timeout=10.0
    ).raise_for_status()

    page.goto(f"{enabled_server}/extensions/{_EXTENSION_ID}/review?conversationId={session_id}")
    frame = _checklist(page)
    expect(frame.locator("#session-title")).to_have_text("Old export")
    expect(frame.locator("#progress")).to_have_text("0 of 11 checked")


def test_settings_section_edits_templates_inside_the_settings_layout(
    page: Page, enabled_server: str
) -> None:
    page.goto(f"{enabled_server}/settings/general")
    link = page.get_by_test_id(f"extension-slot-settings-{_EXTENSION_ID}.settings")
    expect(link).to_be_visible()
    # Extension sections come after every core General entry, whatever their order.
    last_core = page.get_by_test_id("settings-nav-import").bounding_box()
    link_box = link.bounding_box()
    assert last_core is not None and link_box is not None
    assert link_box["y"] > last_core["y"]
    link.click()
    expect(page).to_have_url(
        re.compile(rf"/settings/extensions/{re.escape(_EXTENSION_ID)}/templates$")
    )
    expect(page.get_by_test_id("settings-nav-general")).to_be_visible()

    frame = page.frame_locator("iframe[title='Review checklists']")
    expect(frame.locator("#storage-notice")).to_contain_text("Saved in this browser only")
    frame.get_by_role("button", name="Duplicate Pull request ready to edit").click()
    expect(frame.get_by_label("Template name")).to_have_value("Pull request ready (copy)")
    frame.get_by_label("New item").fill("Screenshots attached")
    frame.get_by_role("button", name="Add item").click()
    expect(frame.get_by_label("Item 7 in Pull request ready (copy)")).to_have_value(
        "Screenshots attached"
    )


def test_session_page_keeps_core_controls_when_the_catalog_fails(
    page: Page, enabled_server: str
) -> None:
    session_id = create_user_session(
        enabled_server, headers={}, metadata={"title": "Add CSV export"}
    )
    page.route("**/v1/extensions", lambda route: route.fulfill(status=500, body="unavailable"))
    page.goto(f"{enabled_server}/c/{session_id}")

    expect(page.get_by_role("textbox", name="Message the agent")).to_be_visible()
    expect(page.locator(f'li[data-sidebar-session-id="{session_id}"]')).to_be_visible()
    expect(page.get_by_test_id(re.compile(r"^extension-slot-"))).to_have_count(0)
