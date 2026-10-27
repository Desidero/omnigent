Title: [Feature] Delete a session label through the API, and default labels per project

### Problem or use case

Session labels are the one place to put your own metadata on a session (team, ticket, customer, purpose). Agent YAML seeds them, policies write them, and downstream tooling reads them. Two gaps make them hard to use:

- You can't remove a label. `PATCH /v1/sessions/{id}` merges, and an empty value only deletes `omni_project` and the pin key, so any other label stays forever, either with its old value or stored as an empty string. #8689 asks the Python client for a label update method and for the merge-or-replace behaviour to be documented; the client PR (#10418) documents the current behaviour verbatim, including that an empty string is stored rather than removing the key.
- Projects can't give their sessions a starting set of labels. Every session in a "customer-acme" project has to be labelled one by one, and sessions created through the API, an automation or an import never get labelled.

Labels matter more as other features read them (cost telemetry, policies, trace attributes), and a web editor for them is only useful once a label can be removed again.

### Proposed solution

1. **Deleting a label through the API.** In `PATCH /v1/sessions/{id}`, `"labels": {"ticket": null}` deletes `ticket`. Reserved keys (`omnigent.*`, `cost_control.*`) stay protected exactly as they are today: deleting one is rejected the same way setting it is. The existing empty-string clear for `omni_project` and the pin key is unchanged (and takes `null` too). An empty or over-width key becomes a 400 instead of a database error. The docstring and `openapi.json` state the merge semantics, which partially answers #8689.
2. **Default labels per project.** A project's config gains `labels` (`{"team": "ml"}`). The server merges them into the labels of any session created in that project, with the request's own labels winning on conflict, in `resolve_project_session_create` next to the `agent_id`, `workspace` and `git` defaults it already applies. Because this happens on the server, API, automation and import creates get them too. A `null` request value leaves that default off the new session, mirroring the PATCH delete. They apply at creation only; moving an existing session into the project doesn't relabel it. The config stays opaque client JSON; malformed, internal or over-length entries are skipped at create.
3. **One definition of "internal label".** `is_internal_label_key` next to `PROJECT_LABEL_KEY` in the conversation store, so the server and clients agree on which keys are Omnigent's own (`omni_project`, `omnigent.*`, `cost_control.*`).

A web UI (a Labels section in the session info popover, a "Default labels" editor in project settings, and "+" > Labels in the new-session composer) follows as a separate PR stacked on this one.

I can send a PR for this, and a follow-up widening the Python client's `set_labels` to `dict[str, str | None]` (or adding `delete_label`) once it lands.

### Alternatives considered

- **Multi-valued tags (#2117):** that design scoped a `conversation_tags` table for bulk sharing and search and was closed in July as internal for now. This proposal doesn't add a data model. It completes the single-valued labels that already exist and leaves room for tags later. If tags are still planned, I'd like to know whether this conflicts with that direction.
- **A dedicated `DELETE /v1/sessions/{id}/labels/{key}` route:** one more endpoint for clients to learn; `null` in the existing PATCH keeps one round trip for a mixed set-and-delete edit and matches how the pin and project keys already clear.
- **Client-side project defaults** (the way the composer pre-fills agent and model): misses API, CLI, automation and import creates.
- **A separate `apply_project_labels: false` flag on create** to opt out of the merge: a second field the client has to understand; `null` per key mirrors the PATCH semantics instead.

Related: #8689 / #10418 (Python client label updates and merge semantics; partially addressed), #2117 / #2118 (session tags design, closed).

### Harness

Not applicable

### Platform or device

Not platform-specific

### Expected reach

Some users

### Authentication type

Not authentication-related
