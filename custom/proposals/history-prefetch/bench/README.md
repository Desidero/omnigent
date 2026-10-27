# history-prefetch bench

Reproduces the scroll-up history measurements. Everything runs against a local
Omnigent server built from the worktree under test.

1. Build the SPA (`pnpm --filter web run build` in the worktree) and start the
   server: `start-server.sh <worktree> <env-dir> 18802` (set `DIST=<other dist>`
   to serve a baseline build from a second port, same database).
   Restart the server after every rebuild: it caches `index.html` with the old
   asset hashes.
2. Seed a 420-item session: `uv run --no-sync python seed.py http://127.0.0.1:18802 <env-dir>/sessions.db 60`
   (prints the session id).
3. Measure: `run-all.sh <worktree> http://127.0.0.1:18802 <session_id> <label> <out_dir>`
   runs `scroll_bench.py` per device (desktop 1280x800 wheel notches; Playwright
   `iPhone 13` with CDP touch flicks, 4x CPU throttle, 100 ms RTT), once
   continuous and once pausing input while a page loads (`--pause-on-loading`,
   which measures the landing shift on a still pane). Each run prints one JSON
   summary line and writes `<label>-<device>[-paused].json` with the raw
   per-frame samples. Add `--video` for a WebM recording.
4. `row_heights.py` prints median mounted-row heights per bubble kind (used to
   evaluate, and reject, a per-kind virtualizer estimate).
