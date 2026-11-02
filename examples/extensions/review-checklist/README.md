# Review checklist extension

An example Omnigent browser extension (`omnigent.review-checklist`). It adds a
review checklist beside a session, reached from the chat header or the
composer, and a settings page for checklist templates. It uses the
[UI slots](../../../docs/extending/extension_ui_slots.md) and the
[browser SDK](../../../docs/extending/browser_extensions.md), including
`sessions.get`, which the session-row slot branch adds; it has no server code.

| Slot | Item | Opens |
| --- | --- | --- |
| `chat.header.actions` | Review checklist | the review page, with the session's `conversationId` |
| `composer.actions` | Review checklist | the same page, once the session exists |
| `settings.sections` | Review checklists | the templates page, inside the settings layout, listed after core's General entries |

## What the pages do

**Review page.** Shows which session it is reviewing (title, status, worktree
branch, project, last update, session id) and the pull request filed from the
session's branch, with **Open pull request** and **Open session** buttons
(a session without a branch skips the lookup and says so). A
banner says when the agent is still running, waiting for you, failed, or has an
unread turn. Below that is the checklist: a template picker that says where its
choice came from, the items as checkboxes, a live "N of M checked" count and
**Uncheck all**. **Refresh** re-reads the session; the page also re-reads when
the tab becomes visible again. It reads the session by id with `sessions.get`,
so archived and sub-agent sessions work too, as long as you can read them.

**Templates page.** Three read-only built-in templates (*Agent change review*,
*Pull request ready*, *Research or answer session*) with **Duplicate to edit**;
your own templates with rename, optional section headings, add, edit, reorder
(up/down buttons) and delete; your default template and per-project defaults;
import and export as JSON text; and storage usage with **Forget all review
checks**.

A session's template is, in order: the one chosen for that session, its
project's default, your default, then *Agent change review*.

## Where data lives

Everything is in the SDK's `storage.user`: IndexedDB in this browser, scoped to
this extension, server and user. Both pages say so. Collaborators, other
devices and other browsers don't see your checks or templates. If the host
can't provide storage, the checklist still works for the visit and says nothing
will be saved.

| Key | Holds | Budget |
| --- | --- | --- |
| `templates.v1` | your templates | 30 KB; 20 templates of up to 60 items |
| `defaults.v1` | your default and per-project defaults | 8 KB |
| `progress.v1` | per-session ticks and template choice | 30 KB; the 150 most recently updated sessions |

A review page saves only its own session's entry in `progress.v1`: each save
re-reads the record and replaces that entry, so pages open on different
sessions normally keep each other's checks. Storage has no transactions, so two
saves landing at the same moment can still lose one. Two pages on the same
session keep the last save.

## What it doesn't do

- Share checks or templates with anyone, or store anything on the server.
- Check anything itself: it doesn't read the transcript, diff, tests or CI.
- Change the session, its labels or the composer.
- Update live: the SDK has no session subscription, so use **Refresh**.
- Take operator-configured templates: to change the built-ins, edit
  `web/src/model.ts` and rebuild.
- Follow the app's colour palette or Appearance font: the SDK passes only
  light or dark, so the page mirrors core's default palette.
- Copy to the clipboard or download a file: the sandbox allows neither, so
  export fills a text box to copy from.

## Build, install and enable

The built `dist/extension.js` and `dist/extension.css` are committed so the
package installs without Node.js. Rebuild after changing `web/src/`:

```bash
pnpm --filter @omnigent/example-review-checklist-extension build
pnpm --filter @omnigent/example-review-checklist-extension test
```

Install the package into the server's environment, enable it in the server
config and restart the server:

```bash
uv pip install examples/extensions/review-checklist
uv run omnigent extensions doctor omnigent.review-checklist
```

```yaml
extensions:
  omnigent.review-checklist:
    enabled: true
```

Tests: `web/src/*.test.ts` (rules and the review page with a stubbed SDK),
`tests/extensions/test_review_checklist_extension.py` (package checks) and
`tests/e2e_ui/extensions/test_review_checklist.py` (the installed wheel in a
real server and browser).

## Credits

- **sakethdhulipalla-wq**: the session review panel opened from the chat
  header with the session id, and the case that browser extensions can't
  contribute one today.
  [#9545](https://github.com/omnigent-ai/omnigent/issues/9545) and its hosted
  follow-on [#11886](https://github.com/omnigent-ai/omnigent/issues/11886).
- **Analytic Endeavors**: the session rail's triage states and the "set this
  session to review" step after a merge, from the public README and screenshots
  of [omnigent-ae-public](https://github.com/analyticendeavors/omnigent-ae-public)
  ("Session rail", `docs/media/rail-overview.jpg`; `patches/README.md` entries
  0020/0022). Apache-2.0; descriptions only, no code read.
- **fanzeyi**: the page-backed UI slots this uses, revived from
  [#5660](https://github.com/omnigent-ai/omnigent/pull/5660).
