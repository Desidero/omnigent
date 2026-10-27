# Evidence for pr-watch

Screenshots, recordings and logs to attach to the upstream PR (see the Demo
section of `../PR.md`). Upload them as GitHub attachments on the PR rather
than committing them, unless they are small and useful to keep here.

Capture them on a clean, throwaway Omnigent server with dummy data: a fresh
`OMNIGENT_DATA_DIR`, scratch projects and repositories, and no real accounts,
sessions, hostnames or credentials in view. Redact anything else before
sharing.

To capture:

- screenshot of the "Watch PRs" popover with All and per-PR boxes (throwaway server, scratch repo PRs)
- screenshot of the Pull Requests panel's "Watch until green" switch
- recording of a failing check producing one wake-up message and the agent's turn, then a stop note when the PR turns green
- curl output of `GET`/`PUT /v1/sessions/{id}/pr-watch`, including the 404 with the flag off
