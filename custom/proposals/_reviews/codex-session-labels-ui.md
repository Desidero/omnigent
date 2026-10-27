# Codex review: session-labels-ui (server PR feat/session-labels-api and web PR feat/session-labels-ui)

Command: `codex exec -C <worktree> --sandbox danger-full-access "<review prompt>, reviewing the diff of \`git diff <base>...HEAD\`"` (codex-cli 0.159.2, model gpt-6.1-sol).
`codex review --base upstream/main` and `codex exec --sandbox read-only` both failed in this environment: the bundled bubblewrap sandbox cannot set up loopback (`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`), so the review ran unsandboxed with a "do not modify any file" instruction; `git status` was clean afterwards.

## Server commit (`git diff upstream/main...HEAD` on feat/session-labels-api)

### Raw findings

60,472
Found one issue I would request changes for:

- **[P2] Mixed label deletes and upserts are not atomic** — [routes_core.py:3315](omnigent/server/routes/sessions/routes_core.py:3315). Each `delete_label()` commits separately, before `set_labels()` opens another transaction. If the upsert fails, the PATCH fails but its deletions remain committed. Concurrent readers can also observe partially applied label changes. Previously, ordinary label updates used the store’s atomic bulk upsert.

  **Reproduce:** On PostgreSQL, seed `team=ml`, then PATCH `{"labels":{"team":null,"env":"\u0000"}}`. PostgreSQL rejects the NUL-containing value, but `team` has already been deleted.

  **Requested change:** Apply label deletions and upserts in one store transaction. Add a regression test that forces the upsert to fail and verifies that deleted labels survive rollback; the added tests cover only successful mixed updates.

`CLAUDE.md` points to `AGENTS.md`; I found no additional actionable convention violations. `git diff --check upstream/main...HEAD` passed. I did not run tests because they create files, which would violate the read-only constraint.

### Disposition

- P2 mixed deletes and upserts not atomic: **fixed**. `ConversationStore.set_labels` takes `delete_keys`; the SQLAlchemy store deletes and upserts in one `run_write_transaction`, and the PATCH route makes one call. Store test `test_set_labels_rolls_back_deletes_when_the_upsert_fails` and route test `test_patch_session_mixed_label_edit_is_atomic` force the upsert to fail and assert the deleted label survives. Test fakes that implement `set_labels(conversation_id, updates)` keep working because the route passes `delete_keys` only when there is a delete.

## Web commit (`git diff feat/session-labels-api...HEAD` on feat/session-labels-ui)

### Raw findings

76,828
I would request changes for three issues in the web-only diff:

1. **[P2] Save/Done silently drops edits to an existing label.**  
   [LabelEditor.tsx:150](web/src/components/LabelEditor.tsx:150) returns `"none"` whenever the add row isn’t active, ignoring `editingKey` and `editValue`. Both Project settings’ Save and the new-session dialog’s Done rely on this handle, so they close successfully while retaining the previous value.

   **Reproduce:** edit an existing default label from `team: ml` to `team: infra`, then click the dialog’s Save directly, without clicking the row’s checkmark. Reopen settings: it still says `ml`. The same happens with Done in the new-session labels dialog. Collect and validate pending edits as well as additions; add coverage for both outer buttons.

2. **[P2] Label choices are lost when the new-session draft is restored.**  
   [NewChatDialog.tsx:2622](web/src/shell/NewChatDialog.tsx:2622) initializes label edits independently of `restoredDraft`, and the existing `LandingDraft` snapshot never includes them. Navigating away preserves the prompt and other composer settings but loses added labels, overrides, and removed-default tombstones. The failed-create recovery path also restores this incomplete draft after the composer has unmounted.

   **Reproduce:** start a draft in a project with `team: ml`, remove that default, add `env: dev`, visit an existing session, then return to New chat for the same project. `env` disappears and `team` returns. Include label edits in draft persistence/recovery and extend the navigation/recovery coverage.

3. **[P2] The labels dialog can grow beyond the viewport with no scrolling.**  
   [NewSessionLabels.tsx:90](web/src/components/composer/NewSessionLabels.tsx:90) gives the dialog only a width constraint. Its label list has no height constraint or overflow handling, and shared `DialogContent` doesn’t provide scrolling. With enough labels, the centered panel extends above and below the viewport, making rows and Done unreachable. Project defaults can populate this state immediately.

   **Reproduce:** configure roughly 20 default labels, open the new-session Labels dialog at a small desktop or mobile viewport, and try reaching every row and Done. Constrain the panel height and provide a scrollable body; verify this in a browser.

The added tests cover the basic CRUD paths but miss these cases. `git diff --check feat/session-labels-api...HEAD` passed. I did not run tests or builds because those can create files, contrary to the read-only constraint. No files were changed.

### Disposition

1. P2 Save/Done drops an edit in progress: **fixed**. `LabelEditorHandle.takePendingLabel` now also commits (or rejects inline) an edit in progress, so Project settings Save and the composer's Done keep it. Tests: `saves an edit still in progress when Save is clicked`, `blocks Save while an edit in progress is invalid` (ProjectSettingsDialog), `keeps an edit still in progress when Done is clicked` (NewChatDialog.projectCreate).
2. P2 label choices lost when the draft is restored: **fixed**. `LandingDraft.labelEdits` carries the raw edits; `useNewSessionLabels` takes them as initial state (and no longer strips removed defaults on first mount); a draft restored under another project keeps added labels and drops that project's removed defaults. Test: `restores label edits with the composer draft`.
3. P2 labels dialog can outgrow the viewport: **fixed**. `NewSessionLabelsDialog` uses the repo's `flex max-h-[85vh] flex-col` dialog pattern (AddAgentDialog) with a `min-h-0 overflow-y-auto` body around the editor. No component test (layout); verified by eye in the browser captures.
