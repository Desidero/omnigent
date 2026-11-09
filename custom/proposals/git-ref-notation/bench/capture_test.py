"""Capture how chat renders issue/PR references and what the system prompt says.

Owns a server and runner per case (like the Pull Requests panel tests) so a
PATH-shimmed ``gh`` resolves a deterministic repository offline: one case whose
runner workspace is a git checkout with a GitHub ``origin``, one whose workspace
is a plain directory. Each case posts a scripted reply with mixed references,
then saves desktop and phone screenshots of the message, the links it rendered,
the panel's repository payload and the tail of the composed system prompt the
mock model received.

Run through ``run_capture.sh <label> <evidence-dir>`` from the checkout root.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, Playwright, expect

from tests._helpers.server_runner import server_runner
from tests._helpers.session import send_user_text
from tests.e2e_ui.conftest import configure_mock_llm
from tests.e2e_ui.github._gh_shim import create_session, make_checkout, stack_env, write_gh_shim

REPO = "example/project"
BRANCH = "topic"
PR = {
    "number": 7,
    "url": f"https://github.com/{REPO}/pull/7",
    "title": "Example change",
    "state": "OPEN",
    "isDraft": False,
    "author": {"login": "contributor"},
    "baseRefName": "main",
    "headRefName": BRANCH,
    "headRefOid": "a" * 40,
    "baseRefOid": "b" * 40,
    "body": "",
    "comments": [],
    "statusCheckRollup": [],
}
PROMPT = "What did you find?"
REPLY = """\
I looked at the related work:

- The crash was first reported in #4821 and the fix landed in PR #4830 \
(cherry-picked in pull #4835).
- The upstream behaviour comes from omnigent-ai/omnigent#11273, which also \
touched `web/src/lib/gitProviders.ts`.
- `git log --grep '#4821'` and `gh pr view 4830` show the history; the \
reference inside this code span stays plain: `#4830`.

```sh
gh pr checkout 4830   # not a reference: #4830
```

Issue #4821 is closed and PR #4830 merged yesterday; see also \
[the tracking issue](https://github.com/example/project/issues/4800).
"""
ASSISTANT = '[data-testid="message-bubble"][data-role="assistant"]'
OUT = Path(os.environ["GIT_REFS_EVIDENCE"])
LABEL = os.environ["GIT_REFS_LABEL"]


@pytest.fixture(params=["git", "plain"])
def case(
    request: pytest.FixtureRequest, built_spa: None, mock_llm_server_url: str, tmp_path: Path
) -> Iterator[tuple[str, str, str]]:
    kind = request.param
    binary = tmp_path / "bin"
    write_gh_shim(binary, repo=REPO, pr=PR)
    workspace = tmp_path / "workspace"
    if kind == "git":
        make_checkout(workspace, branch=BRANCH, remote=f"https://github.com/{REPO}.git")
    else:
        workspace.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    env = stack_env(binary, runtime, mock_llm_server_url)
    with server_runner(runtime, base_env=env, workspace=workspace) as stack:
        stack.start_runner()
        session_id = create_session(stack.base_url, stack.runner_id, workspace)
        yield kind, stack.base_url, session_id


def wait_for_reply(client: httpx.Client, session_id: str, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        items = client.get(f"/v1/sessions/{session_id}/items", timeout=10.0).json()["data"]
        for item in items:
            if item.get("type") == "message" and item.get("role") == "assistant":
                text = "".join(block.get("text", "") for block in item.get("content", []))
                if "Issue #4821" in text:
                    return
        time.sleep(1.0)
    raise RuntimeError(f"no assistant reply in session {session_id}")


def wait_for_repository(client: httpx.Client, session_id: str, *, expect_repo: bool) -> dict:
    """The panel's info once the repository resolves (or once it settles without one)."""
    deadline = time.monotonic() + 60.0
    github: dict = {}
    while time.monotonic() < deadline:
        github = client.get(f"/v1/sessions/{session_id}/resources/github", timeout=60.0).json()
        if not expect_repo or (github.get("repo") or {}).get("name_with_owner"):
            return github
        time.sleep(2.0)
    raise RuntimeError(f"repository never resolved for session {session_id}: {github}")


def last_instructions(mock_url: str) -> str:
    requests = httpx.get(f"{mock_url}/mock/requests", timeout=10.0).json()["requests"]
    for request in reversed(requests):
        if "instructions" in request and PROMPT in json.dumps(request):
            return request["instructions"]
    raise RuntimeError("the mock model received no request with instructions")


def test_capture(
    case: tuple[str, str, str], mock_llm_server_url: str, playwright: Playwright, browser: Browser
) -> None:
    kind, base_url, session_id = case
    OUT.mkdir(parents=True, exist_ok=True)
    configure_mock_llm(mock_llm_server_url, [{"text": REPLY}], match=PROMPT)
    with httpx.Client(base_url=base_url) as client:
        send_user_text(client, session_id=session_id, text=PROMPT)
        wait_for_reply(client, session_id)
        github = wait_for_repository(client, session_id, expect_repo=kind == "git")
    (OUT / f"{LABEL}-github-info-{kind}.json").write_text(
        json.dumps(
            {key: github.get(key) for key in ("available", "reason", "provider", "repo")}, indent=2
        )
        + "\n"
    )
    instructions = last_instructions(mock_llm_server_url)
    tail = "\n".join(instructions.splitlines()[-6:])
    (OUT / f"{LABEL}-system-prompt-{kind}.txt").write_text(
        f"# workspace: {kind} "
        f"({'git checkout with a GitHub origin' if kind == 'git' else 'plain directory'})\n"
        f"# last lines of the composed system prompt the mock model received "
        f"({len(instructions)} characters in all)\n\n{tail}\n"
    )

    for name, options in (
        ("desktop", {"viewport": {"width": 1280, "height": 860}}),
        ("phone", playwright.devices["iPhone 13"]),
    ):
        context = browser.new_context(**options)
        page = context.new_page()
        page.goto(f"{base_url}/c/{session_id}")
        bubble = page.locator(ASSISTANT).last
        expect(bubble).to_contain_text("Issue #4821", timeout=30_000)
        if kind == "git":
            # The repository arrives with the panel's lookup; give the links a moment.
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and bubble.locator("a").count() < 2:
                page.wait_for_timeout(500)
        else:
            page.wait_for_timeout(3000)
        bubble.scroll_into_view_if_needed()
        links = bubble.locator("a").evaluate_all(
            "els => els.map(a => ({text: a.textContent, href: a.getAttribute('href')}))"
        )
        (OUT / f"{LABEL}-{kind}-{name}-links.json").write_text(json.dumps(links, indent=2) + "\n")
        page.screenshot(path=str(OUT / f"{LABEL}-{kind}-{name}.png"), animations="disabled")
        context.close()
