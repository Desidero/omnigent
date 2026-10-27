# Evidence for session-labels-ui

Screenshots, recordings and logs to attach to the upstream PR (see the Demo
section of `../PR.md`). Upload them as GitHub attachments on the PR rather
than committing them, unless they are small and useful to keep here.

Capture them on a clean, throwaway Omnigent server with dummy data: a fresh
`OMNIGENT_DATA_DIR`, scratch projects and repositories, and no real accounts,
sessions, hostnames or credentials in view. Redact anything else before
sharing.

To capture:

- recording of adding, editing and removing a label in the session info popover (throwaway server, dummy labels)
- screenshot of Project settings > Default labels, including an inline validation error
- screenshot of the composer "+" > Labels editor with a "from project" label and the resulting chips
- screenshot of the project settings dialog on a short window with the footer still visible
- curl output of a null-value PATCH removing a label
