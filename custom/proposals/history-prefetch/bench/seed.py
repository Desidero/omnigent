"""Seed a long mixed transcript for the history scroll-up bench.

Usage: uv run --no-sync python bench/seed.py <base_url> <sqlite_db_path> [turns]

Creates a hello_world session over the API (bundle upload, no runner) and
appends `turns` settled turns straight into the store, each: a user prompt,
an assistant preamble, two shell tool calls with multi-line output, and an
assistant markdown summary. 60 turns = 420 items.
"""

from __future__ import annotations

import gzip
import io
import json
import sys
import tarfile

import httpx

AGENT_YAML = """\
name: hello_world
prompt: You are a friendly assistant. Say hello and answer questions.

executor:
  model: gpt-4o-mini
  harness: openai-agents
"""


def bundle() -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        data = AGENT_YAML.encode()
        info = tarfile.TarInfo(name="hello_world.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def tool_output(turn: int, call: int) -> str:
    lines = [f"$ step {turn}.{call}: scanning module {turn * 7 + call}"]
    for line in range(12 + (turn * 3 + call) % 20):
        lines.append(f"  src/pkg/module_{turn}/file_{line:02d}.py:{line * 13}: match {line}")
    lines.append(f"done: {len(lines) - 1} matches")
    return "\n".join(lines)


def seed(base_url: str, db_path: str, turns: int) -> str:
    from omnigent.entities import (
        FunctionCallData,
        FunctionCallOutputData,
        MessageData,
        NewConversationItem,
    )
    from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

    resp = httpx.post(
        f"{base_url}/v1/sessions",
        data={"metadata": json.dumps({"title": f"history bench {turns} turns"})},
        files={"bundle": ("agent.tar.gz", bundle(), "application/gzip")},
        timeout=30.0,
    )
    resp.raise_for_status()
    session_id = resp.json()["session_id"]

    items: list[NewConversationItem] = []
    for turn in range(turns):
        rid = f"resp_{turn:03d}"
        items.append(
            NewConversationItem(
                type="message",
                response_id=rid,
                data=MessageData(
                    role="user",
                    content=[
                        {
                            "type": "input_text",
                            "text": f"Turn {turn}: please inspect module {turn} and summarise what "
                            f"it does, then list the two riskiest functions.",
                        }
                    ],
                ),
            )
        )
        items.append(
            NewConversationItem(
                type="message",
                response_id=rid,
                data=MessageData(
                    role="assistant",
                    content=[
                        {
                            "type": "output_text",
                            "text": f"Looking at module {turn} now. I'll grep for the entry points "
                            f"first and then read the hot paths.",
                        }
                    ],
                    agent="hello_world",
                ),
            )
        )
        for call in range(2):
            call_id = f"call_{turn:03d}_{call}"
            items.append(
                NewConversationItem(
                    type="function_call",
                    response_id=rid,
                    data=FunctionCallData(
                        agent="hello_world",
                        name="shell",
                        arguments=json.dumps({"command": f"grep -rn 'def ' src/pkg/module_{turn} | head -{20 + call}"}),
                        call_id=call_id,
                    ),
                )
            )
            items.append(
                NewConversationItem(
                    type="function_call_output",
                    response_id=rid,
                    data=FunctionCallOutputData(call_id=call_id, output=tool_output(turn, call)),
                )
            )
        bullets = "\n".join(
            f"- `func_{turn}_{i}` — {'reads user input without validation' if i % 2 else 'holds a lock across an await'}"
            for i in range(2 + turn % 3)
        )
        items.append(
            NewConversationItem(
                type="message",
                response_id=rid,
                data=MessageData(
                    role="assistant",
                    content=[
                        {
                            "type": "output_text",
                            "text": f"## Module {turn} summary\n\nModule {turn} wires the request "
                            f"pipeline for feature {turn % 9}. It exposes {3 + turn % 5} public "
                            f"functions and one background worker.\n\nRiskiest functions:\n\n{bullets}\n\n"
                            + ("The worker also retries forever on a closed socket, which is worth a follow-up.\n" * (turn % 4)),
                        }
                    ],
                    agent="hello_world",
                ),
            )
        )
    SqlAlchemyConversationStore(f"sqlite:///{db_path}").append(session_id, items)
    return session_id


if __name__ == "__main__":
    base, db = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    print(seed(base, db, n))
