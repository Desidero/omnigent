# Evidence: jump to the latest message with a new-reply signal

All captures: headless Chromium (Playwright 1.60) against an isolated local server with the mock model, a fresh session seeded with 12 settled turns (prompt, one shell run, four-paragraph reply each). `before-` is `main @ 65be0f2468`, `after-` is the branch. Desktop is a 1280×800 viewport; phone is Playwright's `iPhone 14` descriptor on Chromium (the WebKit build could not launch on the capture host, which lacks its GTK libraries). Every capture was made by `bench/jump.py` from the batch scratch directory, which seeds the session, scripts the mock model, drives the browser and logs every programmatic `scrollTop` write while the reader is away.

The drive, identical before and after: the reader sends a prompt that the model answers with a 200-word reply streamed at 50ms per word; once the reply is under way they scroll two screens up and stop (stage 1); the reply completes below them (stage 2); a second client (another page on the same session) sends a message and gets a short reply (stage 3); the reader uses whatever bottom-edge affordance exists (stage 4); the second client sends another streamed prompt to check that follow-tail re-engaged (stage 5).

| Capture | What it shows |
| --- | --- |
| `before-desktop-1-streaming-scrolled-up.png`, `before-phone-1-streaming-scrolled-up.png` | `main`, reader two screens up while the reply streams: the only affordance is the stock unlabeled arrow icon, 16px inside the scroll container and therefore inside the 32px fade, sitting on the last line of text. Nothing says a reply is streaming. |
| `before-desktop-3-new-messages.png`, `before-phone-3-new-messages.png` | `main`, after a reply completed and the other client added a message and a reply below the reader: the arrow is unchanged, no count, no signal. |
| `before-desktop.webm` | Recording of the whole `main` drive on desktop. |
| `after-desktop-1-streaming-scrolled-up.png`, `after-phone-1-streaming-scrolled-up.png` | Branch, same moment: the "New reply" pill (filled, attention state), centered above the composer, clear of the fade, `aria-label` "New reply streaming, jump to it". |
| `after-desktop-2-after-stream.png` | The reply completed below the reader: "1 new message". |
| `after-desktop-3-new-messages.png`, `after-phone-3-new-messages.png` | After the other client's message and reply: "3 new messages" (the completed reply, the other client's message, its reply), `aria-label` "3 new messages, jump to the latest message". |
| `after-desktop-4-after-return.png`, `after-phone-4-after-return.png` | After clicking the pill: the view is at the bottom (1px from the end, the library's park position), the pill is hidden (`aria-hidden`, out of the tab order). |
| `after-desktop-5-follow-tail.png`, `after-phone-5-follow-tail.png` | A further streamed turn from the other client: the reader stays at the bottom (follow-tail re-engaged), the tail marker is visible, the pill stays hidden. |
| `after-desktop.webm`, `after-phone.webm` | Recordings of the branch drive. |

Pill state per stage as read from the DOM (`text` / `aria-hidden`), identical on desktop and phone:

| Stage | Before (stock arrow) | After (pill) |
| --- | --- | --- |
| 0 at the bottom | absent | "Jump to latest", hidden |
| 1 streaming, two screens up | arrow, no label, 16px from the container's bottom (inside the fade) | "New reply", shown, attention |
| 2 reply completed below | same arrow | "1 new message", shown, attention |
| 3 other client's turn landed | same arrow | "3 new messages", shown, attention |
| 4 after the affordance | absent, 1px from the bottom | "Jump to latest", hidden, 1px from the bottom |
| 5 streamed turn while followed | absent, 1px from the bottom | hidden, 1px from the bottom |

Scroll behaviour while the reader was away (stages 1 to 3), from the `scrollTop` spy: no programmatic writes and no scrollTop change before or after, so the pill adds no scroll traffic.

| Measure | Before desktop | After desktop | Before phone | After phone |
| --- | --- | --- | --- | --- |
| programmatic `scrollTop`/`scrollTo` writes while away | 0 | 0 | 0 | 0 |
| scrollTop drift while away (px) | 0 | 0 | 0 | 0 |
| transcript growth below the reader (px) | 1261 | 1282 | 2077 | 2077 |
| distance from the bottom after returning (px) | 1 | 1 | 1 | 1 |

Raw JSON traces stay out of the repo; the bench script reproduces them.
