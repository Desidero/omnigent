# subscription-accounts+session-labels-ui

Joins: web/src/lib/projectsApi.ts, web/src/shell/ProjectSettingsDialog.tsx

Both series add a per-project default to the same places: a field of the
project config type (`provider`, `labels`), and in the Project settings dialog
its state, its reset when the dialog opens and its line in the save handler.
Neither uses what the other adds. The account's lines come first.
