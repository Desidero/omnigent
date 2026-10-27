# Evidence for gateway-request-tags

Screenshots, recordings and logs to attach to the upstream PR (see the Demo
section of `../PR.md`). Upload them as GitHub attachments on the PR rather
than committing them, unless they are small and useful to keep here.

Capture them on a clean, throwaway Omnigent server with dummy data: a fresh
`OMNIGENT_DATA_DIR`, scratch projects and repositories, and no real accounts,
sessions, hostnames or credentials in view. Redact anything else before
sharing.

To capture:

- redacted query output from a scratch gateway's usage table showing `request_tags` with the session id and a dummy label
- redacted header dump from a local logging proxy showing the header absent for a non-gateway provider and with the opt-out set
