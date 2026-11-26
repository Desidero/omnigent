Title: [Bug] Transcript jumps to the bottom while re-reading a reply that is still streaming

### Description

While a turn streams, scrolling up a little to re-read the beginning of the reply works until the model makes its first tool call (or anything else commits the reply's first item). At that moment the transcript jumps by the whole height of the reply so far: the reader lands near the bottom of the reply, hundreds of pixels (desktop) to several thousand (phone) away from the text they were reading. Scrolling back up finds the text where it was; the content did not move, only the view did.

What I expected: while the stick-to-bottom lock is released, the row under the reader stays where it is, whatever happens below (streaming) or above (re-measured rows, history pages).

Cause (from reading `web/src/components/chat/Transcript.tsx` and `@tanstack/virtual-core` 3.19): the virtualized transcript turns native scroll anchoring off and relies on the virtualizer's own per-row scroll adjustment plus two hand-rolled holds (history prepend, content above the list). An assistant bubble is keyed by its first committed item, so a streaming bubble is keyed `responseId:0` until its first item gets a store-assigned id (the relay publishes it when a tool call closes the streamed text). The row then remounts under the new key with the 280px size estimate; its first measurement finds a row that starts above the viewport top and the library treats the estimate-to-actual delta as "an estimated block above the fold" and scrolls by it (`resizeItem` → `applyScrollAdjustment`), although the row's start never moved. The same heuristic also skips rows that merely span the viewport top and defers on iOS WebKit, so other in-list height changes above the reader are compensated inconsistently.

### Steps to reproduce

1. Open a session with a few dozen earlier messages (so the transcript scrolls) and a model that first answers with a long reply and then calls a tool. With the mock model from `tests/e2e_ui`, queue `{"text": <700 words>, "stream": true, "chunk_delay": 0.015}` followed by a `sys_os_shell` tool call and a short reply, for a prompt sent from the web UI.
2. Send the prompt. Once the reply is taller than the viewport, scroll up ~240px with the wheel (or a finger on a phone) and stop; the stick-to-bottom lock is released and the start of the reply is under the reader.
3. Wait for the tool call.

Observed: the moment the tool call starts, the view jumps down by the reply's height so far. Measured with a Playwright script that samples a visible paragraph's `getBoundingClientRect().top` every frame and logs every programmatic `scrollTop` write: desktop 1280×800 Chromium, one `scrollTo` of +1322px (reply height 1602px minus the 280px estimate) after a 700-word reply, landmark drift −1927px by the end of the turn; iPhone 14 descriptor (Chromium emulation), drift −7164px. With the reader parked in earlier turns instead (one or three screens up) the view holds (0px), so this needs the reader inside the streaming row.

### Version

main @ 65be0f2468

### OS

Ubuntu 24.04 (reproduced in headless Chromium; the same code path runs on iOS Safari, where there is no native scroll anchoring to mask it)

### Harness

Not applicable

### Harness mode

Not applicable

### Platform or device

macOS, Linux, Windows, Desktop app, iOS, Android

### Observed impact

Some users or sessions

### Authentication type

Not authentication-related
