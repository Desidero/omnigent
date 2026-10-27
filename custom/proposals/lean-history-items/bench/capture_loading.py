"""Screenshot the preview notice a lean-page tool row shows while its full
output loads: the per-item GET is held for a few seconds via a Playwright route.

Usage: python capture_loading.py --server URL --session ID --out DIR
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:18803")
    parser.add_argument("--session", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        def hold_item_read(route):
            # Keep the full-output fetch in flight long enough to screenshot.
            page.wait_for_timeout(4000)
            route.continue_()

        page.route(re.compile(r"/v1/sessions/[^/]+/items/[^/?]+$"), hold_item_read)
        page.goto(f"{args.server}/c/{args.session}")
        folded = page.get_by_role("button", name=re.compile(r"^Ran "))
        folded.first.wait_for(timeout=30000)
        page.wait_for_timeout(1500)
        folded.last.click()
        page.wait_for_timeout(800)
        row = page.locator('button[title^="Read src/"]').last
        row.scroll_into_view_if_needed()
        row.locator("svg.lucide-chevron-right").click()
        notice = page.get_by_role("status").last
        notice.wait_for(timeout=5000)
        notice.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / "after-loading.png"))
        print("notice:", notice.inner_text())
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
