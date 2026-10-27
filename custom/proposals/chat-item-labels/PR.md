<!-- Draft PR body for the chat-item-labels series; title: feat(web): preview, close and track labelled items in chat -->
## Related issue

Closes #TODO (issue to be opened)

## Summary

Depends on: run-suggested-commands, codex-native-mode-instructions (stacked; would be rebased or split for upstream).

When an agent tags things it raises with short labels like [Q2] or [R1], a later "still need your call on [Q2]" becomes a chip you can click to see the original question, and a pinned list shows which items are still open.

Long agent sessions raise several items in one verbose reply, then refer back to them across many short updates. Finding the original detail means scrolling back or spending a turn asking for a recap.

- **Labels and chips.** A label is one to three capitals plus one to three digits in brackets (`[Q2]`, `[R12]`), so task-list `[x]`, footnotes `[1]` and markdown link text never match. The first message carrying a label defines the item and shows the label as a static badge. Later mentions, in agent or user messages, render as chips; clicking one (or hovering with a desktop mouse) opens a popover with the defining block (its list item, heading section, table row or paragraph) and a "Show in conversation" link that reuses the existing `?message=` deep link.
- **Closing items.** A struck-through mention (`~~[Q2]~~`) closes the item: its chips are struck everywhere and the popover adds the sentence that closed it. The newest mention decides, so a later plain mention reopens it.
- **Open items panel.** A pinned "Open items" panel above the thread lists open labels as chips (as many as fit, then "+N") and, when expanded, every item with its title, with closed items folded under "Closed".
- **Only when used.** Labels render only once the transcript uses them (a label recurs across messages, or one message tags several items), so a stray bracketed code like `[A4]` in an unrelated session stays plain text.
- **Agent instruction.** Agents only label and close items when told to, so this adds `ITEM_LABEL_INSTRUCTION` to the framework instructions in `omnigent/runtime/prompt.py`, for every agent. SDK harnesses get it each turn with the other framework instructions. claude-native and codex-native take instructions only at launch, so a new `native_startup_instructions()` appends the static instruction to the agent's own instructions on `--append-system-prompt` and `developer_instructions`, for both runner-created and CLI-launched sessions. Other native harnesses have no instruction channel and are unchanged.
- **One `--append-system-prompt`.** Claude Code honours only the last `--append-system-prompt`, so a user-supplied one is now merged into the single flag Omnigent passes rather than shadowed by it.
- **Why the codex-native dependency.** With the instruction always present, codex-native always has `developer_instructions`; the codex-native-mode-instructions fix keeps those from replacing Plan mode's built-in instructions.

If maintainers prefer, this can be split into a renderer-only PR (chips, popover, panel; no prompt change) and a separate PR that adds the instruction.

Docs: new `docs/chat-item-labels.md` describes the label shape, when labels render, chips, closing and the Open items bar.

## Test Plan

Tests added or changed:

- `web/src/lib/itemLabels.test.ts`: label matching, defining-block extraction (list item, nested item, heading section, table row, paragraph), index build, close/reopen, the "only when used" rule, titles and closing sentences.
- `web/src/components/blocks/ChatMarkdown.itemLabels.test.tsx`: chip popover and deep link, static badge in the defining message, struck chips, desktop hover, no hover on touch.
- `web/src/components/chat/OpenItemsPanel.test.tsx`: open/closed listing, outside-press collapse, hidden until labels are used, chip fitting with "+N".
- `web/src/hooks/useHoverPopover.test.tsx`: hover delay, pin on click, focus handling, touch ignored.
- `tests/runtime/test_prompt.py`, `tests/runner/test_runner_dispatch.py`, `tests/spec/test_resolve_agent_bundle.py`: the instruction is appended for every agent; its examples match the chat's label shape.
- `tests/harnesses/claude_native/test_claude_native.py`, `tests/harnesses/codex_native/test_codex_native.py`, `tests/runner/test_app_sessions_native_terminals_autocreate.py`, `tests/runner/test_app_sessions_native_terminals_runtime.py`: native launches carry the instruction after the author text.
- `tests/harnesses/claude_native/test_claude_native_bridge.py::test_augment_claude_args_merges_caller_system_prompt`: a caller's `--append-system-prompt` (both `flag value` and `flag=value` forms) is merged into one flag.
- `tests/e2e_ui/chat/test_item_label_chips.py`: browser journey covering chips, popover, closing, the panel, deep link, and reload at phone width.

```sh
cd web && pnpm exec vitest run src/lib/itemLabels.test.ts src/components/blocks/ChatMarkdown.itemLabels.test.tsx \
  src/components/chat/OpenItemsPanel.test.tsx src/hooks/useHoverPopover.test.tsx
cd web && pnpm exec tsc -b
uv run pytest tests/runtime/test_prompt.py tests/runner/test_runner_dispatch.py tests/spec/test_resolve_agent_bundle.py \
  tests/harnesses/claude_native/test_claude_native.py tests/harnesses/claude_native/test_claude_native_bridge.py \
  tests/harnesses/codex_native/test_codex_native.py tests/runner/test_app_sessions_native_terminals_autocreate.py \
  tests/runner/test_app_sessions_native_terminals_runtime.py
uv run pytest tests/e2e_ui/chat/test_item_label_chips.py
```

Manual:

1. Start a session with any agent and ask: "Audit a hypothetical database migration and raise three open questions and one risk for me."
2. The reply tags items as `[Q1] **Title** ...`, `[R1] ...`. The labels in that reply are static badges, and an "Open items" panel appears above the thread.
3. Ask "What's still open?". In the reply, click the `[Q2]` chip: the popover shows only Q2's block, not the whole message. Click "Show in conversation": the transcript jumps to the defining message.
4. Reply "[Q2] copy them as-is". The agent answers with `~~[Q2]~~ ...`. Q2's chips are struck everywhere, its popover shows the closing sentence, and the panel count drops; expand the panel to see Q2 under "Closed".
5. Mention "[Q2]" again without strikethrough: the item reopens.
6. On desktop, hover a chip to preview it; on a phone, a tap opens it and hover does nothing.
7. In an unrelated session, type a message containing a single `[A4]`: it stays plain text and no panel appears.
8. Launch claude-native with a pass-through `--append-system-prompt "Answer tersely."` (e.g. `omnigent claude --append-system-prompt "Answer tersely."`): both the user prompt and the item-label instruction apply (Claude follows the terse style and uses labels).

## Demo

- [ ] Visual demo attached below
- [ ] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

- [ ] TODO: recording of clicking a later `[Q2]` chip, the popover, and "Show in conversation" (throwaway server, dummy migration-audit conversation)
- [ ] TODO: screenshot of struck chips and the popover's closing sentence after `~~[Q2]~~`
- [ ] TODO: screenshot of the Open items panel collapsed (chips with "+N") and expanded (titles, Closed section)
- [ ] TODO: mobile-width screenshot of a chip popover and the panel
- [ ] TODO: desktop hover preview recording

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
- [x] E2E tests added / updated
- [ ] Manual verification completed
- [ ] Existing tests cover this change
- [ ] Not applicable

## Coverage notes

Parsing, indexing and block extraction are covered at the unit level; rendering and hover behaviour by component tests; one browser journey covers the full flow with a mock LLM, including reload at phone width. Instruction delivery is covered per launch path (SDK per-turn, claude-native and codex-native for runner-created and CLI-launched sessions).

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Agents tag questions, risks and follow-ups with labels such as [Q2]; later mentions become chips that preview the original item, closed items are struck through, and a pinned panel lists what is still open
