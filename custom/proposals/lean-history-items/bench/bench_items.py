"""Measure the items list route: bytes on the wire and localhost round-trip time.

Usage: python bench_items.py --server URL --session ID [--runs 15] [--label before]
Measures GET /v1/sessions/{id}/items for 20- and 200-item pages, full and lean
(tool_output=preview), with Accept-Encoding identity and gzip, plus the
per-item GET /items/{item_id} when the server has it. Writes <label>.json and
prints a markdown table. On a baseline server the lean flag is ignored and the
per-item route is 404; both are reported as such.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time

import httpx

HEADERS = {"X-Forwarded-Email": "bench@example.com"}


def timed_get(client: httpx.Client, url: str, params: dict, gzip: bool, runs: int) -> dict:
    headers = {"Accept-Encoding": "gzip" if gzip else "identity"}
    elapsed: list[float] = []
    wire = 0
    body = 0
    status = 0
    encoding = ""
    for _ in range(runs):
        start = time.perf_counter()
        resp = client.get(url, params=params, headers=headers)
        resp.read()
        elapsed.append((time.perf_counter() - start) * 1000)
        wire = resp.num_bytes_downloaded
        body = len(resp.content)
        status = resp.status_code
        encoding = resp.headers.get("content-encoding", "none")
    return {
        "status": status,
        "wire_bytes": wire,
        "body_bytes": body,
        "content_encoding": encoding,
        "ms_median": round(statistics.median(elapsed), 1),
        "ms_p90": round(sorted(elapsed)[int(len(elapsed) * 0.9) - 1], 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:18803")
    parser.add_argument("--session", required=True)
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--label", default="bench")
    args = parser.parse_args()
    items_url = f"/v1/sessions/{args.session}/items"
    rows: list[dict] = []
    with httpx.Client(base_url=args.server, headers=HEADERS, timeout=60) as client:
        # Warm up the server (sqlite page cache, JIT-free but first-call costs).
        client.get(items_url, params={"limit": 20, "order": "desc"})
        for limit in (20, 200):
            for mode in ("full", "lean"):
                params = {"limit": limit, "order": "desc"}
                if mode == "lean":
                    params["tool_output"] = "preview"
                for gzip in (False, True):
                    result = timed_get(client, items_url, params, gzip, args.runs)
                    # Did the lean flag do anything? Count truncated stubs.
                    page = client.get(items_url, params=params).json()
                    stubs = sum(1 for it in page["data"] if it.get("output_truncated"))
                    rows.append({"what": f"items limit={limit} {mode} gzip={'on' if gzip else 'off'}", "stubs": stubs, **result})
        page = client.get(items_url, params={"limit": 200, "order": "desc", "tool_output": "preview"}).json()
        outputs = [it for it in page["data"] if it["type"] == "function_call_output"]
        biggest = max(outputs, key=lambda it: it.get("output_length", len(it.get("output", ""))))
        for gzip in (False, True):
            result = timed_get(client, f"{items_url}/{biggest['id']}", {}, gzip, args.runs)
            rows.append({"what": f"item GET (largest output) gzip={'on' if gzip else 'off'}", "stubs": 0, **result})
    print(f"| what | status | wire bytes | body bytes | encoding | median ms | p90 ms | stubs |")
    print("|---|---|---|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['what']} | {row['status']} | {row['wire_bytes']:,} | {row['body_bytes']:,} | {row['content_encoding']} | {row['ms_median']} | {row['ms_p90']} | {row['stubs']} |")
    with open(f"{args.label}.json", "w") as fh:
        json.dump(rows, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
