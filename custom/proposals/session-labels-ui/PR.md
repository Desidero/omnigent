<!-- Title: feat(web): view and edit session labels -->
<!-- Branch: feat/session-labels-ui, stacked on feat/session-labels-api (open against upstream main once the server PR merges, or as a stacked PR with the first commit shared) -->
## Related issue

Closes #<to be filed> (the same issue as the server PR; this is its second half)

Stacked on the server PR `feat(server): delete session labels with null and default labels per project`. Only the `feat(web): …` commit is new here.

## Summary

Sessions carry your own tags (labels such as `team: ml`), but the web UI never showed them. This PR lets you see and edit a session's labels, set them before a session starts, and edit the default labels a project gives its new sessions.

- A Labels section in the session info popover lists user labels and, with edit access, adds, edits and removes them, with inline validation against the key (128) and value (256) column widths. Internal labels (`omnigent.*`, `cost_control.*`, `omni_project`) stay hidden, and a read-only viewer sees the list without controls (and no section at all when there are none).
- Project settings gain a "Default labels" editor (same `LabelEditor` component), stored as `config.labels`. A label still typed in the add row is saved with the dialog, an invalid one blocks Save with its inline message, and closing the dialog with unsaved label changes warns once before discarding. The editor is a plain sibling of the existing fields; the dialog's height is left to the dialog layer (see #5194).
- The new-session composer's "+" menu gains Labels, opening the same editor for the session about to be created, with or without a project. Project defaults are filled in, marked "from project", and removable for that session only: a removed default goes to the create as `null`, which the server reads as "leave this default off". The labels show as chips in the composer and go with the create request.
- The session list-cache overlay is shared by title, archive and label updates.
- `feature-map/sessions.md` documents the `labels` sub-feature.

## Test Plan

Tests added or changed:

- `web/src/components/AgentInfo.test.tsx`: Labels section, add/edit/remove, view-only collaborator, hidden when empty for a viewer.
- `web/src/shell/ProjectSettingsDialog.test.tsx`: Default labels editor, pending add-row saved, invalid label blocks Save, reserved key rejected inline, unsaved-changes warning.
- `web/src/shell/NewChatDialog.test.tsx`, `web/src/shell/NewChatDialog.projectCreate.test.tsx`: composer "+" > Labels opens after the menu closes and shows the count; project defaults pre-filled; a removed default is sent as `null`; labels ride along the JSON and multipart creates.
- `web/src/lib/sessionLabels.test.ts`, `web/src/lib/sessionListCache.test.ts`: validation, internal-label filtering, `newSessionLabels`, cache overlay.

```sh
cd web && pnpm exec vitest run src/components/AgentInfo.test.tsx src/shell/ProjectSettingsDialog.test.tsx \
  src/shell/NewChatDialog.test.tsx src/shell/NewChatDialog.projectCreate.test.tsx \
  src/lib/sessionLabels.test.ts src/lib/sessionListCache.test.ts
cd web && pnpm exec tsc -b
```

6 files, 818 tests pass; `tsc -b` clean; `pre-commit run --files <changed>` passes.

Manual:

1. Open a session and click the header's info icon (on mobile, header menu > Agent info). Add `team: ml`, reload, and confirm it is kept. Edit it, then remove it and confirm it is gone after reload.
2. Try a 129-character key and a key starting with `omnigent.`: the inline error appears and nothing is saved.
3. As a view-only collaborator, confirm the labels are listed without controls, and that a session with no labels shows no Labels section.
4. Open a project's three-dot menu > Project settings > Default labels, add `cost_center: research`, Save. Start a session in that project and confirm the label in its info popover.
5. Start another session in the project from the composer: "+" > Labels shows `cost_center` marked "from project". Remove it, add `ticket: 42`, start the session, and confirm only `ticket: 42` is in its popover.
6. Move an existing session into the project and confirm it gains no labels.
7. In Project settings, add a label and close the dialog without saving: a one-time warning appears; closing again discards.

## Demo

- [x] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

<!-- Capture on a throwaway server with dummy data, redact anything private, upload as GitHub attachments (do not commit). States to capture: -->

- [ ] Recording: session info popover > Labels: add `team: ml`, edit it to `team: infra`, remove it (shows the empty state "No labels" before and after).
- [ ] Screenshot: the popover's Labels section with the inline validation error for a key starting with `omnigent.` (or a 129-character key).
- [ ] Screenshot: the popover as a view-only collaborator: labels listed, no Add/edit/remove controls.
- [ ] Screenshot: Project settings > Default labels with two labels and the "Unsaved. Save to apply…" hint.
- [ ] Screenshot: Project settings after closing with unsaved label changes: the one-time red "Your label changes aren't saved…" warning.
- [ ] Screenshot: composer "+" menu showing the Labels item with its count ("2 labels").
- [ ] Screenshot: the composer Labels dialog with a "from project" label and a user-added one, then the chips row under the composer after Done.
- [ ] Screenshot: the new session's popover after step 5 (only `ticket: 42`, the removed project default absent).

## Type of change

- [ ] Bug fix
- [x] Feature
- [x] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [ ] E2E tests added / updated
- [x] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Component tests cover the three editors and the create payloads; the server side is covered in the stacked server PR. There is no browser E2E for the labels journey; the manual steps above cover it end to end and the Demo media shows each state.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

View, add, edit and remove session labels in the web UI, set them when starting a session, and edit a project's default labels for its new sessions

🤖 Generated with [Claude Code](https://claude.com/claude-code)
