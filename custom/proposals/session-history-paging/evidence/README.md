# Evidence for session-history-paging

Screenshots, recordings and logs to attach to the upstream PR (see the Demo
section of `../PR.md`). Upload them as GitHub attachments on the PR rather
than committing them, unless they are small and useful to keep here.

Capture them on a clean, throwaway Omnigent server with dummy data: a fresh
`OMNIGENT_DATA_DIR`, scratch projects and repositories, and no real accounts,
sessions, hostnames or credentials in view. Redact anything else before
sharing.

To capture:

- attach the tool results from manual steps 2 to 4 (a filtered `sys_session_list`, two consecutive forward pages showing `next_cursor` / `has_more`, and the `invalid_cursor` error) from a throwaway server with dummy sessions
