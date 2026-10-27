"""Seed a history-only session with realistic tool-call output for the items benchmark.

Usage: python seed_session.py --server http://127.0.0.1:18803 [--pairs 150] [--title ...]
Prints the new session id. Items are seeded through POST /v1/sessions
(host_type=external, initial_items), so no runner or model is involved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys

import httpx

HEADERS = {"X-Forwarded-Email": "bench@example.com"}
# Deterministic id of the built-in Claude native agent (omnigent.db.utils.builtin_agent_id).
AGENT_NAME = "claude-native-ui"


def builtin_agent_id(name: str) -> str:
    return hashlib.sha256(f"builtin:{name}".encode()).hexdigest()[:32]


def fake_source(rng: random.Random, lines: int) -> str:
    out = []
    for i in range(lines):
        kind = rng.choice(["def", "if", "return", "x =", "#", "for"])
        out.append(f"{'    ' * rng.randint(0, 3)}{kind} value_{i} = compute_{rng.randint(0, 999)}(arg_{i}, {rng.random():.6f})  # line {i}")
    return "\n".join(out)


def tool_pair(rng: random.Random, index: int) -> tuple[dict, dict]:
    call_id = f"call_{index:05d}"
    kind = rng.choice(["read", "read", "bash", "grep", "edit"])
    if kind == "read":
        path = f"src/module_{index % 37}/file_{index}.py"
        args = {"file_path": path}
        body = fake_source(rng, rng.randint(60, 160))
        output = "\n".join(f"{n + 1:6d}\t{line}" for n, line in enumerate(body.split("\n")))
        name = "Read"
    elif kind == "bash":
        args = {"command": f"pytest tests/test_{index}.py -q", "description": "Run tests"}
        stdout = "\n".join(f"tests/test_{index}.py::test_case_{i} PASSED" for i in range(rng.randint(40, 120)))
        output = json.dumps({"stdout": stdout, "stderr": "", "exit_code": 0, "timed_out": False, "cwd": "/workspace"})
        name = "Bash"
    elif kind == "grep":
        args = {"pattern": f"symbol_{index}", "path": "src"}
        output = "\n".join(f"src/pkg_{i % 9}/mod_{i}.py:{rng.randint(1, 400)}:    symbol_{index} = helper_{i}()" for i in range(rng.randint(30, 90)))
        name = "Grep"
    else:
        args = {"file_path": f"src/file_{index}.py", "old_string": "a = 1", "new_string": "a = 2"}
        output = f"The file src/file_{index}.py has been updated successfully."
        name = "Edit"
    call = {
        "type": "function_call",
        "data": {"agent": AGENT_NAME, "name": name, "arguments": json.dumps(args), "call_id": call_id},
    }
    result = {"type": "function_call_output", "data": {"call_id": call_id, "output": output}}
    return call, result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:18803")
    parser.add_argument("--pairs", type=int, default=150)
    parser.add_argument("--title", default="Lean history benchmark")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    items: list[dict] = []
    for index in range(args.pairs):
        if index % 10 == 0:
            items.append({"type": "message", "data": {"role": "user", "content": [{"type": "input_text", "text": f"Please look at batch {index // 10}."}]}})
            items.append({"type": "message", "data": {"role": "assistant", "agent": AGENT_NAME, "content": [{"type": "output_text", "text": f"Looking at batch {index // 10} now."}]}})
        call, result = tool_pair(rng, index)
        items.extend([call, result])
    body = {"agent_id": builtin_agent_id(AGENT_NAME), "host_type": "external", "title": args.title, "initial_items": items}
    with httpx.Client(base_url=args.server, headers=HEADERS, timeout=120) as client:
        resp = client.post("/v1/sessions", json=body)
        if resp.status_code != 201:
            print(resp.status_code, resp.text[:500], file=sys.stderr)
            return 1
        session = resp.json()
    outputs = [len(i["data"]["output"]) for i in items if i["type"] == "function_call_output"]
    print(json.dumps({"session_id": session["id"], "items": len(items), "tool_outputs": len(outputs), "output_chars_total": sum(outputs), "output_chars_mean": sum(outputs) // len(outputs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
