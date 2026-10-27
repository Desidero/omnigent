"""Plan a release: its tag, and the previous release to compare with.

  plan.py --fork OWNER/NAME --custom SHA --patches-commit SHA [--date YYYY-MM-DD]
          [--previous-manifest-out FILE]

Prints shell assignments: tag, resume (1 when this exact build already has a
tag, e.g. a re-run after a failed publish) and previous_tag. Tags are
custom/<date>.<n>, n counting up from 1 per UTC day; existing tags are never
reused for a different build. Reads the fork through `gh api` (GH_TOKEN) and
`git ls-remote`; it never writes.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shlex
import subprocess
import sys
import urllib.parse
from pathlib import Path

TAG_RE = re.compile(r"^custom/(\d{4}-\d{2}-\d{2})\.(\d+)$")


def gh_api(path: str) -> object:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def remote_tags(fork: str) -> dict[str, str]:
    """custom/* tag name -> the commit it points at."""
    out = subprocess.run(
        ["git", "ls-remote", "--tags", f"https://github.com/{fork}.git", "refs/tags/custom/*"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    direct, peeled = {}, {}
    for line in out.splitlines():
        sha, ref = line.split("\t")
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name[:-3]] = sha
        else:
            direct[name] = sha
    return {name: peeled.get(name, sha) for name, sha in direct.items()}


def tag_message(fork: str, tag: str) -> str:
    ref = gh_api(f"repos/{fork}/git/ref/tags/{urllib.parse.quote(tag, safe='/')}")
    target = ref["object"]
    if target["type"] != "tag":
        return ""
    return gh_api(f"repos/{fork}/git/tags/{target['sha']}").get("message", "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fork", required=True)
    parser.add_argument("--custom", required=True)
    parser.add_argument("--patches-commit", required=True)
    parser.add_argument("--date", default=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"))
    parser.add_argument("--previous-manifest-out")
    args = parser.parse_args()

    tags = remote_tags(args.fork)
    tag, resume = "", ""
    for name, commit in sorted(tags.items()):
        if commit == args.custom and f"Patches-Commit: {args.patches_commit}" in tag_message(args.fork, name):
            tag, resume = name, "1"
            break
    if not tag:
        numbers = [int(m.group(2)) for m in map(TAG_RE.match, tags) if m and m.group(1) == args.date]
        tag = f"custom/{args.date}.{max(numbers, default=0) + 1}"

    # The previous release: the newest custom/* release other than this one.
    previous = ""
    releases = gh_api(f"repos/{args.fork}/releases?per_page=50")
    for release in sorted(releases, key=lambda r: r.get("created_at") or "", reverse=True):
        name = release.get("tag_name", "")
        if TAG_RE.match(name) and name != tag and not release.get("draft"):
            previous = name
            if args.previous_manifest_out:
                assets = {a["name"]: a for a in release.get("assets", [])}
                if "manifest.json" in assets:
                    subprocess.run(
                        ["gh", "api", "-H", "Accept: application/octet-stream",
                         f"repos/{args.fork}/releases/assets/{assets['manifest.json']['id']}"],
                        stdout=Path(args.previous_manifest_out).open("wb"),
                        check=True,
                    )
                else:
                    print(f"warning: {name} has no manifest.json", file=sys.stderr)
            break

    for key, value in (("tag", tag), ("resume", resume), ("previous_tag", previous)):
        print(f"{key}={shlex.quote(value)}")


if __name__ == "__main__":
    main()
