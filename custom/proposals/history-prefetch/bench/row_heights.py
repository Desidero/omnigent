"""Median mounted-row height per bubble kind, desktop and phone.

Usage: uv run --no-sync python bench/row_heights.py <base_url> <session_id>
Scrolls up a few screens so a window of rows past the initial view mounts,
then reads each mounted row's height and whether it is a user prompt row.
"""
from __future__ import annotations

import json
import statistics
import sys

from playwright.sync_api import sync_playwright

PROBE = """
() => Array.from(document.querySelectorAll('[data-bubble-key]')).map((node) => ({
  kind: node.querySelector('[data-role="user"][data-user-message-id]') ? 'user' : 'assistant',
  height: node.getBoundingClientRect().height,
}))
"""

base, sid = sys.argv[1], sys.argv[2]
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for device in ("desktop", "phone"):
        kwargs = {"viewport": {"width": 1280, "height": 800}} if device == "desktop" else {
            k: v for k, v in pw.devices["iPhone 13"].items() if k != "default_browser_type"
        }
        page = browser.new_context(**kwargs).new_page()
        page.goto(f"{base}/c/{sid}")
        page.get_by_text("Module 59 summary", exact=False).wait_for(timeout=30_000)
        page.wait_for_timeout(1000)
        rows = {}
        box = page.evaluate("(() => { const r = document.querySelector('[role=\"log\"]').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        page.mouse.move(*box)
        for _ in range(60):
            for row in page.evaluate(PROBE):
                rows.setdefault(row["kind"], set()).add(round(row["height"], 1))
            page.mouse.wheel(0, -400)
            page.wait_for_timeout(60)
        summary = {k: {"n": len(v), "median": statistics.median(v), "min": min(v), "max": max(v)} for k, v in rows.items()}
        print(device, json.dumps(summary))
    browser.close()
