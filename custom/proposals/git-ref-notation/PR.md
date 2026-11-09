<!-- Draft PR body for the git-ref-notation series; title: feat(web): link issue and pull request references in chat and say which they are -->
## Related issue

Closes #TODO (issue to be opened from `issue.md`)

## Summary

When the agent writes `#123` in chat, the number now links to the right page on the session's git provider, and the agent is asked to write `issue #123` or `PR #123` so a reader does not have to remember which one it was.

Agents talk about issues and pull requests all the time, and a transcript full of bare `#123` leaves the reader to guess whether each one is an issue or a PR, then go and find it by hand. Two halves:

- **Web autolink.** A remark plugin (`web/src/lib/gitReferences.ts`) runs with the chat's other remark plugins and turns `#123`, `issue #123`, `PR #123` / `pull #123` / `merge request #123` and `owner/repo#123` in prose into links. A bare `#123` goes to the issue page (GitHub redirects to the pull request when the number is one); an explicit pull/merge-request form goes to the pull page; `!123` counts only on providers that write merge requests that way (GitLab, Azure DevOps), using the provider's `number_prefix`. URL shapes exist for GitHub, GitLab (`/-/issues`, `/-/merge_requests`) and Azure DevOps (work items and `_git/<repo>/pullrequest`); an unknown provider links nothing. Code spans, code blocks and existing links are never touched, and nothing links when the session has no repository.
- **Where the repository comes from.** The Pull Requests panel already resolves the session's provider and `repo.name_with_owner` (`usePullRequestInfo`, shared with the composer status line, so no extra request). A new `useSessionGitRepository` hook derives `{provider, host, repository, requestPrefix}` from it, with the host taken from a tracked PR when there is one (self-hosted instances) and the provider's own host otherwise, and `AppShell` / `GridSessionPane` put it on `FileViewerContext` next to the workspace paths. `FilePathAwareMessageResponse` adds the plugin when a repository is known. Streamdown's memo ignores `remarkPlugins`, so the message is keyed on the repository and re-parses once when the panel's lookup settles.
- **Framework instruction.** `GIT_REFERENCE_NOTATION_INSTRUCTION` in `omnigent/runtime/prompt.py` asks the model for `issue #123` / `PR #123` (or the provider's own notation) and `owner/repo#123` for another repository. The prompt composer only sees the `AgentSpec`, which carries no git signal, so the gate is the cheapest reliable one the runner already has for every turn: the session's resolved workspace (`_session_runtime_cwd`), checked with a stat walk for `.git` (`is_git_checkout`, a directory for a checkout, a file for a linked worktree, no git binary). `workspace_framework_instructions(workspace)` returns the instruction only for a checkout, and both runner composition paths pass it through the existing `framework_instructions` parameter, so the ordering rule holds: authored text, per-request text, spec-level framework guidance, then this. It reaches the harnesses that take composed instructions per turn; harnesses that take instructions only at launch are unchanged. The instruction costs 65 tokens.

## Test Plan

Tests added or changed:

- `web/src/lib/gitReferences.test.ts`: the matcher (kind words, bare numbers, other repositories, the provider's `!` marker, anchors/entities/identifiers/over-long numbers that must not match), the URL builder per provider, `sessionGitRepository` from the panel payload, and the remark transform (splits prose, leaves code spans, code blocks and links alone, no-op without matches).
- `web/src/components/blocks/ChatMarkdown.gitReferences.test.tsx`: a rendered message links its references to the session repository except inside code, and stays plain text without a repository.
- `tests/runtime/test_prompt.py`: `is_git_checkout` (checkout, nested directory, linked worktree, plain directory, missing path), the workspace gate, the ordering after spec-level framework text, and that the instruction names the forms the chat links.

```sh
cd web && pnpm exec vitest run src/lib/gitReferences.test.ts src/components/blocks/ChatMarkdown.gitReferences.test.tsx src/components/blocks/ChatMarkdown.fileLinks.test.tsx
cd web && pnpm exec tsc -b
uv run pytest tests/runtime/test_prompt.py
uv run pytest tests/runner/test_runner_dispatch.py -k "instruction or contract or compose"
pre-commit run --from-ref upstream/main --to-ref HEAD
```

Manual check, on a session whose workspace is a GitHub checkout and one whose workspace is a plain directory: ask the agent (or script a mock reply) for a message with `#N`, `PR #N`, `owner/repo#N` and the same inside backticks; in the checkout session the references are links to the provider and the backticked ones are not; in the plain session nothing links. With the mock model, the request's `instructions` end with the notation sentence only for the checkout session.

Benchmark (median, jsdom, Node 22; the `bench/` scripts beside the evidence reproduce it: `token_count.py`, `run_bench.sh`):

| What | Before | After | How measured |
| --- | --- | --- | --- |
| Tokens the instruction adds to a checkout session's system prompt | 0 | 65 (o200k_base and cl100k_base, separator included) | `tiktoken` over the constant |
| Reference scan, 31 KB message, 0 references | n/a | 0.33 ms | `findGitReferences` |
| Reference scan, 42 KB message, 800 references | n/a | 0.67 ms | `findGitReferences` |
| remark transform, 31 KB / 0 references | n/a | 0.55 ms | `remarkGitReferences` over the parsed paragraphs |
| remark transform, 42 KB / 800 references | n/a | 0.88 ms | same |
| Full chat render, 31 KB, 0 references | 102 ms | 92 ms (plugin on, nothing to link) | `FilePathAwareMessageResponse` in jsdom |
| Full chat render, 29 KB, 14 references | 85 ms | 89 ms | same |
| Full chat render, 42 KB, 800 references | 113 ms | 286 ms | same; the extra time is React rendering 600 link elements, not the matcher |

## Demo

- [x] Visual demo attached below
- [x] Non-visual evidence provided below or in Test Plan
- [ ] Not applicable — no behavioral change

Before (`main @ 65be0f2468`, repository resolved, references are plain text): `evidence/before-git-desktop.png`, `evidence/before-git-phone.png`.
After, same session shape: `evidence/after-git-desktop.png`, `evidence/after-git-phone.png`; the plain-directory session stays unlinked: `evidence/after-plain-desktop.png`.
Links rendered, as text/href pairs: `evidence/after-git-desktop-links.json` (seven) against `evidence/before-git-desktop-links.json` (one, the explicit markdown link).
System prompt tail with and without a checkout: `evidence/after-system-prompt-git.txt`, `evidence/after-system-prompt-plain.txt` (before: `evidence/before-system-prompt-git.txt`, identical to plain).
`evidence/README.md` describes each capture and how it was made. Captures: harness `openai-agents` (SDK) against the mock model, OSS deployment, `gh` shimmed to report `example/project`.

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

Unit tests cover the matcher, URL builder, payload derivation, remark transform, the rendered links and the prompt gate. The end-to-end journey (panel lookup feeding the chat, the instruction reaching the model) was verified by hand on an isolated stack with the gh shim, see Demo; no new E2E test, since the two halves are each covered at their own layer and the browser boundary is exercised by the render test.

## Release notes

Should this change be included in the release notes? Choose exactly one.

- [ ] No — no noteworthy user-facing change.
- [x] Yes — include the entry in the Changelog section.

## Changelog

Issue and pull request references in chat (`#123`, `PR #123`, `owner/repo#123`) link to the session's repository, and agents are asked to say which kind each reference is

🤖 Generated with [Claude Code](https://claude.com/claude-code)
