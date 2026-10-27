Title: [Feature] Jump back to the latest message with a signal when new content lands while scrolled up

### Problem or use case

When a reader scrolls up in the web chat (to re-read an earlier turn while a long reply streams, or to look something up while a teammate or a scheduled run adds turns), the transcript's follow-tail disengages, as it should. From then on nothing tells them that the conversation moved on below them, and nothing takes them back:

- The only affordance is the stock `ConversationScrollButton` from the ai-elements kit: an unlabeled arrow icon rendered inside the scroll container, 16px from its bottom edge, inside the 32px scroll fade. It is half faded, sits on top of the last visible line of text, and is hidden on the hover-revealed top pill's terms (`max-md`), so on a phone it reads as a stray glyph (see `evidence/before-phone-1-streaming-scrolled-up.png`).
- It has no notification state. While a reply streams below the reader, or after a second client has added a user message and a reply, the arrow looks exactly as it did before: the reader has to scroll down to find out whether anything happened.
- It has no accessible name (`aria-label` missing), so screen readers announce "button".

The top edge already has the "Jump to top" pill (`JumpToTopButton` in `web/src/components/chat/chatBubbleParts.tsx`): a labeled pill, outside the fade, keyboard reachable. The bottom edge deserves the same treatment plus a "something new is below you" signal, which is a standard pattern in chat clients.

### Proposed solution

A bottom-edge pill, centered above the composer, shown whenever the reader is away from the bottom (the `use-stick-to-bottom` `isAtBottom` state, which already drives follow-tail):

- Default label "Jump to latest".
- Notification state when new content lands below the reader while they are away: "New reply" while a turn streams, "N new messages" once distinct user/assistant messages have been appended since they scrolled away (older history paged in above does not count). Filled `primary` treatment for the notification state, the outline pill otherwise, matching the top pill and the design tokens.
- Click scrolls to the bottom and re-engages follow-tail. Keyboard reachable with an `aria-label` that carries the count.
- Always visible while away, on desktop and touch alike (nothing to hover on a phone; and the pill is the only indication that follow is off).
- Not shown during the initial mount pin or while a deep link scroll is in flight (a short settle delay before it appears).
- Replaces the stock arrow button in `Transcript.tsx`.

### Alternatives considered

- Keep the stock arrow and move it out of the fade: still unlabeled and still silent about new content.
- A toast or a sidebar badge for new messages in the open session: the reader is looking at the transcript; the signal belongs where their eyes are.
- Auto-scrolling back when new content arrives: this is exactly what the reader opted out of by scrolling up.

### Harness

Not applicable

### Platform or device

Not platform-specific

### Harness mode

Not applicable

### Version

main @ 65be0f2468
