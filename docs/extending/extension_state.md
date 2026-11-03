# Extension session state

An extension can keep a little state about each session: which pull requests a
watcher follows, a review status, a goal's progress. Core stores it beside the
session's labels, deletes it with the session, and decides who can read it.

## Declaring state

The manifest's `state` lists the keys the extension uses and their visibility
(see [Extension manifest](extension_manifest.md#session-state-and-commands)):

| Visibility | Who can read it |
| --- | --- |
| `service` (default) | Only server code acting for the extension. Not even the extension's own page. |
| `editors` | Also users with edit access to the session, through the HTTP API. |
| `readers` | Also anyone who can read the session. |
| `published` | Readers, plus a read-only session label `ext.<extension id>.<key>` that policies and session lists see. |

An extension's page runs in the browser of whoever opens it, so it reads state
with that viewer's access, never as the extension.
