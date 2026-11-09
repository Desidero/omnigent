<!-- Feature request draft for the git-ref-notation series; shape of .github/ISSUE_TEMPLATE/feature_request.yml -->
Title: [Feature] Link issue and pull request references in chat, and have the agent say which kind each one is

### Problem or use case

Agents mention issues and pull requests constantly ("fixed in #4830", "see #4821"), but in the chat those references are plain text, and a bare `#123` does not say whether it is an issue or a pull request. The reader has to remember, or open the provider and search, every time. The session already knows its repository (the Pull Requests panel resolves the provider and `owner/repo` from the workspace), so the chat has what it needs to make each reference one click away.

Version: `main @ 65be0f2468`.

### Proposed solution

Two halves:

1. In the web chat, render `#123`, `issue #123`, `PR #123` / `pull #123` and `owner/repo#123` in prose as links to the session's repository on its git provider: a bare `#123` to the issue page (GitHub redirects it to the pull request when it is one), an explicit `PR #123` to the pull page, `owner/repo#123` to that repository, and the provider's own notation where it differs (`!123` for a GitLab merge request). Never link inside code spans or code blocks, and link nothing when the session has no repository.
2. Add a one-sentence framework instruction, gated like the existing ones, asking the model to write `issue #123` or `PR #123` (or the provider's notation) and `owner/repo#123` for another repository, so the text itself says which kind a reference is. Only sessions working in a git checkout should get it.

### Alternatives considered

- Resolving each number against the provider API to label it an issue or a PR: a network call per reference on every render, needs credentials in the browser, and still leaves the text ambiguous for anyone reading a copy of the transcript. Asking the model to write the kind is free and survives copy/paste.
- Linking in the markdown renderer only, without the instruction: works, but `#123` still reads the same for both kinds.
- Only the instruction, without links: the reader still has to go and find the page.

### Harness

Not applicable

### Platform or device

Not platform-specific

### Harness mode

Not applicable

### Expected reach

Most users

### Authentication type

Not authentication-related
