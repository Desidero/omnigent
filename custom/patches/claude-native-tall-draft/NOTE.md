# claude-native-tall-draft

Needs: none
Covers: 1b787200ab626844

A web message sent to a Claude Code (native) session gets delivered even when
its pasted draft is taller than Claude Code's input box. Claude Code caps the
box's height. A taller draft keeps its last rows in view, the box's opening
rule reads `↑ N more`, and the `❯` row scrolls out of view. The bridge read
that screen as having no input box, so delivery waited for a prompt row that
never came, failed the turn with `ClaudePromptTimeout` and closed the
terminal. Upstream's end-of-draft marker
([#13325](https://github.com/omnigent-ai/omnigent/pull/13325)) only matches a
box whose `❯` row is still on screen.

- **Turn on:** on by default.
- **Docs:** none (fix).
- **Upstream:** proposed from `fix/claude-native-tall-draft-ready` (pull request not opened yet).

## Must hold

- An opening rule labelled `↑ N more` above indented rows is read as the input box (unframed, its visible rows). The pasted draft is seen by its end and submitted with the usual Enter verification.
- A leftover draft of that shape counts as a scrolled draft, and is cleared before delivery like one taller than the pane.
- A box with no label, or with rows that are not indented, is read as before. Menus, pickers, transcript text and permission dialogs gain no new match.

## Key code

- `omnigent/harnesses/claude_native/bridge.py`: `_BOX_SCROLLED_LABEL_RE`, `_composer_box`, `_draft_in_input_box`

## Tests

- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_a_draft_scrolled_inside_its_box_is_seen_by_its_end`
- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_a_message_taller_than_the_input_box_is_submitted_and_verified`
