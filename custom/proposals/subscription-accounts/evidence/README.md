# Evidence for subscription-accounts

Screenshots, recordings and logs to attach to the upstream PR (see the Demo
section of `../PR.md`). Upload them as GitHub attachments on the PR rather
than committing them, unless they are small and useful to keep here.

Capture them on a clean, throwaway Omnigent server with dummy data: a fresh
`OMNIGENT_DATA_DIR`, scratch projects and repositories, and no real accounts,
sessions, hostnames or credentials in view. Redact anything else before
sharing.

To capture:

- screenshot of the new-session harness menu with the Account section (one account disabled as not signed in)
- screenshot of Project settings with the Account field, and the composer note when the project's account can't be used on the chosen host
- recording of switching a running claude-native session to another account from the in-session harness menu, showing the restart toast and the resumed terminal
- curl output of `GET /v1/hosts/{host_id}/providers?harness=claude-native` (no secrets or paths)
- the launch error text for an account that is not signed in
