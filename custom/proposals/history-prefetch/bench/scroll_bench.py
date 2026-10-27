"""Scroll a long transcript to the top and measure history paging.

Usage:
  uv run --no-sync python bench/scroll_bench.py <base_url> <session_id> <label> <out_dir>
      [--device desktop|phone] [--video] [--step PX] [--max-seconds N]

Records, in the page: every /items fetch (start/end/bytes), long tasks,
layout shifts, and one sample per animation frame (scrollTop, scrollHeight,
first mounted bubble key, the mounted rows' top offsets). Drives the scroller
upward with small wheel notches (desktop) or CDP touch flicks (phone) until
the oldest turn is mounted at the top. Writes <out_dir>/<label>-<device>.json
and prints a summary line.

Metrics:
  fetches        history page requests after the initial window
  stall ms       time the scroller sat at the top (scrollTop <= 1) waiting
                 for a page to land, summed / max over pages
  jump px        per-frame |delta(rowTop) + delta(scrollTop)| for rows mounted
                 in both frames: content that moved under the reader; max / sum
                 of frames above 2px
  long tasks     PerformanceObserver longtask count / total ms
  slow frames    rAF intervals above 50 ms
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

INIT_SCRIPT = """
(() => {
  const endpoint = "/items?";
  window.__bench = { fetches: [], longTasks: [], shifts: [], frames: [], t0: performance.now() };
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    if (!url.includes(endpoint)) return originalFetch(input, init);
    const rec = { url, start: performance.now(), end: null, bytes: null, status: null };
    window.__bench.fetches.push(rec);
    const res = await originalFetch(input, init);
    rec.status = res.status;
    const clone = res.clone();
    clone.text().then((t) => { rec.bytes = t.length; rec.end = performance.now(); });
    return res;
  };
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) window.__bench.longTasks.push({ start: e.startTime, duration: e.duration });
    }).observe({ type: "longtask", buffered: true });
  } catch {}
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) window.__bench.shifts.push({ start: e.startTime, value: e.value, input: e.hadRecentInput });
    }).observe({ type: "layout-shift", buffered: true });
  } catch {}
  let scroller = null;
  const findScroller = () => {
    if (scroller && scroller.isConnected) return scroller;
    const row = document.querySelector("[data-bubble-key]");
    let el = row ? row.parentElement : null;
    while (el && el !== document.body) {
      const style = getComputedStyle(el);
      if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight) { scroller = el; return el; }
      el = el.parentElement;
    }
    return document.querySelector('[role="log"]');
  };
  window.__benchScroller = findScroller;
  let last = performance.now();
  const tick = () => {
    const now = performance.now();
    const el = findScroller();
    const rows = {};
    let firstKey = null;
    if (el) {
      const top = el.getBoundingClientRect().top;
      for (const node of el.querySelectorAll("[data-bubble-key]")) {
        const key = node.dataset.bubbleKey;
        if (firstKey === null) firstKey = key;
        rows[key] = [Math.round((node.getBoundingClientRect().top - top) * 10) / 10, Number(node.dataset.index)];
      }
    }
    window.__bench.frames.push({
      t: now, dt: now - last,
      scrollTop: el ? el.scrollTop : null,
      scrollHeight: el ? el.scrollHeight : null,
      clientHeight: el ? el.clientHeight : null,
      firstKey,
      loading: !!document.querySelector("[data-bench-loading], .animate-spin"),
      rows,
    });
    last = now;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})();
