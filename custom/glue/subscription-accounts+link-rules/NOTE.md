# subscription-accounts+link-rules

Joins: omnigent/runner/native/orchestration.py

Each series adds a module-level helper for native launches at the same place
in the runner's orchestration module, before
`_native_startup_instructions_from_spec`: `_claude_native_pinned_provider`
(the account an agent spec pins) and `_launch_link_rules` (the user's chat
link rules). Neither calls the other. The account helper comes first.
