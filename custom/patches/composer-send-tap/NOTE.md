# composer-send-tap

Needs: none
Covers: 7913ca7464b70270

On touch screens, one tap on Send sends even while the on-screen keyboard is
up, instead of sometimes doing nothing until the keyboard is dismissed.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** not proposed yet; no pull request or pushed branch.

## Must hold

- A touch that ends on the enabled Send button submits the composer once, whether or not the browser follows it with a click (iOS WebKit sometimes drops that click while the keyboard is up).
- A touch that slides off the button before lifting sends nothing, and a disabled Send sends nothing.
- Mouse and keyboard activation are unchanged, and the session, side-chat and new-session composers all behave the same, since they share the button.

## Key code

- `web/src/components/composer/ChatComposer.tsx`: `ComposerSendButton`, `onTouchEnd`

## Tests

- `web/src/components/composer/ChatComposer.test.tsx::submits from a tap that ends on the button, without waiting for its click`
- `web/src/components/composer/ChatComposer.test.tsx::leaves a touch that slid off the button alone`
- `web/src/components/composer/ChatComposer.test.tsx::does not submit a disabled button from a tap`