"""


def pause_while_loading(page, args, state) -> None:
    """In --pause-on-loading mode, hold input while the loading row shows, then
    a beat longer so the prepend lands on a still pane (pure hold quality)."""
    if not args.pause_on_loading:
        return
    waited = 0
    while waited < 5000 and page.evaluate("!!document.querySelector('.animate-spin')"):
        if not state.get("stall_shot") and page.evaluate("window.__benchScroller().scrollTop <= 1"):
            state["stall_shot"] = True
            page.screenshot(path=str(state["stall_shot_path"]))
        page.wait_for_timeout(50)
        waited += 50
    if waited:
        page.wait_for_timeout(300)


def drive_desktop(page, args, state):
    scroller_box = page.evaluate("(() => { const r = window.__benchScroller().getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
    x = scroller_box[0] + scroller_box[2] / 2
    y = scroller_box[1] + scroller_box[3] / 2
    page.mouse.move(x, y)
    deadline = time.monotonic() + args.max_seconds
    while time.monotonic() < deadline:
        page.mouse.wheel(0, -args.step)
        page.wait_for_timeout(args.interval_ms)
        pause_while_loading(page, args, state)
        if maybe_done(page, state):
            break


def drive_phone(page, args, state):
    cdp = page.context.new_cdp_session(page)
    box = page.evaluate("(() => { const r = window.__benchScroller().getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
    x = box[0] + box[2] / 2
    y0 = box[1] + box[3] * 0.35
    deadline = time.monotonic() + args.max_seconds
    while time.monotonic() < deadline:
        # One finger flick: 10 moves of `step/10` px downward over ~130 ms, then lift.
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y0}]})
        y = y0
        for _ in range(10):
            y += args.step / 10
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
            page.wait_for_timeout(8)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_timeout(args.interval_ms)
        pause_while_loading(page, args, state)
        if maybe_done(page, state):
            break


def maybe_done(page, state) -> bool:
    info = page.evaluate(
        """(() => {
          const el = window.__benchScroller();
          const first = document.querySelector('[data-bubble-key]');
          const text = first ? first.textContent || '' : '';
          const loading = !!document.querySelector('.animate-spin');
          return { top: el ? el.scrollTop : null, atStart: text.includes('Turn 0:'), loading };
        })()"""
    )
    if info["top"] is not None and info["top"] <= 1 and info["loading"] and not state.get("stall_shot"):
        state["stall_shot"] = True
        page.screenshot(path=str(state["stall_shot_path"]))
    if info["atStart"] and info["top"] is not None and info["top"] <= 1:
        state["reached_start"] = True
        return True
    return False


def summarize(bench: dict, started_at: float) -> dict:
    frames = bench["frames"]
    fetches = [f for f in bench["fetches"] if f["start"] >= started_at]
    initial = [f for f in bench["fetches"] if f["start"] < started_at]
    # Prepend landings: frames whose first mounted key differs from the previous frame's.
    prepends = []
    for prev, cur in zip(frames, frames[1:]):
        shared = [k for k in prev["rows"] if k in cur["rows"]]
        if shared and any(cur["rows"][k][1] > prev["rows"][k][1] for k in shared):
            prepends.append(cur["t"])
    prepend_set = set(prepends)
    # Stalls: runs of frames at the top that end with a prepend.
    stalls = []
    run_start = None
    for prev, cur in zip(frames, frames[1:]):
        at_top = cur["scrollTop"] is not None and cur["scrollTop"] <= 1 and cur["t"] >= started_at
        if at_top and run_start is None:
            run_start = cur["t"]
        if cur["t"] in prepend_set and run_start is not None:
            stalls.append(cur["t"] - run_start)
            run_start = None
        if not at_top:
            run_start = None
    # Jumps: how far the rows on screen moved in one frame beyond the reader's
    # own scroll pace (px/ms over the previous ~6 frames, scaled by this
    # frame's duration). A perfect prepend hold moves them by exactly the pace.
    jumps = []
    moves: list[float | None] = []
    for prev, cur in zip(frames, frames[1:]):
        deltas = [
            cur["rows"][k][0] - prev["rows"][k][0]
            for k in prev["rows"]
            if k in cur["rows"] and 0 <= prev["rows"][k][0] < prev["clientHeight"]
        ]
        moves.append(statistics.median(deltas) if deltas else None)
    still_prepend_jumps = []
    for i, (prev, cur) in enumerate(zip(frames, frames[1:])):
        if cur["t"] < started_at or moves[i] is None:
            continue
        if cur["t"] in prepend_set and i >= 2 and all(
            moves[j] is not None and abs(moves[j]) < 1 for j in (i - 1, i - 2)
        ):
            still_prepend_jumps.append(round(moves[i], 1))
        window = [(moves[j], frames[j + 1]["dt"]) for j in range(max(0, i - 6), i) if moves[j] is not None]
        total_dt = sum(dt for _, dt in window)
        velocity = sum(m for m, _ in window) / total_dt if total_dt > 0 else 0.0
        jump = moves[i] - velocity * cur["dt"]
        if abs(jump) > 2:
            jumps.append({"t": cur["t"], "px": round(jump, 1), "prepend": cur["t"] in prepend_set})
    prepend_jumps = [abs(j["px"]) for j in jumps if j["prepend"]]
    long_tasks = [lt for lt in bench["longTasks"] if lt["start"] >= started_at]
    page_tasks = []
    for f in fetches:
        if f["end"] is None:
            continue
        page_tasks.append(
            round(sum(lt["duration"] for lt in long_tasks if f["end"] <= lt["start"] <= f["end"] + 400))
        )
    slow_frames = [f for f in frames if f["t"] >= started_at and f["dt"] > 50]
    durations = [f["end"] - f["start"] for f in fetches if f["end"] is not None]
    return {
        "initial_fetch_bytes": sum(f["bytes"] or 0 for f in initial),
        "fetches": len(fetches),
        "fetch_bytes_total": sum(f["bytes"] or 0 for f in fetches),
        "fetch_ms_median": round(statistics.median(durations), 1) if durations else None,
        "prepends": len(prepends),
        "stall_count": len(stalls),
        "stall_ms_total": round(sum(stalls)),
        "stall_ms_max": round(max(stalls)) if stalls else 0,
        "jump_frames": len([j for j in jumps if abs(j["px"]) > 40]),
        "jump_px_max": max((abs(j["px"]) for j in jumps), default=0),
        "prepend_jump_px_max": max(prepend_jumps, default=0),
        "prepend_jump_px_median": round(statistics.median(prepend_jumps), 1) if prepend_jumps else 0,
        "still_prepends": len(still_prepend_jumps),
        "still_prepend_jump_px_max": max((abs(j) for j in still_prepend_jumps), default=0),
        "still_prepend_jumps": still_prepend_jumps,
        "long_tasks": len(long_tasks),
        "long_task_ms": round(sum(lt["duration"] for lt in long_tasks)),
        "long_task_ms_max": round(max((lt["duration"] for lt in long_tasks), default=0)),
        "slow_frames": len(slow_frames),
        "layout_shifts": len([s for s in bench["shifts"] if s["start"] >= started_at and s["value"] > 0.01]),
        "jumps": jumps,
        "page_long_task_ms": page_tasks,
        "stalls_ms": [round(s) for s in stalls],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("session_id")
    parser.add_argument("label")
    parser.add_argument("out_dir")
    parser.add_argument("--device", choices=["desktop", "phone"], default="desktop")
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--pause-on-loading", action="store_true", help="hold input while a page loads (measures the hold)")
    parser.add_argument("--step", type=int, default=None, help="px per wheel notch / flick")
    parser.add_argument("--interval-ms", type=int, default=None)
    parser.add_argument("--max-seconds", type=int, default=120)
    parser.add_argument("--latency-ms", type=int, default=None, help="emulated RTT (default 100 on phone, 20 on desktop)")
    parser.add_argument("--cpu-throttle", type=float, default=None, help="CDP CPU slowdown (default 4 on phone)")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{args.label}-{args.device}" + ("-paused" if args.pause_on_loading else "")
    if args.step is None:
        args.step = 120 if args.device == "desktop" else 400
    if args.interval_ms is None:
        args.interval_ms = 30 if args.device == "desktop" else 500

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx_kwargs: dict = {}
        if args.device == "phone":
            ctx_kwargs.update(
                {k: v for k, v in pw.devices["iPhone 13"].items() if k != "default_browser_type"}
            )
        else:
            ctx_kwargs["viewport"] = {"width": 1280, "height": 800}
        if args.video:
            ctx_kwargs["record_video_dir"] = str(out_dir / "video")
            ctx_kwargs["record_video_size"] = ctx_kwargs["viewport"]
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        page.add_init_script(INIT_SCRIPT)
        throttle = args.cpu_throttle if args.cpu_throttle is not None else (4 if args.device == "phone" else 1)
        latency = args.latency_ms if args.latency_ms is not None else (100 if args.device == "phone" else 20)
        cdp = page.context.new_cdp_session(page)
        if throttle > 1:
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
        if latency > 0:
            cdp.send("Network.enable")
            cdp.send(
                "Network.emulateNetworkConditions",
                {"offline": False, "latency": latency, "downloadThroughput": -1, "uploadThroughput": -1},
            )
        page.goto(f"{args.base_url}/c/{args.session_id}")
        page.get_by_text("Module 59 summary", exact=False).wait_for(timeout=30_000)
        page.wait_for_timeout(1500)
        started_at = page.evaluate("performance.now()")
        state = {"stall_shot_path": out_dir / f"{name}-stall.png"}
        t_wall = time.monotonic()
        if args.device == "desktop":
            drive_desktop(page, args, state)
        else:
            drive_phone(page, args, state)
        elapsed = time.monotonic() - t_wall
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / f"{name}-end.png"))
        bench = page.evaluate("window.__bench")
        video = page.video
        context.close()
        if video is not None:
            video.save_as(str(out_dir / f"{name}.webm"))
        browser.close()

    summary = summarize(bench, started_at)
    summary.update(
        label=args.label,
        device=args.device,
        reached_start=bool(state.get("reached_start")),
        elapsed_s=round(elapsed, 1),
        step_px=args.step,
        cpu_throttle=throttle,
        latency_ms=latency,
        interval_ms=args.interval_ms,
    )
    (out_dir / f"{name}.json").write_text(json.dumps({"summary": summary, "raw": bench}, indent=1))
    keys = [
        "label", "device", "reached_start", "elapsed_s", "fetches", "fetch_bytes_total", "fetch_ms_median",
        "prepends", "stall_count", "stall_ms_total", "stall_ms_max", "jump_frames", "jump_px_max",
        "prepend_jump_px_max", "prepend_jump_px_median", "still_prepends", "still_prepend_jump_px_max", "long_tasks", "long_task_ms", "long_task_ms_max", "slow_frames", "layout_shifts", "cpu_throttle", "latency_ms",
    ]
    print(json.dumps({k: summary[k] for k in keys}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
