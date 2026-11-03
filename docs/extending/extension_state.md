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

## Turning it on

Extension state is off until the operator enables the extension. Only
enabled extensions get state, commands and published fields. Enablement is
persistent configuration, never runtime health: a replica whose extension
failed to activate still shows the same published fields as the others.

Enablement comes from the server config's `extensions` section
(`extensions: {<extension id>: {enabled: true}}`), which the UI slots
feature adds; the server passes it to `create_app(extension_is_enabled=...)`.
Without that feature, nothing is enabled: no field is published, and labels
under the prefix of an installed extension that declares published fields
are hidden (see below). Nothing else changes unless such an extension is
installed; `ext.` labels are read-only either way.

## Limits

- At most 64 keys per extension per session. A write that would add a 65th
  key fails; updating an existing key always works.
- Commands may create at most 48 of those keys, and at most a prefix field's
  `max_keys` (16 by default) under that prefix, so users running commands
  can't use up the 16 keys kept for the extension's server code. Users can
  still use up the commands' share: on a shared session, readers running a
  `read`-access command can fill its prefix (and with several such prefixes,
  all 48), after which that command fails for everyone until keys are
  cleared. Give `read` commands a small `max_keys`.
- Values are at most 16,382 bytes. Larger values are rejected, never
  truncated. Published values are UTF-8 text of at most the field's
  `max_length` characters (256 at most).
- Each key has a `version`, 1 when created and incremented on every write.
  Writers can pass the version they read and fail with `409` if another
  write got there first.
- `updated_by` names the user whose command made the last write. It is
  attribution, not a history, and only callers with edit access see it.

Deleting a session deletes its state (and its sub-agents' state). Forking a
session copies neither its state nor its `ext.` labels.

## Published fields

A published field appears in three places, always read-only:

- `published_fields` on session responses: `{"acme.review": {"status": "blocked"}}`;
- the session label `ext.acme.review.status`, which policies and label-based
  views read;
- the state API, for anyone who can read the session.

Only core writes `ext.` labels, and the check also catches spellings a
case- or accent-insensitive database collation treats as the same key
(`EXT.`, `éxt.`). Label updates, session creation and forks reject them, and
policies' label writes to them are dropped.

For every installed extension that declares published fields, core owns its
whole `ext.<extension id>.` label prefix: a label there is shown only when the
extension is enabled, the label is a declared published field, and the
extension's state holds the same value. Anything else under the prefix, such
as a label written before the prefix was reserved, or every label of an
extension that is installed but not enabled, is hidden from session
responses and unreadable to policies (its row is kept). Labels under other
`ext.` prefixes, including those of an uninstalled extension, stay visible
as ordinary read-only labels; `published_fields` lists only enabled
extensions.

## Commands

A command runs on the server as the extension. The caller needs the
command's `required_access` (`edit` by default, or `read`) on the session.
Arguments are checked against their `choices`, `pattern` and `max_length`
before they are put into the key and value templates, and the resulting key
must be a valid state key that the command's own declared field covers. A
write records the caller in `updated_by` and in the server log. `confirm` is
for clients to show before running the command; the server does not check
that anyone confirmed.

## HTTP API

All routes are under `/v1/sessions/{session_id}/extensions/{extension_id}`
and answer `404` for an extension that is not installed or not enabled.

| Route | Access | Does |
| --- | --- | --- |
| `GET state?after=&limit=` | read | Lists the keys the caller may read, in key order, 1-100 per page. Follow `next_after` until it is `null`. Keys the caller may not read never show up, not even in page sizes or cursors. |
| `GET state/{key}` | read | One key, or `404` when it is unset or the caller may not read it. |
| `POST commands/{command_id}` | the command's | Runs a command. Body: `{"arguments": {...}, "expected_version": 3}` (`expected_version` optional; `0` means the key must be unset). Returns the written entry and the session's `published_fields`. |

Entries carry `value` (UTF-8 text, or `null` for other bytes),
`value_base64`, `version`, `updated_at` and `updated_by`. Errors: `400` for
invalid arguments, `403` when the caller's access is too low for the command,
`409` for a version conflict or a key quota.

There is no route that writes state directly: browsers change state only
through declared commands. Server code acting for an extension writes it
through `ExtensionStateService.write_state` and `clear_state`
(`omnigent.server.extension_state`), which mirror published keys as the
manifest says and hold a published key to the same UTF-8 and `max_length`
rules as commands.
