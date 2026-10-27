"""Open a seeded session in the web UI, record the items requests, and screenshot
the collapsed and expanded tool card.

Usage: python capture_ui.py --server URL --session ID --label before --out DIR
Writes <out>/<label>-collapsed.png, <out>/<label>-expanded.png and
<out>/<label>-requests.json (every /items request: url, wire bytes, elapsed).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:18803")
    parser.add_argument("--session", required=True)
    parser.add_argument("--label", default="before")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    requests: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        page = context.new_page()
        started: dict[str, float] = {}

        def on_request(request):
            if "/items" in request.url:
                started[request.url] = time.perf_counter()

        def on_response(response):
            if "/items" in response.url:
                body = response.body()
                sizes = response.request.sizes()
                requests.append(
                    {
                        "url": response.url.split(args.server)[-1],
                        "status": response.status,
                        "wire_bytes": sizes["responseBodySize"],
                        "body_bytes": len(body),
                        "encoding": response.headers.get("content-encoding", "none"),
                        "ms": round((time.perf_counter() - started.get(response.url, time.perf_counter())) * 1000, 1),
                    }
                )

        page.on("request", on_request)
        page.on("response", on_response)
        nav_start = time.perf_counter()
        page.goto(f"{args.server}/c/{args.session}")
        # The transcript has rendered once a tool row is on screen.
        folded = page.get_by_role("button", name=re.compile(r"^Ran "))
        folded.first.wait_for(timeout=30000)
        first_paint_ms = round((time.perf_counter() - nav_start) * 1000)
        page.wait_for_timeout(1500)
        # Unfold the newest turn's tool run so its collapsed tool rows show.
        folded.last.click()
        page.wait_for_timeout(800)
        row = page.locator('button[title^="Read src/"]').last
        row.scroll_into_view_if_needed()
        page.screenshot(path=str(out / f"{args.label}-collapsed.png"))
        # Expand the last Read tool (a large file read) via its chevron: the
        # path text is a link that would open the file viewer instead.
        row.locator("svg.lucide-chevron-right").click()
        page.wait_for_timeout(1500)
        row.scroll_into_view_if_needed()
        page.screenshot(path=str(out / f"{args.label}-expanded.png"))
        browser.close()
    summary = {"transcript_visible_ms": first_paint_ms, "items_requests": requests}
    (out / f"{args.label}-requests.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
