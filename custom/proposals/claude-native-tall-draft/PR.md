<!--
Draft PR into omnigent-ai/omnigent, to be opened as a draft.
Title: fix(claude-native): read a draft scrolled inside its input box
Head: Desidero:fix/claude-native-tall-draft-ready (one commit, signed off)
Before opening: no upstream issue covers this yet. File one (text at the end of
this file) and put its number in "Closes #", or the needs-issue bot closes the PR.
-->

## Related issue

<!--
Link the issue this PR addresses with a closing keyword so GitHub auto-links it
(and closes it on merge): e.g. `Closes #123`. One issue per PR. Linking also
gives this PR the issue's priority in the review queue. If an older, still-open
community PR already closes the same issue, the newer one may be auto-closed as
a duplicate (maintainer PRs are exempt).

If this is either a `Refactor / chore`, `Docs`, or `Test / CI` *Type of change* 
below, then no issue is required to be associated. 
-->

Closes #<issue>

Related:
- [#13325](https://github.com/omnigent-ai/omnigent/pull/13325) (merged) added the end-of-draft marker for drafts whose first line scrolls away. It matches only rows under a `❯` row that is still on screen, so it does not reach the screen described here.
- [#13447](https://github.com/omnigent-ai/omnigent/pull/13447) and [#14636](https://github.com/omnigent-ai/omnigent/pull/14636) (open) change the delivery and recovery path that calls `_composer_box` and `_draft_in_input_box`. Neither changes how those functions read the box, and neither handles the `↑ N more` rule, so this fix is separate from both. Whichever PR lands second will need a small rebase in `bridge.py`.
- [#10483](https://github.com/omnigent-ai/omnigent/issues/10483) (open) is a different failure in a narrow pane: Claude Code never becomes ready in a pane only a few columns wide. A narrow pane wraps a paste into more rows, so it reaches the box's height cap sooner, but this PR does not address #10483.

## Summary

Long pasted messages could fail to reach a Claude Code (native) session. Claude Code caps the height of its input box. When a pasted draft is taller than the box, Claude Code keeps the draft's last rows in view and draws `─── ↑ N more ───` on the box's top border. The `❯` row scrolls out of view with the first rows:

```
─── ↑ 11 more ─────────────────────────────────
  Then ask a reviewer to weigh the general idea,
  what we have seen, and what they think makes
  the most sense.
───────────────────────────────────────────────
  ⏵⏵ auto mode on (shift+tab to cycle)
```

`_composer_box` only finds the box by a glyph row under its opening rule, so it reported this screen as having no input box. The paste wait never saw the draft, so delivery took the "paste dropped" recovery and waited for a `❯` row. That row cannot come back while the draft sits in the box. After 30 s the turn failed with `ClaudePromptTimeout`, the terminal was closed, and the message was never submitted. We have hit this repeatedly with long pasted messages.

The fix (18 lines in `omnigent/harnesses/claude_native/bridge.py`):

- `_composer_box` reads a box as an unframed box of its visible rows when its opening rule carries the `↑ N more` label and every non-blank row under it is indented. Unlabelled boxes, and boxes whose rows are not indented, are read as before.
- `_draft_in_input_box` matches the needle (or the end-of-draft marker from #13325) against those rows when there is no glyph row.

As a result, the paste is seen and submitted with the usual Enter verification and retries. A leftover draft of this shape counts as a scrolled draft and is cleared before delivery, like one taller than the pane. The same check now also verifies a pasted draft taller than the pane, which was previously submitted without verification.

## Test Plan

- New unit tests in `tests/harnesses/claude_native/test_claude_native_bridge.py`:
  - `test_a_draft_scrolled_inside_its_box_is_seen_by_its_end` uses a pane in this layout, modelled on a capture from Claude Code 2.1.332 in a 47-column pane. It checks that `_composer_box` reads the three visible rows, that `_draft_in_input_box` matches by the draft's end, and that `_occupying_surface` reports a scrolled draft.
  - `test_a_message_taller_than_the_input_box_is_submitted_and_verified` drives `inject_user_message` against the `_EditableComposer` fake, given a new `box_rows` option that caps the box and draws the `↑ N more` rule. It checks that the message is submitted.
- Both tests fail on `main` without the `bridge.py` change and pass with it.
- `uv run pytest tests/harnesses/claude_native/test_claude_native_bridge.py`: 1076 passed, 1 skipped. The existing menu, picker, transcript, shell-mode and permission-dialog fixtures in that file still pass, so none of them gains a new match.
- Limits: the tests use one screen layout from one Claude Code version. They do not prove the label check is safe across every Claude Code screen variant. The guards against false matches are the label on the rule above the rows and the indented rows.

## Demo

<!--
Choose the evidence format that applies. UI / frontend changes require video or
images. For non-visual changes, put reproducible evidence here or in Test Plan.
-->

- [ ] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

## Type of change

- [x] Bug fix
- [ ] Feature
- [ ] UI / frontend change
- [ ] Refactor / chore
- [ ] Docs
- [ ] Test / CI
- [ ] Breaking change

## Test coverage

<!-- Check all that apply. Be honest: reviewers and agents use this to spot coverage gaps. -->

- [x] Unit tests added / updated
- [ ] Integration tests added / updated
- [ ] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

<!--
Optional — but required if you checked "Manual verification completed" or
"Not applicable" above. Describe what you verified manually, or why automated
test coverage is not needed for this change.
-->

Unit tests only. There is no live Claude Code run in CI. The screen layout comes from a Claude Code 2.1.332 capture.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [x] No — no noteworthy user-facing change.
- [ ] Yes — include the entry in the Changelog section.

<!--
Choose Yes only for outstanding user-facing features, bug fixes, UX changes,
and breaking changes. Breaking changes must choose Yes and explain the
compatibility impact in Changelog. Features behind a feature flag are eligible
only once the flag is enabled for users.
Choose No for small fixes or improvements, features behind disabled flags, and
internal changes such as CI, refactors, test-only changes, or dependency bumps
with no user impact. Keep this section and both checkboxes.
This records the author's recommendation; maintainers curate the release notes.
-->

🤖 Generated with [Claude Code](https://claude.com/claude-code)

<!--
=========================================================================
Issue to file first (title and body). Not part of the PR body.
=========================================================================

Title: claude-native: a pasted message taller than the input box times out and closes the terminal

Claude Code caps the height of its input box. When a web message's pasted
draft is taller than the box, Claude Code shows the draft's last rows under a
`─── ↑ N more ───` top border, and the `❯` row scrolls out of view.
`_composer_box` in `omnigent/harnesses/claude_native/bridge.py` does not
recognise that box, so the bridge never sees the pasted draft. Delivery then
waits for a `❯` row that cannot return while the draft is in the box. After
30 s the turn fails with `ClaudePromptTimeout`, the terminal is closed, and
the message stays unsent.

Repro: in a claude-native session, send a message from the web UI that wraps
to more rows than the input box shows. A narrow terminal makes this easier.
Expected: the message is submitted. Actual: "Claude Code terminal did not
become ready" and the terminal is closed.

Claude Code version where seen: 2.1.332.
-->
