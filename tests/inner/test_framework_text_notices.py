"""A framework text notice reaches the model on every harness family, never as user text.

The server may add framework-owned text to a message as a notice block (the
open items note, for one); these tests follow it to each harness's own
context channel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from omnigent.harnesses.codex_native import hook as codex_hook
from omnigent.harnesses.codex_native.app_server import _codex_policy_hooks_settings
from omnigent.harnesses.codex_native.bridge import CODEX_FRAMEWORK_CONTEXT_FILE
from omnigent.inner import claude_native_executor, codex_native_executor
from omnigent.inner import pi_native_executor as pne
from omnigent.inner.claude_native_executor import ClaudeNativeExecutor
from omnigent.inner.native_attachments import (
    expand_framework_notices,
    framework_notice_block,
    framework_notices,
    framework_text_notice_block,
    framework_text_notices,
    resize_notice,
)

_NOTE = '[Open items] Q3 "Region?" was labelled in chat without being recorded.'


def _content() -> list[dict[str, Any]]:
    return [{"type": "input_text", "text": "Next step"}, framework_text_notice_block(_NOTE)]


def test_text_notices_sit_beside_upload_notices() -> None:
    dimensions = {"width": 6000, "height": 4000}
    content = [*_content(), framework_notice_block(dimensions)]
    assert framework_notices(content) == [_NOTE, resize_notice(dimensions)]
    assert framework_text_notices(content) == [_NOTE]


def test_sdk_harnesses_read_the_note_as_system_context() -> None:
    """The provider boundary SDK harnesses share turns notices into system messages."""
    expanded = expand_framework_notices([{"role": "user", "content": _content()}])
    assert expanded == [
        {"role": "system", "content": [{"type": "input_text", "text": _NOTE}]},
        {"role": "user", "content": [{"type": "input_text", "text": "Next step"}]},
    ]


@pytest.mark.asyncio
async def test_claude_native_hands_the_note_to_its_prompt_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sent: list[str] = []

    def inject(bridge_dir: Path, *, content: str, **_: Any) -> None:
        sent.append(content)

    monkeypatch.setattr(claude_native_executor, "inject_user_message", inject)
    executor = ClaudeNativeExecutor(tmp_path)
    async for _ in executor.run_turn([{"role": "user", "content": _content()}], [], ""):
        pass
    assert sent == ["Next step"]
    assert (tmp_path / "pending_framework_context.txt").read_text() == _NOTE


def test_codex_native_hands_the_note_to_its_prompt_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    codex_native_executor._stage_framework_context(tmp_path, _content())
    assert (tmp_path / CODEX_FRAMEWORK_CONTEXT_FILE).read_text() == _NOTE
    # A message without a text notice leaves nothing for the hook.
    codex_native_executor._stage_framework_context(tmp_path / "none", ["plain"])
    assert not (tmp_path / "none").exists()

    monkeypatch.setattr("sys.stdin", type("Stdin", (), {"read": lambda self: "{}"})())
    assert codex_hook.main(["framework-context", "--bridge-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": _NOTE}
    }
    assert not (tmp_path / CODEX_FRAMEWORK_CONTEXT_FILE).exists()
    assert codex_hook.main(["framework-context", "--bridge-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""

    # Registered on every prompt, answering in the shell while no notice waits.
    settings = _codex_policy_hooks_settings(tmp_path, "/usr/bin/python3")
    [prompt_hooks] = settings["hooks"]["UserPromptSubmit"]
    [context_hook] = [
        hook for hook in prompt_hooks["hooks"] if "framework-context" in hook["command"]
    ]
    assert context_hook["command"].startswith("if [ ! -e ")
    assert "omnigent.harnesses.codex_native.hook" in context_hook["command"]


@pytest.mark.asyncio
async def test_pi_native_queues_the_note_beside_the_message(tmp_path: Path) -> None:
    executor = pne.PiNativeExecutor(bridge_dir=tmp_path)
    async for _ in executor.run_turn([{"role": "user", "content": _content()}], [], ""):
        pass
    [queued] = [json.loads(path.read_text()) for path in (tmp_path / "inbox").glob("*.json")]
    assert queued["content"] == "Next step"
    # The extension adds it as hidden context when the agent starts
    # (omnigent_pi_native_extension.test.js).
    assert queued["framework_context"] == _NOTE
