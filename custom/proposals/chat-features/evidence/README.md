# Evidence for chat-features

Screenshots, recordings and logs to attach to the upstream PR (see the Demo
section of `../PR.md`). Upload them as GitHub attachments on the PR rather
than committing them, unless they are small and useful to keep here.

Capture them on a clean, throwaway Omnigent server with dummy data: a fresh
`OMNIGENT_DATA_DIR`, scratch projects and repositories, and no real accounts,
sessions, hostnames or credentials in view. Redact anything else before
sharing.

To capture:

- screenshot of Settings > General > Chat features, enabled and disabled-with-note states (throwaway server)
- screenshot of the toggle in the new-chat dialog's agent menu and in the session configure menu, including the native "applies after restart" note
- recording of turning the feature off in a session and the Run button disappearing on the next turn
- screenshot of a competing-edit row with its Keep button
- curl output of `GET /v1/chat-features` and a `PATCH /v1/sessions/{id}` with `chat_features`
