# Evidence: transcript hold while a turn streams

All captures: headless Chromium (Playwright 1.60), isolated local server with the mock model, a session seeded with 14 settled turns (prompt, two shell runs, five-paragraph reply each). `before-` is `main @ 65be0f2468`, `after-` is the fix. Desktop is a 1280×800 viewport; phone is Playwright's `iPhone 14` descriptor on Chromium (the WebKit build could not launch on the capture host, which lacks its GTK/GStreamer libraries). Every capture was made by `bench/drift.py` from the batch scratch directory, which seeds the session, scripts the mock model, drives the browser, samples the landmark once per painted frame and logs every programmatic `scrollTop` write.

Scenario `reread`: the model streams a 700-word reply (15ms per word), then calls `sys_os_shell`, then answers briefly. Once the reply is taller than the viewport the reader scrolls up 240px (two wheel ticks), stops, and the rest of the turn runs with hands off. The landmark is the paragraph crossing the viewport top (the start of the streamed reply). Afterwards the reader scrolls back to the bottom and a second streamed turn checks that follow-tail re-engaged.

Scenario `3up` / `1up`: eight shell tool calls then a 220-word streamed reply; once the turn is under way the reader scrolls up three (or one) screens into earlier turns and stops. Same measurement and follow-tail check.

| Capture | What it shows |
| --- | --- |
| `before-desktop-reread.webm` | Recording of the bug: the reader is re-reading the start of the reply; when the tool call starts, the view jumps to the end of the reply. |
| `before-desktop-reread-1-scrolled-up.png` | Still just after scrolling up: the start of the streamed reply under the reader. |
| `before-desktop-reread-2-after-turn.png` | Still after the turn: the reader was thrown down by 1927px (the landmark paragraph is far above the viewport). |
| `before-phone-reread.webm`, `before-phone-reread-1-scrolled-up.png`, `before-phone-reread-2-after-turn.png` | Same on the iPhone 14 descriptor: drift −7164px, the whole reply. |
| `after-desktop-reread.webm`, `after-desktop-reread-1-scrolled-up.png`, `after-desktop-reread-2-after-turn.png` | Same drive on the fix: the start of the reply stays under the reader through the tool call and the rest of the stream (0px, no scroll writes). |
| `after-phone-reread.webm`, `after-phone-reread-1-scrolled-up.png`, `after-phone-reread-2-after-turn.png` | Same on the phone descriptor: 0px. |
| `after-desktop-reread-3-back-at-bottom.png`, `after-phone-reread-3-back-at-bottom.png` | After scrolling back down and sending another prompt: the view follows the new streamed reply to the bottom (follow-tail re-engaged). |
| `after-desktop-3up-2-after-turn.png`, `after-phone-3up-2-after-turn.png` | Reader parked three screens up in earlier turns while eight tool calls and a streamed reply land below: 0px, unchanged from before the fix. |

Drift is the landmark's on-screen top at the end of the turn minus its top when the reader stopped scrolling; writes are programmatic `scrollTop`/`scrollTo` calls during that window.

| Scenario | Before (drift / writes) | After (drift / writes) |
| --- | --- | --- |
| desktop, reread | −1927px / 2 (+1966px) | 0px / 0 |
| phone, reread | −7164px / 2 (+7204px) | 0px / 0 |
| desktop, 3 screens up | 0px / 0 | 0px / 0 |
| phone, 3 screens up | 0px / 0 | 0px / 0 |
| desktop, 1 screen up | 0px / 0 | 0px / 0 |
| phone, 1 screen up | 0px / 0 | 0px / 0 |

# Raw traces and recordings stay out of the repo (size); PNG stills and the bench scripts reproduce them.
