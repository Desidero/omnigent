# Evidence: issue and pull request references in chat

The screenshots listed below are kept outside the repository; attach them to the upstream PR.

All captures come from an isolated local stack (server, runner and mock model
on private ports, `gh` replaced by the Pull Requests panel tests' shim that
reports the repository `example/project`). The model reply is scripted and
identical in every capture: a message with `#4821`, `PR #4830`, `pull #4835`,
`omnigent-ai/omnigent#11273`, `Issue #4821`, the same numbers inside a code
span and a code block, and one explicit markdown link. Two cases per revision:
`git` (the runner workspace is a one-commit checkout whose `origin` is on
GitHub) and `plain` (an empty directory).

`before-*` is `main @ 65be0f2468`; `after-*` is the same checkout with the
change applied. Both were produced by the same script
(`bench/run_capture.sh`, a pytest capture placed beside the panel tests for
its fixtures), with the web UI rebuilt for each revision.

| File | What it shows |
| --- | --- |
| `before-git-desktop.png` | Desktop (1280x860): with a resolved repository, only the explicit markdown link is a link; every reference is plain text. |
| `before-git-phone.png` | The same message at the iPhone 13 viewport. |
| `before-plain-desktop.png`, `before-plain-phone.png` | The plain-directory session, same rendering. |
| `before-git-desktop-links.json`, `before-git-phone-links.json`, `before-plain-*-links.json` | Every `<a>` in the assistant message (text and href): one link, the explicit one. |
| `before-github-info-git.json`, `before-github-info-plain.json` | The panel's info payload: `example/project` resolved for the checkout, `not_a_git_repo` for the plain directory. |
| `before-system-prompt-git.txt`, `before-system-prompt-plain.txt` | Tail of the composed system prompt the mock model received; identical for both workspaces, ending with the embedded-browser guidance. |
| `after-git-desktop.png` | Desktop: `#4821` and `Issue #4821` link to the issue page, `PR #4830` and `pull #4835` to the pull page (with the panel's pull request icon), `omnigent-ai/omnigent#11273` to that repository; the code span and code block stay plain. |
| `after-git-phone.png` | The same at phone width; links wrap with the prose, no horizontal scroll. |
| `after-plain-desktop.png`, `after-plain-phone.png` | The plain-directory session: no repository, so references stay plain text. |
| `after-git-*-links.json` | Seven links: the six references plus the explicit link, with their hrefs. |
| `after-plain-*-links.json` | One link, the explicit one. |
| `after-github-info-*.json` | Same payloads as before (the panel is unchanged). |
| `after-system-prompt-git.txt` | The prompt tail now ends with the reference-notation instruction (932 characters in all). |
| `after-system-prompt-plain.txt` | The plain directory's prompt is unchanged (692 characters): the instruction is absent without a checkout. |

Captions for the PR: commit as listed in the PR; harness `openai-agents`
(SDK transport) against the mock model; OSS deployment; entry point: the
session chat view (`/c/<id>`), desktop and phone viewports.
