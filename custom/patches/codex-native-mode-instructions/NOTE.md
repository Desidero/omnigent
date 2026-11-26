# codex-native-mode-instructions

Needs: none
Covers: 4b841f48744bec0f

A Default-mode Codex turn keeps Codex's own Default mode instructions instead
of having them replaced by the agent's developer instructions (the Plan toggle
already does this upstream).

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/codex-native-default-mode-instructions`.

## Must hold

- A Default-mode Codex turn sends `developer_instructions: null` in its collaboration mode, so Codex applies its built-in Default mode instructions.
- The agent's configured developer instructions are never echoed into the collaboration mode; they still reach Codex through its own config (`config.toml`).

## Key code

- `omnigent/harnesses/codex_native/forwarder.py`: `_default_collaboration_mode`

## Tests

- `tests/harnesses/codex_native/forwarder/test_instructions.py::test_default_collaboration_mode_keeps_codex_mode_instructions`
