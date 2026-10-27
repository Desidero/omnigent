# Evidence: scroll-up history prefetch and page size

All captures: local Omnigent server, headless Chromium (Playwright), seeded session of 420 items (60 turns of prompt, reply, two `shell` calls with output, markdown summary). "before" is `upstream/main` @ 65be0f2468; "after" is `fix/history-prefetch` @ efa0347afe. Phone runs use the Playwright `iPhone 13` descriptor with CDP touch flicks (400 px every 500 ms), a 4x CPU throttle and 100 ms emulated RTT; desktop runs are 1280x800 with wheel notches (120 px every 30 ms) and 20 ms RTT. Mock data only; nothing private.

| file | shows | how |
| --- | --- | --- |
| `before-phone.webm` | Phone flicking up on `main`: the pane stops on "Loading earlier messages…" at the top for each 20-item page, sixteen times. | `scroll_bench.py --device phone --video` against the `main` build |
| `after-phone.webm` | Same flicks with the fix: six pages, landed from memory once the fling settles; the spinner is gone by the time the pane stops. | `scroll_bench.py --device phone --video` against the fix |
| `before-desktop.webm` | Desktop wheel on `main`: sixteen loading rows on the way up. | `scroll_bench.py --device desktop --video` against the `main` build |
| `after-desktop.webm` | Desktop wheel with the fix: four pages, landed while still scrolling. | `scroll_bench.py --device desktop --video` against the fix |
| `before-phone-paused-stall.png` | Phone on `main` stopped at the top of the loaded window (turn 14's reply, the prompt cut off above) waiting for the next page. | screenshot taken by `scroll_bench.py --pause-on-loading` when `scrollTop <= 1` with the loading row showing |
| `before-phone-end.png`, `after-phone-end.png` | The first turn ("Turn 0") at the top at the end of each phone run. | end-of-run screenshot |
| `before-desktop-end.png`, `after-desktop-end.png` | The first turn at the top at the end of each desktop run. | end-of-run screenshot |
| `before-*.json`, `after-*.json` | Benchmark output: the summary line plus raw per-frame samples (scroll offset, mounted rows, fetches, long tasks). The `-paused` variants hold input while a page loads to measure the landing shift on a still pane. | `run-all.sh` |

The scripts (`start-server.sh`, `seed.py`, `scroll_bench.py`, `run-all.sh`, `row_heights.py`, `README.md`) are in `bench/` next to this directory.

# Raw traces and recordings stay out of the repo (size); PNG stills and the bench scripts reproduce them.
