"""Session-row slots from a packaged, manifest-only extension through a real server.

The test package declares a published status field and two commands, and binds
a row badge, a row-menu submenu and a tooltip row to them. It reuses the
packaged-install fixture from the page-slot tests; no extension code runs in
the browser.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, Locator, Page, Route, expect

from tests._helpers.extensions import extension_server, install_extension_packages
from tests._helpers.polling import poll_until
from tests.e2e_ui.collaboration._multi_user_server import create_user_session

_PACKAGE = Path(__file__).resolve().parent / "packages" / "session-status"
_EXTENSION_ID = "omnigent-test.session-status"
_KEY = f"ext.{_EXTENSION_ID}.status"
_MENU = f"session-row-menu-{_EXTENSION_ID}.menu"


@pytest.fixture(scope="module")
def status_packages(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return install_extension_packages([_PACKAGE], tmp_path_factory.mktemp("ext") / "packages")


@pytest.fixture
def enabled_server(built_spa: None, status_packages: Path, tmp_path: Path) -> Iterator[str]:
    with extension_server(
        tmp_path / "enabled",
        status_packages,
        extensions={_EXTENSION_ID: {"enabled": True}},
    ) as base_url:
        yield base_url


def _published(base_url: str, session_id: str) -> dict[str, str]:
    response = httpx.get(f"{base_url}/v1/sessions/{session_id}", timeout=10)
    response.raise_for_status()
    return response.json()["published_fields"].get(_EXTENSION_ID, {})


def _run(
    base_url: str,
    session_id: str,
    command: str,
    headers: Mapping[str, str] | None = None,
    **arguments: str,
) -> httpx.Response:
    return httpx.post(
        f"{base_url}/v1/sessions/{session_id}/extensions/{_EXTENSION_ID}/commands/"
        f"{_EXTENSION_ID}.{command}",
        json={"arguments": arguments},
        headers=headers,
        timeout=10,
    )


def _row(page: Page, session_id: str) -> Locator:
    return page.locator(f'li[data-sidebar-session-id="{session_id}"]')


def _choice(status: str) -> str:
    return f"session-row-command-{_EXTENSION_ID}.menu-{status}"


def _set_status_from_kebab(page: Page, session_id: str, status: str) -> None:
    row = _row(page, session_id)
    row.hover()
    row.get_by_test_id("conversation-actions").click()
    page.get_by_test_id(_MENU).click()
    page.get_by_test_id(_choice(status)).click()


def _show_grouping_tooltip(page: Page) -> None:
    def serve_info(route: Route) -> None:
        response = route.fetch()
        info = response.json()
        info["features"] = {**info.get("features", {}), "sidebar_grouping_ui": True}
        route.fulfill(response=response, json=info)

    page.route("**/v1/info", serve_info)


def test_installed_but_not_enabled_adds_nothing_to_rows(
    page: Page, built_spa: None, status_packages: Path, tmp_path: Path
) -> None:
    with extension_server(tmp_path / "installed", status_packages) as base_url:
        session_id = create_user_session(base_url, headers={}, metadata={"title": "Plain row"})
        # State and commands need the operator's enablement too.
        assert _run(base_url, session_id, "set", status="done").status_code == 404
        # Only core writes the published field's mirror label.
        rejected = httpx.patch(
            f"{base_url}/v1/sessions/{session_id}", json={"labels": {_KEY: "done"}}, timeout=10
        )
        assert rejected.status_code == 400

        page.goto(base_url)
        row = _row(page, session_id)
        expect(row).to_be_visible()
        expect(row.get_by_test_id("session-row-decorations")).to_have_count(0)
        row.hover()
        row.get_by_test_id("conversation-actions").click()
        expect(page.get_by_test_id("mark-unread-conversation")).to_be_visible()
        expect(page.get_by_test_id(_MENU)).to_have_count(0)


def test_set_check_and_clear_status_from_the_row_menu(page: Page, enabled_server: str) -> None:
    session_id = create_user_session(enabled_server, headers={}, metadata={"title": "Status row"})
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(enabled_server)

    _set_status_from_kebab(page, session_id, "blocked")
    # The command's response repaints the row; the server holds the published field.
    badge = _row(page, session_id).get_by_role("img", name="Status: Blocked")
    expect(badge).to_be_visible()
    assert _published(enabled_server, session_id) == {"status": "blocked"}

    # Keyboard: the menu marks the current value, and Enter sets another.
    row = _row(page, session_id)
    row.hover()
    row.get_by_test_id("conversation-actions").click()
    page.get_by_test_id(_MENU).press("ArrowRight")
    expect(page.get_by_test_id(_choice("blocked"))).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id(_choice("clear"))).to_have_text("Clear status")
    page.get_by_test_id(_choice("done")).focus()
    page.keyboard.press("Enter")
    expect(row.get_by_role("img", name="Status: Done")).to_be_visible()

    # The legacy tooltip lists the value as text.
    page.mouse.move(0, 0)
    row.locator("a").first.hover()
    expect(page.get_by_test_id(f"session-tooltip-{_EXTENSION_ID}.hover")).to_have_text(
        "Status: Done"
    )

    page.reload()
    expect(_row(page, session_id).get_by_role("img", name="Status: Done")).to_be_visible()

    _set_status_from_kebab(page, session_id, "clear")
    expect(_row(page, session_id).get_by_test_id("session-row-decorations")).to_have_count(0)
    assert _published(enabled_server, session_id) == {}
    page.reload()
    expect(_row(page, session_id)).to_be_visible()
    expect(_row(page, session_id).get_by_test_id("session-row-decorations")).to_have_count(0)


def test_grouping_tooltip_lists_the_status_row(page: Page, enabled_server: str) -> None:
    session_id = create_user_session(enabled_server, headers={}, metadata={"title": "Hover row"})
    _run(enabled_server, session_id, "set", status="needs-review").raise_for_status()
    _show_grouping_tooltip(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(enabled_server)

    _row(page, session_id).locator("a").first.hover()
    detail = page.get_by_test_id(f"session-tooltip-{_EXTENSION_ID}.hover")
    expect(detail).to_have_text(re.compile(r"^Status\s*Needs review$"))


def test_phone_menu_swaps_to_the_choices(page: Page, enabled_server: str) -> None:
    session_id = create_user_session(enabled_server, headers={}, metadata={"title": "Phone row"})
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(enabled_server)
    page.get_by_role("button", name="Open sidebar").click()

    _row(page, session_id).locator("a").first.click(button="right")
    page.get_by_test_id(_MENU).click()
    back = page.get_by_test_id("session-row-command-back")
    expect(back).to_be_visible()
    blocked = page.get_by_test_id(_choice("blocked"))
    box = blocked.bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 390
    blocked.click()

    expect(_row(page, session_id).get_by_role("img", name="Status: Blocked")).to_be_visible()
    assert _published(enabled_server, session_id) == {"status": "blocked"}


def test_viewers_see_the_status_but_only_editors_can_set_it(
    browser: Browser, built_spa: None, status_packages: Path, tmp_path: Path
) -> None:
    owner = {"X-Forwarded-Email": "owner@ui.test"}
    viewer = {"X-Forwarded-Email": "viewer@ui.test"}
    with extension_server(
        tmp_path / "multi-user",
        status_packages,
        extensions={_EXTENSION_ID: {"enabled": True}},
        env={"OMNIGENT_LOCAL_SINGLE_USER": None},
    ) as base_url:
        read_only, editable = (
            create_user_session(base_url, headers=owner, metadata={"title": title})
            for title in ("Read-only share", "Editable share")
        )
        for session_id, level in ((read_only, 1), (editable, 2)):
            _run(base_url, session_id, "set", owner, status="in-progress").raise_for_status()
            httpx.put(
                f"{base_url}/v1/sessions/{session_id}/permissions",
                json={"user_id": viewer["X-Forwarded-Email"], "level": level},
                headers=owner,
                timeout=10,
            ).raise_for_status()
        # The server's share-level check is the real gate.
        denied = _run(base_url, read_only, "set", viewer, status="done")
        assert denied.status_code == 403, denied.text

        context = browser.new_context(
            extra_http_headers=viewer, viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()
        page.goto(base_url)
        # Shared sessions list under "All sessions".
        page.get_by_test_id("session-filter").click()
        page.get_by_test_id("session-filter-all").click()
        for session_id, allowed in ((read_only, False), (editable, True)):
            row = _row(page, session_id)
            expect(row.get_by_role("img", name="Shared session")).to_be_visible()
            expect(row.get_by_role("img", name="Status: In progress")).to_be_visible()
            row.locator("a").first.click(button="right")
            expect(page.get_by_test_id("mark-unread-conversation")).to_be_visible()
            menu = page.get_by_test_id(_MENU)
            expect(menu).to_be_visible()
            if allowed:
                expect(menu).not_to_have_attribute("aria-disabled", "true")
            else:
                expect(menu).to_have_attribute("aria-disabled", "true")
            page.keyboard.press("Escape")
        context.close()


def _state_rows(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        (count,) = connection.execute("SELECT COUNT(*) FROM extension_session_state").fetchone()
    return count


def test_deleting_the_session_deletes_its_state(
    page: Page, enabled_server: str, tmp_path: Path
) -> None:
    session_id = create_user_session(enabled_server, headers={}, metadata={"title": "Gone row"})
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(enabled_server)
    _set_status_from_kebab(page, session_id, "parked")
    expect(_row(page, session_id).get_by_role("img", name="Status: Parked")).to_be_visible()
    database = tmp_path / "enabled" / "server" / "chat.db"
    assert _state_rows(database) == 1

    httpx.delete(f"{enabled_server}/v1/sessions/{session_id}", timeout=10).raise_for_status()

    poll_until(lambda: _state_rows(database) == 0, timeout_s=10)
    gone = httpx.get(
        f"{enabled_server}/v1/sessions/{session_id}/extensions/{_EXTENSION_ID}/state/status",
        timeout=10,
    )
    assert gone.status_code == 404
