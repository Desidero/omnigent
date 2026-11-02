"""The session status example, installed as a wheel, through a real server and browser.

Reuses the packaged-install fixture from the UI-slot tests. The package is
manifest-only: core draws its row badge, its row-menu submenu and its tooltip
row from the published status field, and runs its commands as the viewer.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from tests._helpers.extensions import extension_server, install_extension_packages
from tests.e2e_ui.collaboration._multi_user_server import create_user_session

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STATUS_PACKAGE = _REPO_ROOT / "examples" / "extensions" / "session-status"
_EXTENSION_ID = "omnigent.session-status"
_KEY = f"ext.{_EXTENSION_ID}.status"
_MENU = f"session-row-menu-{_EXTENSION_ID}.menu"
_ENABLED = {_EXTENSION_ID: {"enabled": True}}


@pytest.fixture(scope="module")
def status_packages(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return install_extension_packages(
        [_STATUS_PACKAGE], tmp_path_factory.mktemp("ext") / "packages"
    )


@pytest.fixture
def grouping_server(built_spa: None, status_packages: Path, tmp_path: Path) -> Iterator[str]:
    with extension_server(
        tmp_path / "enabled",
        status_packages,
        extensions=_ENABLED,
        env={"OMNIGENT_FEATURES": "sidebar_grouping_ui"},
    ) as base_url:
        yield base_url


def _status(base_url: str, session_id: str, headers: dict[str, str] | None = None) -> str | None:
    response = httpx.get(f"{base_url}/v1/sessions/{session_id}", headers=headers or {}, timeout=10)
    response.raise_for_status()
    return response.json()["published_fields"].get(_EXTENSION_ID, {}).get("status")


def _set_status(
    base_url: str, session_id: str, status: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.post(
        f"{base_url}/v1/sessions/{session_id}/extensions/{_EXTENSION_ID}/commands/"
        f"{_EXTENSION_ID}.set",
        json={"arguments": {"status": status}},
        headers=headers or {},
        timeout=10,
    )


def _row(page: Page, session_id: str) -> Locator:
    return page.locator(f'li[data-sidebar-session-id="{session_id}"]')


def _option(value: str) -> str:
    return f"session-row-command-{_EXTENSION_ID}.menu-{value}"


def _open_status_menu(page: Page, session_id: str) -> None:
    row = _row(page, session_id)
    row.hover()
    row.get_by_test_id("conversation-actions").click()
    page.get_by_test_id(_MENU).click()


def test_installed_but_not_enabled_shows_no_badge_or_menu(
    page: Page, built_spa: None, status_packages: Path, tmp_path: Path
) -> None:
    with extension_server(tmp_path / "installed", status_packages) as base_url:
        session_id = create_user_session(base_url, headers={}, metadata={"title": "Plain row"})
        # Its state and commands need the operator's enablement too.
        assert _set_status(base_url, session_id, "done").status_code == 404
        # Only core writes the status's mirror label.
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


def test_owner_sets_a_status_from_the_row_menu_and_clears_it(
    page: Page, grouping_server: str
) -> None:
    session_id = create_user_session(
        grouping_server, headers={}, metadata={"title": "Retry inventory sync"}
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(grouping_server)

    _open_status_menu(page, session_id)
    for value in ("in-progress", "blocked", "needs-review", "parked", "done"):
        expect(page.get_by_test_id(_option(value))).to_be_visible()
    expect(page.get_by_test_id(_option("clear"))).to_have_text("Clear status")
    page.get_by_test_id(_option("needs-review")).click()

    row = _row(page, session_id)
    expect(row.get_by_role("img", name="Status: Needs review")).to_be_visible()
    assert _status(grouping_server, session_id) == "needs-review"

    # With sidebar_grouping_ui on, the tooltip lists it as a label/value row.
    page.mouse.move(0, 0)
    row.locator("a").first.hover()
    expect(page.get_by_test_id(f"session-tooltip-{_EXTENSION_ID}.hover")).to_have_text(
        re.compile(r"^Status\s*Needs review$")
    )

    page.reload()
    expect(_row(page, session_id).get_by_role("img", name="Status: Needs review")).to_be_visible()

    _open_status_menu(page, session_id)
    expect(page.get_by_test_id(_option("needs-review"))).to_have_attribute("aria-checked", "true")
    page.get_by_test_id(_option("clear")).click()
    expect(_row(page, session_id).get_by_test_id("session-row-decorations")).to_have_count(0)
    assert _status(grouping_server, session_id) is None


def _arrow_down_to(page: Page, target: Locator) -> None:
    for _ in range(10):
        if target.evaluate("node => node === document.activeElement"):
            return
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(50)
    expect(target).to_be_focused()


def test_status_submenu_works_from_the_keyboard(page: Page, grouping_server: str) -> None:
    session_id = create_user_session(
        grouping_server, headers={}, metadata={"title": "Keyboard row"}
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(grouping_server)

    row = _row(page, session_id)
    row.hover()
    actions = row.get_by_test_id("conversation-actions")
    actions.focus()
    page.keyboard.press("Enter")
    menu = page.get_by_test_id(_MENU)
    expect(menu).to_be_visible()
    # Arrow down to Status, open it with the right arrow, pick Parked with Enter.
    _arrow_down_to(page, menu)
    page.keyboard.press("ArrowRight")
    expect(page.get_by_test_id(_option("in-progress"))).to_be_focused()
    _arrow_down_to(page, page.get_by_test_id(_option("parked")))
    page.keyboard.press("Enter")

    expect(row.get_by_role("img", name="Status: Parked")).to_be_visible()
    assert _status(grouping_server, session_id) == "parked"
    expect(page.get_by_test_id(_MENU)).to_have_count(0)


def test_read_only_sharee_sees_the_badge_but_cannot_set_it(
    browser: Browser, built_spa: None, status_packages: Path, tmp_path: Path
) -> None:
    owner = {"X-Forwarded-Email": "owner@ui.test"}
    sharee = {"X-Forwarded-Email": "sharee@ui.test"}
    with extension_server(
        tmp_path / "multi-user",
        status_packages,
        extensions=_ENABLED,
        env={"OMNIGENT_LOCAL_SINGLE_USER": None},
    ) as base_url:
        read_only, editable = (
            create_user_session(base_url, headers=owner, metadata={"title": title})
            for title in ("Read-only share", "Editable share")
        )
        for session_id, level in ((read_only, 1), (editable, 2)):
            _set_status(base_url, session_id, "blocked", owner).raise_for_status()
            httpx.put(
                f"{base_url}/v1/sessions/{session_id}/permissions",
                json={"user_id": sharee["X-Forwarded-Email"], "level": level},
                headers=owner,
                timeout=10,
            ).raise_for_status()

        context = browser.new_context(
            extra_http_headers=sharee, viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()
        page.goto(base_url)
        page.get_by_test_id("session-filter").click()
        page.get_by_test_id("session-filter-all").click()
        for session_id, allowed in ((read_only, False), (editable, True)):
            row = _row(page, session_id)
            expect(row.get_by_role("img", name="Shared session")).to_be_visible()
            expect(row.get_by_role("img", name="Status: Blocked")).to_be_visible()
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

        # The server's share-level check is the real gate, whatever the menu shows.
        denied = _set_status(base_url, read_only, "done", sharee)
        assert denied.status_code == 403, denied.text
        assert _status(base_url, read_only, owner) == "blocked"
